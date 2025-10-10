#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU Skin Scraper - Scrape skins for a specific champion from LCU
"""

import requests
from typing import Optional, Dict, List, Tuple
from utils.logging import get_logger
from constants import LCU_SKIN_SCRAPER_TIMEOUT_S, SKIN_NAME_MIN_SIMILARITY

log = get_logger()


class ChampionSkinCache:
    """Cache for champion skins scraped from LCU"""
    
    def __init__(self):
        self.champion_id = None
        self.champion_name = None
        self.skins = []  # List of {skinId, skinName, isBase, chromas, chromaDetails}
        self.skin_id_map = {}  # skinId -> skin data
        self.skin_name_map = {}  # skinName -> skin data
        self.chroma_id_map = {}  # chromaId -> chroma data (for quick lookup)
        self.chroma_variant_names = {}  # chromaId -> variant name from CDragon
    
    def clear(self):
        """Clear the cache"""
        self.champion_id = None
        self.champion_name = None
        self.skins = []
        self.skin_id_map = {}
        self.skin_name_map = {}
        self.chroma_id_map = {}
        self.chroma_variant_names = {}
    
    def is_loaded_for_champion(self, champion_id: int) -> bool:
        """Check if cache is loaded for a specific champion"""
        return self.champion_id == champion_id and len(self.skins) > 0
    
    def get_skin_by_id(self, skin_id: int) -> Optional[Dict]:
        """Get skin data by skin ID"""
        return self.skin_id_map.get(skin_id)
    
    def get_skin_by_name(self, skin_name: str) -> Optional[Dict]:
        """Get skin data by skin name (exact match)"""
        return self.skin_name_map.get(skin_name)
    
    def get_all_skins(self) -> List[Dict]:
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
    
    def fetch_all_chroma_names_from_cdragon(self, champion_id: int) -> Dict[int, str]:
        """Fetch ALL chroma names for a champion in one API call
        
        Args:
            champion_id: Champion ID
            
        Returns:
            Dict mapping chroma_id -> variant_name (e.g. {86015: "Amethyst"})
        """
        try:
            # CommunityDragon champion endpoint - gets ALL skins and chromas at once
            url = f"https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/champions/{champion_id}.json"
            response = requests.get(url, timeout=LCU_SKIN_SCRAPER_TIMEOUT_S)
            
            if response.status_code != 200:
                return {}
            
            data = response.json()
            chroma_name_map = {}
            
            # Parse all skins and their chromas
            for skin in data.get('skins', []):
                skin_name = skin.get('name', 'Unknown')
                for chroma in skin.get('chromas', []):
                    chroma_id = chroma.get('id')
                    full_name = chroma.get('name')
                    
                    if chroma_id and full_name:
                        # Extract last word as variant name
                        variant_name = full_name.split()[-1]
                        chroma_name_map[chroma_id] = variant_name
                        
                        # Debug: Log if variant name is same as champion name (likely missing variant)
                        if variant_name == data.get('name', ''):
                            log.debug(f"[CDragon] {chroma_id} ({skin_name}): full='{full_name}' -> variant='{variant_name}' (SAME AS CHAMP)")
            
            if chroma_name_map:
                log.info(f"[CDragon] Fetched {len(chroma_name_map)} chroma names for champion {champion_id}")
                # Log a few samples
                sample_ids = list(chroma_name_map.keys())[:3]
                for cid in sample_ids:
                    log.debug(f"[CDragon] Sample: {cid} -> '{chroma_name_map[cid]}'")
            else:
                log.warning(f"[CDragon] No chroma names found for champion {champion_id}")
            
            return chroma_name_map
            
        except Exception as e:
            log.debug(f"[CDragon] Failed to fetch chroma names for champion {champion_id}: {e}")
            return {}
    
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
        
        # Extract skins
        raw_skins = champ_data.get('skins', [])
        
        for skin in raw_skins:
            skin_id = skin.get('id')
            skin_name = skin.get('name', '')
            
            if skin_id is None or not skin_name:
                continue
            
            # Extract detailed chroma information
            raw_chromas = skin.get('chromas', [])
            chroma_details = []
            
            for chroma in raw_chromas:
                chroma_id = chroma.get('id')
                chroma_name = chroma.get('name', '')
                
                if chroma_id is None:
                    continue
                
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
                'skinName': skin_name,
                'isBase': skin.get('isBase', False),
                'chromas': len(raw_chromas),
                'chromaDetails': chroma_details,  # Full chroma data
                'num': skin.get('num', 0)  # Skin number (0 = base)
            }
            
            self.cache.skins.append(skin_data)
            self.cache.skin_id_map[skin_id] = skin_data
            self.cache.skin_name_map[skin_name] = skin_data
        
        log.info(f"[LCU-SCRAPER] ✓ Scraped {len(self.cache.skins)} skins for {self.cache.champion_name} (ID: {champion_id})")
        
        # Log first few skins for debugging
        if self.cache.skins:
            log.debug(f"[LCU-SCRAPER] Sample skins:")
            for skin in self.cache.skins[:3]:
                log.debug(f"  - {skin['skinName']} (ID: {skin['skinId']})")
        
        return True
    
    def find_skin_by_text(self, text: str, use_levenshtein: bool = True) -> Optional[Tuple[int, str, float]]:
        """Find best matching skin by OCR text using Levenshtein distance
        
        Args:
            text: OCR text to match
            use_levenshtein: If True, use Levenshtein distance for fuzzy matching
            
        Returns:
            Tuple of (skinId, skinName, similarity_score) if found, None otherwise
        """
        if not text or not self.cache.skins:
            return None
        
        # Try exact match first
        exact_match = self.cache.get_skin_by_name(text)
        if exact_match:
            return (exact_match['skinId'], exact_match['skinName'], 1.0)
        
        # Fuzzy matching with Levenshtein distance
        if not use_levenshtein:
            return None
        
        try:
            from rapidfuzz.distance import Levenshtein
        except ImportError:
            log.warning("[LCU-SCRAPER] rapidfuzz not available for fuzzy matching")
            return None
        
        best_match = None
        best_distance = float('inf')
        best_similarity = 0.0
        
        for skin in self.cache.skins:
            skin_name = skin['skinName']
            
            # Calculate Levenshtein distance
            distance = Levenshtein.distance(text, skin_name)
            max_len = max(len(text), len(skin_name))
            similarity = 1.0 - (distance / max_len) if max_len > 0 else 0.0
            
            # Update best match
            if distance < best_distance:
                best_distance = distance
                best_similarity = similarity
                best_match = skin
        
        # Only return if similarity is above threshold
        if best_match and best_similarity >= SKIN_NAME_MIN_SIMILARITY:
            return (best_match['skinId'], best_match['skinName'], best_similarity)
        
        return None
    
    def get_cached_champion_name(self) -> Optional[str]:
        """Get the name of the currently cached champion"""
        return self.cache.champion_name
    
    def get_cached_champion_id(self) -> Optional[int]:
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
    
    def get_chroma_variant_name(self, chroma_id: int) -> Optional[str]:
        """Get chroma variant name from cached CommunityDragon data
        
        Args:
            chroma_id: Chroma ID to look up
            
        Returns:
            Variant name (e.g. "Amethyst", "Ruby") or None
        """
        return self.cache.chroma_variant_names.get(chroma_id)

