#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Name Resolver
Resolves skin name for injection based on state (historic, random, or hovered)
"""

import logging
from typing import Optional

from state import SharedState
from utils.core.logging import get_logger

log = get_logger()


class SkinNameResolver:
    """Resolves skin name for injection"""
    
    def __init__(self, state: SharedState, skin_scraper=None):
        """Initialize skin name resolver
        
        Args:
            state: Shared application state
            skin_scraper: Skin scraper instance
        """
        self.state = state
        self.skin_scraper = skin_scraper
    
    def resolve_injection_name(self) -> Optional[str]:
        """Resolve injection name based on current state
        
        Returns:
            Injection name (e.g., "skin_1234" or "chroma_5678") or None
        """
        # Historic mode override
        if getattr(self.state, 'historic_mode_active', False) and getattr(self.state, 'historic_skin_id', None):
            hist_id = int(self.state.historic_skin_id)
            chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
            if chroma_id_map and hist_id in chroma_id_map:
                name = f"chroma_{hist_id}"
                log.info(f"[HISTORIC] Using historic chroma ID for injection: {hist_id}")
            else:
                name = f"skin_{hist_id}"
                log.info(f"[HISTORIC] Using historic skin ID for injection: {hist_id}")
            return name
        
        # Random mode
        random_mode_active = getattr(self.state, 'random_mode_active', False)
        random_skin_name = getattr(self.state, 'random_skin_name', None)
        if random_mode_active and random_skin_name:
            random_skin_id = getattr(self.state, 'random_skin_id', None)
            if random_skin_id:
                if self.skin_scraper and self.skin_scraper.cache and random_skin_id in self.skin_scraper.cache.chroma_id_map:
                    name = f"chroma_{random_skin_id}"
                    log.info(f"[RANDOM] Injecting random chroma: {random_skin_name} (ID: {random_skin_id})")
                else:
                    name = f"skin_{random_skin_id}"
                    log.info(f"[RANDOM] Injecting random skin: {random_skin_name} (ID: {random_skin_id})")
                return name
            else:
                log.error(f"[RANDOM] No random skin ID available for injection")
                return None
        
        # Normal hovered skin
        skin_id = getattr(self.state, 'last_hovered_skin_id', None)
        if skin_id:
            from utils.core.utilities import is_base_skin
            chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
            
            if is_base_skin(skin_id, chroma_id_map):
                name = f"skin_{skin_id}"
                log.debug(f"[INJECT] Using base skin ID from state: '{name}' (ID: {skin_id})")
            else:
                name = f"chroma_{skin_id}"
                log.debug(f"[INJECT] Using chroma ID from state: '{name}' (chroma: {skin_id})")
            return name
        else:
            log.error(f"[INJECT] No skin ID available for injection")
            log.error(f"[INJECT] State: last_hovered_skin_id={getattr(self.state, 'last_hovered_skin_id', None)}")
            log.error(f"[INJECT] State: last_hovered_skin_key={getattr(self.state, 'last_hovered_skin_key', None)}")
            return None
    
    def build_skin_label(self) -> Optional[str]:
        """Build clean skin label for logging
        
        Returns:
            Clean skin label or None
        """
        raw = self.state.last_hovered_skin_key or self.state.last_hovered_skin_slug \
            or (str(self.state.last_hovered_skin_id) if self.state.last_hovered_skin_id else None)
        
        if not raw:
            return None
        
        try:
            champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
            cname = ""
            if champ_id and self.skin_scraper and self.skin_scraper.cache.is_loaded_for_champion(champ_id):
                cname = self.skin_scraper.cache.champion_name or ""

            # Get skin name from LCU
            base = ""
            if self.state.last_hovered_skin_id and self.skin_scraper and self.skin_scraper.cache.is_loaded_for_champion(champ_id):
                skin_data = self.skin_scraper.cache.get_skin_by_id(self.state.last_hovered_skin_id)
                if skin_data:
                    base = skin_data.get('skinName', '').strip()
            
            if not base:
                base = (raw or "").strip()

            # Normalize spaces and apostrophes
            base_clean = base.replace(" ", " ").replace("'", "'")
            c_clean = (cname or "").replace(" ", " ").replace("'", "'")

            # Remove champion prefix if present
            if c_clean and base_clean.lower().startswith(c_clean.lower() + " "):
                base_clean = base_clean[len(c_clean) + 1:].lstrip()
            elif c_clean and base_clean.lower().endswith(" " + c_clean.lower()):
                base_clean = base_clean[:-(len(c_clean) + 1)].rstrip()

            # Check if champion name is already included
            nb = base_clean.lower().strip() if base_clean else ""
            nc = c_clean.lower().strip() if c_clean else ""
            if nc and (nc in nb.split()):
                final_label = base_clean
            else:
                final_label = (base_clean + (" " + c_clean if c_clean else "")).strip()
            
            return final_label
        except Exception:
            return raw or ""

