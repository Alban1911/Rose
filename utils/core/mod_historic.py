#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mod Historic utilities: persist and read last selected mods (map, font, announcer, other).
File format: mod_historic.json with shape:
{
  "map": "<relative_path>",
  "font": "<relative_path>",
  "announcer": "<relative_path>",
  // Category mods (multi-select, stored per category)
  "ui": ["ui/<relative_path>", ...],
  "voiceover": ["voiceover/<relative_path>", ...],
  "loading_screen": ["loading_screen/<relative_path>", ...],
  "vfx": ["vfx/<relative_path>", ...],
  "sfx": ["sfx/<relative_path>", ...],
  "others": ["others/<relative_path>", ...]

  // Legacy (backward compat):
  // "other": "<relative_path>" | ["<relative_path>", ...]
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Union, List, Iterable

from utils.core.paths import get_user_data_dir


_CATEGORY_KEYS = (
    "ui",
    "voiceover",
    "loading_screen",
    "vfx",
    "sfx",
    "others",
)


def _infer_category_from_relative_path(rel_path: str) -> str:
    p = str(rel_path).replace("\\", "/").lstrip("/")
    first = (p.split("/", 1)[0] if "/" in p else p).strip().lower()
    return first if first in _CATEGORY_KEYS else "others"


def _as_list(value: Union[str, List[str], None]) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str)]
    if isinstance(value, str):
        return [value]
    return []


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        if not isinstance(item, str):
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _mod_historic_file_path() -> Path:
    data_dir = get_user_data_dir()
    return data_dir / "mod_historic.json"


def load_mod_historic() -> Dict[str, Union[str, List[str]]]:
    """Load the mod historic mapping. Returns empty dict if missing or invalid.

    Normalized shape returned:
      - "map"/"font"/"announcer": string
      - category keys ("ui"/"voiceover"/"loading_screen"/"vfx"/"sfx"/"others"): list[str]

    Also supports legacy "other" (string or list) and will merge it into category keys.
    If the file is legacy-only, this function will best-effort migrate it to the new shape.
    """
    try:
        p = _mod_historic_file_path()
        if not p.exists():
            return {}
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            result: Dict[str, Union[str, List[str]]] = {}

            # Single-select types
            for k in ("map", "font", "announcer"):
                v = data.get(k)
                if isinstance(v, str):
                    result[k] = v

            # New per-category lists (string accepted as convenience)
            any_new_category_key = False
            for cat in _CATEGORY_KEYS:
                v = data.get(cat)
                if isinstance(v, str) or isinstance(v, list):
                    items = _as_list(v)
                    if items:
                        result[cat] = _dedupe_keep_order(items)
                        any_new_category_key = True
                    else:
                        result[cat] = []
                else:
                    result[cat] = []

            # Legacy "other" -> merge into inferred categories
            legacy_items = _as_list(data.get("other"))
            has_legacy_other = bool(legacy_items)
            for item in legacy_items:
                cat = _infer_category_from_relative_path(item)
                existing = result.get(cat, [])
                if not isinstance(existing, list):
                    existing = []
                result[cat] = _dedupe_keep_order([*existing, item])

            # Best-effort migration: legacy-only "other" and no new category keys
            if has_legacy_other and not any_new_category_key:
                try:
                    compact: Dict[str, Union[str, List[str]]] = {}
                    for k in ("map", "font", "announcer"):
                        if isinstance(result.get(k), str):
                            compact[k] = result[k]  # type: ignore[assignment]
                    for cat in _CATEGORY_KEYS:
                        items = result.get(cat, [])
                        if isinstance(items, list) and items:
                            compact[cat] = items
                    p.parent.mkdir(parents=True, exist_ok=True)
                    with p.open("w", encoding="utf-8") as wf:
                        json.dump(compact, wf, ensure_ascii=False, indent=2)
                except Exception:
                    pass

            # Return compact (drop empty category lists)
            out: Dict[str, Union[str, List[str]]] = {}
            for k in ("map", "font", "announcer"):
                if k in result:
                    out[k] = result[k]
            for cat in _CATEGORY_KEYS:
                items = result.get(cat, [])
                if isinstance(items, list) and items:
                    out[cat] = items
            return out
        return {}
    except Exception:
        return {}


def get_historic_mod(mod_type: str) -> Union[Optional[str], Optional[List[str]]]:
    """Get historic mod for a specific type.

    - "map"/"font"/"announcer": returns str|None
    - category keys ("ui"/"voiceover"/"loading_screen"/"vfx"/"sfx"/"others"): returns list[str]|None
    - legacy "other": returns combined list across category keys (best-effort compat)
    """
    m = load_mod_historic()
    value = m.get(mod_type)
    if mod_type in _CATEGORY_KEYS:
        if isinstance(value, list) and value:
            return value
        return None
    if mod_type == "other":
        combined: List[str] = []
        for cat in _CATEGORY_KEYS:
            v = m.get(cat)
            if isinstance(v, list):
                combined.extend(v)
        combined = _dedupe_keep_order(combined)
        return combined if combined else None
    # Other types return string or None
    return value if isinstance(value, str) else None


def write_historic_mod(mod_type: str, relative_path: Union[str, List[str]]) -> None:
    """Write or overwrite the entry for the mod type.
    
    Args:
        mod_type: "map"/"font"/"announcer" or a category key (ui/voiceover/loading_screen/vfx/sfx/others).
        relative_path: For category keys, can be a list of relative paths. For single-select keys, must be a string.
    """
    p = _mod_historic_file_path()
    m = load_mod_historic()
    
    # Normalize legacy "other" writes into per-category keys
    if mod_type == "other":
        items = _as_list(relative_path)
        grouped: Dict[str, List[str]] = {cat: [] for cat in _CATEGORY_KEYS}
        for item in items:
            cat = _infer_category_from_relative_path(item)
            grouped[cat].append(item)
        for cat, paths in grouped.items():
            if paths:
                m[cat] = _dedupe_keep_order(paths)
        # Avoid writing legacy key
        if "other" in m:
            del m["other"]
        mod_type = "others"

    if mod_type in _CATEGORY_KEYS:
        items = _as_list(relative_path)
        if items:
            m[mod_type] = _dedupe_keep_order(items)
        else:
            if mod_type in m:
                del m[mod_type]
    else:
        # Single-select types (string)
        if isinstance(relative_path, list):
            m[mod_type] = str(relative_path[0]) if relative_path else ""
        else:
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
    if mod_type == "other":
        # Backward compat: clear all category keys
        changed = False
        for cat in _CATEGORY_KEYS:
            if cat in m:
                del m[cat]
                changed = True
        if "other" in m:
            del m["other"]
            changed = True
        if not changed:
            return
    else:
        if mod_type not in m:
            return
        del m[mod_type]

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    except Exception:
        # Silently ignore write errors; feature is best-effort
        pass

