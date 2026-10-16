"""Resolve Rift Classic's real default skin carrier from live LCU data."""

from collections.abc import Iterable
from typing import Optional

from injection.classic import (
    CLASSIC_CHAMPION_ID_OFFSET,
    is_classic_game_mode,
    to_classic_champion_id,
)


def is_classic_champion_id(champion_id: object) -> bool:
    try:
        value = int(champion_id)
    except (TypeError, ValueError):
        return False
    return CLASSIC_CHAMPION_ID_OFFSET < value < CLASSIC_CHAMPION_ID_OFFSET + 1000


def _skin_ids(values: object, champion_id: int) -> set[int]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes, dict)):
        return set()
    result = set()
    for entry in values:
        value = entry.get("id", entry.get("skinId")) if isinstance(entry, dict) else entry
        try:
            skin_id = int(value)
        except (TypeError, ValueError):
            continue
        if skin_id > 0 and skin_id // 1000 == champion_id:
            result.add(skin_id)
    return result


def resolve_classic_default_skin_id(
    champion_id: int,
    carousel: object,
    pickable_skin_ids: object,
) -> int:
    """Resolve the native Skin0/Skin301/Skin302 carrier from live catalogs."""
    mode_champion_id = int(to_classic_champion_id(champion_id) or 0)
    carousel_ids = _skin_ids(carousel, mode_champion_id)
    candidates = carousel_ids & _skin_ids(pickable_skin_ids, mode_champion_id)
    if not candidates:
        raise ValueError("Classic carrier is absent from the active catalog")

    declared = []
    if isinstance(carousel, list):
        for entry in carousel:
            if not isinstance(entry, dict) or not (entry.get("isBase") or entry.get("isDefault")):
                continue
            try:
                skin_id = int(entry.get("id", entry.get("skinId")))
            except (TypeError, ValueError):
                continue
            if skin_id in candidates:
                declared.append(skin_id)

    native_slots = sorted(skin_id for skin_id in candidates if skin_id % 1000 in (301, 302))
    if len(native_slots) == 1:
        return native_slots[0]
    declared_native = [skin_id for skin_id in declared if skin_id in native_slots]
    if len(declared_native) == 1:
        return declared_native[0]
    if len(native_slots) > 1:
        raise ValueError(f"Classic carrier is ambiguous: {native_slots}")
    if len(declared) == 1:
        return declared[0]

    skin0 = mode_champion_id * 1000
    if skin0 in candidates:
        return skin0
    raise ValueError("Classic catalog does not identify a native default carrier")


def cache_classic_default_skin_id(lcu, state, champion_id: int) -> Optional[int]:
    """Cache a verified carrier for the active champion; never invent Skin0."""
    if not (
        is_classic_game_mode(getattr(state, "current_game_mode", None))
        or is_classic_champion_id(champion_id)
    ):
        return None
    mode_champion_id = int(to_classic_champion_id(champion_id) or 0)
    cached = getattr(state, "classic_default_skin_id", None)
    if cached and int(cached) // 1000 == mode_champion_id:
        return int(cached)
    try:
        carrier = resolve_classic_default_skin_id(
            mode_champion_id,
            lcu.get("/lol-champ-select/v1/skin-carousel-skins"),
            lcu.get("/lol-lobby-team-builder/champ-select/v1/pickable-skin-ids"),
        )
    except (AttributeError, TypeError, ValueError):
        state.classic_default_skin_id = None
        return None
    state.classic_default_skin_id = carrier
    return carrier


def carrier_skin_id_for_force(lcu, state, requested_skin_id: int) -> int:
    """Replace a generated Classic Skin0 request with its verified carrier."""
    champion_id = getattr(state, "locked_champ_id", None) or getattr(
        state, "hovered_champ_id", None
    )
    if not (
        is_classic_game_mode(getattr(state, "current_game_mode", None))
        or is_classic_champion_id(champion_id)
    ):
        return int(requested_skin_id)
    carrier = cache_classic_default_skin_id(lcu, state, int(champion_id))
    if carrier is None:
        raise RuntimeError("Classic native carrier is unavailable; refusing Skin0 fallback")
    return carrier


def cached_classic_carrier_for_champion(state, champion_id: int) -> Optional[int]:
    """Return the cached carrier only when it belongs to this champion."""
    if not (
        is_classic_game_mode(getattr(state, "current_game_mode", None))
        or is_classic_champion_id(champion_id)
    ):
        return None
    mode_champion_id = int(to_classic_champion_id(champion_id) or 0)
    cached = getattr(state, "classic_default_skin_id", None)
    try:
        return int(cached) if cached and int(cached) // 1000 == mode_champion_id else None
    except (TypeError, ValueError):
        return None


def classic_carrier_needs_refresh(state, champion_id: int) -> bool:
    """Return whether a Classic champion lacks a matching cached carrier."""
    return (
        is_classic_game_mode(getattr(state, "current_game_mode", None))
        or is_classic_champion_id(champion_id)
    ) and cached_classic_carrier_for_champion(state, champion_id) is None


def default_skin_id_for_state(state, champion_id: int) -> Optional[int]:
    if (
        is_classic_game_mode(getattr(state, "current_game_mode", None))
        or is_classic_champion_id(champion_id)
    ):
        return getattr(state, "classic_default_skin_id", None)
    return int(champion_id) * 1000
