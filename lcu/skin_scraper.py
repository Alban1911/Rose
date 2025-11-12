#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU Skin Scraper - Scrape skins for a specific champion from LCU
"""

from typing import Optional, Dict, List
from utils.logging import get_logger
from config import LCU_SKIN_SCRAPER_TIMEOUT_S

log = get_logger()


class ChampionSkinCache:
    """Cache for champion skins scraped from LCU"""
    
    def __init__(self):
        self.champion_id = None
        self.champion_name = None
        self.skins = []  # List of {skinId, skinName, isBase, chromas, chromaDetails}
        self.skin_id_map = {}  # skinId -> skin data
        self.chroma_id_map = {}  # chromaId -> chroma data (for quick lookup)
        # No longer using external data sources - LCU provides all needed data
    
    def clear(self):
        """Clear the cache"""
        self.champion_id = None
        self.champion_name = None
        self.skins = []
        self.skin_id_map = {}
        self.chroma_id_map = {}
        # No longer using external data sources
    
    def is_loaded_for_champion(self, champion_id: int) -> bool:
        """Check if cache is loaded for a specific champion"""
        return self.champion_id == champion_id and bool(self.skins)
    
    def get_skin_by_id(self, skin_id: int) -> Optional[Dict]:
        """Get skin data by skin ID"""
        return self.skin_id_map.get(skin_id)
    
    @property
    def all_skins(self) -> List[Dict]:
        """Get all skins for the cached champion"""
        return self.skins.copy()


class LCUSkinScraper:
    """Scrape skins for a specific champion from LCU API"""
    
    def __init__(self, lcu_client):
        """Initialize scraper with LCU client
        
        Args:
            lcu_client: LCU client instance
        """
        self.lcu = lcu_client
        self.cache = ChampionSkinCache()
    
    # No longer fetching external data - LCU provides all needed information
    
    def scrape_champion_skins(self, champion_id: int, force_refresh: bool = False) -> bool:
        """Scrape all skins for a specific champion from LCU
        
        Args:
            champion_id: Champion ID to scrape skins for
            force_refresh: If True, force refresh even if already cached
            
        Returns:
            True if scraping succeeded, False otherwise
        """
        # Check if already cached
        if not force_refresh and self.cache.is_loaded_for_champion(champion_id):
            log.debug(f"[LCU-SCRAPER] Champion {champion_id} skins already cached ({len(self.cache.skins)} skins)")
            return True
        
        # Clear old cache
        self.cache.clear()
        
        log.info(f"[LCU-SCRAPER] Scraping skins for champion ID {champion_id}...")
        
        # Try multiple endpoints to get champion skins
        endpoints = [
            f"/lol-game-data/assets/v1/champions/{champion_id}.json",
            f"/lol-champions/v1/inventories/scouting/champions/{champion_id}",
        ]
        
        champ_data = None
        for endpoint in endpoints:
            try:
                data = self.lcu.get(endpoint, timeout=LCU_SKIN_SCRAPER_TIMEOUT_S)
                if data and isinstance(data, dict) and 'skins' in data:
                    champ_data = data
                    log.debug(f"[LCU-SCRAPER] Successfully fetched data from {endpoint}")
                    break
            except Exception as e:
                log.debug(f"[LCU-SCRAPER] Failed to fetch from {endpoint}: {e}")
                continue
        
        if not champ_data:
            log.warning(f"[LCU-SCRAPER] Failed to scrape skins for champion {champion_id}")
            return False
        
        # Extract champion info
        self.cache.champion_id = champion_id
        self.cache.champion_name = champ_data.get('name', f'Champion{champion_id}')
        
        # Using only LCU data - no external sources needed
        
        # Extract skins
        raw_skins = champ_data.get('skins', [])
        
        for skin in raw_skins:
            skin_id = skin.get('id')
            localized_skin_name = skin.get('name', '')
            
            if skin_id is None or not localized_skin_name:
                continue
            
            # Use localized skin name directly from LCU
            english_skin_name = localized_skin_name
            
            # Extract detailed chroma information
            raw_chromas = skin.get('chromas', [])
            chroma_details = []
            
            for chroma in raw_chromas:
                chroma_id = chroma.get('id')
                localized_chroma_name = chroma.get('name', '')
                
                if chroma_id is None:
                    continue
                
                # Use localized chroma name directly from LCU
                chroma_name = localized_chroma_name
                
                # Extract color palette from chroma
                colors = chroma.get('colors', [])
                chroma_path = chroma.get('chromaPath', '')
                
                chroma_info = {
                    'id': chroma_id,
                    'name': chroma_name,
                    'colors': colors,
                    'chromaPath': chroma_path,
                    'skinId': skin_id
                }
                
                chroma_details.append(chroma_info)
                self.cache.chroma_id_map[chroma_id] = chroma_info
            
            skin_data = {
                'skinId': skin_id,
                'championId': champion_id,
                'skinName': english_skin_name,  # Use English skin name
                'isBase': skin.get('isBase', False),
                'chromas': len(raw_chromas),
                'chromaDetails': chroma_details,  # Full chroma data
                'num': skin.get('num', 0)  # Skin number (0 = base)
            }
            
            self.cache.skins.append(skin_data)
            self.cache.skin_id_map[skin_id] = skin_data
            # Skin names are stored on each entry; we no longer index by name.
        
        log.info(f"[LCU-SCRAPER] ✓ Scraped {len(self.cache.skins)} skins for {self.cache.champion_name} (ID: {champion_id})")
        
        # Log first few skins for debugging
        if self.cache.skins:
            log.debug(f"[LCU-SCRAPER] Sample skins:")
            for skin in self.cache.skins[:3]:
                log.debug(f"  - {skin['skinName']} (ID: {skin['skinId']})")
        
        return True
    
    # No longer converting to English - using LCU localized names directly
    
    @property
    def cached_champion_name(self) -> Optional[str]:
        """Get the name of the currently cached champion"""
        return self.cache.champion_name
    
    @property
    def cached_champion_id(self) -> Optional[int]:
        """Get the ID of the currently cached champion"""
        return self.cache.champion_id
    
    def get_chromas_for_skin(self, skin_id: int) -> Optional[list]:
        """Get chroma details for a specific skin
        
        Args:
            skin_id: Skin ID to get chromas for
            
        Returns:
            List of chroma dicts with 'id', 'name', 'colors', 'chromaPath', or None if not found
        """
        skin_data = self.cache.get_skin_by_id(skin_id)
        if skin_data:
            return skin_data.get('chromaDetails', [])
        return None
    
    def get_chroma_by_id(self, chroma_id: int) -> Optional[dict]:
        """Get chroma data by chroma ID
        
        Args:
            chroma_id: Chroma ID to look up
            
        Returns:
            Chroma dict or None if not found
        """
        return self.cache.chroma_id_map.get(chroma_id)
    
    # No longer using external data for chroma names

