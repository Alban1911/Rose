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
