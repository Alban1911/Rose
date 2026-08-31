"""Classic Mode ID conversion at the LCU boundary.

Rose stores the same champion and skin IDs used by the external ``classic``
resource tree.  JADE's ``600`` prefix is added only for LCU reads and writes.
"""

from __future__ import annotations

from typing import Iterable, Optional


CLASSIC_MODE = "JADE"
CLASSIC_QUEUE_ID = 3260
CLASSIC_MAP_ID = 453
CLASSIC_CHAMPION_OFFSET = 60_000
CLASSIC_SKIN_OFFSET = CLASSIC_CHAMPION_OFFSET * 1000
CLASSIC_CHAMPION_MIN = CLASSIC_CHAMPION_OFFSET + 1
CLASSIC_CHAMPION_MAX = CLASSIC_CHAMPION_OFFSET + 999


def normalize_game_mode(game_mode: object, queue_id: object, map_id: object) -> Optional[str]:
    """Return the strongest normalized mode signal available from LCU."""
    if isinstance(game_mode, str) and game_mode.strip():
        return game_mode.strip().upper()
    try:
        if int(queue_id) == CLASSIC_QUEUE_ID:
            return CLASSIC_MODE
    except (TypeError, ValueError):
        pass
    try:
        if int(map_id) == CLASSIC_MAP_ID:
            return CLASSIC_MODE
    except (TypeError, ValueError):
        pass
    return None


def is_classic_mode(game_mode: object) -> bool:
    return isinstance(game_mode, str) and game_mode.upper() == CLASSIC_MODE


def is_classic_champion_id(champion_id: object) -> bool:
    try:
        value = int(champion_id)
    except (TypeError, ValueError):
        return False
    return CLASSIC_CHAMPION_MIN <= value <= CLASSIC_CHAMPION_MAX


def is_classic_skin_id(skin_id: object) -> bool:
    try:
        return is_classic_champion_id(int(skin_id) // 1000)
    except (TypeError, ValueError):
        return False


def resource_champion_id(champion_id: object) -> int:
    """Return the champion folder ID used below the external classic root."""
    value = int(champion_id or 0)
    return value - CLASSIC_CHAMPION_OFFSET if is_classic_champion_id(value) else value


def mode_champion_id(champion_id: object) -> int:
    """Add JADE's champion prefix for an LCU request."""
    value = int(champion_id or 0)
    if is_classic_champion_id(value):
        return value
    if value <= 0 or value >= 1000:
        raise ValueError(f"Invalid champion ID: {champion_id!r}")
    return value + CLASSIC_CHAMPION_OFFSET


def resource_skin_id(skin_id: object) -> int:
    """Strip JADE's prefix from an LCU skin ID."""
    value = int(skin_id or 0)
    return value - CLASSIC_SKIN_OFFSET if is_classic_skin_id(value) else value


def mode_skin_id(skin_id: object) -> int:
    """Add JADE's prefix to a resource skin ID for an LCU request."""
    value = int(skin_id or 0)
    if is_classic_skin_id(value):
        return value
    champion_id = value // 1000
    if champion_id <= 0 or champion_id >= 1000:
        raise ValueError(f"Invalid skin ID: {skin_id!r}")
    return value + CLASSIC_SKIN_OFFSET


def catalog_skin_ids(catalog: object, champion_id: object) -> set[int]:
    """Return canonical resource IDs from a Classic catalog payload."""
    if not isinstance(catalog, list) or not (1 <= len(catalog) <= 256):
        return set()
    expected_champion = resource_champion_id(champion_id)
    result = set()
    for entry in catalog:
        value = entry.get("id", entry.get("skinId", 0)) if isinstance(entry, dict) else entry
        try:
            skin_id = resource_skin_id(value)
        except (TypeError, ValueError):
            continue
        if skin_id > 0 and skin_id // 1000 == expected_champion:
            result.add(skin_id)
    return result


def resolve_default_skin_id(
    champion_id: object,
    catalog: Optional[Iterable[object]] = None,
    advertised_default: object = None,
) -> int:
    """Resolve the canonical default from live LCU data, never a hero table."""
    champion = resource_champion_id(champion_id)
    try:
        advertised = resource_skin_id(advertised_default)
    except (TypeError, ValueError):
        advertised = 0
    if advertised > 0 and advertised // 1000 == champion:
        return advertised

    candidates = set()
    for value in catalog or ():
        if isinstance(value, dict):
            value = value.get("id", value.get("skinId", 0))
        try:
            candidate = resource_skin_id(value)
        except (TypeError, ValueError):
            continue
        if candidate > 0 and candidate // 1000 == champion:
            candidates.add(candidate)
    if not candidates:
        raise ValueError(f"Classic default is unavailable for champion {champion!r}")
    return min(candidates, key=lambda value: (value % 1000 != 0, value))


def validated_default_skin_id(
    champion_id: object,
    catalog: object,
    advertised_default: object = None,
) -> int:
    """Validate a frontend default against its canonical catalog."""
    candidates = catalog_skin_ids(catalog, champion_id)
    if advertised_default is None:
        raise ValueError("Classic default was not advertised")
    default_skin_id = resolve_default_skin_id(
        champion_id, candidates, advertised_default
    )
    if default_skin_id not in candidates:
        raise ValueError("Classic default is outside the active catalog")
    return default_skin_id
