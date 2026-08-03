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
from typing import Callable, Dict, List, Optional

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


def compute_room_key(host_summoner_id: int, host_key: bytes) -> str:
    """Derive a room key from the host's token."""
    raw = str(host_summoner_id).encode() + host_key
    return hashlib.sha256(raw).hexdigest()[:32]


class PartyRelay:
    """WebSocket connection to a shared party room.

    Members join, announce themselves, and broadcast skin selections.
    The Worker broadcasts the full member list on every change.
    """

    def __init__(self, room_key: str):
        self.room_key = room_key
        self._ws = None
        self._connected = False
        self._recv_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None

        # Current state: list of members with their skin picks
        self.members: List[dict] = []

        # Callbacks
        self._on_members_changed: Optional[Callable[[List[dict]], None]] = None

    @property
    def connected(self) -> bool:
        return (
            self._connected
            and self._ws is not None
            and not bool(getattr(self._ws, "closed", False))
        )

    def set_on_members_changed(self, callback: Callable[[List[dict]], None]):
        """Called whenever the member list changes (join/leave/skin update)."""
        self._on_members_changed = callback

    async def connect(self, timeout: float = 15.0) -> bool:
        """Connect to the relay room."""
        if self.connected:
            return True
        if not RELAY_URL:
            log.warning("[RELAY] No relay URL configured")
            return False

        url = f"{RELAY_URL}/room?key={self.room_key}"
        log.info(f"[RELAY] Connecting to room {self.room_key[:8]}...")

        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(url, max_size=65536),
                timeout=timeout,
            )
            self._connected = True
            self._recv_task = asyncio.create_task(self._receive_loop())
            self._ping_task = asyncio.create_task(self._keepalive_loop())
            log.info("[RELAY] Connected")
            return True
        except Exception as e:
            self._connected = False
            self._ws = None
            log.warning(f"[RELAY] Connection failed: {e}")
            return False

    async def join(self, summoner_id: int, summoner_name: str):
        """Announce ourselves to the room."""
        await self._send_json({
            "type": "join",
            "summoner_id": summoner_id,
            "summoner_name": summoner_name,
        })

    async def send_skin(self, skin: Optional[dict]):
        """Broadcast our skin selection to the room."""
        await self._send_json({
            "type": "skin",
            "skin": skin,
        })

    async def disconnect(self):
        """Leave the room."""
        self._connected = False

        for task in [self._ping_task, self._recv_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._ping_task = None
        self._recv_task = None

        if self._ws:
            try:
                await self._ws.send(json.dumps({"type": "leave"}))
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        self.members = []
        log.info("[RELAY] Disconnected")

    async def _send_json(self, data: dict):
        if self._ws and self._connected:
            try:
                await self._ws.send(json.dumps(data))
            except (ConnectionClosed, OSError) as exc:
                self._connected = False
                log.info(f"[RELAY] Send failed; reconnect scheduled: {exc}")

    async def _receive_loop(self):
        try:
            async for message in self._ws:
                if isinstance(message, str):
                    if message == "pong":
                        continue
                    try:
                        msg = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    if msg.get("type") == "members":
                        self.members = self._deduplicate_members(
                            msg.get("members", [])
                        )
                        log.info(f"[RELAY] Members updated: {len(self.members)} in room")
                        if self._on_members_changed:
                            try:
                                self._on_members_changed(self.members)
                            except Exception as e:
                                log.debug(f"[RELAY] Callback error: {e}")
        except ConnectionClosed:
            log.info("[RELAY] Connection closed")
            self._connected = False
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.warning(f"[RELAY] Receive error: {e}")
            self._connected = False
        finally:
            if self._ws and bool(getattr(self._ws, "closed", False)):
                self._connected = False

    @staticmethod
    def _deduplicate_members(members: list) -> List[dict]:
        """Collapse stale duplicate sockets after a fast Rose restart."""
        by_summoner_id: Dict[int, dict] = {}
        for member in members if isinstance(members, list) else []:
            if not isinstance(member, dict):
                continue
            summoner_id = int(member.get("summoner_id", 0) or 0)
            if not summoner_id:
                continue
            existing = by_summoner_id.get(summoner_id)
            if existing is None or (
                not existing.get("skin") and member.get("skin")
            ):
                by_summoner_id[summoner_id] = member
        return list(by_summoner_id.values())

    async def _keepalive_loop(self):
        try:
            while self._connected:
                await asyncio.sleep(PING_INTERVAL)
                if self._ws and self._connected:
                    try:
                        await self._ws.send("ping")
                    except Exception as exc:
                        self._connected = False
                        log.info(f"[RELAY] Keepalive failed: {exc}")
                        break
        except asyncio.CancelledError:
            return
