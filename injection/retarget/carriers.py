#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin carriers: the owned skin each injected skin runs as.

The player picks one in champ select, per skin: skin_carriers.json maps a skin id to the owned skin or chroma it is
retargeted onto (injection.retarget), { "103014": 103001 }. The skin's chromas and forms use the same carrier, and
so does a custom mod picked on the skin. A carrier that can't be used, no longer owned or one the skin is built on,
leaves the skin on the champion's default skin, as Rose has always done.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from utils.core.atomic_file import atomic_write
from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir
from utils.core.utilities import get_base_skin_id_for_chroma, is_selectable_owned

from .retarget import RetargetError, RetargetPlan, plan_retarget

log = get_logger()

# Read-modify-write cycles run from the injection and the Pengu bridge
_write_lock = threading.RLock()


def _carriers_file_path() -> Path:
    return get_user_data_dir() / "skin_carriers.json"


def load_carrier_map() -> Dict[str, int]:
    try:
        p = _carriers_file_path()
        if not p.exists():
            return {}
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        result: Dict[str, int] = {}
        for key, value in data.items():
            try:
                result[str(int(key))] = int(value)
            except (TypeError, ValueError):
                continue
        return result
    except Exception as e:
        log.warning(f"[CARRIER] Could not read the saved skin carriers: {e}")
        return {}


def get_carrier(skin_id: int) -> Optional[int]:
    """The carrier saved for a skin, if any."""
    return load_carrier_map().get(str(int(skin_id)))


def set_carrier(skin_id: int, carrier_id: Optional[int]) -> None:
    """Save the carrier of a skin; None or the champion's default skin clears it."""
    skin_id = int(skin_id)
    with _write_lock:
        data = load_carrier_map()
        if carrier_id is None or int(carrier_id) % 1000 == 0:
            data.pop(str(skin_id), None)
        else:
            carrier_id = int(carrier_id)
            if carrier_id // 1000 != skin_id // 1000:
                raise ValueError(f"skin {carrier_id} is not one of skin {skin_id}'s champion")
            data[str(skin_id)] = carrier_id
        with atomic_write(_carriers_file_path()) as f:
            json.dump(data, f, indent=2)
    log.info(f"[CARRIER] Skin {skin_id} runs as {carrier_id or 'the default skin'}")


def carrier_key(skin_id: int, chroma_id_map: Optional[dict]) -> int:
    """The skin a carrier is saved under: a chroma's or a form's base skin, or the skin itself."""
    base = get_base_skin_id_for_chroma(int(skin_id), chroma_id_map)
    return int(base) if base else int(skin_id)


def resolve_carrier(skin_id: Optional[int], owned_skin_ids, chroma_id_map: Optional[dict]) -> Optional[int]:
    """The carrier an injected skin or chroma runs as, when one is saved and the client still lets the player pick
    it, or None for the default skin."""
    if not skin_id:
        return None
    key = carrier_key(skin_id, chroma_id_map)
    carrier = get_carrier(key)
    if not carrier or carrier // 1000 != key // 1000 or carrier % 1000 == 0:
        return None
    if not is_selectable_owned(carrier, set(owned_skin_ids or ()), chroma_id_map):
        log.info(f"[CARRIER] Skin {carrier} is no longer selectable, skin {skin_id} stays on the default skin")
        return None
    return carrier


def plan_for_carrier(source: Optional[Path], carrier_id: int, game_dir: Optional[Path]) -> Optional[RetargetPlan]:
    """The skin of this mod retargeted onto the carrier, or None (logged) when it can't be."""
    if source is None:
        return None
    try:
        return plan_retarget(Path(source), carrier_id % 1000, game_dir)
    except RetargetError as e:
        log.warning(f"[CARRIER] Skin {carrier_id} can't carry {Path(source).name}: {e}")
    except Exception as e:
        log.warning(f"[CARRIER] Retargeting {Path(source).name} onto skin {carrier_id} failed: {e}", exc_info=True)
    return None


def carrier_options(
    skins: List[dict],
    owned_skin_ids,
    chroma_id_map: Optional[dict],
    check: Optional[Callable[[int], Optional[str]]] = None,
) -> List[dict]:
    """The skins and chromas of a champion the player can pick as a carrier, from the skin scraper's list.

    check(carrier_id) returns why a carrier can't be used for the skin asked about, or None when it can.
    """
    owned = set(owned_skin_ids or ())
    options: List[dict] = []

    def add(option_id: int, entry: dict) -> None:
        reason = None
        if check:
            try:
                reason = check(option_id)
            except Exception as e:
                log.debug(f"[CARRIER] Could not check skin {option_id}: {e}")
        options.append({**entry, "id": option_id, "unavailableReason": reason})

    for skin in skins:
        skin_id = skin.get("skinId")
        if not skin_id or skin.get("isBase") or int(skin_id) % 1000 == 0:
            continue
        skin_id = int(skin_id)
        if is_selectable_owned(skin_id, owned, chroma_id_map):
            add(skin_id, {
                "name": skin.get("skinName") or str(skin_id),
                "chroma": False,
                "parentId": None,
                "tilePath": skin.get("tilePath") or None,
            })
        for chroma in skin.get("chromaDetails") or []:
            chroma_id = chroma.get("id")
            if chroma_id and is_selectable_owned(int(chroma_id), owned, chroma_id_map):
                add(int(chroma_id), {
                    "name": chroma.get("name") or skin.get("skinName") or str(chroma_id),
                    "chroma": True,
                    "parentId": skin_id,
                    "colors": chroma.get("colors") or [],
                    "chromaPath": chroma.get("chromaPath") or None,
                })
    return options
