#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ChromaUI - UI component for chroma selection
Manages chroma selector and panel for skins with chromas
"""

import threading
from typing import Optional
from utils.logging import get_logger
from ui.chroma_selector import ChromaSelector

log = get_logger()


class ChromaUI:
    """UI component for chroma selection functionality"""
    
    def __init__(self, skin_scraper, state, db=None):
        self.skin_scraper = skin_scraper
        self.state = state
        self.db = db
        self.lock = threading.Lock()
        
        # Initialize chroma selector
        self.chroma_selector = ChromaSelector(
            skin_scraper=skin_scraper,
            state=state,
            db=db
        )
        
        log.debug("[ChromaUI] Initialized")
    
    def show_for_skin(self, skin_id: int, skin_name: str, champion_name: str = None):
        """Show ChromaUI for a skin with chromas"""
        with self.lock:
            try:
                log.debug(f"[ChromaUI] Showing for skin: {skin_name} (ID: {skin_id})")
                self.chroma_selector.show_button_for_skin(skin_id, skin_name, champion_name)
            except Exception as e:
                log.error(f"[ChromaUI] Error showing for skin: {e}")
    
    def hide(self):
        """Hide ChromaUI"""
        with self.lock:
            try:
                log.debug("[ChromaUI] Hiding")
                self.chroma_selector.hide()
            except Exception as e:
                log.debug(f"[ChromaUI] Error hiding: {e}")
    
    def cleanup(self):
        """Clean up ChromaUI resources"""
        with self.lock:
            try:
                if self.chroma_selector:
                    self.chroma_selector.cleanup()
                log.debug("[ChromaUI] Cleaned up")
            except Exception as e:
                log.debug(f"[ChromaUI] Error during cleanup: {e}")
