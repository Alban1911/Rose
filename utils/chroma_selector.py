#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma Selection Integration - New Workflow
Shows chroma wheel immediately when skin is detected (not during injection)
"""

import threading
from typing import Optional
from utils.chroma_wheel import get_chroma_wheel
from utils.logging import get_logger

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
        
        # Get global wheel manager
        self.wheel = get_chroma_wheel()
        self.wheel.on_chroma_selected = self._on_chroma_selected
    
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
    
    def should_show_chroma_wheel(self, skin_id: int) -> bool:
        """
        Check if chroma wheel should be shown for this skin
        
        Args:
            skin_id: Skin ID to check
            
        Returns:
            True if skin has chromas and wheel should be shown
        """
        if skin_id is None or skin_id == 0:
            return False  # Base skins don't have chromas
        
        try:
            chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
            return chromas is not None and len(chromas) > 0
        except Exception as e:
            log.debug(f"[CHROMA] Error checking chromas for skin {skin_id}: {e}")
            return False
    
    def show_for_skin(self, skin_id: int, skin_name: str):
        """
        Show chroma wheel for a skin (called immediately when OCR detects it)
        
        Args:
            skin_id: Skin ID to show chromas for
            skin_name: Display name of the skin
        """
        with self.lock:
            # Don't show if already showing for this skin
            if self.current_skin_id == skin_id and self.state.pending_chroma_selection:
                return
            
            chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
            
            if not chromas or len(chromas) == 0:
                log.debug(f"[CHROMA] No chromas found for skin {skin_id}")
                return
            
            log.info(f"[CHROMA] Showing wheel for {skin_name} ({len(chromas)} chromas)")
            
            self.current_skin_id = skin_id
            self.state.pending_chroma_selection = True
            
            # Reset to base by default
            self.state.selected_chroma_id = None
            
            # Show the wheel
            try:
                self.wheel.show(skin_name, chromas)
            except Exception as e:
                log.error(f"[CHROMA] Failed to show wheel: {e}")
                self.state.pending_chroma_selection = False
    
    def hide(self):
        """Hide the chroma wheel and reopen button"""
        with self.lock:
            self.wheel.hide()
            self.wheel.hide_reopen_button()
            self.state.pending_chroma_selection = False
            self.current_skin_id = None
    
    def cleanup(self):
        """Clean up resources"""
        with self.lock:
            if self.wheel:
                try:
                    self.wheel.cleanup()
                except Exception as e:
                    log.debug(f"[CHROMA] Error cleaning up wheel: {e}")


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
