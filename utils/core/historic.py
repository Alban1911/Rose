#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Historic mode utilities: persist and read last injected unowned skin per champion.
File format: historic.json with shape { "<championId>": <skinOrChromaId> | "path:<relativePath>", ... }
Supports both:
  - Integer skin/chroma IDs for official skins: { "234": 234000 }
  - String custom mod paths: { "234": "path:skins/234000/old-aatrox-viego_1.2.0.fantome" }
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Optional, Union

from utils.core.atomic_file import atomic_write
from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir

log = get_logger()

# Read-modify-write cycles run from several threads (injection, UI, Pengu bridge)
_write_lock = threading.RLock()


def _write_json(path: Path, data: dict) -> None:
    with atomic_write(path) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _historic_file_path() -> Path:
    data_dir = get_user_data_dir()
    return data_dir / "historic.json"


def _historic_path(scope: str = "regular") -> Path:
    filename = "historic_classic.json" if scope == "classic" else "historic.json"
    return get_user_data_dir() / filename


def _historic_target_file_path() -> Path:
    data_dir = get_user_data_dir()
    return data_dir / "historic_targets.json"


def _historic_target_path(scope: str = "regular") -> Path:
    filename = (
        "historic_targets_classic.json"
        if scope == "classic"
        else "historic_targets.json"
    )
    return get_user_data_dir() / filename


def historic_scope_for_state(state) -> str:
    from injection.classic import is_classic_game_mode

    return (
        "classic"
        if is_classic_game_mode(getattr(state, "current_game_mode", None))
        else "regular"
    )


def _champion_keys(champion_id: int, scope: str) -> tuple[str, ...]:
    raw_key = str(int(champion_id))
    if scope != "classic":
        return (raw_key,)
    from injection.classic import to_regular_champion_id

    canonical_key = str(int(to_regular_champion_id(int(champion_id)) or 0))
    return (canonical_key,) if canonical_key == raw_key else (canonical_key, raw_key)


def load_historic_target_map(scope: str = "regular") -> Dict[str, int]:
    """Load the exact last skin/chroma target for custom history entries."""
    try:
        p = _historic_target_path(scope)
        if not p.exists():
            return {}
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}

        result: Dict[str, int] = {}
        for key, value in data.items():
            try:
                target_id = int(value)
                if target_id > 0:
                    result[str(int(key))] = target_id
            except (TypeError, ValueError):
                continue
        return result
    except Exception as e:
        log.warning(f"[HISTORIC] Could not read the saved custom mod targets: {e}")
        return {}


def get_historic_target_for_champion(
    champion_id: int, scope: str = "regular"
) -> Optional[int]:
    """Return the exact last selected skin/chroma target for a champion."""
    targets = load_historic_target_map(scope)
    return next(
        (targets[key] for key in _champion_keys(champion_id, scope) if key in targets),
        None,
    )


def write_historic_target(
    champion_id: int, target_skin_id: int, scope: str = "regular"
) -> None:
    """Persist the exact last selected skin/chroma target for a champion."""
    try:
        target_id = int(target_skin_id)
        if target_id <= 0:
            return
        with _write_lock:
            targets = load_historic_target_map(scope)
            keys = _champion_keys(champion_id, scope)
            targets[keys[0]] = target_id
            for legacy_key in keys[1:]:
                targets.pop(legacy_key, None)
            _write_json(_historic_target_path(scope), targets)
    except Exception as e:
        log.warning(f"[HISTORIC] Could not save target {target_skin_id} for champion {champion_id}: {e}")


def clear_historic_target(champion_id: int, scope: str = "regular") -> None:
    """Remove the exact last selected skin/chroma target for a champion."""
    try:
        with _write_lock:
            targets = load_historic_target_map(scope)
            keys = _champion_keys(champion_id, scope)
            if not any(key in targets for key in keys):
                return
            for key in keys:
                targets.pop(key, None)
            _write_json(_historic_target_path(scope), targets)
    except Exception as e:
        log.warning(f"[HISTORIC] Could not clear target for champion {champion_id}: {e}")


def load_historic_map(scope: str = "regular") -> Dict[str, Union[int, str]]:
    """Load the historic mapping. Returns empty dict if missing or invalid.
    
    Returns:
        Dict mapping champion IDs to either skin/chroma IDs (int) or custom mod paths (str with "path:" prefix)
    """
    try:
        p = _historic_path(scope)
        if not p.exists():
            return {}
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            result: Dict[str, Union[int, str]] = {}
            for k, v in data.items():
                try:
                    key = str(int(k))
                    # Keep value as-is: int for skin IDs, str for custom mod paths
                    if isinstance(v, int):
                        result[key] = int(v)
                    elif isinstance(v, str):
                        result[key] = str(v)
                except Exception:
                    continue
            return result
        return {}
    except Exception as e:
        # Historic mode would silently forget every saved skin
        log.warning(f"[HISTORIC] Could not read the saved skins: {e}")
        return {}


def get_historic_skin_for_champion(
    champion_id: int, scope: str = "regular"
) -> Optional[Union[int, str]]:
    """Get historic entry for a champion.
    
    Returns:
        Integer skin/chroma ID, or string custom mod path (with "path:" prefix), or None
    """
    m = load_historic_map(scope)
    return next(
        (m[key] for key in _champion_keys(champion_id, scope) if key in m),
        None,
    )


def write_historic_entry(
    champion_id: int,
    skin_or_chroma_id: Union[int, str],
    scope: str = "regular",
) -> None:
    """Write or overwrite the entry for the champion ID.
    
    Args:
        champion_id: Champion ID
        skin_or_chroma_id: Either an integer skin/chroma ID, or a string custom mod path (with "path:" prefix)
    """
    with _write_lock:
        m = load_historic_map(scope)
        keys = _champion_keys(champion_id, scope)
        m[keys[0]] = skin_or_chroma_id
        for legacy_key in keys[1:]:
            m.pop(legacy_key, None)
        try:
            _write_json(_historic_path(scope), m)
        except Exception as e:
            log.warning(f"[HISTORIC] Could not save entry for champion {champion_id}: {e}")


def clear_historic_entry(champion_id: int, scope: str = "regular") -> None:
    """Remove the historic entry for a champion if it exists."""
    try:
        with _write_lock:
            m = load_historic_map(scope)
            keys = _champion_keys(champion_id, scope)
            if any(key in m for key in keys):
                for key in keys:
                    m.pop(key, None)
                _write_json(_historic_path(scope), m)
    except Exception as e:
        log.warning(f"[HISTORIC] Could not clear entry for champion {champion_id}: {e}")
    clear_historic_target(champion_id, scope)


def is_custom_mod_path(value: Union[int, str]) -> bool:
    """Check if a historic value is a custom mod path.
    
    Args:
        value: Historic value (int or str)
    
    Returns:
        True if value is a string starting with "path:", False otherwise
    """
    return isinstance(value, str) and value.startswith("path:")


def get_custom_mod_path(value: Union[int, str]) -> Optional[str]:
    """Extract custom mod path from historic value.
    
    Args:
        value: Historic value (int or str)
    
    Returns:
        Custom mod path without "path:" prefix, or None if not a custom mod path
    """
    if is_custom_mod_path(value):
        return value[5:]  # Remove "path:" prefix
    return None
