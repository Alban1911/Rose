#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU Properties
Property-based accessors for common LCU endpoints
"""

from typing import Optional

from utils.core.logging import get_logger

log = get_logger()


class LCUProperties:
    """Property-based accessors for LCU endpoints"""
    
    def __init__(self, api):
        """Initialize properties handler
        
        Args:
            api: LCUAPI instance
        """
        self.api = api
    
    @property
    def phase(self) -> Optional[str]:
        """Get current gameflow phase"""
        ph = self.api.get("/lol-gameflow/v1/gameflow-phase")
        return ph if isinstance(ph, str) else None
    
    @property
    def session(self) -> Optional[dict]:
        """Get current session"""
        return self.api.get("/lol-champ-select/v1/session")
    
    @property
    def hovered_champion_id(self) -> Optional[int]:
        """Get hovered champion ID"""
        v = self.api.get("/lol-champ-select/v1/hovered-champion-id")
        try: 
            return int(v) if v is not None else None
        except (ValueError, TypeError) as e:
            log.debug(f"Failed to parse hovered champion ID: {e}")
            return None
    
    @property
    def my_selection(self) -> Optional[dict]:
        """Get my selection"""
        return self.api.get("/lol-champ-select/v1/session/my-selection") or self.api.get("/lol-champ-select/v1/selection")
    
    @property
    def unlocked_skins(self) -> Optional[dict]:
        """Get unlocked skins"""
        return self.api.get("/lol-champions/v1/owned-champions-minimal")
    
    def owned_skins(self) -> Optional[list[int]]:
        """
        Get owned skins (returns list of skin IDs)
        
        Note: This is a method (not property) because it's expensive and
        should be called explicitly when needed, not accessed frequently.
        """
        # This endpoint returns all skins the player owns
        data = self.api.get("/lol-inventory/v2/inventory/CHAMPION_SKIN")
        if isinstance(data, list):
            # Extract skin IDs from the inventory items
            skin_ids = []
            for item in data:
                if isinstance(item, dict):
                    item_id = item.get("itemId")
                    if item_id is not None:
                        try:
                            skin_ids.append(int(item_id))
                        except (ValueError, TypeError):
                            pass
            return skin_ids
        return None
    
    @property
    def current_summoner(self) -> Optional[dict]:
        """Get current summoner info"""
        return self.api.get("/lol-summoner/v1/current-summoner")
    
    @property
    def region_locale(self) -> Optional[dict]:
        """Get client region and locale information"""
        return self.api.get("/riotclient/region-locale")
    
    @property
    def client_language(self) -> Optional[str]:
        """Get client language from LCU API"""
        locale_info = self.region_locale
        if locale_info and isinstance(locale_info, dict):
            return locale_info.get("locale")
        return None
    
    @property
    def game_session(self) -> Optional[dict]:
        """Get current game session with mode and map info"""
        return self.api.get("/lol-gameflow/v1/session")
    
    def get_champion_name_by_id(self, champion_id: int) -> Optional[str]:
        """Get champion name by champion ID"""
        try:
            # Try to get champion data from LCU
            champion_data = self.api.get(f"/lol-game-data/assets/v1/champions/{champion_id}.json")
            if champion_data and isinstance(champion_data, dict):
                return champion_data.get("name")
            
            # Fallback: try inventory endpoint
            inventory_data = self.api.get(f"/lol-champions/v1/inventories/scouting/champions/{champion_id}")
            if inventory_data and isinstance(inventory_data, dict):
                return inventory_data.get("name")
            
            return None
            
        except Exception as e:
            log.debug(f"Error getting champion name for ID {champion_id}: {e}")
            return None

