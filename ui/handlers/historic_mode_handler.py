#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Historic Mode Handler
Handles historic mode activation and deactivation
"""

from typing import Optional
from state import SharedState
from utils.core.logging import get_logger

log = get_logger()


class HistoricModeHandler:
    """Handles historic mode activation and deactivation"""
    
    def __init__(self, state: SharedState):
        """Initialize historic mode handler
        
        Args:
            state: Shared application state
        """
        self.state = state
    
    def check_and_activate(self, skin_id: int) -> None:
        """Check and activate historic mode if conditions are met"""
        if self.state.historic_first_detection_done or self.state.locked_champ_id is None:
            return
        
        # Check if current skin is the default skin (champion_id * 1000)
        base_skin_id = self.state.locked_champ_id * 1000
        if skin_id == base_skin_id:
            # Check if there's a historic entry for this champion
            try:
                from utils.core.historic import get_historic_skin_for_champion, is_custom_mod_path
                historic_value = get_historic_skin_for_champion(self.state.locked_champ_id)
                
                if historic_value is not None:
                    # Activate historic mode
                    self.state.historic_mode_active = True
                    self.state.historic_skin_id = historic_value
                    
                    if is_custom_mod_path(historic_value):
                        log.info(f"[HISTORIC] Historic mode ACTIVATED for champion {self.state.locked_champ_id} (custom mod path: {historic_value})")
                    else:
                        log.info(f"[HISTORIC] Historic mode ACTIVATED for champion {self.state.locked_champ_id} (historic skin ID: {historic_value})")
                    
                    # Broadcast state to JavaScript
                    try:
                        if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                            self.state.ui_skin_thread._broadcast_historic_state()
                            log.debug("[HISTORIC] Broadcasted state to JavaScript")
                    except Exception as e:
                        log.debug(f"[UI] Failed to broadcast historic state on activation: {e}")
                else:
                    log.debug(f"[HISTORIC] No historic entry found for champion {self.state.locked_champ_id}")
            except Exception as e:
                log.debug(f"[HISTORIC] Failed to check historic entry: {e}")
        else:
            log.debug(f"[HISTORIC] First detected skin is not default (skin_id={skin_id}, base={base_skin_id}) - historic mode not activated")
        
        # Mark first detection as done AFTER processing
        self.state.historic_first_detection_done = True
    
    def check_and_deactivate(self, skin_id: int, new_base_skin_id: Optional[int]) -> None:
        """Check and deactivate historic mode if skin changed from default"""
        if not self.state.historic_mode_active or self.state.locked_champ_id is None:
            return
        
        base_skin_id = self.state.locked_champ_id * 1000
        # Check if current skin is not the default skin (and not a chroma of the default skin)
        if new_base_skin_id != base_skin_id:
            # Skin changed to a different base skin - deactivate historic mode
            self.state.historic_mode_active = False
            self.state.historic_skin_id = None
            log.info(f"[HISTORIC] Historic mode DEACTIVATED - skin changed from default to {skin_id} (base: {new_base_skin_id})")
            
            # Broadcast state to JavaScript
            try:
                if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                    self.state.ui_skin_thread._broadcast_historic_state()
            except Exception as e:
                log.debug(f"[UI] Failed to broadcast historic state on deactivation: {e}")

