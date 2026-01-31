#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UDP Transport Layer
Handles UDP socket operations with NAT hole punching
"""

import asyncio
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

from utils.core.logging import get_logger

log = get_logger()

# Hole punching configuration
HOLE_PUNCH_ATTEMPTS = 10
HOLE_PUNCH_INTERVAL = 0.3   # seconds between attempts
HOLE_PUNCH_RECV_TIMEOUT = 0.8  # wait for reply (NAT + RTT can be slow)

# Keepalive configuration
KEEPALIVE_INTERVAL = 15.0  # seconds
KEEPALIVE_TIMEOUT = 45.0   # consider dead after this


@dataclass
class PeerEndpoint:
    """Represents a peer's network endpoint"""
    external_ip: str
    external_port: int
    internal_ip: str
    internal_port: int
    last_seen: float = 0.0
    is_lan: bool = False

    def get_addresses(self) -> list[Tuple[str, int]]:
        """Get list of addresses to try (external first, then internal for LAN)"""
        addrs = [(self.external_ip, self.external_port)]
        # Only try internal if it's a real LAN address (0.0.0.0 is invalid to send to)
        if self.internal_ip and self.internal_ip != "0.0.0.0" and self.internal_ip != self.external_ip:
            addrs.append((self.internal_ip, self.internal_port))
        return addrs


