#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma Selection Handler
Handles chroma selection callbacks and state updates
"""

from typing import Optional
from state import SharedState
from utils.core.logging import get_logger
from ui.chroma.special_cases import ChromaSpecialCases

log = get_logger()


class ChromaSelectionHandler:
    """Handles chroma selection callbacks and state updates"""
    
    def __init__(self, state: SharedState, skin_scraper=None, panel=None, current_skin_id: Optional[int] = None):
        """Initialize chroma selection handler
        
        Args:
            state: Shared application state
            skin_scraper: Skin scraper instance
            panel: Chroma panel instance
            current_skin_id: Current skin ID being shown
        """
        self.state = state
        self.skin_scraper = skin_scraper
        self.panel = panel
        self.current_skin_id = current_skin_id
    
    def handle_selection(self, chroma_id: int, chroma_name: str):
        """Handle chroma selection callback
        
        Args:
            chroma_id: Selected chroma ID (0 or None for base skin)
            chroma_name: Selected chroma name
        """
        try:
            # Check if this is an Elementalist Lux Form
            if ChromaSpecialCases.is_elementalist_form(chroma_id):
                self._handle_elementalist_form_selection(chroma_id, chroma_name)
            # Check if this is a Sahn Uzal Mordekaiser Form
            elif ChromaSpecialCases.is_mordekaiser_form(chroma_id):
                self._handle_mordekaiser_form_selection(chroma_id, chroma_name)
            # Check if this is a Spirit Blossom Morgana Form
            elif ChromaSpecialCases.is_morgana_form(chroma_id):
                self._handle_morgana_form_selection(chroma_id, chroma_name)
            # Check if this is a Radiant Sett Form
            elif ChromaSpecialCases.is_sett_form(chroma_id):
                self._handle_sett_form_selection(chroma_id, chroma_name)
            # Check if this is a KDA Seraphine Form
            elif ChromaSpecialCases.is_seraphine_form(chroma_id):
                self._handle_seraphine_form_selection(chroma_id, chroma_name)
            # Check if this is a HOL chroma
            elif ChromaSpecialCases.is_hol_chroma(chroma_id):
                self._handle_hol_chroma_selection(chroma_id, chroma_name)
            # Base skin selected
            elif chroma_id == 0 or chroma_id is None:
                self._handle_base_skin_selection()
            # Regular chroma selected
            else:
                self._handle_regular_chroma_selection(chroma_id, chroma_name)
            
            # Safety check: Disable HistoricMode if active and chroma/skin is selected
            self._safety_check_historic_mode()
            
            self.state.pending_chroma_selection = False
        except Exception as e:
            log.error(f"[CHROMA] Error in selection callback: {e}")
            import traceback
            log.error(traceback.format_exc())
    
    def _handle_elementalist_form_selection(self, chroma_id: int, chroma_name: str):
        """Handle Elementalist Lux form selection"""
        log.info(f"[CHROMA] Form selected: {chroma_name} (Fake ID: {chroma_id})")
        
        # Find the Form data to get the form_path
        form_data = None
        if self.current_skin_id == 99007:  # Elementalist Lux
            forms = ChromaSpecialCases.get_elementalist_forms()
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
            
            # Update Swiftplay tracking dictionary if in Swiftplay mode
            if self.state.is_swiftplay_mode:
                champion_id = 99  # Lux champion ID
                self.state.swiftplay_skin_tracking[champion_id] = chroma_id
                log.info(f"[CHROMA] Updated Swiftplay tracking: champion {champion_id} -> Elementalist form {chroma_id}")
            
            # Disable HistoricMode if active
            self._disable_historic_mode(f"Elementalist Lux form selection (formId={chroma_id})")
            
            # Update the skin name to include the Form name for injection
            if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
                base_skin_name = self.panel.current_skin_name
                form_skin_name = f"{base_skin_name} {chroma_name}"
                self.state.last_hovered_skin_key = form_skin_name
                log.debug(f"[CHROMA] Form skin name: {form_skin_name}")
                log.debug(f"[CHROMA] Form path: {form_data['form_path']}")
                log.debug(f"[CHROMA] Using fake ID {chroma_id} for injection (not owned)")
    
    def _handle_mordekaiser_form_selection(self, chroma_id: int, chroma_name: str):
        """Handle Sahn Uzal Mordekaiser form selection"""
        log.info(f"[CHROMA] Form selected: {chroma_name} (Fake ID: {chroma_id})")
        
        # Find the Form data to get the form_path
        form_data = None
        if self.current_skin_id == 82054:  # Sahn Uzal Mordekaiser
            forms = ChromaSpecialCases.get_mordekaiser_forms()
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
            
            # Update Swiftplay tracking dictionary if in Swiftplay mode
            if self.state.is_swiftplay_mode:
                champion_id = 82  # Mordekaiser champion ID
                self.state.swiftplay_skin_tracking[champion_id] = chroma_id
                log.info(f"[CHROMA] Updated Swiftplay tracking: champion {champion_id} -> Mordekaiser form {chroma_id}")
            
            # Disable HistoricMode if active
            self._disable_historic_mode(f"Sahn Uzal Mordekaiser form selection (formId={chroma_id})")
            
            # Update the skin name to include the Form name for injection
            if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
                base_skin_name = self.panel.current_skin_name
                form_skin_name = f"{base_skin_name} {chroma_name}"
                self.state.last_hovered_skin_key = form_skin_name
                log.debug(f"[CHROMA] Form skin name: {form_skin_name}")
                log.debug(f"[CHROMA] Form path: {form_data['form_path']}")
                log.debug(f"[CHROMA] Using fake ID {chroma_id} for injection (not owned)")
    
    def _handle_morgana_form_selection(self, chroma_id: int, chroma_name: str):
        """Handle Spirit Blossom Morgana form selection"""
        log.info(f"[CHROMA] Form selected: {chroma_name} (Fake ID: {chroma_id})")
        
        # Find the Form data to get the form_path
        form_data = None
        if self.current_skin_id == 25080:  # Spirit Blossom Morgana
            forms = ChromaSpecialCases.get_morgana_forms()
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
            
            # Update Swiftplay tracking dictionary if in Swiftplay mode
            if self.state.is_swiftplay_mode:
                champion_id = 25  # Morgana champion ID
                self.state.swiftplay_skin_tracking[champion_id] = chroma_id
                log.info(f"[CHROMA] Updated Swiftplay tracking: champion {champion_id} -> Morgana form {chroma_id}")
            
            # Disable HistoricMode if active
            self._disable_historic_mode(f"Spirit Blossom Morgana form selection (formId={chroma_id})")
            
            # Update the skin name to include the Form name for injection
            if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
                base_skin_name = self.panel.current_skin_name
                form_skin_name = f"{base_skin_name} {chroma_name}"
                self.state.last_hovered_skin_key = form_skin_name
                log.debug(f"[CHROMA] Form skin name: {form_skin_name}")
                log.debug(f"[CHROMA] Form path: {form_data['form_path']}")
                log.debug(f"[CHROMA] Using fake ID {chroma_id} for injection (not owned)")
    
    def _handle_sett_form_selection(self, chroma_id: int, chroma_name: str):
        """Handle Radiant Sett form selection"""
        log.info(f"[CHROMA] Form selected: {chroma_name} (Real ID: {chroma_id})")
        
        # Find the Form data to get the form_path
        form_data = None
        if self.current_skin_id == 875066:  # Radiant Sett
            forms = ChromaSpecialCases.get_sett_forms()
            for form in forms:
                if form['id'] == chroma_id:
                    form_data = form
                    break
        
        if form_data:
            # Store the Form file path for injection
            self.state.selected_form_path = form_data['form_path']
            self.state.selected_chroma_id = chroma_id  # Store the real ID
            
            # Update the skin ID to the form ID so injection system treats it as unowned
            self.state.last_hovered_skin_id = chroma_id
            
            # Update Swiftplay tracking dictionary if in Swiftplay mode
            if self.state.is_swiftplay_mode:
                champion_id = 875  # Sett champion ID
                self.state.swiftplay_skin_tracking[champion_id] = chroma_id
                log.info(f"[CHROMA] Updated Swiftplay tracking: champion {champion_id} -> Sett form {chroma_id}")
            
            # Disable HistoricMode if active
            self._disable_historic_mode(f"Radiant Sett form selection (formId={chroma_id})")
            
            # Update the skin name to include the Form name for injection
            if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
                base_skin_name = self.panel.current_skin_name
                form_skin_name = f"{base_skin_name} {chroma_name}"
                self.state.last_hovered_skin_key = form_skin_name
                log.debug(f"[CHROMA] Form skin name: {form_skin_name}")
                log.debug(f"[CHROMA] Form path: {form_data['form_path']}")
                log.debug(f"[CHROMA] Using real ID {chroma_id} for injection (not owned)")
    
    def _handle_seraphine_form_selection(self, chroma_id: int, chroma_name: str):
        """Handle KDA Seraphine form selection"""
        log.info(f"[CHROMA] Form selected: {chroma_name} (Real ID: {chroma_id})")
        
        # Find the Form data to get the form_path
        form_data = None
        if self.current_skin_id == 147001:  # KDA Seraphine
            forms = ChromaSpecialCases.get_seraphine_forms()
            for form in forms:
                if form['id'] == chroma_id:
                    form_data = form
                    break
        
        if form_data:
            # Store the Form file path for injection
            self.state.selected_form_path = form_data['form_path']
            self.state.selected_chroma_id = chroma_id  # Store the real ID
            
            # Update the skin ID to the form ID so injection system treats it as unowned
            self.state.last_hovered_skin_id = chroma_id
            
            # Update Swiftplay tracking dictionary if in Swiftplay mode
            if self.state.is_swiftplay_mode:
                champion_id = 147  # Seraphine champion ID
                self.state.swiftplay_skin_tracking[champion_id] = chroma_id
                log.info(f"[CHROMA] Updated Swiftplay tracking: champion {champion_id} -> Seraphine form {chroma_id}")
            
            # Disable HistoricMode if active
            self._disable_historic_mode(f"KDA Seraphine form selection (formId={chroma_id})")
            
            # Update the skin name to include the Form name for injection
            if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
                base_skin_name = self.panel.current_skin_name
                form_skin_name = f"{base_skin_name} {chroma_name}"
                self.state.last_hovered_skin_key = form_skin_name
                log.debug(f"[CHROMA] Form skin name: {form_skin_name}")
                log.debug(f"[CHROMA] Form path: {form_data['form_path']}")
                log.debug(f"[CHROMA] Using real ID {chroma_id} for injection (not owned)")
    
    def _handle_hol_chroma_selection(self, chroma_id: int, chroma_name: str):
        """Handle HOL chroma selection (Kai'Sa or Ahri)"""
        if chroma_id == 145071:
            log.info(f"[CHROMA] HOL chroma selected: {chroma_name} (Real ID: {chroma_id})")
            target_skin_id = 145071  # Immortalized Legend Kai'Sa skin ID
        elif chroma_id == 103086:
            log.info(f"[CHROMA] Ahri HOL chroma selected: {chroma_name} (Real ID: {chroma_id})")
            target_skin_id = 103086  # Immortalized Legend Ahri skin ID
        elif chroma_id == 103087:
            log.info(f"[CHROMA] Ahri Form 2 selected: {chroma_name} (Real ID: {chroma_id})")
            target_skin_id = 103087  # Form 2 Ahri skin ID
        else:
            return
        
        # Store the HOL skin ID for injection
        self.state.selected_chroma_id = chroma_id
        self.state.last_hovered_skin_id = target_skin_id
        
        # Update Swiftplay tracking dictionary if in Swiftplay mode
        if self.state.is_swiftplay_mode:
            from utils.core.utilities import get_champion_id_from_skin_id
            champion_id = get_champion_id_from_skin_id(target_skin_id)
            self.state.swiftplay_skin_tracking[champion_id] = chroma_id
            log.info(f"[CHROMA] Updated Swiftplay tracking: champion {champion_id} -> HOL chroma {chroma_id}")
        
        # Disable HistoricMode if active
        self._disable_historic_mode(f"HOL chroma selection (chromaId={chroma_id})")
        
        # Update the skin name to include the HOL chroma name for injection
        if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
            base_skin_name = self.panel.current_skin_name
            hol_skin_name = f"{base_skin_name} {chroma_name}"
            self.state.last_hovered_skin_key = hol_skin_name
            log.debug(f"[CHROMA] HOL skin name: {hol_skin_name}")
            log.debug(f"[CHROMA] HOL skin ID: {target_skin_id}")
            log.debug(f"[CHROMA] Using real ID {chroma_id} for injection (not owned)")
    
    def _handle_base_skin_selection(self):
        """Handle base skin selection"""
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
        
        # Update Swiftplay tracking dictionary if in Swiftplay mode
        if self.state.is_swiftplay_mode and self.current_skin_id:
            from utils.core.utilities import get_champion_id_from_skin_id
            champion_id = get_champion_id_from_skin_id(self.current_skin_id)
            self.state.swiftplay_skin_tracking[champion_id] = self.current_skin_id
            log.info(f"[CHROMA] Updated Swiftplay tracking: champion {champion_id} -> base skin {self.current_skin_id}")
        
        log.info(f"[CHROMA] Reset to base skin ID: {self.current_skin_id}")
    
    def _handle_regular_chroma_selection(self, chroma_id: int, chroma_name: str):
        """Handle regular chroma selection"""
        log.info(f"[CHROMA] Chroma selected: {chroma_name} (ID: {chroma_id})")
        self.state.selected_chroma_id = chroma_id
        
        # Update the hovered skin ID to the chroma ID
        self.state.last_hovered_skin_id = chroma_id
        
        # Update Swiftplay tracking dictionary if in Swiftplay mode
        if self.state.is_swiftplay_mode:
            from utils.core.utilities import get_champion_id_from_skin_id
            champion_id = get_champion_id_from_skin_id(chroma_id)
            self.state.swiftplay_skin_tracking[champion_id] = chroma_id
            log.info(f"[CHROMA] Updated Swiftplay tracking: champion {champion_id} -> skin {chroma_id}")
        
        # Disable HistoricMode if active
        self._disable_historic_mode(f"chroma selection (chromaId={chroma_id})")
        
        # Update the skin key to include chroma ID for injection path
        if hasattr(self.panel, 'current_skin_name') and self.panel.current_skin_name:
            # Get the base skin name (remove any existing chroma IDs from the name)
            base_skin_name = self.panel.current_skin_name
            
            # Remove any trailing chroma IDs from the skin name to get the clean base name
            words = base_skin_name.split()
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
    
    def _disable_historic_mode(self, reason: str):
        """Disable HistoricMode if active"""
        if self.state.historic_mode_active:
            self.state.historic_mode_active = False
            self.state.historic_skin_id = None
            log.info(f"[HISTORIC] Historic mode DISABLED due to {reason}")
            
            # Broadcast deactivated state to JavaScript
            try:
                if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                    self.state.ui_skin_thread._broadcast_historic_state()
            except Exception as e:
                log.debug(f"[CHROMA] Failed to broadcast historic state: {e}")
    
    def _safety_check_historic_mode(self):
        """Safety check: Disable HistoricMode if active and chroma/skin is selected (not base skin)"""
        try:
            if self.state.historic_mode_active and self.state.locked_champ_id is not None and self.state.last_hovered_skin_id is not None:
                base_skin_id = self.state.locked_champ_id * 1000
                # Check if the selected skin/chroma is not the base skin
                selected_skin_id = self.state.last_hovered_skin_id
                if selected_skin_id != base_skin_id:
                    self.state.historic_mode_active = False
                    self.state.historic_skin_id = None
                    log.info(f"[HISTORIC] Historic mode DISABLED due to chroma selection (selectedId={selected_skin_id} vs baseId={base_skin_id})")
                    
                    # Broadcast deactivated state to JavaScript
                    try:
                        if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                            self.state.ui_skin_thread._broadcast_historic_state()
                    except Exception as e:
                        log.debug(f"[CHROMA] Failed to broadcast historic state in safety check: {e}")
        except Exception as e:
            log.debug(f"[CHROMA] Error disabling historic mode: {e}")

