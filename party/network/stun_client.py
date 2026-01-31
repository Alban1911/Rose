#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STUN Client for NAT Discovery
Implements RFC 5389 STUN protocol to discover external IP and port
"""

import asyncio
import os
import socket
import struct
from dataclasses import dataclass
from typing import Optional, Tuple

from utils.core.logging import get_logger

log = get_logger()

# STUN message types
STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101

# STUN attributes
STUN_ATTR_MAPPED_ADDRESS = 0x0001
STUN_ATTR_XOR_MAPPED_ADDRESS = 0x0020

# STUN magic cookie (RFC 5389)
STUN_MAGIC_COOKIE = 0x2112A442

# Public STUN servers
STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
    ("stun2.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
    ("stun.stunprotocol.org", 3478),
]


@dataclass
class StunResult:
    """Result of STUN discovery"""
    external_ip: str
    external_port: int
    local_ip: str
    local_port: int


class StunClient:
    """STUN client for NAT type discovery and external address resolution"""

    def __init__(self, timeout: float = 3.0):
        """Initialize STUN client

        Args:
            timeout: Timeout for STUN requests in seconds
        """
        self.timeout = timeout

    def _create_binding_request(self) -> Tuple[bytes, bytes]:
        """Create a STUN Binding Request message

        Returns:
            Tuple of (message bytes, transaction ID)
        """
        # Generate random transaction ID (12 bytes)
        transaction_id = os.urandom(12)

        # STUN header: type (2) + length (2) + magic cookie (4) + transaction ID (12)
        # Binding Request with no attributes has length 0
        header = struct.pack(
            ">HHI",
            STUN_BINDING_REQUEST,
            0,  # Message length (no attributes)
            STUN_MAGIC_COOKIE,
        )

        message = header + transaction_id
        return message, transaction_id

    def _parse_binding_response(
        self, data: bytes, transaction_id: bytes
    ) -> Optional[Tuple[str, int]]:
        """Parse a STUN Binding Response

        Args:
            data: Response data
            transaction_id: Expected transaction ID

        Returns:
            Tuple of (external_ip, external_port) or None if parsing fails
        """
        if len(data) < 20:
            log.debug("[STUN] Response too short")
            return None

        # Parse header
        msg_type, msg_length, magic_cookie = struct.unpack(">HHI", data[:8])
        resp_transaction_id = data[8:20]

        # Verify message type
        if msg_type != STUN_BINDING_RESPONSE:
            log.debug(f"[STUN] Unexpected message type: {msg_type:#x}")
            return None

        # Verify magic cookie
        if magic_cookie != STUN_MAGIC_COOKIE:
            log.debug(f"[STUN] Invalid magic cookie: {magic_cookie:#x}")
            return None

        # Verify transaction ID
        if resp_transaction_id != transaction_id:
            log.debug("[STUN] Transaction ID mismatch")
            return None

        # Parse attributes
        offset = 20
        while offset < len(data):
            if offset + 4 > len(data):
                break

            attr_type, attr_length = struct.unpack(">HH", data[offset : offset + 4])
            offset += 4

            if offset + attr_length > len(data):
                break

            attr_value = data[offset : offset + attr_length]

            # XOR-MAPPED-ADDRESS (preferred) or MAPPED-ADDRESS
            if attr_type == STUN_ATTR_XOR_MAPPED_ADDRESS:
                result = self._parse_xor_mapped_address(attr_value, transaction_id)
                if result:
                    return result
            elif attr_type == STUN_ATTR_MAPPED_ADDRESS:
                result = self._parse_mapped_address(attr_value)
                if result:
                    return result

            # Align to 4-byte boundary
            offset += attr_length
            if attr_length % 4 != 0:
                offset += 4 - (attr_length % 4)

        log.debug("[STUN] No mapped address found in response")
        return None

    def _parse_xor_mapped_address(
        self, data: bytes, transaction_id: bytes
    ) -> Optional[Tuple[str, int]]:
        """Parse XOR-MAPPED-ADDRESS attribute"""
        if len(data) < 8:
            return None

        # Format: reserved (1) + family (1) + port (2) + address (4 or 16)
        family = data[1]
        xor_port = struct.unpack(">H", data[2:4])[0]

        # XOR with magic cookie upper 16 bits
        port = xor_port ^ (STUN_MAGIC_COOKIE >> 16)

        if family == 0x01:  # IPv4
            xor_addr = struct.unpack(">I", data[4:8])[0]
            addr = xor_addr ^ STUN_MAGIC_COOKIE
            ip = socket.inet_ntoa(struct.pack(">I", addr))
            return ip, port
        elif family == 0x02:  # IPv6
            # IPv6 XOR with magic cookie + transaction ID
            if len(data) < 20:
                return None
            xor_addr = data[4:20]
            magic_bytes = struct.pack(">I", STUN_MAGIC_COOKIE) + transaction_id
            addr_bytes = bytes(a ^ b for a, b in zip(xor_addr, magic_bytes))
            ip = socket.inet_ntop(socket.AF_INET6, addr_bytes)
            return ip, port

        return None

    def _parse_mapped_address(self, data: bytes) -> Optional[Tuple[str, int]]:
        """Parse MAPPED-ADDRESS attribute (non-XOR)"""
        if len(data) < 8:
            return None

        family = data[1]
        port = struct.unpack(">H", data[2:4])[0]

        if family == 0x01:  # IPv4
            ip = socket.inet_ntoa(data[4:8])
            return ip, port
        elif family == 0x02:  # IPv6
            if len(data) < 20:
                return None
            ip = socket.inet_ntop(socket.AF_INET6, data[4:20])
            return ip, port

        return None

    async def discover(self, local_socket: Optional[socket.socket] = None) -> Optional[StunResult]:
        """Discover external IP and port using STUN

        Args:
            local_socket: When provided, use this socket for the STUN query so the
                returned external address is the one peers must use to reach us.

        Returns:
            StunResult with external and local addresses, or None if discovery fails
        """
        try:
            if local_socket is not None:
                return await self._discover_with_socket(local_socket)

            local_ip = self._get_local_ip()
            for server_host, server_port in STUN_SERVERS:
                try:
                    result = await self._query_stun_server(
                        None, server_host, server_port
                    )
                    if result:
                        external_ip, external_port = result
                        log.info(
                            f"[STUN] Discovered external address: {external_ip}:{external_port} "
                            f"(local: {local_ip}) via {server_host}"
                        )
                        return StunResult(
                            external_ip=external_ip,
                            external_port=external_port,
                            local_ip=local_ip,
                            local_port=0,
                        )
                except Exception as e:
                    log.debug(f"[STUN] Failed to query {server_host}: {e}")
                    continue

            log.warning("[STUN] All STUN servers failed")
            return None

        except Exception as e:
            log.error(f"[STUN] Discovery error: {e}")
            return None

    async def _discover_with_socket(self, sock: socket.socket) -> Optional[StunResult]:
        """Discover external address using the given bound socket (async, no new socket)."""
        loop = asyncio.get_event_loop()
        try:
            bound_ip, local_port = sock.getsockname()[:2]
            # Bind address 0.0.0.0 is not valid for token (can't send to it); use real LAN IP
            local_ip = self._get_local_ip() if bound_ip == "0.0.0.0" else bound_ip
        except OSError:
            local_ip = self._get_local_ip()
            local_port = 0

        for server_host, server_port in STUN_SERVERS:
            try:
                addr_info = socket.getaddrinfo(
                    server_host, server_port, socket.AF_INET, socket.SOCK_DGRAM
                )
                if not addr_info:
                    continue
                server_addr = addr_info[0][4]
                request, transaction_id = self._create_binding_request()

                await loop.sock_sendto(sock, request, server_addr)
                data, _ = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 1024),
                    timeout=self.timeout,
                )
                result = self._parse_binding_response(data, transaction_id)
                if result:
                    external_ip, external_port = result
                    log.info(
                        f"[STUN] Discovered external address: {external_ip}:{external_port} "
                        f"(local: {local_ip}:{local_port}) via {server_host}"
                    )
                    return StunResult(
                        external_ip=external_ip,
                        external_port=external_port,
                        local_ip=local_ip,
                        local_port=local_port,
                    )
            except asyncio.TimeoutError:
                log.debug(f"[STUN] Timeout waiting for response from {server_host}")
                continue
            except Exception as e:
                log.debug(f"[STUN] Failed to query {server_host}: {e}")
                continue

        log.warning("[STUN] All STUN servers failed (with socket)")
        return None

    async def _query_stun_server(
        self, sock: socket.socket, host: str, port: int
    ) -> Optional[Tuple[str, int]]:
        """Query a single STUN server

        Args:
            sock: UDP socket to use
            host: STUN server hostname
            port: STUN server port

        Returns:
            Tuple of (external_ip, external_port) or None
        """
        loop = asyncio.get_event_loop()

        # Run blocking STUN query in thread executor (more reliable on Windows)
        def blocking_query():
            try:
                # Resolve hostname
                addr_info = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)
                if not addr_info:
                    return None
                server_addr = addr_info[0][4]

                # Create request
                request, transaction_id = self._create_binding_request()

                # Create a new socket for this query (avoid state issues)
                query_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                query_sock.settimeout(self.timeout)
                query_sock.bind(("0.0.0.0", 0))

                try:
                    # Send request
                    query_sock.sendto(request, server_addr)

                    # Wait for response
                    data, _ = query_sock.recvfrom(1024)
                    return self._parse_binding_response(data, transaction_id), query_sock.getsockname()
                finally:
                    query_sock.close()

            except socket.timeout:
                log.debug(f"[STUN] Timeout waiting for response from {host}")
                return None
            except Exception as e:
                log.debug(f"[STUN] Error querying {host}: {e}")
                return None

        try:
            result = await loop.run_in_executor(None, blocking_query)
            if result and result[0]:
                return result[0]  # Return just the (ip, port) tuple
            return None
        except Exception as e:
            log.debug(f"[STUN] Query error for {host}: {e}")
            return None

    def _get_local_ip(self) -> str:
        """Get local IP address (best guess for LAN IP)"""
        try:
            # Create a dummy connection to determine local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
