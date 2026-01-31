#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Token Encoding/Decoding
Compact, shareable tokens for P2P connection establishment
"""

import base64
import struct
import time
import zlib
from dataclasses import dataclass
from typing import Optional

from utils.core.logging import get_logger

log = get_logger()

# Token prefix for identification
TOKEN_PREFIX = "ROSE:"
# Token version
TOKEN_VERSION = 1
# Token expiration time (1 hour)
TOKEN_EXPIRY_SECONDS = 3600


@dataclass
class PartyToken:
    """Party connection token containing all info needed to establish P2P connection"""

    external_ip: str            # External IP address (from STUN)
    external_port: int          # External UDP port (from STUN)
    internal_ip: str            # Internal/LAN IP address
    internal_port: int          # Internal UDP port
    summoner_id: int            # League summoner ID
    encryption_key: bytes       # 32-byte encryption key
    timestamp: int              # Token creation time (Unix timestamp)
    version: int = TOKEN_VERSION

    def encode(self) -> str:
        """Encode token to compact base64 string

        Format (binary, before compression):
        - version (1 byte)
        - timestamp (4 bytes, uint32)
        - summoner_id (8 bytes, uint64)
        - external_port (2 bytes, uint16)
        - internal_port (2 bytes, uint16)
        - external_ip (4 bytes for IPv4)
        - internal_ip (4 bytes for IPv4)
        - encryption_key (32 bytes)

        Total: 57 bytes before compression

        Returns:
            String like "ROSE:abc123..." suitable for sharing
        """
        try:
            # Pack external IP
            ext_ip_bytes = self._ip_to_bytes(self.external_ip)
            int_ip_bytes = self._ip_to_bytes(self.internal_ip)

            # Pack all data
            data = struct.pack(
                ">BIQHH",
                self.version,
                self.timestamp,
                self.summoner_id,
                self.external_port,
                self.internal_port,
            )
            data += ext_ip_bytes + int_ip_bytes + self.encryption_key

            # Compress
            compressed = zlib.compress(data, level=9)

            # Base64 encode with URL-safe alphabet
            encoded = base64.urlsafe_b64encode(compressed).decode("ascii")

            # Remove padding for shorter token
            encoded = encoded.rstrip("=")

            return TOKEN_PREFIX + encoded

        except Exception as e:
            log.error(f"[TOKEN] Failed to encode token: {e}")
            raise ValueError(f"Token encoding failed: {e}")

    @classmethod
    def decode(cls, token_str: str) -> "PartyToken":
        """Decode token from base64 string

        Args:
            token_str: Token string (with or without ROSE: prefix)

        Returns:
            PartyToken instance

        Raises:
            ValueError: If token is invalid or expired
        """
        try:
            # Remove prefix if present
            if token_str.startswith(TOKEN_PREFIX):
                token_str = token_str[len(TOKEN_PREFIX):]

            # Restore base64 padding
            padding = 4 - (len(token_str) % 4)
            if padding != 4:
                token_str += "=" * padding

            # Base64 decode
            compressed = base64.urlsafe_b64decode(token_str.encode("ascii"))

            # Decompress
            data = zlib.decompress(compressed)

            # Unpack header
            if len(data) < 57:  # Minimum expected size
                raise ValueError("Token data too short")

            version, timestamp, summoner_id, ext_port, int_port = struct.unpack(
                ">BIQHH", data[:17]
            )

            if version != TOKEN_VERSION:
                raise ValueError(f"Unsupported token version: {version}")

            # Unpack IPs and key
            ext_ip = cls._bytes_to_ip(data[17:21])
            int_ip = cls._bytes_to_ip(data[21:25])
            encryption_key = data[25:57]

            if len(encryption_key) != 32:
                raise ValueError("Invalid encryption key length")

            token = cls(
                version=version,
                timestamp=timestamp,
                summoner_id=summoner_id,
                external_ip=ext_ip,
                external_port=ext_port,
                internal_ip=int_ip,
                internal_port=int_port,
                encryption_key=encryption_key,
            )

            # Check expiration
            if token.is_expired():
                raise ValueError("Token has expired")

            return token

        except zlib.error as e:
            raise ValueError(f"Token decompression failed: {e}")
        except Exception as e:
            log.error(f"[TOKEN] Failed to decode token: {e}")
            raise ValueError(f"Token decoding failed: {e}")

    def is_expired(self) -> bool:
        """Check if token has expired"""
        return time.time() > (self.timestamp + TOKEN_EXPIRY_SECONDS)

    def time_until_expiry(self) -> int:
        """Get seconds until token expires (negative if expired)"""
        return int(self.timestamp + TOKEN_EXPIRY_SECONDS - time.time())

    @staticmethod
    def _ip_to_bytes(ip: str) -> bytes:
        """Convert IPv4 address string to 4 bytes"""
        parts = ip.split(".")
        if len(parts) != 4:
            raise ValueError(f"Invalid IPv4 address: {ip}")
        return bytes(int(p) for p in parts)

    @staticmethod
    def _bytes_to_ip(data: bytes) -> str:
        """Convert 4 bytes to IPv4 address string"""
        if len(data) != 4:
            raise ValueError("IP bytes must be 4 bytes")
        return ".".join(str(b) for b in data)

    def __str__(self) -> str:
        """Human-readable representation"""
        expiry = self.time_until_expiry()
        expiry_str = f"{expiry}s" if expiry > 0 else "EXPIRED"
        return (
            f"PartyToken(summoner={self.summoner_id}, "
            f"ext={self.external_ip}:{self.external_port}, "
            f"int={self.internal_ip}:{self.internal_port}, "
            f"expires_in={expiry_str})"
        )


def create_token(
    external_ip: str,
    external_port: int,
    internal_ip: str,
    internal_port: int,
    summoner_id: int,
    encryption_key: Optional[bytes] = None,
) -> PartyToken:
    """Create a new party token

    Args:
        external_ip: External IP address from STUN
        external_port: External UDP port from STUN
        internal_ip: Internal/LAN IP address
        internal_port: Internal UDP port
        summoner_id: League summoner ID
        encryption_key: Optional 32-byte key (generated if not provided)

    Returns:
        PartyToken instance
    """
    from .crypto import PartyCrypto

    if encryption_key is None:
        encryption_key = PartyCrypto.generate_key()

    return PartyToken(
        external_ip=external_ip,
        external_port=external_port,
        internal_ip=internal_ip,
        internal_port=internal_port,
        summoner_id=summoner_id,
        encryption_key=encryption_key,
        timestamp=int(time.time()),
    )
