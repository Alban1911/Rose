#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket Relay Client for Party Mode
Connects to a shared room where party members broadcast skin selections.
"""

import asyncio
import hashlib
import json
import os
import ssl
import time
from typing import Callable, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from utils.core.logging import get_logger

log = get_logger()

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
# the delays over. One dropped sooner keeps them growing.
STABLE_CONNECTION_S = 60.0
# The relay closes a connection with this reason when the same player joins the
# room again: another connection (a second Rose, another PC) now has our place
REPLACED_REASON = "replaced"

_ssl_contexts_cache: Optional[List[ssl.SSLContext]] = None


def compute_room_key(host_summoner_id: int, host_key: bytes) -> str:
    """Derive a room key from the host's token."""
    raw = str(host_summoner_id).encode() + host_key
    return hashlib.sha256(raw).hexdigest()[:32]


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
    if status == 409:
        return "this party is full (10 players max)"
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
    list on every change. A dropped connection is reopened in the background,
    and our join and last state are sent again, until _run gives up.

    Our state only goes out while someone else is in the room: every message
    wakes the room on the relay, whose active time is what the relay pays for,
    and a room with only us in it has no one to tell. It goes out as soon as
    someone joins.
    """

    def __init__(self, room_key: str, summoner_id: int, summoner_name: str):
        self.room_key = room_key
        self._summoner_id = summoner_id
        self._join_msg = {
            "type": "join",
            "summoner_id": summoner_id,
            "summoner_name": summoner_name,
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
        # The last connection attempt was refused because the room is full
        self._room_full = False

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
        if not self._stopped or self._closing:
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
        if ws is None or not self._connected or not self._others_present():
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
        """Open the connection and announce ourselves."""
        if not RELAY_URL:
            self.last_error = "no party server is configured in this build"
            log.warning("[RELAY] No relay URL configured")
            return False

        url = f"{RELAY_URL}/room?key={self.room_key}"
        self._room_full = False
        contexts = _ssl_contexts() if url.startswith("wss://") else [None]
        error: Optional[BaseException] = None

        for context in contexts:
            kwargs = {"max_size": 65536}
            if context is not None:
                kwargs["ssl"] = context
            try:
                ws = await asyncio.wait_for(websockets.connect(url, **kwargs), timeout=timeout)
            except ssl.SSLCertVerificationError as e:
                error = e
                continue  # try the next trust store
            except Exception as e:
                error = e
                break

            try:
                # Our state follows once the room's member list shows someone else
                await ws.send(json.dumps(self._join_msg))
            except Exception as e:
                error = e
                break

            self._ws = ws
            self._connected = True
            self._sent_state = None  # a new connection starts without our state
            self.last_error = None
            log.info(f"[RELAY] Connected to room {self.room_key[:8]}")
            self._notify(self._on_connection_changed)
            return True

        self.last_error = _describe_error(error)
        self._room_full = _status_code(error) == 409
        log.warning(f"[RELAY] Connection to room {self.room_key[:8]} failed: {error}")
        return False

    async def _run(self):
        """Receive room updates; reopen the connection when it drops.

        Every connection wakes the room on the relay, which the relay pays for,
        so this gives up (until resume()) rather than retry forever: when the
        relay handed our place to another connection of ours, when the room is
        full, and after trying every delay without getting a connection that
        lasts.
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
                    if self._room_full:
                        self._stop("the room is full")
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
            if getattr(ws, "close_reason", None) == REPLACED_REASON:
                self._stop("this account joined it from another connection")
                return
            if time.monotonic() - opened_at >= STABLE_CONNECTION_S:
                attempt = 0
            log.info(f"[RELAY] Lost connection to room {self.room_key[:8]}, reconnecting...")
            self._notify(self._on_connection_changed)

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

                if isinstance(msg, dict) and msg.get("type") == "members":
                    members = msg.get("members")
                    self.members = [m for m in members if isinstance(m, dict)] if isinstance(members, list) else []
                    log.debug(f"[RELAY] Room {self.room_key[:8]}: {len(self.members)} member(s)")
                    await self._deliver_state()
                    self._notify(self._on_members_changed)
        except ConnectionClosed as e:
            log.info(f"[RELAY] Room {self.room_key[:8]} connection closed: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"[RELAY] Receive error in room {self.room_key[:8]}: {e}")

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
