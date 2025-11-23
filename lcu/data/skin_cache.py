#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Cache
Cache for champion skins scraped from LCU
"""

from typing import Dict, List, Optional


class ChampionSkinCache:
    """Cache for champion skins scraped from LCU"""
    
    def __init__(self):
        self.champion_id = None
        self.champion_name = None
        self.skins = []  # List of {skinId, skinName, isBase, chromas, chromaDetails}
        self.skin_id_map = {}  # skinId -> skin data
        self.skin_name_map = {}  # skinName -> skin data
        self.chroma_id_map = {}  # chromaId -> chroma data (for quick lookup)
    
    def clear(self):
        """Clear the cache"""
        self.champion_id = None
        self.champion_name = None
        self.skins = []
        self.skin_id_map = {}
        self.skin_name_map = {}
        self.chroma_id_map = {}
    
    def is_loaded_for_champion(self, champion_id: int) -> bool:
        """Check if cache is loaded for a specific champion"""
        return self.champion_id == champion_id and bool(self.skins)
    
    def get_skin_by_id(self, skin_id: int) -> Optional[Dict]:
        """Get skin data by skin ID"""
        return self.skin_id_map.get(skin_id)
    
    def get_skin_by_name(self, skin_name: str) -> Optional[Dict]:
        """Get skin data by skin name (exact match)"""
        return self.skin_name_map.get(skin_name)
    
    @property
    def all_skins(self) -> List[Dict]:
        """Get all skins for the cached champion"""
        return self.skins.copy()

