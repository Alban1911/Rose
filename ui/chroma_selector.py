#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma Selection Integration - New Workflow
Shows chroma wheel immediately when skin is detected (not during injection)
"""

import threading
from typing import Optional
from ui.chroma_panel import get_chroma_panel
from utils.logging import get_logger
from utils.validation import validate_skin_id, validate_skin_name

log = get_logger()


class ChromaSelector:
    """
    Manages chroma selection with new workflow:
    - Show wheel immediately when UI detection finds skin with chromas
    - Clicking chroma instantly updates state.last_hovered_skin_id
    - No confirmation needed
    - Injection later uses the selected chroma ID
    """
    
    def __init__(self, skin_scraper, state, db=None):
        """
        Initialize chroma selector
        
        Args:
            skin_scraper: LCUSkinScraper instance to get chroma data
            state: SharedState instance to track selection
            db: NameDB instance for cross-language lookups
        """
        self.skin_scraper = skin_scraper
        self.state = state
        self.db = db
        self.lock = threading.Lock()
        self.current_skin_id = None  # Track which skin we're showing chromas for
        
        # Get global panel manager
        self.panel = get_chroma_panel(state=state, lcu=skin_scraper.lcu)
        self.panel.on_chroma_selected = self._on_chroma_selected
        
        # Pass database to preview manager
        if db:
            from ui.chroma_preview_manager import get_preview_manager
            preview_manager = get_preview_manager(db)
            log.debug("[CHROMA] Database passed to preview manager for cross-language lookups")
    
    def _on_chroma_selected(self, chroma_id: int, chroma_name: str):
        """Callback when user clicks a chroma - update state immediately"""
        try:
            with self.lock:
                if chroma_id == 0 or chroma_id is None:
                    # Base skin selected - reset to original skin ID and skin name
                    log.info(f"[CHROMA] Base skin selected")
                    self.state.selected_chroma_id = None
                    
                    # Reset skin key to just the skin name (no chroma ID)
                    if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
                        # Get English skin name from database if available
                        english_skin_name = self.panel.current_skin_name
                        if self.db and self.current_skin_id:
                            try:
                                db_english_name = self.db.get_english_skin_name_by_id(self.current_skin_id)
                                if db_english_name:
                                    english_skin_name = db_english_name
                            except Exception:
                                pass
                        
                        # For base skins, use just the skin name (no chroma ID)
                        self.state.last_hovered_skin_key = english_skin_name
                        log.debug(f"[CHROMA] Reset last_hovered_skin_key to: {self.state.last_hovered_skin_key}")
                    
                    log.info(f"[CHROMA] Reset to base skin ID: {self.current_skin_id}")
                else:
                    # Chroma selected - update skin ID to chroma ID
                    log.info(f"[CHROMA] Chroma selected: {chroma_name} (ID: {chroma_id})")
                    self.state.selected_chroma_id = chroma_id
                    
                    # UPDATE: Change the hovered skin ID to the chroma ID
                    # This way injection will use the chroma ID
                    self.state.last_hovered_skin_id = chroma_id
                    
                    # Also update the skin key to include chroma ID for injection path
                    # Format: "{base_skin_name} {chroma_id}" for injection system
                    if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
                        # Get the base skin name (remove any existing chroma IDs from the name)
                        base_skin_name = self.panel.current_skin_name
                        
                        # Remove any trailing chroma IDs from the skin name to get the clean base name
                        # This prevents corruption like "Garen 86008 86009 86008"
                        words = base_skin_name.split()
                        # Keep only the champion name and base skin name, remove any chroma IDs
                        clean_words = []
                        for word in words:
                            # Skip words that look like chroma IDs (numbers)
                            if not word.isdigit():
                                clean_words.append(word)
                            else:
                                # Stop at the first number we encounter (base skin ID or chroma ID)
                                break
                        
                        base_skin_name = ' '.join(clean_words)
                        
                        # Get English skin name from database if available
                        english_skin_name = base_skin_name
                        if self.db and self.current_skin_id:
                            try:
                                db_english_name = self.db.get_english_skin_name_by_id(self.current_skin_id)
                                if db_english_name:
                                    english_skin_name = db_english_name
                            except Exception:
                                pass
                        
                        # For chromas, append the chroma ID to the clean base skin name
                        self.state.last_hovered_skin_key = f"{english_skin_name} {chroma_id}"
                        log.debug(f"[CHROMA] Updated last_hovered_skin_key to: {self.state.last_hovered_skin_key}")
                    
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
        Show button for a skin (called when UI detection finds any unowned skin or owned skin with chromas)
        
        The button displays:
        - Unowned skins with chromas: clickable chroma wheel + golden border + lock
        - Unowned skins without chromas: golden border + lock only (no wheel)
        - Owned skins with chromas: clickable chroma wheel (no golden border/lock)
        
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
            # Check if this is a chroma ID - if so, get the base skin ID for chroma data
            base_skin_id = skin_id
            if self.skin_scraper and self.skin_scraper.cache:
                if skin_id in self.skin_scraper.cache.chroma_id_map:
                    # This is a chroma, get its base skin ID
                    chroma_data = self.skin_scraper.cache.chroma_id_map[skin_id]
                    base_skin_id = chroma_data.get('skinId')
                    log.debug(f"[CHROMA] Detected chroma {skin_id}, using base skin {base_skin_id} for chroma data")
            
            chromas = self.skin_scraper.get_chromas_for_skin(base_skin_id)
            
            # Mark ownership status on each chroma for the injection system (if chromas exist)
            owned_skin_ids = self.state.owned_skin_ids
            owned_count = 0
            if chromas:
                for chroma in chromas:
                    chroma_id = chroma.get('id')
                    is_owned = chroma_id in owned_skin_ids
                    chroma['is_owned'] = is_owned  # Add ownership flag
                    if is_owned:
                        owned_count += 1
            
            # Show button regardless of whether chromas exist
            # The UnownedFrame (golden border + lock) will be shown for unowned skins
            if chromas and len(chromas) > 0:
                log.debug(f"[CHROMA] Updating button for {skin_name} ({len(chromas)} total chromas, {owned_count} owned, {len(chromas) - owned_count} unowned)")
            else:
                log.debug(f"[CHROMA] Showing button for {skin_name} (no chromas - UnownedFrame only)")
            
            # Check if this is a chroma selection for the same base skin
            is_chroma_selection = False
            if self.current_skin_id is not None and self.current_skin_id != skin_id:
                log.debug(f"[CHROMA] Checking chroma selection: current={self.current_skin_id} -> new={skin_id}")
                
                # Check if both IDs are chromas of the same base skin
                current_base_id = self.current_skin_id
                new_base_id = skin_id
                
                # If current is a chroma, get its base skin ID from the chroma cache
                if current_base_id in self.skin_scraper.cache.chroma_id_map:
                    chroma_data = self.skin_scraper.cache.chroma_id_map[current_base_id]
                    current_base_id = chroma_data.get('skinId', current_base_id)
                    log.debug(f"[CHROMA] Current skin {self.current_skin_id} is chroma of base skin {current_base_id}")
                
                # If new is a chroma, get its base skin ID from the chroma cache
                if new_base_id in self.skin_scraper.cache.chroma_id_map:
                    chroma_data = self.skin_scraper.cache.chroma_id_map[new_base_id]
                    new_base_id = chroma_data.get('skinId', new_base_id)
                    log.debug(f"[CHROMA] New skin {skin_id} is chroma of base skin {new_base_id}")
                
                # If both have the same base skin ID, it's a chroma selection
                is_chroma_selection = (current_base_id == new_base_id)
                log.debug(f"[CHROMA] Base skin comparison: {current_base_id} == {new_base_id} -> is_chroma_selection={is_chroma_selection}")
            
            self.current_skin_id = skin_id
            
            # Show the button with chromas (or empty list if no chromas)
            try:
                self.panel.show_button_for_skin(skin_id, skin_name, chromas or [], champion_name, is_chroma_selection)
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


def init_chroma_selector(skin_scraper, state, db=None):
    """Initialize global chroma selector"""
    global _chroma_selector
    _chroma_selector = ChromaSelector(skin_scraper, state, db)
    log.debug("[CHROMA] Chroma selector initialized")
    return _chroma_selector


def get_chroma_selector() -> Optional[ChromaSelector]:
    """Get global chroma selector instance"""
    return _chroma_selector
