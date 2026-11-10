#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket Relay Client for Party Mode
Connects to a shared room where party members broadcast skin selections.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import ssl
import time
from typing import Callable, List, Optional
from urllib.parse import quote, urlencode, urlsplit

from websockets.exceptions import ConnectionClosed, SecurityError
from websockets.legacy.client import Connect

from config import APP_VERSION
from utils.core.logging import get_logger

log = get_logger()
# websockets logs request headers at DEBUG, including Authorization.
connection_log = logging.getLogger(f"{__name__}.connection")
connection_log.setLevel(logging.INFO)

try:
    from .relay_config import RELAY_URL as _CONFIGURED_URL
except ImportError:
    _CONFIGURED_URL = ""

RELAY_URL = os.environ.get("ROSE_RELAY_URL", _CONFIGURED_URL)
PING_INTERVAL = 25.0
CONNECT_TIMEOUT = 15.0
# Wait before each reconnect attempt, in seconds
RECONNECT_DELAYS = (1.0, 2.0, 5.0, 10.0, 20.0, 30.0)
# A connection that lasted this long was a working one: the next drop starts
# the delays over. One dropped sooner keeps them growing. Well above the 100s
# after which Cloudflare cuts a connection that carries nothing: a client whose
# pings never get through (a firewall...) otherwise reconnected every 100s all day
STABLE_CONNECTION_S = 300.0
# The relay sends this message when the same player joins the room again:
# another connection (a second Rose, another PC) now has our place, and the
# room stops listening to this one. Relays from before it closed the
# connection with this reason instead
REPLACED_EVENT = "replaced"
REPLACED_REASON = "replaced"
# The relay refuses a Rose too old for it with this status: no point retrying
UPDATE_REQUIRED_STATUS = 426
# Our summoner is in the room from another installation (another PC, or a
# Rose reinstalled without its data) for as long as that one stays connected
IDENTITY_CONFLICT_STATUS = 403
ROOM_FULL_STATUS = 409
# Refusals that end reconnecting until resume(): the room's state changes on its own
_BUSY_REFUSALS = (IDENTITY_CONFLICT_STATUS, ROOM_FULL_STATUS)
RELAY_PROTOCOL_VERSION = "2"
RELAY_PROTOCOL_HEADER = "X-Rose-Party-Protocol"
_MEMBER_KEY = re.compile(r"[0-9a-f]{64}")

_ssl_contexts_cache: Optional[List[ssl.SSLContext]] = None


def compute_room_key(host_summoner_id: int, host_key: bytes) -> str:
    """Derive a room key from the host's token."""
    raw = str(host_summoner_id).encode() + host_key
    return hashlib.sha256(raw).hexdigest()[:32]


class _RelayConnect(Connect):
    def handle_redirect(self, uri: str) -> None:
        # websockets 12 reuses the Authorization header across redirects.
        raise SecurityError("the party server redirected the connection")


def _ssl_contexts() -> List[ssl.SSLContext]:
    """Trust stores to try, in order.

    certifi first: a stale intermediate cached in the Windows store makes
    OpenSSL fail with "certificate has expired" even though the relay's chain
    is valid. The Windows store comes second, for antivirus or proxies that
    re-sign TLS traffic with their own root.
    """
    global _ssl_contexts_cache
    if _ssl_contexts_cache is None:
        contexts = []
        try:
            import certifi
            contexts.append(ssl.create_default_context(cafile=certifi.where()))
        except Exception as e:
            log.debug(f"[RELAY] certifi CA bundle unavailable: {e}")
        contexts.append(ssl.create_default_context())
        _ssl_contexts_cache = contexts
    return _ssl_contexts_cache


def _status_code(error: Optional[BaseException]) -> Optional[int]:
    return getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)


