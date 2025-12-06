#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mod Historic utilities: persist and read last selected mods (map, font, announcer, other).
File format: mod_historic.json with shape:
{
  "map": "<relative_path>",
  "font": "<relative_path>",
  "announcer": "<relative_path>",
  "other": "<relative_path>"
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from utils.core.paths import get_user_data_dir


def _mod_historic_file_path() -> Path:
    data_dir = get_user_data_dir()
    return data_dir / "mod_historic.json"


def load_mod_historic() -> Dict[str, str]:
    """Load the mod historic mapping. Returns empty dict if missing or invalid."""
    try:
        p = _mod_historic_file_path()
        if not p.exists():
            return {}
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            result: Dict[str, str] = {}
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, str):
                    result[k] = v
            return result
        return {}
    except Exception:
        return {}


def get_historic_mod(mod_type: str) -> Optional[str]:
    """Get historic mod for a specific type (map, font, announcer, other).
    
    Args:
        mod_type: One of "map", "font", "announcer", "other"
    
    Returns:
        Relative path to the mod or None
    """
    m = load_mod_historic()
    return m.get(mod_type)


def write_historic_mod(mod_type: str, relative_path: str) -> None:
    """Write or overwrite the entry for the mod type.
    
    Args:
        mod_type: One of "map", "font", "announcer", "other"
        relative_path: Relative path to the mod (used as identifier)
    """
    p = _mod_historic_file_path()
    m = load_mod_historic()
    m[mod_type] = str(relative_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    except Exception:
        # Silently ignore write errors; feature is best-effort
        pass


def clear_historic_mod(mod_type: str) -> None:
    """Clear the historic entry for a specific mod type.
    
    Args:
        mod_type: One of "map", "font", "announcer", "other"
    """
    p = _mod_historic_file_path()
    m = load_mod_historic()
    if mod_type in m:
        del m[mod_type]
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False, indent=2)
        except Exception:
            # Silently ignore write errors; feature is best-effort
            pass

