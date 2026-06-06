#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Token Encoding/Decoding
Compact, shareable tokens for party connection establishment via WebSocket relay.
"""

import base64
import secrets
import struct
import time
import zlib
from dataclasses import dataclass
from typing import Optional

from utils.core.logging import get_logger

log = get_logger()

# Token prefix for identification
TOKEN_PREFIX = "ROSE:"
# Token version (v2 = WebSocket relay, no IP/port needed)
TOKEN_VERSION = 2
# Token expiration time (1 hour)
TOKEN_EXPIRY_SECONDS = 3600


@dataclass
class PartyToken:
    """Party connection token containing info needed to connect via relay.

    v2 format: no IP/port fields since relay handles connectivity.
    Only summoner_id + encryption_key are needed.
    """

    summoner_id: int            # League summoner ID
    encryption_key: bytes       # 32-byte encryption key
    timestamp: int              # Token creation time (Unix timestamp)
    version: int = TOKEN_VERSION

    def encode(self) -> str:
        """Encode token to compact base64 string.

        Format (binary, before compression):
        - version (1 byte)
        - timestamp (4 bytes, uint32)
        - summoner_id (8 bytes, uint64)
        - encryption_key (32 bytes)

        Total: 45 bytes before compression

        Returns:
            String like "ROSE:abc123..." suitable for sharing
        """
        try:
            data = struct.pack(
                ">BIQ",
                self.version,
                self.timestamp,
                self.summoner_id,
            )
            data += self.encryption_key

            compressed = zlib.compress(data, level=9)
            encoded = base64.urlsafe_b64encode(compressed).decode("ascii")
            encoded = encoded.rstrip("=")

            return TOKEN_PREFIX + encoded

        except Exception as e:
            log.error(f"[TOKEN] Failed to encode token: {e}")
            raise ValueError(f"Token encoding failed: {e}")

    @classmethod
    def decode(cls, token_str: str) -> "PartyToken":
        """Decode token from base64 string.

        Supports both v1 (legacy P2P with IP/port) and v2 (relay-only) tokens.

        Args:
            token_str: Token string (with or without ROSE: prefix)

        Returns:
            PartyToken instance

        Raises:
            ValueError: If token is invalid or expired
        """
        try:
            if token_str.startswith(TOKEN_PREFIX):
                token_str = token_str[len(TOKEN_PREFIX):]

            padding = 4 - (len(token_str) % 4)
            if padding != 4:
                token_str += "=" * padding

            compressed = base64.urlsafe_b64decode(token_str.encode("ascii"))
            data = zlib.decompress(compressed)

            if len(data) < 13:
                raise ValueError("Token data too short")

            version = data[0]

            if version == 1:
                # Legacy v1 token: has IP/port fields
                if len(data) < 57:
                    raise ValueError("Token data too short for v1")
                _, timestamp, summoner_id, _, _ = struct.unpack(">BIQHH", data[:17])
                encryption_key = data[25:57]
            elif version == 2:
                # v2 token: relay-only, no IP/port
                if len(data) < 45:
                    raise ValueError("Token data too short for v2")
                _, timestamp, summoner_id = struct.unpack(">BIQ", data[:13])
                encryption_key = data[13:45]
            else:
                raise ValueError(f"Unsupported token version: {version}")

            if len(encryption_key) != 32:
                raise ValueError("Invalid encryption key length")

            token = cls(
                version=version,
                timestamp=timestamp,
                summoner_id=summoner_id,
                encryption_key=encryption_key,
            )

            if token.is_expired():
                raise ValueError("Token has expired")

            return token

        except zlib.error as e:
            raise ValueError(f"Token decompression failed: {e}")
        except ValueError:
            raise
        except Exception as e:
            log.error(f"[TOKEN] Failed to decode token: {e}")
            raise ValueError(f"Token decoding failed: {e}")

    def is_expired(self) -> bool:
        return time.time() > (self.timestamp + TOKEN_EXPIRY_SECONDS)

    def time_until_expiry(self) -> int:
        return int(self.timestamp + TOKEN_EXPIRY_SECONDS - time.time())

    def __str__(self) -> str:
        expiry = self.time_until_expiry()
        expiry_str = f"{expiry}s" if expiry > 0 else "EXPIRED"
        return f"PartyToken(summoner={self.summoner_id}, expires_in={expiry_str})"


def create_token(
    summoner_id: int,
    encryption_key: Optional[bytes] = None,
) -> PartyToken:
    """Create a new party token.

    Args:
        summoner_id: League summoner ID
        encryption_key: Optional 32-byte key (generated if not provided)

    Returns:
        PartyToken instance
    """
    if encryption_key is None:
        encryption_key = secrets.token_bytes(32)

    return PartyToken(
        summoner_id=summoner_id,
        encryption_key=encryption_key,
        timestamp=int(time.time()),
    )