def _describe_error(error: Optional[BaseException]) -> str:
    """Short, user-facing reason for a failed connection."""
    if error is None:
        return "unknown error"
    if isinstance(error, ssl.SSLCertVerificationError):
        return f"secure connection failed ({error.verify_message or error})"
    status = _status_code(error)
    if status == ROOM_FULL_STATUS:
        return "this party is full (10 players max)"
    if status == UPDATE_REQUIRED_STATUS:
        return "this version of Rose is too old for party mode, please update Rose"
    if status == IDENTITY_CONFLICT_STATUS:
        return "this account is in this party from another Rose installation, try again once it has left"
    if status:
        return f"the party server answered with HTTP {status}"
    if isinstance(error, asyncio.TimeoutError):
        return "the party server did not answer in time"
    if isinstance(error, OSError):
        return f"network error ({error.strerror or error})"
    return str(error) or type(error).__name__


class PartyRelay:
    """WebSocket connection to one shared party room.

    Members join, announce themselves, and broadcast their state (skin pick
    and the other rooms they are in). The Worker broadcasts the full member
    list on every change. A dropped connection is reopened with the same
    credentials in the background, and our last state is sent again.

    Our state only goes out while someone else is in the room: every message
    wakes the room on the relay, whose active time is what the relay pays for,
    and a room with only us in it has no one to tell. It goes out as soon as
    someone joins.
    """

    def __init__(self, room_key: str, summoner_id: int, summoner_name: str, identity_key: bytes):
        self.room_key = room_key
        self._summoner_id = summoner_id
        self._identity_key = identity_key
        self._identity_headers = {
            "X-Rose-Summoner-Id": str(summoner_id),
            "X-Rose-Summoner-Name": quote(summoner_name[:64], safe=""),
        }
        self._state: Optional[dict] = None
        # The state the room has for us on the current connection
        self._sent_state: Optional[dict] = None
        self._ws = None
        self._connected = False
        self._closing = False
        self._run_task: Optional[asyncio.Task] = None
        # Reconnecting stopped (see _run) until resume()
        self._stopped = False
        self._refused_status: Optional[int] = None
        # The relay gave our place in the room to another connection of ours
        self._replaced = False

        # Last member list received (kept while reconnecting)
        self.members: List[dict] = []
        # Why the last connection attempt failed, for the UI
        self.last_error: Optional[str] = None

        # Callbacks
        self._on_members_changed: Optional[Callable[["PartyRelay"], None]] = None
        self._on_connection_changed: Optional[Callable[["PartyRelay"], None]] = None

    @property
    def connected(self) -> bool:
        return self._connected and self._ws is not None

    @property
    def stopped(self) -> bool:
        """Reconnecting gave up; resume() starts it again."""
        return self._stopped

    @property
    def permanently_refused(self) -> bool:
        return self._refused_status == UPDATE_REQUIRED_STATUS

    def set_callbacks(
        self,
        on_members_changed: Optional[Callable[["PartyRelay"], None]] = None,
        on_connection_changed: Optional[Callable[["PartyRelay"], None]] = None,
    ):
        """on_members_changed: member list changed (join/leave/state update).
        on_connection_changed: connection lost or restored."""
        self._on_members_changed = on_members_changed
        self._on_connection_changed = on_connection_changed

    async def connect(self, timeout: float = CONNECT_TIMEOUT) -> bool:
        """Join the room. Returns False if the room can't be reached;
        once joined, drops are retried in the background until disconnect()."""
        if not await self._open(timeout):
            return False
        if self._closing:
            # disconnect() was called while we were connecting
            ws, self._ws = self._ws, None
            self._connected = False
            await self._close_ws(ws)
            return False
        self._run_task = asyncio.create_task(self._run())
        return True

    def resume(self):
        """Reconnect a room we stopped reconnecting to (at a moment the party
        needs it: a lobby, a champ select, a friend added again)."""
        if not self._stopped or self._closing or self.permanently_refused:
            return
        self._stopped = False
        log.info(f"[RELAY] Reconnecting to room {self.room_key[:8]}")
        self._run_task = asyncio.create_task(self._run())

    async def send_state(self, state: Optional[dict]):
        """Share our state with the room (again after reconnects, and when
        someone joins a room we were alone in)."""
        self._state = state
        await self._deliver_state()

    def _others_present(self) -> bool:
        return any(m.get("summoner_id") != self._summoner_id for m in self.members)

    async def _deliver_state(self):
        """Send our state if someone else is in the room and it doesn't have it yet."""
        ws = self._ws
        if ws is None or not self._connected or self._replaced or not self._others_present():
            return
        state = self._state
        if state == self._sent_state:
            return
        try:
            await ws.send(json.dumps({"type": "skin", "skin": state}))
            self._sent_state = state
        except ConnectionClosed:
            pass  # _run notices the drop and reconnects

    async def disconnect(self):
        """Leave the room for good."""
        self._closing = True

        task, self._run_task = self._run_task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        ws, self._ws = self._ws, None
        self._connected = False
        await self._close_ws(ws)

        self.members = []
        log.info(f"[RELAY] Left room {self.room_key[:8]}")

    @staticmethod
    async def _close_ws(ws):
        if ws is None:
            return
        try:
            await ws.send(json.dumps({"type": "leave"}))
            await asyncio.wait_for(ws.close(), timeout=2.0)
        except Exception:
            pass

    async def _open(self, timeout: float) -> bool:
        """Join the room using a credential scoped to the configured relay."""
        self._refused_status = None
        if not RELAY_URL:
            self.last_error = "no party server is configured in this build"
            log.warning("[RELAY] No relay URL configured")
            return False

        try:
            endpoint = urlsplit(RELAY_URL)
            hostname = endpoint.hostname
            port = endpoint.port
        except ValueError:
            self.last_error = "the party server URL is invalid"
            return False
        if not hostname or endpoint.query or endpoint.fragment or endpoint.username is not None:
            self.last_error = "the party server URL is invalid"
            return False
        local = endpoint.scheme == "ws" and hostname in ("localhost", "127.0.0.1", "::1")
        if endpoint.scheme != "wss" and not local:
            self.last_error = "the party server must use a secure WebSocket connection"
            log.warning("[RELAY] Refusing to send credentials over an insecure connection")
            return False
        if port is None:
            port = 443 if endpoint.scheme == "wss" else 80
        # Stable across rooms on this relay, distinct across relay origins.
        origin = f"{endpoint.scheme}://{hostname}:{port}".encode("utf-8")
        credential = hmac.digest(self._identity_key, b"rose-party-relay-v2:" + origin, "sha256")
        headers = {**self._identity_headers, "Authorization": f"Bearer {credential.hex()}"}
        query = urlencode({"key": self.room_key, "v": APP_VERSION, "p": RELAY_PROTOCOL_VERSION})
        url = f"{RELAY_URL.rstrip('/')}/room?{query}"
        contexts = _ssl_contexts() if endpoint.scheme == "wss" else [None]
        error: Optional[BaseException] = None

        for context in contexts:
            # A room can send ten members' state, each with an 8 KiB limit.
            kwargs = {"max_size": 128 * 1024, "extra_headers": headers, "logger": connection_log}
            if context is not None:
                kwargs["ssl"] = context
            try:
                ws = await asyncio.wait_for(_RelayConnect(url, **kwargs), timeout=timeout)
            except ssl.SSLCertVerificationError as e:
                error = e
                continue  # try the next trust store
            except Exception as e:
                error = e
                break

            if ws.response_headers.get_all(RELAY_PROTOCOL_HEADER) != [RELAY_PROTOCOL_VERSION]:
                await self._close_socket(ws)
                self.last_error = "the party server does not support authenticated connections"
                self._refused_status = UPDATE_REQUIRED_STATUS
                log.warning("[RELAY] Party server did not confirm protocol %s", RELAY_PROTOCOL_VERSION)
                return False

            self._ws = ws
            self._connected = True
            self._replaced = False
            self._sent_state = None  # a new connection starts without our state
            self.last_error = None
            log.info(f"[RELAY] Connected to room {self.room_key[:8]}")
            self._notify(self._on_connection_changed)
            return True

        self.last_error = _describe_error(error)
        self._refused_status = _status_code(error)
        log.warning(f"[RELAY] Connection to room {self.room_key[:8]} failed: {error}")
        return False

    async def _run(self):
        """Receive room updates; reopen the connection when it drops.

        Every connection wakes the room on the relay, which the relay pays for,
        so this gives up (until resume()) rather than retry forever: when the
        relay handed our place to another connection of ours, when the room
        is full or refuses our identity or protocol, and after trying every
        delay without getting a connection that lasts.
        """
        attempt = 0
        while not self._closing:
            if self._ws is None:
                if attempt >= len(RECONNECT_DELAYS):
                    self._stop(f"no lasting connection after {attempt} attempts")
                    return
                await asyncio.sleep(RECONNECT_DELAYS[attempt])
                attempt += 1
                if self._closing:
                    return
                if not await self._open(CONNECT_TIMEOUT):
                    if self.permanently_refused or self._refused_status in _BUSY_REFUSALS:
                        if self.permanently_refused:
                            self.members = []
                        self._stop(self.last_error or "the party server refused the connection")
                        return
                    continue

            ws = self._ws
            opened_at = time.monotonic()
            keepalive = asyncio.create_task(self._keepalive(ws))
            try:
                await self._receive(ws)
            finally:
                keepalive.cancel()

            if self._closing:
                return
            self._ws = None
            self._connected = False
            replaced = self._replaced
            if replaced or getattr(ws, "close_reason", None) == REPLACED_REASON:
                # The room no longer reaches us: the members we last saw are stale
                self.members = []
                self._sent_state = None
                # Stop before closing, so a resume() while it closes reconnects
                self._stop("this account joined it from another connection")
                if replaced:
                    # The relay stopped listening but left the connection open
                    await self._close_socket(ws)
                return
            if time.monotonic() - opened_at >= STABLE_CONNECTION_S:
                attempt = 0
            log.info(f"[RELAY] Lost connection to room {self.room_key[:8]}, reconnecting...")
            self._notify(self._on_connection_changed)

    @staticmethod
    async def _close_socket(ws):
        """Close a socket without sending a room message."""
        try:
            await asyncio.wait_for(ws.close(), timeout=2.0)
        except Exception:
            pass

    def _stop(self, reason: str):
        self._stopped = True
        log.info(f"[RELAY] Stopped reconnecting to room {self.room_key[:8]}: {reason}")
        self._notify(self._on_connection_changed)

    async def _receive(self, ws):
        try:
            async for message in ws:
                if not isinstance(message, str) or message == "pong":
                    continue
                try:
                    msg = json.loads(message)
                except json.JSONDecodeError:
                    continue

                if isinstance(msg, dict) and msg.get("type") == REPLACED_EVENT:
                    log.info(f"[RELAY] Room {self.room_key[:8]}: this account joined it from another connection")
                    self._replaced = True
                    return
                if isinstance(msg, dict) and msg.get("type") == "members":
                    members = msg.get("members")
                    self.members = self._normalize_members(members)
                    log.debug(f"[RELAY] Room {self.room_key[:8]}: {len(self.members)} member(s)")
                    self._notify(self._on_members_changed)
                    await self._deliver_state()
        except ConnectionClosed as e:
            log.info(f"[RELAY] Room {self.room_key[:8]} connection closed: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"[RELAY] Receive error in room {self.room_key[:8]}: {e}")

    @staticmethod
    def _normalize_members(members) -> List[dict]:
        """The relay sends decimal IDs to preserve all 64 bits on the wire."""
        normalized = []
        if not isinstance(members, list):
            return normalized
        for member in members:
            if not isinstance(member, dict):
                continue
            member_key = member.get("member_key")
            if not isinstance(member_key, str) or not _MEMBER_KEY.fullmatch(member_key):
                continue
            summoner_id = member.get("summoner_id")
            if (
                isinstance(summoner_id, str)
                and len(summoner_id) <= 20
                and summoner_id.isascii()
                and summoner_id.isdecimal()
            ):
                summoner_id = int(summoner_id)
            if type(summoner_id) is int and 0 < summoner_id < 2**64:
                normalized.append({**member, "summoner_id": summoner_id})
        return normalized

    async def _keepalive(self, ws):
        """App-level ping; the relay answers it without waking the room."""
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL)
                await ws.send("ping")
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # the receive loop sees the closed connection

    def _notify(self, callback: Optional[Callable[["PartyRelay"], None]]):
        if callback:
            try:
                callback(self)
            except Exception as e:
                log.debug(f"[RELAY] Callback error: {e}")
