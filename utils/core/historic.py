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
from pathlib import Path
from typing import Dict, Optional, Union

from utils.core.paths import get_user_data_dir


def _historic_file_path() -> Path:
    data_dir = get_user_data_dir()
    return data_dir / "historic.json"


def _historic_target_file_path() -> Path:
    data_dir = get_user_data_dir()
    return data_dir / "historic_targets.json"


def load_historic_target_map() -> Dict[str, int]:
    """Load the exact last skin/chroma target for custom history entries."""
    try:
        p = _historic_target_file_path()
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
    except Exception:
        return {}


def get_historic_target_for_champion(champion_id: int) -> Optional[int]:
    """Return the exact last selected skin/chroma target for a champion."""
    return load_historic_target_map().get(str(int(champion_id)))


def write_historic_target(champion_id: int, target_skin_id: int) -> None:
    """Persist the exact last selected skin/chroma target for a champion."""
    try:
        target_id = int(target_skin_id)
        if target_id <= 0:
            return
        p = _historic_target_file_path()
        targets = load_historic_target_map()
        targets[str(int(champion_id))] = target_id
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(targets, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def clear_historic_target(champion_id: int) -> None:
    """Remove the exact last selected skin/chroma target for a champion."""
    try:
        p = _historic_target_file_path()
        targets = load_historic_target_map()
        if str(int(champion_id)) not in targets:
            return
        targets.pop(str(int(champion_id)), None)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(targets, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_historic_map() -> Dict[str, Union[int, str]]:
    """Load the historic mapping. Returns empty dict if missing or invalid.
    
    Returns:
        Dict mapping champion IDs to either skin/chroma IDs (int) or custom mod paths (str with "path:" prefix)
    """
    try:
        p = _historic_file_path()
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
    except Exception:
        return {}


def get_historic_skin_for_champion(champion_id: int) -> Optional[Union[int, str]]:
    """Get historic entry for a champion.
    
    Returns:
        Integer skin/chroma ID, or string custom mod path (with "path:" prefix), or None
    """
    m = load_historic_map()
    key = str(int(champion_id))
    return m.get(key)


def write_historic_entry(champion_id: int, skin_or_chroma_id: Union[int, str]) -> None:
    """Write or overwrite the entry for the champion ID.
    
    Args:
        champion_id: Champion ID
        skin_or_chroma_id: Either an integer skin/chroma ID, or a string custom mod path (with "path:" prefix)
    """
    p = _historic_file_path()
    m = load_historic_map()
    m[str(int(champion_id))] = skin_or_chroma_id
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    except Exception:
        # Silently ignore write errors; feature is best-effort
        pass


def clear_historic_entry(champion_id: int) -> None:
    """Remove the historic entry for a champion if it exists."""
    try:
        p = _historic_file_path()
        m = load_historic_map()
        key = str(int(champion_id))
        if key in m:
            m.pop(key, None)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=2)
    except Exception:
        # Best-effort; ignore errors
        pass
    clear_historic_target(champion_id)


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