class UDPTransport:
    """Async UDP transport with hole punching support"""

    def __init__(self, local_port: int = 0):
        """Initialize UDP transport

        Args:
            local_port: Local port to bind to (0 for auto-assign)
        """
        self._local_port = local_port
        self._socket: Optional[socket.socket] = None
        self._bound = False
        self._receive_task: Optional[asyncio.Task] = None
        self._running = False

        # Message handlers by source address
        self._handlers: Dict[Tuple[str, int], Callable[[bytes, Tuple[str, int]], None]] = {}
        self._default_handler: Optional[Callable[[bytes, Tuple[str, int]], None]] = None

        # Pending receives (for hole punching)
        self._pending_receives: asyncio.Queue = asyncio.Queue()

    @property
    def local_port(self) -> int:
        """Get the bound local port"""
        return self._local_port

    @property
    def local_address(self) -> Tuple[str, int]:
        """Get the local address"""
        if self._socket:
            return self._socket.getsockname()
        return ("0.0.0.0", self._local_port)

    async def bind(self) -> int:
        """Bind to local port

        Returns:
            The bound port number
        """
        if self._bound:
            return self._local_port

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setblocking(False)

        # Allow address reuse
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Bind to specified port (or 0 for auto-assign)
        self._socket.bind(("0.0.0.0", self._local_port))

        # Get assigned port
        self._local_port = self._socket.getsockname()[1]
        self._bound = True

        log.info(f"[UDP] Bound to port {self._local_port}")
        return self._local_port

    def get_socket(self) -> Optional[socket.socket]:
        """Get the underlying socket (for STUN client)"""
        return self._socket

    async def start_receiving(self):
        """Start the receive loop"""
        if self._running:
            return

        if not self._bound:
            await self.bind()

        self._running = True
        self._receive_task = asyncio.create_task(self._receive_loop())
        log.debug("[UDP] Receive loop started")

    async def stop(self):
        """Stop the transport"""
        self._running = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._socket:
            self._socket.close()
            self._socket = None

        self._bound = False
        log.info("[UDP] Transport stopped")

    async def send(self, data: bytes, addr: Tuple[str, int]):
        """Send UDP packet

        Args:
            data: Data to send
            addr: Destination (ip, port) tuple
        """
        if not self._socket:
            raise RuntimeError("Transport not bound")

        loop = asyncio.get_event_loop()
        try:
            await loop.sock_sendto(self._socket, data, addr)
        except Exception as e:
            log.warning(f"[UDP] Send failed to {addr}: {e}")
            raise

    async def recv(self, timeout: float = 5.0) -> Tuple[bytes, Tuple[str, int]]:
        """Receive a UDP packet with timeout

        Args:
            timeout: Timeout in seconds

        Returns:
            Tuple of (data, (ip, port))

        Raises:
            asyncio.TimeoutError: If no packet received within timeout
        """
        try:
            return await asyncio.wait_for(
                self._pending_receives.get(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise

    def set_handler(self, addr: Tuple[str, int], handler: Callable[[bytes, Tuple[str, int]], None]):
        """Set handler for packets from specific address"""
        self._handlers[addr] = handler

    def remove_handler(self, addr: Tuple[str, int]):
        """Remove handler for specific address"""
        self._handlers.pop(addr, None)

    def set_default_handler(self, handler: Callable[[bytes, Tuple[str, int]], None]):
        """Set default handler for unmatched packets"""
        self._default_handler = handler

    async def hole_punch(
        self,
        endpoint: PeerEndpoint,
        punch_data: bytes = b"PUNCH",
        max_attempts: int = HOLE_PUNCH_ATTEMPTS,
    ) -> Optional[Tuple[str, int]]:
        """Attempt UDP hole punching to establish connection

        Args:
            endpoint: Peer endpoint to punch through to
            punch_data: Data to send in punch packets
            max_attempts: Maximum number of punch attempts per address

        Returns:
            Working address (ip, port) or None if punching failed
        """
        if not self._socket:
            await self.bind()

        addresses = endpoint.get_addresses()
        log.info(f"[UDP] Starting hole punch to {len(addresses)} address(es)")

        # Try each address
        for addr in addresses:
            log.debug(f"[UDP] Trying to punch through to {addr}")

            # Send multiple punch packets
            for attempt in range(max_attempts):
                try:
                    await self.send(punch_data, addr)
                    log.debug(f"[UDP] Sent punch packet {attempt + 1}/{max_attempts} to {addr}")
                except Exception as e:
                    log.debug(f"[UDP] Punch send failed: {e}")

                # Wait a bit between sends
                await asyncio.sleep(HOLE_PUNCH_INTERVAL)

                # Check if we received a response (reply from other side, or HELLO if they initiated first)
                try:
                    data, recv_addr = await asyncio.wait_for(
                        self._pending_receives.get(),
                        timeout=HOLE_PUNCH_RECV_TIMEOUT,
                    )

                    # Check if response is from expected peer (or their external address)
                    if recv_addr[0] == addr[0] or recv_addr[0] == endpoint.external_ip:
                        log.info(f"[UDP] Hole punch successful! Connected via {recv_addr}")
                        # If it's not a PUNCH reply (e.g. encrypted HELLO from them), put back for handshake
                        if not data.startswith(b"PUNCH"):
                            await self._pending_receives.put((data, recv_addr))
                        return recv_addr

                    # Put back if not from expected peer
                    await self._pending_receives.put((data, recv_addr))

                except asyncio.TimeoutError:
                    continue

        log.warning(f"[UDP] Hole punch failed after {max_attempts} attempts per address")
        return None

    async def _receive_loop(self):
        """Background loop to receive packets"""
        loop = asyncio.get_event_loop()

        while self._running and self._socket:
            try:
                data, addr = await loop.sock_recvfrom(self._socket, 65535)

                # Reply to PUNCH so hole punch succeeds (other side gets a response)
                if data.startswith(b"PUNCH"):
                    try:
                        await self.send(data, addr)
                        log.debug(f"[UDP] Sent punch reply to {addr}")
                    except Exception as e:
                        log.debug(f"[UDP] Punch reply failed: {e}")

                # Check for specific handler
                handler = self._handlers.get(addr)
                if handler:
                    try:
                        handler(data, addr)
                    except Exception as e:
                        log.warning(f"[UDP] Handler error for {addr}: {e}")
                elif self._default_handler:
                    try:
                        self._default_handler(data, addr)
                    except Exception as e:
                        log.warning(f"[UDP] Default handler error: {e}")
                else:
                    # Queue for recv() calls (e.g. hole punch initiator waiting for reply)
                    await self._pending_receives.put((data, addr))

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    log.debug(f"[UDP] Receive error: {e}")
                await asyncio.sleep(0.1)

        log.debug("[UDP] Receive loop ended")


class UDPProtocol(asyncio.DatagramProtocol):
    """Alternative asyncio-native UDP protocol"""

    def __init__(self):
        self.transport: Optional[asyncio.DatagramTransport] = None
        self._receive_queue: asyncio.Queue = asyncio.Queue()
        self._handlers: Dict[Tuple[str, int], Callable] = {}
        self._default_handler: Optional[Callable] = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        handler = self._handlers.get(addr)
        if handler:
            handler(data, addr)
        elif self._default_handler:
            self._default_handler(data, addr)
        else:
            self._receive_queue.put_nowait((data, addr))

    def error_received(self, exc: Exception):
        log.warning(f"[UDP] Protocol error: {exc}")

    def connection_lost(self, exc: Optional[Exception]):
        if exc:
            log.warning(f"[UDP] Connection lost: {exc}")
