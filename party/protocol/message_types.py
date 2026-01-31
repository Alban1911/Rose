#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Mode Message Types
Protocol message definitions for P2P communication
"""

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Optional

from utils.core.logging import get_logger

log = get_logger()


class MessageType(Enum):
    """Types of P2P messages"""

    # Connection management
    PING = "ping"
    PONG = "pong"
    HELLO = "hello"          # Initial handshake
    HELLO_ACK = "hello_ack"  # Handshake acknowledgment

    # Skin sharing
    SKIN_UPDATE = "skin_update"    # Single skin selection update
    SKIN_SYNC = "skin_sync"        # Full skin state sync request/response
    SKIN_CLEAR = "skin_clear"      # Clear skin selection

    # Lobby coordination
    LOBBY_INFO = "lobby_info"      # Share lobby/summoner info
    LOBBY_MATCH = "lobby_match"    # Confirm same lobby
    READY = "ready"                # Ready for injection

    # Errors
    ERROR = "error"


@dataclass
class Message:
    """P2P protocol message"""

    type: MessageType
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    sequence: int = 0

    def to_bytes(self) -> bytes:
        """Serialize message to bytes for transmission"""
        data = {
            "type": self.type.value,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "sequence": self.sequence,
        }
        return json.dumps(data, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> "Message":
        """Deserialize message from bytes"""
        try:
            parsed = json.loads(data.decode("utf-8"))
            return cls(
                type=MessageType(parsed["type"]),
                payload=parsed.get("payload", {}),
                timestamp=parsed.get("timestamp", time.time()),
                sequence=parsed.get("sequence", 0),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            log.warning(f"[MSG] Failed to parse message: {e}")
            raise ValueError(f"Invalid message format: {e}")


@dataclass
class SkinSelection:
    """Skin selection data for a single champion"""

    summoner_id: int
    summoner_name: str
    champion_id: int
    skin_id: int
    chroma_id: Optional[int] = None
    custom_mod_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for message payload"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkinSelection":
        """Create from dictionary"""
        return cls(
            summoner_id=data["summoner_id"],
            summoner_name=data.get("summoner_name", "Unknown"),
            champion_id=data["champion_id"],
            skin_id=data["skin_id"],
            chroma_id=data.get("chroma_id"),
            custom_mod_path=data.get("custom_mod_path"),
        )


# Message factory functions
def create_hello(summoner_id: int, summoner_name: str, encryption_key: bytes) -> Message:
    """Create HELLO handshake message"""
    return Message(
        type=MessageType.HELLO,
        payload={
            "summoner_id": summoner_id,
            "summoner_name": summoner_name,
            "key": encryption_key.hex(),
            "version": 1,
        },
    )


def create_hello_ack(summoner_id: int, summoner_name: str) -> Message:
    """Create HELLO_ACK response"""
    return Message(
        type=MessageType.HELLO_ACK,
        payload={
            "summoner_id": summoner_id,
            "summoner_name": summoner_name,
        },
    )


def create_ping(sequence: int = 0) -> Message:
    """Create PING message"""
    return Message(type=MessageType.PING, sequence=sequence)


def create_pong(sequence: int = 0) -> Message:
    """Create PONG response"""
    return Message(type=MessageType.PONG, sequence=sequence)


def create_skin_update(selection: SkinSelection) -> Message:
    """Create SKIN_UPDATE message"""
    return Message(
        type=MessageType.SKIN_UPDATE,
        payload=selection.to_dict(),
    )


def create_skin_sync(selections: list[SkinSelection]) -> Message:
    """Create SKIN_SYNC message with all skin selections"""
    return Message(
        type=MessageType.SKIN_SYNC,
        payload={
            "selections": [s.to_dict() for s in selections],
        },
    )


def create_skin_clear(summoner_id: int, champion_id: int) -> Message:
    """Create SKIN_CLEAR message"""
    return Message(
        type=MessageType.SKIN_CLEAR,
        payload={
            "summoner_id": summoner_id,
            "champion_id": champion_id,
        },
    )


def create_lobby_info(
    summoner_id: int,
    lobby_summoner_ids: list[int],
    game_mode: Optional[str] = None,
) -> Message:
    """Create LOBBY_INFO message"""
    return Message(
        type=MessageType.LOBBY_INFO,
        payload={
            "summoner_id": summoner_id,
            "lobby_summoner_ids": lobby_summoner_ids,
            "game_mode": game_mode,
        },
    )


def create_lobby_match(matched: bool, common_summoner_ids: list[int]) -> Message:
    """Create LOBBY_MATCH confirmation"""
    return Message(
        type=MessageType.LOBBY_MATCH,
        payload={
            "matched": matched,
            "common_summoner_ids": common_summoner_ids,
        },
    )


def create_ready() -> Message:
    """Create READY message"""
    return Message(type=MessageType.READY)


def create_error(code: str, message: str) -> Message:
    """Create ERROR message"""
    return Message(
        type=MessageType.ERROR,
        payload={
            "code": code,
            "message": message,
        },
    )
