#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rift Classic (game mode JADE)

Classic games spawn separate Jade_<Champion> characters, so regular skin mods
(<champion>/skins/skin0.bin) are never loaded there. Rose injects the Classic
skins stored in LeagueSkins' classic/ folder instead (%LOCALAPPDATA%/Rose/classic),
which target Jade_<Champion>'s default skin.

The client reports Classic champions and skins with offset IDs (60000+ and
60000000+), while the Classic library is stored under the regular IDs.
"""

import re
from typing import Optional

JADE_GAME_MODE = "JADE"
CLASSIC_CHAMPION_ID_OFFSET = 60_000
CLASSIC_SKIN_ID_OFFSET = CLASSIC_CHAMPION_ID_OFFSET * 1000

_INJECTION_NAME_RE = re.compile(r"^(skin|chroma)_(\d+)$")


def is_classic_game_mode(game_mode: Optional[str]) -> bool:
    return isinstance(game_mode, str) and game_mode.upper() == JADE_GAME_MODE


def to_regular_champion_id(champion_id: Optional[int]) -> Optional[int]:
    """Map a Rift Classic champion ID (60001) to the regular one (1)."""
    if champion_id is not None and champion_id >= CLASSIC_CHAMPION_ID_OFFSET:
        return champion_id - CLASSIC_CHAMPION_ID_OFFSET
    return champion_id


def to_regular_skin_id(skin_id: Optional[int]) -> Optional[int]:
    """Map a Rift Classic skin or chroma ID (60001001) to the regular one (1001)."""
    if skin_id is not None and skin_id >= CLASSIC_SKIN_ID_OFFSET:
        return skin_id - CLASSIC_SKIN_ID_OFFSET
    return skin_id


def to_regular_skin_name(skin_name: str) -> str:
    """Map a Rift Classic injection name (skin_60001001) to the regular one (skin_1001)."""
    match = _INJECTION_NAME_RE.match(skin_name or "")
    if not match:
        return skin_name
    return f"{match.group(1)}_{to_regular_skin_id(int(match.group(2)))}"
