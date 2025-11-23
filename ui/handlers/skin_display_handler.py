#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Display Handler
Handles skin display logic and chroma UI management
"""

from typing import Optional
from state import SharedState
from utils.core.logging import get_logger
from utils.core.utilities import (
    is_owned, is_chroma_id, get_base_skin_id_for_chroma,
    is_base_skin_owned, is_base_skin
)

log = get_logger()


class SkinDisplayHandler:
    """Handles skin display logic and chroma UI management"""
    
    def __init__(self, state: SharedState, skin_scraper=None, chroma_ui=None):
        """Initialize skin display handler
        
        Args:
            state: Shared application state
            skin_scraper: Skin scraper instance
            chroma_ui: ChromaUI instance
        """
        self.state = state
        self.skin_scraper = skin_scraper
        self.chroma_ui = chroma_ui
        self._last_base_skin_id: Optional[int] = None
    
    def show_skin(
        self,
        skin_id: int,
        skin_name: str,
        champion_name: str = None,
        champion_id: int = None,
        current_skin_id: Optional[int] = None,
        current_skin_name: Optional[str] = None,
        current_champion_name: Optional[str] = None,
    ) -> tuple[Optional[int], Optional[int]]:
        """Show UI for a specific skin
        
        Returns:
            Tuple of (new_base_skin_id, prev_base_skin_id)
        """
        # Prevent duplicate processing of the same skin
        if (current_skin_id == skin_id and 
            current_skin_name == skin_name and 
            current_champion_name == champion_name):
            log.debug(f"[UI] Skipping duplicate skin: {skin_name} (ID: {skin_id})")
            return None, None
        
        log.info(f"[UI] Showing skin: {skin_name} (ID: {skin_id})")
        
        # Capture previous base skin before updating current
        prev_skin_id = current_skin_id
        prev_base_skin_id = None
        if prev_skin_id is not None:
            prev_chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
            prev_base_skin_id = prev_skin_id if is_base_skin(prev_skin_id, prev_chroma_id_map) else get_base_skin_id_for_chroma(prev_skin_id, prev_chroma_id_map)
        
        # Check if this is a chroma selection for the same base skin
        is_chroma_selection = self._is_chroma_selection_for_same_base_skin(skin_id, skin_name, current_skin_id)
        
        # Check if skin has chromas
        has_chromas = self.skin_has_chromas(skin_id)
        
        # Check ownership
        is_owned_var = is_owned(skin_id, self.state.owned_skin_ids)
        chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
        is_base_skin_var = is_base_skin(skin_id, chroma_id_map)
        # Determine new base skin id for current selection
        new_base_skin_id = skin_id if is_base_skin_var else get_base_skin_id_for_chroma(skin_id, chroma_id_map)
        
        # Check if base skin is owned
        base_skin_owned = is_base_skin_owned(skin_id, self.state.owned_skin_ids, chroma_id_map)
        
        # Special case: Elementalist Lux forms (fake IDs 99991-99999) should always show UnownedFrame
        is_elementalist_form = 99991 <= skin_id <= 99999
        # Special case: Sahn Uzal Mordekaiser forms (IDs 82998, 82999) should always show UnownedFrame
        is_mordekaiser_form = skin_id in (82998, 82999)
        # Special case: Spirit Blossom Morgana forms (ID 25999) should always show UnownedFrame
        is_morgana_form = skin_id == 25999
        # Special case: Radiant Sett forms (IDs 875998, 875999) should always show UnownedFrame
        is_sett_form = skin_id in (875998, 875999)
        # Special case: KDA Seraphine forms (IDs 147002, 147003) should always show UnownedFrame
        is_seraphine_form = skin_id in (147002, 147003)
        
        # Same-base chroma swap occurs when switching from base skin (or its chroma) to another chroma of same base
        is_same_base_chroma = (not is_base_skin_var) and (prev_base_skin_id is not None) and (new_base_skin_id == prev_base_skin_id)
        
        # Determine what to show
        should_show_chroma_ui = has_chromas
        
        log.debug(f"[UI] Skin analysis: has_chromas={has_chromas}, is_owned={is_owned_var}, is_base_skin={is_base_skin_var}, base_skin_owned={base_skin_owned}, is_elementalist_form={is_elementalist_form}, is_mordekaiser_form={is_mordekaiser_form}, is_morgana_form={is_morgana_form}, is_sett_form={is_sett_form}, is_seraphine_form={is_seraphine_form}, is_chroma_selection={is_chroma_selection}")
        log.debug(f"[UI] Will show: chroma_ui={should_show_chroma_ui}")
        
        # Show/hide ChromaUI based on chromas
        if should_show_chroma_ui:
            self._show_chroma_ui(skin_id, skin_name, champion_name, champion_id)
        else:
            self._hide_chroma_ui()
        
        # Update last base skin id after handling
        self._last_base_skin_id = new_base_skin_id if new_base_skin_id is not None else (skin_id if is_base_skin_var else None)
        
        return new_base_skin_id, prev_base_skin_id
    
    def skin_has_chromas(self, skin_id: int) -> bool:
        """Check if skin has chromas"""
        try:
            # Special case: Elementalist Lux (skin ID 99007) has Forms instead of chromas
            if skin_id == 99007:
                log.debug(f"[UI] Elementalist Lux detected - has Forms instead of chromas")
                return True
            
            # Special case: Elementalist Lux forms (fake IDs 99991-99999) are considered chromas
            if 99991 <= skin_id <= 99999:
                log.debug(f"[UI] Elementalist Lux form detected - considered as chroma")
                return True
            
            # Special case: Sahn Uzal Mordekaiser (skin ID 82054) has Forms instead of chromas
            if skin_id == 82054:
                log.debug(f"[UI] Sahn Uzal Mordekaiser detected - has Forms instead of chromas")
                return True
            
            # Special case: Sahn Uzal Mordekaiser forms (IDs 82998, 82999) are considered chromas
            if skin_id in (82998, 82999):
                log.debug(f"[UI] Sahn Uzal Mordekaiser form detected - considered as chroma")
                return True
            
            # Special case: Spirit Blossom Morgana (skin ID 25080) has Forms instead of chromas
            if skin_id == 25080:
                log.debug(f"[UI] Spirit Blossom Morgana detected - has Forms instead of chromas")
                return True
            
            # Special case: Spirit Blossom Morgana forms (ID 25999) are considered chromas
            if skin_id == 25999:
                log.debug(f"[UI] Spirit Blossom Morgana form detected - considered as chroma")
                return True
            
            # Special case: Radiant Sett (skin ID 875066) has Forms instead of chromas
            if skin_id == 875066:
                log.debug(f"[UI] Radiant Sett detected - has Forms instead of chromas")
                return True
            
            # Special case: Radiant Sett forms (IDs 875998, 875999) are considered chromas
            if skin_id in (875998, 875999):
                log.debug(f"[UI] Radiant Sett form detected - considered as chroma")
                return True
            
            # Special case: KDA Seraphine (skin ID 147001) has Forms instead of chromas
            if skin_id == 147001:
                log.debug(f"[UI] KDA Seraphine detected - has Forms instead of chromas")
                return True
            
            # Special case: KDA Seraphine forms (IDs 147002, 147003) are considered chromas
            if skin_id in (147002, 147003):
                log.debug(f"[UI] KDA Seraphine form detected - considered as chroma")
                return True
            
            # Special case: Risen Legend Kai'Sa (skin ID 145070) has HOL chroma instead of regular chromas
            if skin_id == 145070:
                log.debug(f"[UI] Risen Legend Kai'Sa detected - has HOL chroma instead of regular chromas")
                return True
            
            # Special case: Immortalized Legend Kai'Sa (skin ID 145071) is treated as a chroma of Risen Legend
            if skin_id == 145071:
                log.debug(f"[UI] Immortalized Legend Kai'Sa detected - treated as chroma of Risen Legend")
                return True
            
            # Special case: Risen Legend Kai'Sa HOL chroma (fake ID 100001) is considered a chroma
            if skin_id == 100001:
                log.debug(f"[UI] Risen Legend Kai'Sa HOL chroma detected - considered as chroma")
                return True
            
            # Special case: Risen Legend Ahri (skin ID 103085) has HOL chroma instead of regular chromas
            if skin_id == 103085:
                log.debug(f"[UI] Risen Legend Ahri detected - has HOL chroma instead of regular chromas")
                return True
            
            # Special case: Immortalized Legend Ahri (skin ID 103086) is treated as a chroma of Risen Legend Ahri
            if skin_id == 103086:
                log.debug(f"[UI] Immortalized Legend Ahri detected - treated as chroma of Risen Legend Ahri")
                return True
            
            # Special case: Risen Legend Ahri HOL chroma (fake ID 88888) is considered a chroma
            if skin_id == 88888:
                log.debug(f"[UI] Risen Legend Ahri HOL chroma detected - considered as chroma")
                return True
            
            # First, check if this skin_id is a chroma by looking it up in the chroma cache
            if self.skin_scraper and self.skin_scraper.cache:
                if skin_id in self.skin_scraper.cache.chroma_id_map:
                    # This is a chroma - it's always considered to have chromas
                    return True
            
            # For base skins, check if they actually have chromas
            chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
            return bool(chromas)
        except Exception as e:
            log.debug(f"[UI] Error checking chromas for skin {skin_id}: {e}")
            return False
    
    def _is_chroma_selection_for_same_base_skin(self, skin_id: int, skin_name: str, current_skin_id: Optional[int]) -> bool:
        """Check if this is a chroma selection for the same base skin we were already showing"""
        try:
            # Check if we have a current skin ID that's a base skin
            if not current_skin_id:
                return False
            
            # Check if the current skin is a base skin
            current_base_skin_id = current_skin_id
            chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
            if is_chroma_id(current_base_skin_id, chroma_id_map):
                # Current skin is already a chroma, get its base skin
                current_base_skin_id = get_base_skin_id_for_chroma(current_base_skin_id, chroma_id_map)
                if current_base_skin_id is None:
                    return False
            
            # Check if the new skin_id is a chroma of the same base skin
            if is_base_skin(skin_id, chroma_id_map):
                # New skin is a base skin, not a chroma selection
                return False
            
            # Get the base skin ID for the new chroma
            new_base_skin_id = get_base_skin_id_for_chroma(skin_id, chroma_id_map)
            if new_base_skin_id is None:
                return False
            
            # Check if both chromas belong to the same base skin
            is_same_base = current_base_skin_id == new_base_skin_id
            
            if is_same_base:
                log.debug(f"[UI] Detected chroma selection for same base skin: {current_base_skin_id} -> {skin_id}")
            
            return is_same_base
            
        except Exception as e:
            log.debug(f"[UI] Error checking chroma selection: {e}")
            return False
    
    def _show_chroma_ui(self, skin_id: int, skin_name: str, champion_name: str = None, champion_id: int = None):
        """Show ChromaUI for skin with chromas"""
        if self.chroma_ui:
            try:
                self.chroma_ui.show_for_skin(skin_id, skin_name, champion_name, champion_id)
                log.debug(f"[UI] ChromaUI shown for {skin_name}")
            except Exception as e:
                log.error(f"[UI] Error showing ChromaUI: {e}")
    
    def _hide_chroma_ui(self):
        """Hide ChromaUI"""
        if self.chroma_ui:
            try:
                self.chroma_ui.hide()
                log.debug("[UI] ChromaUI hidden")
            except Exception as e:
                log.debug(f"[UI] Error hiding ChromaUI: {e}")

