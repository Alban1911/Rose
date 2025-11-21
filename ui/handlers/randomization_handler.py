#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Randomization Handler
Handles random skin selection logic
"""

import random
from typing import Optional, Tuple
from state.shared_state import SharedState
from utils.logging import get_logger
from utils.utilities import is_base_skin

log = get_logger()


class RandomizationHandler:
    """Handles random skin selection logic"""
    
    def __init__(self, state: SharedState, skin_scraper=None):
        """Initialize randomization handler
        
        Args:
            state: Shared application state
            skin_scraper: Skin scraper instance
        """
        self.state = state
        self.skin_scraper = skin_scraper
        self._randomization_in_progress = False
        self._randomization_started = False
    
    def handle_dice_click_disabled(self, current_skin_id: Optional[int]) -> bool:
        """Handle dice button click in disabled state - start randomization
        
        Returns:
            True if randomization was started, False otherwise
        """
        # Prevent multiple simultaneous randomization attempts
        if self._randomization_started:
            log.debug("[UI] Randomization already in progress, ignoring click")
            return False
        
        log.info("[UI] Starting random skin selection")
        self._randomization_started = True
        
        # Force champion's base skin first
        champion_id = self.skin_scraper.cache.champion_id if self.skin_scraper and self.skin_scraper.cache else None
        base_champion_skin_id = champion_id * 1000 if champion_id else None
        
        if current_skin_id == base_champion_skin_id:
            # Already champion's base skin, proceed with randomization
            self._start_randomization()
            return True
        else:
            # Need to force champion's base skin first
            return False  # Caller should call force_base_skin_and_randomize
    
    def handle_dice_click_enabled(self):
        """Handle dice button click in enabled state - cancel randomization"""
        log.info("[UI] Cancelling random skin selection")
        self.cancel()
    
    def force_base_skin_and_randomize(self, lcu) -> bool:
        """Force champion's base skin via LCU API then start randomization
        
        Returns:
            True if base skin was forced and randomization started, False otherwise
        """
        if not self.state.locked_champ_id:
            log.warning("[UI] Cannot force base skin - no locked champion")
            return False
        
        # Set flag to prevent cancellation during randomization
        self._randomization_in_progress = True
        
        # Get champion's base skin ID (champion_id * 1000)
        champion_id = self.state.locked_champ_id
        base_skin_id = champion_id * 1000
        log.info(f"[UI] Forcing champion base skin: {base_skin_id} (champion {champion_id})")
        
        # Force base skin via LCU
        try:
            if not lcu:
                log.warning("[UI] No LCU instance available")
                self._randomization_in_progress = False
                return False
            
            # Try to set base skin
            if lcu.set_my_selection_skin(base_skin_id):
                log.info(f"[UI] Forced champion base skin: {base_skin_id}")
                # Start randomization immediately
                self._start_randomization()
                return True
            else:
                log.warning("[UI] Failed to force champion base skin")
                self._randomization_in_progress = False
                self._randomization_started = False
                return False
        except Exception as e:
            log.error(f"[UI] Error forcing champion base skin: {e}")
            self._randomization_in_progress = False
            self._randomization_started = False
            return False
    
    def _start_randomization(self):
        """Start the randomization sequence"""
        # Check if randomization was cancelled
        if not self._randomization_started:
            log.debug("[UI] Randomization was cancelled, aborting start")
            self._randomization_in_progress = False
            return
        
        # Disable HistoricMode if active
        try:
            if getattr(self.state, 'historic_mode_active', False):
                self.state.historic_mode_active = False
                self.state.historic_skin_id = None
                log.info("[HISTORIC] Historic mode DISABLED due to RandomMode activation")
                # Broadcast state to JavaScript
                try:
                    if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                        self.state.ui_skin_thread._broadcast_historic_state()
                except Exception as e:
                    log.debug(f"[UI] Failed to broadcast historic state on RandomMode activation: {e}")
        except Exception:
            pass
        
        # Select random skin
        random_selection = self.select_random_skin()
        if random_selection:
            random_skin_name, random_skin_id = random_selection
            self.state.random_skin_name = random_skin_name
            self.state.random_skin_id = random_skin_id
            self.state.random_mode_active = True
            log.info(f"[UI] Random skin selected: {random_skin_name} (ID: {random_skin_id})")
            
            # Broadcast random mode state to JavaScript
            try:
                if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                    self.state.ui_skin_thread._broadcast_random_mode_state()
            except Exception as e:
                log.debug(f"[UI] Failed to broadcast random mode state: {e}")
        else:
            log.warning("[UI] No random skin available")
            self.cancel()
        
        # Clear the randomization flags AFTER everything is set up
        self._randomization_in_progress = False
        self._randomization_started = False
    
    def cancel(self):
        """Cancel randomization and reset state"""
        # Reset state
        self.state.random_skin_name = None
        self.state.random_skin_id = None
        self.state.random_mode_active = False
        
        # Broadcast random mode state to JavaScript
        try:
            if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                self.state.ui_skin_thread._broadcast_random_mode_state()
        except Exception as e:
            log.debug(f"[UI] Failed to broadcast random mode state on cancel: {e}")
        
        # Clear randomization flags
        self._randomization_in_progress = False
        self._randomization_started = False
    
    def select_random_skin(self) -> Optional[Tuple[str, int]]:
        """Select a random skin from available skins (excluding base skin)
        
        Returns:
            Tuple of (skin_name, skin_id) or None if no skin available
        """
        if not self.skin_scraper or not self.skin_scraper.cache.skins:
            log.warning("[UI] No skins available for random selection")
            return None
        
        # Filter out the champion's base skin and actual chromas
        champion_id = self.skin_scraper.cache.champion_id
        base_champion_skin_id = champion_id * 1000 if champion_id else None
        
        chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
        available_skins = [
            skin for skin in self.skin_scraper.cache.skins 
            if skin.get('skinId') != base_champion_skin_id and is_base_skin(skin.get('skinId'), chroma_id_map)
        ]
        
        # Debug logging
        log.debug(f"[UI] Champion ID: {champion_id}, Base skin ID: {base_champion_skin_id}")
        log.debug(f"[UI] Total skins in cache: {len(self.skin_scraper.cache.skins)}")
        log.debug(f"[UI] Available skins for random selection: {len(available_skins)}")
        for skin in available_skins[:5]:  # Show first 5 for debugging
            log.debug(f"[UI] Available skin: {skin.get('skinName')} (ID: {skin.get('skinId')})")
        
        if not available_skins:
            log.warning("[UI] No non-base skins available for random selection")
            return None
        
        # Select random skin
        selected_skin = random.choice(available_skins)
        skin_id = selected_skin.get('skinId')
        localized_skin_name = selected_skin.get('skinName', '')
        
        if not localized_skin_name or not skin_id:
            log.warning("[UI] Selected skin has no name or ID")
            return None
        
        # Use localized skin name directly from LCU
        english_skin_name = localized_skin_name
        
        # Check if this skin has chromas
        chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
        if chromas:
            log.info(f"[UI] Skin '{english_skin_name}' has {len(chromas)} chromas, selecting random chroma")
            
            # Create list of all options: base skin + all chromas
            all_options = []
            
            # Add base skin
            all_options.append({
                'id': skin_id,
                'name': english_skin_name,
                'type': 'base'
            })
            
            # Add all chromas
            for chroma in chromas:
                localized_chroma_name = chroma.get('name', f'{english_skin_name} Chroma')
                english_chroma_name = localized_chroma_name
                all_options.append({
                    'id': chroma.get('id'),
                    'name': english_chroma_name,
                    'type': 'chroma'
                })
            
            # Select random option from base + chromas
            selected_option = random.choice(all_options)
            selected_name = selected_option['name']
            selected_id = selected_option['id']
            selected_type = selected_option['type']
            
            log.info(f"[UI] Random selection: {selected_type} '{selected_name}' (ID: {selected_id})")
            return (selected_name, selected_id)
        else:
            # No chromas, return the base skin name and ID
            log.info(f"[UI] Skin '{english_skin_name}' has no chromas, using base skin")
            return (english_skin_name, skin_id)
    
    def update_dice_button(self, current_skin_id: Optional[int]):
        """Broadcast dice button state to JavaScript"""
        # Skip dice button in Swiftplay mode
        if self.state.is_swiftplay_mode:
            return
        
        # Broadcast random mode state to JavaScript
        if current_skin_id:
            try:
                if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                    self.state.ui_skin_thread._broadcast_random_mode_state()
            except Exception as e:
                log.debug(f"[UI] Failed to broadcast random mode state on dice button update: {e}")
    
    @property
    def randomization_in_progress(self) -> bool:
        """Check if randomization is in progress"""
        return self._randomization_in_progress
    
    @property
    def randomization_started(self) -> bool:
        """Check if randomization has started"""
        return self._randomization_started
    
    @randomization_started.setter
    def randomization_started(self, value: bool):
        """Set randomization started flag"""
        self._randomization_started = value
    
    def reset_on_skin_change(self):
        """Reset randomization flags when skin changes"""
        if self._randomization_started:
            log.debug("[UI] Resetting randomization flag due to skin change")
            self._randomization_started = False
            # Also reset in-progress flag if it was set
            if self._randomization_in_progress:
                log.debug("[UI] Cancelling randomization in progress due to skin change")
                self._randomization_in_progress = False
                # Cancel the state but don't call full cancel to avoid double broadcast
                if self.state.random_mode_active:
                    self.state.random_skin_name = None
                    self.state.random_skin_id = None
                    self.state.random_mode_active = False
                    try:
                        if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                            self.state.ui_skin_thread._broadcast_random_mode_state()
                    except Exception as e:
                        log.debug(f"[UI] Failed to broadcast random mode state on skin change: {e}")

