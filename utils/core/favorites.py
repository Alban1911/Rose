#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Favorites Manager
Persists and manages favorite skins and chromas per champion.
Saved in %LOCALAPPDATA%\\Rose\\favorites.json.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.core.paths import get_user_data_dir

log = logging.getLogger(__name__)

_favorites_lock = threading.Lock()


def _get_favorites_file_path() -> Path:
    """Return the Path to favorites.json in the user data directory."""
    data_dir = get_user_data_dir()
    return data_dir / "favorites.json"


def load_favorites_data() -> Dict[str, Any]:
    """Load the full favorites data dictionary. Returns default structure on error/missing."""
    with _favorites_lock:
        path = _get_favorites_file_path()
        if not path.exists():
            return {"version": 1, "favorites": {}}

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "favorites" in data and isinstance(data["favorites"], dict):
                return data
            return {"version": 1, "favorites": {}}
        except Exception as e:
            log.warning(f"[Favorites] Failed to load favorites.json: {e}")
            return {"version": 1, "favorites": {}}


def save_favorites_data(data: Dict[str, Any]) -> bool:
    """Save the full favorites data dictionary to favorites.json."""
    with _favorites_lock:
        path = _get_favorites_file_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            log.error(f"[Favorites] Failed to save favorites.json: {e}")
            return False


def get_champion_favorites(champion_id: int) -> Dict[str, Any]:
    """
    Get the favorites structure for a specific champion.
    Returns:
        {
            "skins": [skin_id, ...],
            "chromas": {
                "<skin_id>": [chroma_id, ...]
            }
        }
    """
    data = load_favorites_data()
    favorites_map = data.get("favorites", {})
    champ_key = str(int(champion_id))
    champ_favs = favorites_map.get(champ_key, {})
    
    skins = champ_favs.get("skins", [])
    if not isinstance(skins, list):
        skins = []
    
    chromas = champ_favs.get("chromas", {})
    if not isinstance(chromas, dict):
        chromas = {}

    return {
        "championId": int(champion_id),
        "skins": [int(s) for s in skins if isinstance(s, (int, str)) and str(s).isdigit()],
        "chromas": {
            str(k): [int(c) for c in v if isinstance(c, (int, str)) and str(c).isdigit()]
            for k, v in chromas.items()
            if isinstance(v, list)
        }
    }


def get_favorite_skins_for_champion(champion_id: int) -> List[int]:
    """Get the list of favorited skin IDs for a champion."""
    favs = get_champion_favorites(champion_id)
    return favs.get("skins", [])


def get_favorite_chromas_for_skin(champion_id: int, skin_id: int) -> List[int]:
    """Get the list of favorited chroma IDs (including base style if favorited) for a skin."""
    favs = get_champion_favorites(champion_id)
    chromas_map = favs.get("chromas", {})
    return chromas_map.get(str(int(skin_id)), [])


def toggle_skin_favorite(champion_id: int, skin_id: int) -> Tuple[bool, Dict[str, Any]]:
    """
    Toggle favorite status for a skin.
    Returns (is_now_favorite, updated_champion_favorites).
    """
    data = load_favorites_data()
    favorites_map = data.setdefault("favorites", {})
    champ_key = str(int(champion_id))
    champ_favs = favorites_map.setdefault(champ_key, {"skins": [], "chromas": {}})
    
    skins_list = champ_favs.setdefault("skins", [])
    skin_num = int(skin_id)
    
    if skin_num in skins_list:
        skins_list.remove(skin_num)
        # Also clean up chromas for this skin if removed
        if "chromas" in champ_favs and str(skin_num) in champ_favs["chromas"]:
            del champ_favs["chromas"][str(skin_num)]
        is_fav = False
        log.info(f"[Favorites] Removed skin {skin_num} from favorites for champion {champion_id}")
    else:
        skins_list.append(skin_num)
        # Also auto-favorite the base/default chroma style (skin_num itself)
        chromas_dict = champ_favs.setdefault("chromas", {})
        skin_chromas = chromas_dict.setdefault(str(skin_num), [])
        if skin_num not in skin_chromas:
            skin_chromas.append(skin_num)
        is_fav = True
        log.info(f"[Favorites] Added skin {skin_num} (with default base style) to favorites for champion {champion_id}")
    
    save_favorites_data(data)
    return is_fav, get_champion_favorites(champion_id)


def toggle_chroma_favorite(champion_id: int, skin_id: int, chroma_id: int) -> Tuple[bool, Dict[str, Any]]:
    """
    Toggle favorite status for a chroma (or base skin style).
    If the parent skin is not favorited yet, it is automatically favorited too.
    Returns (is_now_favorite, updated_champion_favorites).
    """
    data = load_favorites_data()
    favorites_map = data.setdefault("favorites", {})
    champ_key = str(int(champion_id))
    champ_favs = favorites_map.setdefault(champ_key, {"skins": [], "chromas": {}})
    
    skins_list = champ_favs.setdefault("skins", [])
    skin_num = int(skin_id)
    chroma_num = int(chroma_id)
    
    # Auto-add parent skin to favorites if not present
    if skin_num not in skins_list:
        skins_list.append(skin_num)
    
    chromas_dict = champ_favs.setdefault("chromas", {})
    skin_chromas = chromas_dict.setdefault(str(skin_num), [])
    
    if chroma_num in skin_chromas:
        skin_chromas.remove(chroma_num)
        is_fav = False
        log.info(f"[Favorites] Removed chroma {chroma_num} from skin {skin_num} (champion {champion_id})")
    else:
        skin_chromas.append(chroma_num)
        is_fav = True
        log.info(f"[Favorites] Added chroma {chroma_num} to skin {skin_num} (champion {champion_id})")
    
    save_favorites_data(data)
    return is_fav, get_champion_favorites(champion_id)


def is_skin_favorite(champion_id: int, skin_id: int) -> bool:
    """Check if a skin is favorited for the champion."""
    return int(skin_id) in get_favorite_skins_for_champion(champion_id)


def is_chroma_favorite(champion_id: int, skin_id: int, chroma_id: int) -> bool:
    """Check if a chroma is favorited for the given skin."""
    return int(chroma_id) in get_favorite_chromas_for_skin(champion_id, skin_id)
