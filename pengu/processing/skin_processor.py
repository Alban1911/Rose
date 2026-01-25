#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Processor
Handles processing skin names and mapping to IDs
"""

import logging
from typing import Optional

from utils.core.utilities import get_champion_id_from_skin_id

log = logging.getLogger(__name__)


class SkinProcessor:
    """Processes skin names and updates shared state"""
    
    def __init__(self, shared_state, skin_scraper=None, skin_mapping=None):
        """Initialize skin processor
        
        Args:
            shared_state: Shared application state
            skin_scraper: LCU skin scraper instance
            skin_mapping: Skin mapping instance
        """
        self.shared_state = shared_state
        self.skin_scraper = skin_scraper
        self.skin_mapping = skin_mapping
        self.last_skin_name: Optional[str] = None
    
    def process_skin_name(self, skin_name: str, broadcaster=None) -> None:
        """Process a skin name and update shared state
        
        Args:
            skin_name: Skin name to process
            broadcaster: Optional broadcaster for sending updates
        """
        try:
            log.info("[SkinMonitor] Skin detected: '%s'", skin_name)
            self.shared_state.ui_last_text = skin_name
            
            if getattr(self.shared_state, "is_swiftplay_mode", False):
                self._process_swiftplay_skin_name(skin_name, broadcaster)
            else:
                self._process_regular_skin_name(skin_name, broadcaster)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "[SkinMonitor] Error processing skin '%s': %s",
                skin_name,
                exc,
            )
    
    def _process_swiftplay_skin_name(self, skin_name: str, broadcaster=None) -> None:
        """Process skin name for Swiftplay mode"""
        if not self.skin_mapping:
            log.warning("[SkinMonitor] No skin mapping available for Swiftplay")
            return
        
        skin_id = self.skin_mapping.find_skin_id_by_name(skin_name)
        if skin_id is None:
            log.warning(
                "[SkinMonitor] Unable to map Swiftplay skin '%s' to ID",
                skin_name,
            )
            return
        
        champion_id = get_champion_id_from_skin_id(skin_id)
        self.shared_state.swiftplay_skin_tracking[champion_id] = skin_id
        self.shared_state.ui_skin_id = skin_id
        self.shared_state.last_hovered_skin_id = skin_id
        
        log.info(
            "[SkinMonitor] Swiftplay skin '%s' mapped to champion %s (id=%s)",
            skin_name,
            champion_id,
            skin_id,
        )
        
        if broadcaster:
            broadcaster.broadcast_skin_state(skin_name, skin_id)
    
    def _process_regular_skin_name(self, skin_name: str, broadcaster=None) -> None:
        """Process skin name for regular champion select"""
        if not self.skin_scraper:
            log.warning("[SkinMonitor] No skin scraper available")
            return
        
        result = self._find_skin_id(skin_name)
        if result is None:
            log.debug(
                "[SkinMonitor] No skin ID found for '%s' with current data",
                skin_name,
            )
            return
        
        skin_id, matched_name = result
        self.shared_state.ui_skin_id = skin_id
        self.shared_state.last_hovered_skin_id = skin_id
        
        # Use the matched name from the matcher instead of the input
        self.shared_state.last_hovered_skin_key = matched_name
        log.info(
            "[SkinMonitor] Skin '%s' mapped to ID %s (key=%s)",
            skin_name,
            skin_id,
            self.shared_state.last_hovered_skin_key,
        )
        
        if broadcaster:
            # Broadcast the matched name, not the input name
            broadcaster.broadcast_skin_state(matched_name, skin_id)
    
    def _find_skin_id(self, skin_name: str) -> Optional[tuple[int, str]]:
        """Find skin ID and matched name using skin scraper
        
        Returns:
            Tuple of (skin_id, matched_name) if found, None otherwise
        """
        champ_id = getattr(self.shared_state, "locked_champ_id", None)
        if not champ_id:
            return None
        
        if not self.skin_scraper:
            return None
        
        try:
            if not self.skin_scraper.scrape_champion_skins(champ_id):
                return None
        except Exception:
            return None
        
        try:
            result = self.skin_scraper.find_skin_by_text(skin_name)
        except Exception:
            return None
        
        if result:
            skin_id, matched_name, similarity = result
            log.info(
                "[SkinMonitor] Matched '%s' -> '%s' (ID=%s, similarity=%.4f)",
                skin_name,
                matched_name,
                skin_id,
                similarity,
            )
            return (skin_id, matched_name)
        else:
            log.warning(
                "[SkinMonitor] No match found for '%s'",
                skin_name
            )
        
        return None
    
    def clear_cache(self) -> None:
        """Clear cached state"""
        self.last_skin_name = None
        self.shared_state.ui_skin_id = None
        self.shared_state.ui_last_text = None

