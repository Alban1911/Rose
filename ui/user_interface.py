#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
User Interface Manager - Parent class for all UI components
Manages ChromaUI and UnownedFrame as separate components
"""

import threading
from typing import Optional, Callable
from utils.logging import get_logger
from ui.chroma_ui import ChromaUI

log = get_logger()


class UserInterface:
    """Parent class managing all UI components"""
    
    def __init__(self, state, skin_scraper, db=None):
        self.state = state
        self.skin_scraper = skin_scraper
        self.db = db
        self.lock = threading.Lock()
        
        # UI Components
        self.chroma_ui = None
        self.unowned_frame = None
        
        # Current skin tracking
        self.current_skin_id = None
        self.current_skin_name = None
        self.current_champion_name = None
        
        # Initialize components
        self._initialize_components()
    
    def _initialize_components(self):
        """Initialize all UI components"""
        # Initialize ChromaUI (chroma selector + panel)
        self.chroma_ui = ChromaUI(
            skin_scraper=self.skin_scraper,
            state=self.state,
            db=self.db
        )
        
        # Create UnownedFrame instance directly
        from ui.unowned_frame import UnownedFrame
        self.unowned_frame = UnownedFrame()
        self._last_unowned_skin_id = None
    
    def show_skin(self, skin_id: int, skin_name: str, champion_name: str = None):
        """Show UI for a specific skin - manages both ChromaUI and UnownedFrame"""
        with self.lock:
            # Prevent duplicate processing of the same skin
            if (self.current_skin_id == skin_id and 
                self.current_skin_name == skin_name and 
                self.current_champion_name == champion_name):
                log.debug(f"[UI] Skipping duplicate skin: {skin_name} (ID: {skin_id})")
                return
            
            log.info(f"[UI] Showing skin: {skin_name} (ID: {skin_id})")
            
            # Update current skin tracking
            self.current_skin_id = skin_id
            self.current_skin_name = skin_name
            self.current_champion_name = champion_name
            
            # Check if skin has chromas
            has_chromas = self._skin_has_chromas(skin_id)
            
            # Check ownership
            is_owned = skin_id in self.state.owned_skin_ids
            is_base_skin = skin_id % 1000 == 0
            
            # Determine what to show
            should_show_chroma_ui = has_chromas
            should_show_unowned_frame = not is_owned and not is_base_skin
            
            log.debug(f"[UI] Skin analysis: has_chromas={has_chromas}, is_owned={is_owned}, is_base_skin={is_base_skin}")
            log.debug(f"[UI] Will show: chroma_ui={should_show_chroma_ui}, unowned_frame={should_show_unowned_frame}")
            
            # Show/hide ChromaUI based on chromas
            if should_show_chroma_ui:
                self._show_chroma_ui(skin_id, skin_name, champion_name)
            else:
                self._hide_chroma_ui()
            
            # Show/hide UnownedFrame based on ownership
            if should_show_unowned_frame:
                self._show_unowned_frame(skin_id, skin_name, champion_name)
            else:
                self._hide_unowned_frame()
    
    def hide_all(self):
        """Hide all UI components"""
        with self.lock:
            log.info("[UI] Hiding all UI components")
            self._hide_chroma_ui()
            self._hide_unowned_frame()
    
    def _skin_has_chromas(self, skin_id: int) -> bool:
        """Check if skin has chromas"""
        try:
            chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
            return chromas and len(chromas) > 0
        except Exception as e:
            log.debug(f"[UI] Error checking chromas for skin {skin_id}: {e}")
            return False
    
    def _show_chroma_ui(self, skin_id: int, skin_name: str, champion_name: str = None):
        """Show ChromaUI for skin with chromas"""
        if self.chroma_ui:
            try:
                self.chroma_ui.show_for_skin(skin_id, skin_name, champion_name)
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
    
    def _show_unowned_frame(self, skin_id: int, skin_name: str, champion_name: str = None):
        """Show UnownedFrame for unowned skin"""
        if self.unowned_frame:
            try:
                # UnownedFrame is statically positioned - just show it
                # Check if this is the first unowned skin or switching between unowned skins
                if self._last_unowned_skin_id is None:
                    # First unowned skin - immediate fade in
                    self.unowned_frame.fade_in()
                    log.debug(f"[UI] UnownedFrame first shown for {skin_name}")
                else:
                    # Switching between unowned skins - fade out then fade in
                    self.unowned_frame.fade_out()
                    # Schedule fade in after fade out completes
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(200, lambda: self.unowned_frame.fade_in())
                    log.debug(f"[UI] UnownedFrame transition shown for {skin_name}")
                
                # Track the last unowned skin
                self._last_unowned_skin_id = skin_id
            except Exception as e:
                log.error(f"[UI] Error showing UnownedFrame: {e}")
    
    def _hide_unowned_frame(self):
        """Hide UnownedFrame"""
        if self.unowned_frame:
            try:
                # Fade out UnownedFrame
                self.unowned_frame.fade_out()
                # Reset tracking when hiding
                self._last_unowned_skin_id = None
                log.debug("[UI] UnownedFrame hidden")
            except Exception as e:
                log.debug(f"[UI] Error hiding UnownedFrame: {e}")
    
    
    def cleanup(self):
        """Clean up all UI components"""
        with self.lock:
            if self.chroma_ui:
                self.chroma_ui.cleanup()
            if self.unowned_frame:
                self.unowned_frame.cleanup()
            log.info("[UI] All UI components cleaned up")


# Global UI instance
_user_interface = None


def get_user_interface(state=None, skin_scraper=None, db=None) -> UserInterface:
    """Get or create global user interface instance"""
    global _user_interface
    if _user_interface is None:
        _user_interface = UserInterface(state, skin_scraper, db)
    return _user_interface
