#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stable automatic Party Mode room selection.

The room is derived from the premade lobby members, then frozen across queue,
ready-check, champion select, and the game. Random matchmade teammates are
never used to change the room.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Optional, Tuple


AUTO_ROOM_NAMESPACE = "rose-private-auto-party-v1"

DISCOVERY_PHASES = {"Lobby", "Matchmaking", "ReadyCheck"}
HOLD_PHASES = {
    "Matchmaking",
    "ReadyCheck",
    "ChampSelect",
    "GameStart",
    "Reconnect",
    "InProgress",
}
RESET_PHASES = {
    "PreEndOfGame",
    "EndOfGame",
    "WaitingForStats",
    "TerminatedInError",
}


def normalize_lobby_members(
    summoner_ids: Iterable[int],
    my_summoner_id: int,
) -> Tuple[int, ...]:
    members = {
        int(value)
        for value in summoner_ids
        if int(value) > 0
    }
    if int(my_summoner_id) not in members or len(members) < 2:
        return ()
    return tuple(sorted(members))


def compute_auto_room_key(members: Iterable[int]) -> str:
    normalized = tuple(sorted({int(value) for value in members}))
    payload = (
        AUTO_ROOM_NAMESPACE
        + ":"
        + ",".join(str(value) for value in normalized)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass
class AutoLobbyRoom:
    """State machine that prevents room churn during game transitions."""

    active_room_key: Optional[str] = None
    lobby_members: Tuple[int, ...] = field(default_factory=tuple)

    def restore(
        self,
        room_key: Optional[str],
        lobby_members: Iterable[int],
    ) -> None:
        members = tuple(sorted({int(value) for value in lobby_members}))
        if room_key and len(members) >= 2:
            self.active_room_key = str(room_key)
            self.lobby_members = members

    def update(
        self,
        phase: str,
        premade_lobby_ids: Iterable[int],
        my_summoner_id: int,
    ) -> Optional[str]:
        phase = str(phase or "")
        members = normalize_lobby_members(
            premade_lobby_ids,
            my_summoner_id,
        )

        # Lobby membership is authoritative before matchmaking. If somebody
        # joins or leaves, every Rose client derives the same replacement room.
        if phase in DISCOVERY_PHASES and members:
            room_key = compute_auto_room_key(members)
            self.active_room_key = room_key
            self.lobby_members = members
            return room_key

        # In the plain lobby, a one-person lobby means the premade disbanded.
        if phase == "Lobby" and not members:
            self.clear()
            return None

        # Once matchmaking starts, never derive from champion-select myTeam:
        # that list contains matchmade strangers and can change visibility.
        if phase in HOLD_PHASES:
            return self.active_room_key

        if phase in RESET_PHASES:
            self.clear()
            return None

        return self.active_room_key

    def clear(self) -> None:
        self.active_room_key = None
        self.lobby_members = ()
