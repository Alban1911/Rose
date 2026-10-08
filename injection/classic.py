#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rift Classic (game mode JADE)

Classic games spawn separate Jade_<Champion> characters, so regular skin mods
(<champion>/skins/skin0.bin) are never loaded there. Rose injects the Classic
skins stored in LeagueSkins' classic/ folder instead (%LOCALAPPDATA%/Rose/classic),
which target Jade_<Champion>'s default skin.

The client reports Classic champions and skins with offset IDs (60103 and
60103001 for Ahri and Dynasty Ahri). The Classic library keeps each champion
under its Classic ID, the Classic version of a regular skin or chroma under the
regular ID (classic/60103/103001) and a skin that only exists in Rift Classic
under its Classic ID (classic/60103/60103301).
"""

import re
from pathlib import Path
from typing import Optional

JADE_GAME_MODE = "JADE"
CLASSIC_CHAMPION_ID_OFFSET = 60_000
CLASSIC_SKIN_ID_OFFSET = CLASSIC_CHAMPION_ID_OFFSET * 1000

_INJECTION_NAME_RE = re.compile(r"^(skin|chroma)_(\d+)$")


def is_classic_game_mode(game_mode: Optional[str]) -> bool:
    return isinstance(game_mode, str) and game_mode.upper() == JADE_GAME_MODE


def is_classic_champion_id(champion_id: object) -> bool:
    try:
        value = int(champion_id)
    except (TypeError, ValueError):
        return False
    return CLASSIC_CHAMPION_ID_OFFSET < value < CLASSIC_CHAMPION_ID_OFFSET + 1000


def is_default_skin_for_state(state, skin_id: Optional[int]) -> bool:
    if skin_id is None:
        return False
    if (
        is_classic_game_mode(getattr(state, "current_game_mode", None))
        or is_classic_champion_id(int(skin_id) // 1000)
    ):
        selected = to_regular_skin_id(int(skin_id))
        champion_id = to_regular_champion_id(int(skin_id) // 1000)
        fallback = to_classic_champion_id(champion_id) * 1000
        default = to_regular_skin_id(
            getattr(state, "classic_default_skin_id", fallback)
        )
        return selected is not None and selected == default
    return int(skin_id) % 1000 == 0


def default_skin_id_for_state(state, champion_id: int) -> Optional[int]:
    if (
        is_classic_game_mode(getattr(state, "current_game_mode", None))
        or is_classic_champion_id(champion_id)
    ):
        mode_champion_id = int(to_classic_champion_id(champion_id) or 0)
        return getattr(
            state, "classic_default_skin_id", mode_champion_id * 1000
        )
    return int(champion_id) * 1000


def to_classic_champion_id(champion_id: Optional[int]) -> Optional[int]:
    """Map a regular champion ID (1) to the Rift Classic one (60001)."""
    if champion_id is not None and 0 < champion_id < CLASSIC_CHAMPION_ID_OFFSET:
        return champion_id + CLASSIC_CHAMPION_ID_OFFSET
    return champion_id


def to_regular_champion_id(champion_id: Optional[int]) -> Optional[int]:
    """Map a Rift Classic champion ID (60055) to its resource ID (55)."""
    if champion_id is not None and is_classic_champion_id(champion_id):
        return int(champion_id) - CLASSIC_CHAMPION_ID_OFFSET
    return champion_id


def to_classic_skin_id(skin_id: Optional[int]) -> Optional[int]:
    """Map a resource skin ID to the full Rift Classic LCU ID."""
    if skin_id is None:
        return None
    value = int(skin_id)
    if is_classic_champion_id(value // 1000):
        return value
    if value <= 0 or value // 1000 >= 1000:
        raise ValueError(f"Invalid skin ID: {skin_id!r}")
    return value + CLASSIC_SKIN_ID_OFFSET


def to_regular_skin_id(skin_id: Optional[int]) -> Optional[int]:
    """Map a Rift Classic skin or chroma ID (60001001) to the regular one (1001)."""
    if skin_id is not None and skin_id >= CLASSIC_SKIN_ID_OFFSET:
        return skin_id - CLASSIC_SKIN_ID_OFFSET
    return skin_id


def classic_catalog_skin_ids(catalog: object, champion_id: int) -> set[int]:
    """Return canonical resource IDs from a bounded Classic catalog payload."""
    if not isinstance(catalog, list) or not (1 <= len(catalog) <= 256):
        return set()
    result = set()
    for entry in catalog:
        value = entry.get("id", entry.get("skinId")) if isinstance(entry, dict) else entry
        try:
            skin_id = int(to_regular_skin_id(int(value)) or 0)
        except (TypeError, ValueError):
            continue
        if skin_id > 0 and skin_id // 1000 == int(champion_id):
            result.add(skin_id)
    return result


def to_library_id(champion_dir: Path, skin_id: Optional[int]) -> Optional[int]:
    """The ID a Classic skin or chroma is stored under in its champion's library folder."""
    regular_id = to_regular_skin_id(skin_id)
    if regular_id != skin_id and (
        (champion_dir / str(regular_id)).is_dir()  # a skin
        or any(champion_dir.glob(f"*/{regular_id}"))  # a chroma, inside its skin
    ):
        return regular_id
    return skin_id


def to_library_skin_name(champion_dir: Path, skin_name: str) -> str:
    """Map an injection name (skin_60001001) to the ID the Classic library stores it under."""
    match = _INJECTION_NAME_RE.match(skin_name or "")
    if not match:
        return skin_name
    return f"{match.group(1)}_{to_library_id(champion_dir, int(match.group(2)))}"
