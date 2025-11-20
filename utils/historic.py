#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Historic mode utilities: persist and read last injected unowned skin per champion.
File format: historic.json with shape { "<championId>": <skinOrChromaId>, ... }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from utils.paths import get_user_data_dir


def _historic_file_path() -> Path:
    data_dir = get_user_data_dir()
    return data_dir / "historic.json"


def load_historic_map() -> Dict[str, int]:
    """Load the historic mapping. Returns empty dict if missing or invalid."""
    try:
        p = _historic_file_path()
        if not p.exists():
            return {}
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # Coerce values to int if possible
            result: Dict[str, int] = {}
            for k, v in data.items():
                try:
                    result[str(int(k))] = int(v)
                except Exception:
                    continue
            return result
        return {}
    except Exception:
        return {}


def get_historic_skin_for_champion(champion_id: int) -> Optional[int]:
    m = load_historic_map()
    key = str(int(champion_id))
    return m.get(key)


def write_historic_entry(champion_id: int, skin_or_chroma_id: int) -> None:
    """Write or overwrite the entry for the champion ID."""
    p = _historic_file_path()
    m = load_historic_map()
    m[str(int(champion_id))] = int(skin_or_chroma_id)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    except Exception:
        # Silently ignore write errors; feature is best-effort
        pass
