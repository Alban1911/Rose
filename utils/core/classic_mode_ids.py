"""Classic Mode identity and carrier helpers.

LCU exposes Classic champions in a virtual 60000+ namespace.  Rose keeps
those server-facing IDs separate from the regular IDs used by skin packages.
"""

from __future__ import annotations

from typing import Iterable, Optional


CLASSIC_MODE = "JADE"
CLASSIC_QUEUE_ID = 3260
CLASSIC_MAP_ID = 453
CLASSIC_CHAMPION_OFFSET = 60_000
CLASSIC_CHAMPION_MIN = 60_001
CLASSIC_CHAMPION_MAX = 60_999
CLASSIC_CARRIER_MANIFEST_VERSION = 1

# Captured from the 2026-08-03 Classic champion catalog. Runtime catalog data
# is authoritative; this versioned matrix is used only while it is unavailable.
CLASSIC_CARRIER_LCU_SKIN_IDS = {
    1: 60001301, 2: 60002000, 4: 60004301, 9: 60009301,
    10: 60010302, 11: 60011301, 12: 60012301, 13: 60013301,
    14: 60014301, 15: 60015000, 16: 60016301, 17: 60017301,
    18: 60018301, 19: 60019301, 20: 60020301, 21: 60021000,
    22: 60022000, 23: 60023000, 24: 60024301, 25: 60025301,
    26: 60026000, 27: 60027000, 28: 60028301, 29: 60029301,
    30: 60030301, 31: 60031000, 32: 60032000, 33: 60033000,
    34: 60034000, 35: 60035000, 36: 60036301, 37: 60037000,
    38: 60038301, 40: 60040000, 41: 60041301, 42: 60042000,
    44: 60044301, 45: 60045000, 53: 60053000, 54: 60054000,
    55: 60055301, 59: 60059000, 62: 60062000, 63: 60063000,
    64: 60064301, 67: 60067000, 72: 60072301, 74: 60074301,
    75: 60075301, 76: 60076301, 79: 60079000, 80: 60080301,
    81: 60081301, 86: 60086301, 89: 60089000, 90: 60090000,
    96: 60096000, 99: 60099000, 103: 60103301, 117: 60117000,
}


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
    """Convert a mode champion ID to the regular package champion ID."""
    value = int(champion_id or 0)
    return value - CLASSIC_CHAMPION_OFFSET if is_classic_champion_id(value) else value


def mode_champion_id(champion_id: object) -> int:
    """Convert a regular champion ID to the Classic LCU champion ID."""
    value = int(champion_id or 0)
    if is_classic_champion_id(value):
        return value
    if value <= 0 or value >= 1000:
        raise ValueError(f"Invalid champion ID: {champion_id!r}")
    return value + CLASSIC_CHAMPION_OFFSET


def resource_skin_id(skin_id: object) -> int:
    """Convert a raw Classic LCU skin ID to the package resource skin ID."""
    value = int(skin_id or 0)
    champion_id, skin_number = divmod(value, 1000)
    if is_classic_champion_id(champion_id):
        return resource_champion_id(champion_id) * 1000 + skin_number
    return value


def mode_skin_id(skin_id: object) -> int:
    """Convert a package resource skin ID to the raw Classic LCU skin ID."""
    value = int(skin_id or 0)
    if is_classic_skin_id(value):
        return value
    champion_id, skin_number = divmod(value, 1000)
    return mode_champion_id(champion_id) * 1000 + skin_number


def fallback_carrier_lcu_skin_id(champion_id: object) -> int:
    """Return the versioned fallback carrier for a supported champion."""
    prime_id = resource_champion_id(champion_id)
    try:
        return CLASSIC_CARRIER_LCU_SKIN_IDS[prime_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported Classic champion ID: {champion_id!r}") from exc


def carrier_skin_number(carrier_lcu_skin_id: object) -> int:
    """Return Skin0/Skin301/Skin302 from a validated raw carrier ID."""
    value = int(carrier_lcu_skin_id or 0)
    if not is_classic_skin_id(value) or value % 1000 not in {0, 301, 302}:
        raise ValueError(f"Invalid Classic carrier skin ID: {carrier_lcu_skin_id!r}")
    return value % 1000


def catalog_skin_ids(catalog: object, champion_id: object) -> set[int]:
    """Return raw skin IDs belonging to one Classic mode champion."""
    if not isinstance(catalog, list) or not (1 <= len(catalog) <= 256):
        return set()
    expected_champion = mode_champion_id(champion_id)
    result = set()
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        try:
            skin_id = int(entry.get("id", entry.get("skinId", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if skin_id > 0 and skin_id // 1000 == expected_champion:
            result.add(skin_id)
    return result


def validated_carrier_lcu_skin_id(
    champion_id: object,
    catalog: object,
    advertised_carrier: object = None,
) -> int:
    """Validate a live carrier, otherwise use the versioned fallback."""
    raw_ids = catalog_skin_ids(catalog, champion_id)
    try:
        advertised = int(advertised_carrier or 0)
    except (TypeError, ValueError):
        advertised = 0
    if advertised in raw_ids:
        try:
            carrier_skin_number(advertised)
            return advertised
        except ValueError:
            pass
    return resolve_carrier_lcu_skin_id(champion_id, raw_ids)


def resolve_carrier_lcu_skin_id(
    champion_id: object,
    catalog_skin_ids: Optional[Iterable[object]] = None,
) -> int:
    """Resolve a champion-owned carrier from catalog data, then the manifest."""
    prime_id = resource_champion_id(champion_id)
    expected_mode_champion = mode_champion_id(prime_id)
    fallback = fallback_carrier_lcu_skin_id(prime_id)
    candidates = set()
    for skin_id in catalog_skin_ids or ():
        try:
            value = int(skin_id)
        except (TypeError, ValueError):
            continue
        if value // 1000 == expected_mode_champion and value % 1000 in {0, 301, 302}:
            candidates.add(value)
    if fallback in candidates:
        return fallback
    return fallback if not candidates else min(candidates, key=lambda value: (value % 1000 == 0, value))
