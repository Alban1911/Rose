#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LAN WebSocket Server for Party Mode
Runs a local WebSocket server that party members connect to directly.
Replaces the Cloudflare Worker relay with a lightweight Python server.
"""

import asyncio
import json
import socket
from typing import Callable, Dict, List, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol

from utils.core.logging import get_logger

log = get_logger()

DEFAULT_PORT = 7865
MAX_MEMBERS = 10


class _MemberState:
    """Tracks a connected member's info and WebSocket."""

    __slots__ = ("ws", "summoner_id", "summoner_name", "skin")

    def __init__(self, ws: WebSocketServerProtocol):
        self.ws = ws
        self.summoner_id: int = 0
        self.summoner_name: str = "Unknown"
        self.skin: Optional[dict] = None


class PartyLANServer:
    """Local WebSocket server for LAN party mode.

    Behaves identically to the Cloudflare Durable Object ``PartyRoom``:
    members join, announce themselves, and broadcast skin selections.
    The server broadcasts the full member list on every change.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._server: Optional[websockets.WebSocketServer] = None
        self._members: Dict[WebSocketServerProtocol, _MemberState] = {}
        self._running = False

        # Callbacks (same interface as PartyRelay)
        self._on_members_changed: Optional[Callable[[List[dict]], None]] = None

    @property
    def connected(self) -> bool:
        return self._running and self._server is not None

    @property
    def members(self) -> List[dict]:
        """Return current member list in relay-compatible format."""
        return self._build_members_list()

    def set_on_members_changed(self, callback: Callable[[List[dict]], None]):
        """Called whenever the member list changes (join/leave/skin update)."""
        self._on_members_changed = callback

    async def start(self, timeout: float = 10.0, max_port_retries: int = 5) -> bool:
        """Start the WebSocket server with automatic port fallback if occupied.

        Returns:
            True if server started successfully, False otherwise.
        """
        if self._running:
            log.warning("[LAN_SERVER] Server is already running")
            return True

        initial_port = self.port
        for attempt in range(max_port_retries):
            target_port = initial_port + attempt
            try:
                self._server = await asyncio.wait_for(
                    websockets.serve(
                        self._handle_connection,
                        self.host,
                        target_port,
                        max_size=65536,
                        ping_interval=25,
                        ping_timeout=10,
                    ),
                    timeout=timeout,
                )
                self.port = target_port
                self._running = True
                if attempt > 0:
                    log.info(
                        f"[LAN_SERVER] Port {initial_port} in use, successfully bound to fallback port {self.port}"
                    )
                else:
                    log.info(f"[LAN_SERVER] Started on {self.host}:{self.port}")
                return True
            except OSError as e:
                if (
                    e.errno == 10048
                    or "address already in use" in str(e).lower()
                    or "only one usage of each socket address" in str(e).lower()
                ):
                    log.warning(
                        f"[LAN_SERVER] Port {target_port} is already in use, trying next port..."
                    )
                    continue
                else:
                    log.error(f"[LAN_SERVER] Failed to start on port {target_port}: {e}")
                    return False
            except asyncio.TimeoutError:
                log.error(f"[LAN_SERVER] Start timed out on port {target_port}")
                return False
            except Exception as e:
                log.error(f"[LAN_SERVER] Failed to start: {e}")
                return False

        log.error(
            f"[LAN_SERVER] All {max_port_retries} port attempts starting from {initial_port} failed (in use)."
        )
        return False

    # Alias for PartyRelay interface compatibility
    async def connect(self, timeout: float = 10.0) -> bool:
        """Start the server (alias for ``start()``)."""
        return await self.start(timeout=timeout)

    async def join(self, summoner_id: int, summoner_name: str):
        """Register the host as a member (adds a virtual local member)."""
        # The host doesn't have a WebSocket connection to itself,
        # so we store it as a sentinel with ws=None.
        sentinel = _MemberState(ws=None)  # type: ignore[arg-type]
        sentinel.summoner_id = summoner_id
        sentinel.summoner_name = summoner_name
        self._members[None] = sentinel  # type: ignore[index]
        self._broadcast_members()
        log.info(f"[LAN_SERVER] Host joined as {summoner_name} ({summoner_id})")

    async def send_skin(self, skin: Optional[dict]):
        """Update the host's own skin selection."""
        host_member = self._members.get(None)  # type: ignore[arg-type]
        if host_member:
            host_member.skin = skin
            self._broadcast_members()

    async def stop(self):
        """Stop the server and disconnect all members."""
        self._running = False

        # Close all client connections
        close_tasks = []
        for ws, member in list(self._members.items()):
            if ws is not None:
                close_tasks.append(self._close_ws(ws))

        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

        self._members.clear()

        if self._server:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            self._server = None

        log.info("[LAN_SERVER] Stopped")

    # Alias for PartyRelay interface compatibility
    async def disconnect(self):
        """Stop the server (alias for ``stop()``)."""
        await self.stop()

    # ─── Connection handler ──────────────────────────────────────────────

    async def _handle_connection(
        self, ws: WebSocketServerProtocol, path: str = "/"
    ):
        """Handle a new WebSocket connection from a party member."""
        # Check capacity (exclude the host sentinel keyed by None)
        real_connections = sum(1 for k in self._members if k is not None)
        if real_connections >= MAX_MEMBERS:
            log.warning("[LAN_SERVER] Room is full, rejecting connection")
            await ws.close(1013, "Room is full")
            return

        member = _MemberState(ws)
        self._members[ws] = member
        log.info(f"[LAN_SERVER] New connection from {ws.remote_address}")

        # Send current member list to the new joiner
        try:
            members_list = self._build_members_list()
            await ws.send(json.dumps({"type": "members", "members": members_list}))
        except Exception:
            pass

        try:
            async for message in ws:
                if not self._running:
                    break
                if isinstance(message, str):
                    if message == "ping":
                        try:
                            await ws.send("pong")
                        except Exception:
                            pass
                        continue
                    await self._handle_message(ws, member, message)
        except ConnectionClosed:
            pass
        except Exception as e:
            log.warning(f"[LAN_SERVER] Connection error: {e}")
        finally:
            self._members.pop(ws, None)
            self._broadcast_members()
            name = member.summoner_name or "Unknown"
            log.info(f"[LAN_SERVER] {name} disconnected")

    async def _handle_message(
        self, ws: WebSocketServerProtocol, member: _MemberState, raw: str
    ):
        """Process a JSON message from a connected member."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type")

        if msg_type == "join":
            member.summoner_id = msg.get("summoner_id", 0)
            member.summoner_name = msg.get("summoner_name", "Unknown")
            log.info(
                f"[LAN_SERVER] {member.summoner_name} "
                f"({member.summoner_id}) joined the room"
            )
            self._broadcast_members()

        elif msg_type == "skin":
            member.skin = msg.get("skin")
            self._broadcast_members()

        elif msg_type == "leave":
            try:
                await ws.close(1000, "client left")
            except Exception:
                pass

    # ─── Broadcasting ────────────────────────────────────────────────────

    def _build_members_list(self) -> List[dict]:
        """Build the member list in the same format as the Cloudflare relay."""
        members = []
        for member in self._members.values():
            if member.summoner_id:
                members.append({
                    "summoner_id": member.summoner_id,
                    "summoner_name": member.summoner_name,
                    "skin": member.skin,
                })
        return members

    def _broadcast_members(self):
        """Send updated member list to all connected clients and notify callback."""
        members_list = self._build_members_list()
        payload = json.dumps({"type": "members", "members": members_list})

        # Send to all connected WebSocket clients (not the host sentinel)
        for ws in list(self._members.keys()):
            if ws is not None:
                try:
                    asyncio.ensure_future(ws.send(payload))
                except Exception:
                    pass

        # Notify the callback (used by PartyManager to update local state)
        if self._on_members_changed:
            try:
                self._on_members_changed(members_list)
            except Exception as e:
                log.debug(f"[LAN_SERVER] Callback error: {e}")

    @staticmethod
    async def _close_ws(ws: WebSocketServerProtocol):
        """Safely close a WebSocket connection."""
        try:
            await ws.close(1001, "server stopping")
        except Exception:
            pass


# ─── Network interface detection ─────────────────────────────────────────

def get_network_interfaces() -> List[dict]:
    """Detect available network interfaces with their IP addresses.

    Returns a list of dicts, each with:
        - name: human-readable interface description
        - ip: the IPv4 address
        - type: "hamachi", "tailscale", "ethernet", "wifi", "loopback", "other"
    """
    interfaces = []

    try:
        import psutil
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()

        for iface_name, addr_list in addrs.items():
            # Skip interfaces that are down
            if iface_name in stats and not stats[iface_name].isup:
                continue

            for addr in addr_list:
                # Only IPv4
                if addr.family != socket.AF_INET:
                    continue

                ip = addr.address
                if not ip or ip == "0.0.0.0":
                    continue

                iface_type = _classify_interface(iface_name, ip)
                interfaces.append({
                    "name": iface_name,
                    "ip": ip,
                    "type": iface_type,
                })

    except ImportError:
        # Fallback without psutil: use socket to get the default IP
        log.debug("[LAN_SERVER] psutil not available, using socket fallback")
        try:
            hostname = socket.gethostname()
            ips = socket.getaddrinfo(hostname, None, socket.AF_INET)
            seen = set()
            for _, _, _, _, sockaddr in ips:
                ip = sockaddr[0]
                if ip not in seen and ip != "0.0.0.0":
                    seen.add(ip)
                    interfaces.append({
                        "name": f"Interface ({ip})",
                        "ip": ip,
                        "type": _classify_interface("", ip),
                    })
        except Exception as e:
            log.warning(f"[LAN_SERVER] Failed to detect interfaces: {e}")

    # Always include loopback for local testing
    if not any(i["ip"] == "127.0.0.1" for i in interfaces):
        interfaces.append({
            "name": "Loopback (localhost)",
            "ip": "127.0.0.1",
            "type": "loopback",
        })

    # Sort: hamachi/tailscale first, then ethernet/wifi, loopback last
    type_order = {"hamachi": 0, "tailscale": 1, "ethernet": 2, "wifi": 3, "other": 4, "loopback": 5}
    interfaces.sort(key=lambda i: type_order.get(i["type"], 4))

    return interfaces


def _classify_interface(name: str, ip: str) -> str:
    """Classify an interface by name and IP range."""
    name_lower = name.lower()

    # Hamachi uses 25.x.x.x or interface name contains "hamachi"
    if ip.startswith("25.") or "hamachi" in name_lower:
        return "hamachi"

    # Tailscale uses 100.x.x.x range
    if ip.startswith("100.") or "tailscale" in name_lower:
        return "tailscale"

    # Radmin VPN uses 26.x.x.x
    if ip.startswith("26.") or "radmin" in name_lower:
        return "hamachi"  # Group with hamachi for sorting

    # ZeroTier uses various ranges but name contains "zt"
    if "zerotier" in name_lower or "zt" in name_lower:
        return "tailscale"  # Group with tailscale for sorting

    # Loopback
    if ip.startswith("127."):
        return "loopback"

    # Common ethernet/wifi names
    if "ethernet" in name_lower or "eth" in name_lower:
        return "ethernet"
    if "wi-fi" in name_lower or "wifi" in name_lower or "wlan" in name_lower:
        return "wifi"

    # Default private ranges
    if ip.startswith("192.168.") or ip.startswith("10."):
        return "ethernet"

    return "other"
