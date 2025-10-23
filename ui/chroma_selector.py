#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma Selection Integration - New Workflow
Shows chroma wheel immediately when skin is detected (not during injection)
"""

# Standard library imports
import threading
from typing import TYPE_CHECKING, Optional

# Local imports
from ui.chroma_panel import get_chroma_panel
from utils.logging import get_logger
from utils.utilities import is_default_skin, is_owned
from utils.validation import validate_skin_id, validate_skin_name

if TYPE_CHECKING:
    from state.shared_state import SharedState

log = get_logger()


class ChromaSelector:
    """
    Manages chroma selection with new workflow:
    - Show wheel immediately when UI detection finds skin with chromas
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
        self.panel = get_chroma_panel(state=state, lcu=skin_scraper.lcu)
        self.panel.on_chroma_selected = self._on_chroma_selected
        
        # Preview manager no longer needs database - uses LCU data only
    
    
    def _get_elementalist_forms(self):
        """Get Elementalist Lux Forms data structure (equivalent to chromas)"""
        forms = [
            {'id': 99991, 'name': 'Air', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Air.zip'},
            {'id': 99992, 'name': 'Dark', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Dark.zip'},
            {'id': 99993, 'name': 'Ice', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Ice.zip'},
            {'id': 99994, 'name': 'Magma', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Magma.zip'},
            {'id': 99995, 'name': 'Mystic', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Mystic.zip'},
            {'id': 99996, 'name': 'Nature', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Nature.zip'},
            {'id': 99997, 'name': 'Storm', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Storm.zip'},
            {'id': 99998, 'name': 'Water', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Water.zip'},
            {'id': 99999, 'name': 'Fire', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Elementalist Lux Fire.zip'},
        ]
        log.debug(f"[CHROMA] Created {len(forms)} Elementalist Lux Forms with fake IDs (99991-99999)")
        return forms
    
    def _get_hol_chromas(self):
        """Get Risen Legend Kai'Sa HOL chroma data structure (equivalent to chromas)"""
        chromas = [
            {'id': 145071, 'name': 'Immortalized Legend', 'colors': [], 'is_owned': False},
        ]
        log.debug(f"[CHROMA] Created {len(chromas)} Risen Legend Kai'Sa HOL chromas with real skin ID (145071)")
        return chromas
    
    def _get_ahri_hol_chromas(self):
        """Get Risen Legend Ahri HOL chroma data structure (equivalent to chromas)"""
        chromas = [
            {'id': 103086, 'name': 'Immortalized Legend', 'colors': [], 'is_owned': False},
        ]
        log.debug(f"[CHROMA] Created {len(chromas)} Risen Legend Ahri HOL chromas with real skin ID (103086)")
        return chromas
    
    def _on_chroma_selected(self, chroma_id, chroma_name: str):
        """Callback when user clicks a chroma - update state immediately"""
        try:
            with self.lock:
                # Check if this is an Elementalist Lux Form (fake ID 99991-99999)
                if isinstance(chroma_id, int) and 99991 <= chroma_id <= 99999:
                    # This is a Form selection
                    log.info(f"[CHROMA] Form selected: {chroma_name} (Fake ID: {chroma_id})")
                    
                    # Find the Form data to get the form_path
                    form_data = None
                    if self.current_skin_id == 99007:  # Elementalist Lux
                        forms = self._get_elementalist_forms()
                        for form in forms:
                            if form['id'] == chroma_id:
                                form_data = form
                                break
                    
                    if form_data:
                        # Store the Form file path for injection
                        self.state.selected_form_path = form_data['form_path']
                        self.state.selected_chroma_id = chroma_id  # Store the fake ID
                        
                        # Update the skin ID to the fake ID so injection system treats it as unowned
                        self.state.last_hovered_skin_id = chroma_id
                        
                        # Update the skin name to include the Form name for injection
                        if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
                            base_skin_name = self.panel.current_skin_name
                            # Create the Form skin name: "Elementalist Lux {Form Name}"
                            form_skin_name = f"{base_skin_name} {chroma_name}"
                            self.state.last_hovered_skin_key = form_skin_name
                            log.debug(f"[CHROMA] Form skin name: {form_skin_name}")
                            log.debug(f"[CHROMA] Form path: {form_data['form_path']}")
                            log.debug(f"[CHROMA] Using fake ID {chroma_id} for injection (not owned)")
                
                # Check if this is a Risen Legend Kai'Sa HOL chroma (real ID 145071)
                elif chroma_id == 145071:
                    # This is a HOL chroma selection
                    log.info(f"[CHROMA] HOL chroma selected: {chroma_name} (Real ID: {chroma_id})")
                    
                    # Store the HOL skin ID for injection
                    self.state.selected_chroma_id = chroma_id
                    self.state.last_hovered_skin_id = 145071  # Immortalized Legend Kai'Sa skin ID
                    
                    # Update the skin name to include the HOL chroma name for injection
                    if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
                        base_skin_name = self.panel.current_skin_name
                        # Create the HOL skin name: "Risen Legend Kai'Sa Immortalized Legend"
                        hol_skin_name = f"{base_skin_name} {chroma_name}"
                        self.state.last_hovered_skin_key = hol_skin_name
                        log.debug(f"[CHROMA] HOL skin name: {hol_skin_name}")
                        log.debug(f"[CHROMA] HOL skin ID: 145071")
                        log.debug(f"[CHROMA] Using real ID {chroma_id} for injection (not owned)")
                
                # Check if this is a Risen Legend Ahri HOL chroma (real ID 103086)
                elif chroma_id == 103086:
                    # This is a HOL chroma selection
                    log.info(f"[CHROMA] Ahri HOL chroma selected: {chroma_name} (Real ID: {chroma_id})")
                    
                    # Store the HOL skin ID for injection
                    self.state.selected_chroma_id = chroma_id
                    self.state.last_hovered_skin_id = 103086  # Immortalized Legend Ahri skin ID
                    
                    # Update the skin name to include the HOL chroma name for injection
                    if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
                        base_skin_name = self.panel.current_skin_name
                        # Create the HOL skin name: "Risen Legend Ahri Immortalized Legend"
                        hol_skin_name = f"{base_skin_name} {chroma_name}"
                        self.state.last_hovered_skin_key = hol_skin_name
                        log.debug(f"[CHROMA] Ahri HOL skin name: {hol_skin_name}")
                        log.debug(f"[CHROMA] Ahri HOL skin ID: 103086")
                        log.debug(f"[CHROMA] Using real ID {chroma_id} for injection (not owned)")
                    
                elif chroma_id == 0 or chroma_id is None:
                    # Base skin selected - reset to original skin ID and skin name
                    log.info(f"[CHROMA] Base skin selected")
                    self.state.selected_chroma_id = None
                    
                    # Reset skin key to just the skin name (no chroma ID)
                    if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
                        # Get English skin name from LCU skin scraper cache
                        english_skin_name = self.panel.current_skin_name
                        if self.skin_scraper and self.skin_scraper.cache.is_loaded_for_champion(self.state.locked_champ_id):
                            skin_data = self.skin_scraper.cache.get_skin_by_id(self.current_skin_id)
                            if skin_data:
                                english_skin_name = skin_data.get('skinName', '')
                        
                        # For base skins, use just the skin name (no chroma ID)
                        self.state.last_hovered_skin_key = english_skin_name
                        log.debug(f"[CHROMA] Reset last_hovered_skin_key to: {self.state.last_hovered_skin_key}")
                    
                    log.info(f"[CHROMA] Reset to base skin ID: {self.current_skin_id}")
                else:
                    # Regular chroma selected - update skin ID to chroma ID
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
                                # Check if this looks like a skin/chroma ID vs year
                                if len(word) >= 5:
                                    # This looks like a skin ID (5+ digits) or chroma ID (6+ digits), stop here
                                    break
                                else:
                                    # This might be a year (4 digits) or other short number, keep it
                                    clean_words.append(word)
                        
                        base_skin_name = ' '.join(clean_words)
                        
                        # Get English skin name from LCU skin scraper cache
                        english_skin_name = base_skin_name
                        if self.skin_scraper and self.skin_scraper.cache.is_loaded_for_champion(self.state.locked_champ_id):
                            skin_data = self.skin_scraper.cache.get_skin_by_id(self.current_skin_id)
                            if skin_data:
                                english_skin_name = skin_data.get('skinName', '')
                        
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
    
    def show_button_for_skin(self, skin_id: int, skin_name: str, champion_name: str = None, champion_id: int = None):
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
            
            # Special handling for Elementalist Lux forms (fake IDs 99991-99999)
            if 99991 <= skin_id <= 99999:
                base_skin_id = 99007  # Elementalist Lux base skin ID
                log.debug(f"[CHROMA] Detected Elementalist Lux form {skin_id}, using base skin {base_skin_id} for chroma data")
            elif self.skin_scraper and self.skin_scraper.cache:
                if skin_id in self.skin_scraper.cache.chroma_id_map:
                    # This is a chroma, get its base skin ID
                    chroma_data = self.skin_scraper.cache.chroma_id_map[skin_id]
                    base_skin_id = chroma_data.get('skinId')
                    log.debug(f"[CHROMA] Detected chroma {skin_id}, using base skin {base_skin_id} for chroma data")
            
            # Special case: Elementalist Lux (skin ID 99007) has Forms instead of chromas
            if base_skin_id == 99007:
                chromas = self._get_elementalist_forms()
                log.debug(f"[CHROMA] Using Elementalist Lux Forms instead of chromas")
            # Special case: Risen Legend Kai'Sa (skin ID 145070) has HOL chroma instead of regular chromas
            elif base_skin_id == 145070:
                chromas = self._get_hol_chromas()
                log.debug(f"[CHROMA] Using Risen Legend Kai'Sa HOL chroma instead of regular chromas")
            # Special case: Immortalized Legend Kai'Sa (skin ID 145071) is treated as a chroma of Risen Legend
            elif base_skin_id == 145071:
                chromas = self._get_hol_chromas()
                log.debug(f"[CHROMA] Using Risen Legend Kai'Sa HOL chroma for Immortalized Legend (treated as chroma)")
            # Special case: Risen Legend Ahri (skin ID 103085) has HOL chroma instead of regular chromas
            elif base_skin_id == 103085:
                chromas = self._get_ahri_hol_chromas()
                log.debug(f"[CHROMA] Using Risen Legend Ahri HOL chroma instead of regular chromas")
            # Special case: Immortalized Legend Ahri (skin ID 103086) is treated as a chroma of Risen Legend Ahri
            elif base_skin_id == 103086:
                chromas = self._get_ahri_hol_chromas()
                log.debug(f"[CHROMA] Using Risen Legend Ahri HOL chroma for Immortalized Legend Ahri (treated as chroma)")
            else:
                chromas = self.skin_scraper.get_chromas_for_skin(base_skin_id)
            
            # Mark ownership status on each chroma for the injection system (if chromas exist)
            owned_count = 0
            if chromas:
                for chroma in chromas:
                    chroma_id = chroma.get('id')
                    is_owned_var = is_owned(chroma_id, self.state.owned_skin_ids)
                    chroma['is_owned'] = is_owned_var  # Add ownership flag
                    if is_owned_var:
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
                
                # Special handling for Elementalist Lux forms (fake IDs 99991-99999)
                if 99991 <= current_base_id <= 99999:
                    current_base_id = 99007  # Elementalist Lux base skin ID
                    log.debug(f"[CHROMA] Current skin {self.current_skin_id} is Elementalist Lux form of base skin {current_base_id}")
                elif current_base_id == 99007:
                    current_base_id = 99007  # Elementalist Lux base skin ID
                    log.debug(f"[CHROMA] Current skin {self.current_skin_id} is Elementalist Lux base skin")
                elif current_base_id in self.skin_scraper.cache.chroma_id_map:
                    chroma_data = self.skin_scraper.cache.chroma_id_map[current_base_id]
                    current_base_id = chroma_data.get('skinId', current_base_id)
                    log.debug(f"[CHROMA] Current skin {self.current_skin_id} is chroma of base skin {current_base_id}")
                
                # Special handling for Elementalist Lux forms (fake IDs 99991-99999)
                if 99991 <= new_base_id <= 99999:
                    new_base_id = 99007  # Elementalist Lux base skin ID
                    log.debug(f"[CHROMA] New skin {skin_id} is Elementalist Lux form of base skin {new_base_id}")
                elif new_base_id == 99007:
                    new_base_id = 99007  # Elementalist Lux base skin ID
                    log.debug(f"[CHROMA] New skin {skin_id} is Elementalist Lux base skin")
                elif new_base_id in self.skin_scraper.cache.chroma_id_map:
                    chroma_data = self.skin_scraper.cache.chroma_id_map[new_base_id]
                    new_base_id = chroma_data.get('skinId', new_base_id)
                    log.debug(f"[CHROMA] New skin {skin_id} is chroma of base skin {new_base_id}")
                
                # If both have the same base skin ID, it's a chroma selection
                is_chroma_selection = (current_base_id == new_base_id)
                log.debug(f"[CHROMA] Base skin comparison: {current_base_id} == {new_base_id} -> is_chroma_selection={is_chroma_selection}")
            
            self.current_skin_id = skin_id
            
            # Show the button with chromas (or empty list if no chromas)
            try:
                self.panel.show_button_for_skin(skin_id, skin_name, chromas or [], champion_name, is_chroma_selection, champion_id)
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
