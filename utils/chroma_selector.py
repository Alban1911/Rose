#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma Selection Integration - New Workflow
Shows chroma wheel immediately when skin is detected (not during injection)
"""

import threading
from typing import Optional
from utils.chroma_panel import get_chroma_panel
from utils.logging import get_logger
from utils.validation import validate_skin_id, validate_skin_name

log = get_logger()


class ChromaSelector:
    """
    Manages chroma selection with new workflow:
    - Show wheel immediately when OCR detects skin with chromas
    - Clicking chroma instantly updates state.last_hovered_skin_id
    - No confirmation needed
    - Injection later uses the selected chroma ID
    """
    
    def __init__(self, skin_scraper, state):
        """
        Initialize chroma selector
        
        Args:
            skin_scraper: LCUSkinScraper instance to get chroma data
            state: SharedState instance to track selection
        """
        self.skin_scraper = skin_scraper
        self.state = state
        self.lock = threading.Lock()
        self.current_skin_id = None  # Track which skin we're showing chromas for
        
        # Get global panel manager
        self.panel = get_chroma_panel()
        self.panel.on_chroma_selected = self._on_chroma_selected
    
    def _on_chroma_selected(self, chroma_id: int, chroma_name: str):
        """Callback when user clicks a chroma - update state immediately"""
        try:
            with self.lock:
                if chroma_id == 0 or chroma_id is None:
                    # Base skin selected - use original skin ID
                    log.info(f"[CHROMA] Base skin selected")
                    self.state.selected_chroma_id = None
                    # Keep original skin ID
                else:
                    # Chroma selected - update skin ID to chroma ID
                    log.info(f"[CHROMA] Chroma selected: {chroma_name} (ID: {chroma_id})")
                    self.state.selected_chroma_id = chroma_id
                    
                    # UPDATE: Change the hovered skin ID to the chroma ID
                    # This way injection will use the chroma ID
                    self.state.last_hovered_skin_id = chroma_id
                    
                    log.info(f"[CHROMA] Updated last_hovered_skin_id from {self.current_skin_id} to {chroma_id}")
                
                self.state.pending_chroma_selection = False
        except Exception as e:
            log.error(f"[CHROMA] Error in selection callback: {e}")
            import traceback
            log.error(traceback.format_exc())
    
    def should_show_chroma_panel(self, skin_id: int) -> bool:
        """
        Check if chroma panel should be shown for this skin
        
        Args:
            skin_id: Skin ID to check
            
        Returns:
            True if skin has any chromas (owned or unowned)
            
        Raises:
            TypeError: If skin_id is not an integer
            ValueError: If skin_id is negative
        """
        # Validate input
        validate_skin_id(skin_id)
        
        try:
            chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
            # Show panel if there are ANY chromas (owned or unowned)
            return chromas and len(chromas) > 0
        except Exception as e:
            log.debug(f"[CHROMA] Error checking chromas for skin {skin_id}: {e}")
            return False
    
    def show_button_for_skin(self, skin_id: int, skin_name: str, champion_name: str = None):
        """
        Show button for a skin (called when OCR detects skin with chromas)
        
        Args:
            skin_id: Skin ID to show button for
            skin_name: Display name of the skin
            champion_name: Champion name for direct path to chromas folder
            
        Raises:
            TypeError: If skin_id is not an integer or skin_name is not a string
            ValueError: If skin_id is negative or skin_name is empty
        """
        # Validate inputs
        validate_skin_id(skin_id)
        validate_skin_name(skin_name)
        
        with self.lock:
            chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
            
            if not chromas or len(chromas) == 0:
                log.debug(f"[CHROMA] No chromas found for skin {skin_id}")
                self.hide()
                return
            
            # Mark ownership status on each chroma for the injection system
            owned_skin_ids = self.state.owned_skin_ids
            owned_count = 0
            for chroma in chromas:
                chroma_id = chroma.get('id')
                is_owned = chroma_id in owned_skin_ids
                chroma['is_owned'] = is_owned  # Add ownership flag
                if is_owned:
                    owned_count += 1
            
            # Show ALL chromas (owned and unowned)
            # The injection system will handle them differently:
            # - Unowned chromas: inject as usual
            # - Owned chromas: force using base skin forcing mechanism
            log.debug(f"[CHROMA] Updating button for {skin_name} ({len(chromas)} total chromas, {owned_count} owned, {len(chromas) - owned_count} unowned)")
            
            self.current_skin_id = skin_id
            
            # Show the button with ALL chromas (owned + unowned)
            try:
                self.panel.show_button_for_skin(skin_id, skin_name, chromas, champion_name)
            except Exception as e:
                log.error(f"[CHROMA] Failed to show button: {e}")
    
    def hide(self):
        """Hide the chroma panel and reopen button"""
        with self.lock:
            self.panel.hide()
            self.panel.hide_reopen_button()
            self.state.pending_chroma_selection = False
            self.current_skin_id = None
    
    def cleanup(self):
        """Clean up resources"""
        with self.lock:
            if self.panel:
                try:
                    self.panel.cleanup()
                except Exception as e:
                    log.debug(f"[CHROMA] Error cleaning up panel: {e}")


# Global chroma selector instance (will be initialized in main.py)
_chroma_selector = None


def init_chroma_selector(skin_scraper, state):
    """Initialize global chroma selector"""
    global _chroma_selector
    _chroma_selector = ChromaSelector(skin_scraper, state)
    log.debug("[CHROMA] Chroma selector initialized")
    return _chroma_selector


def get_chroma_selector() -> Optional[ChromaSelector]:
    """Get global chroma selector instance"""
    return _chroma_selector
