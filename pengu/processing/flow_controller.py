#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flow Controller
Controls when skin detection should be active based on game phase/state
"""

import logging

log = logging.getLogger(__name__)


class FlowController:
    """Controls flow of skin detection processing"""
    
    def __init__(self, shared_state):
        """Initialize flow controller
        
        Args:
            shared_state: Shared application state
        """
        self.shared_state = shared_state
        self._injection_disconnect_active = False
        self._last_phase = None
    
    def should_process_payload(self) -> bool:
        """Determine if payload should be processed
        
        Returns:
            True if payload should be processed, False otherwise
        """
        current_phase = getattr(self.shared_state, "phase", None)
        if current_phase != self._last_phase:
            if current_phase == "ChampSelect":
                self._injection_disconnect_active = False
            self._last_phase = current_phase
        
        if self._injection_disconnect_active:
            if current_phase in {"ChampSelect", "FINALIZATION"} or getattr(
                self.shared_state, "own_champion_locked", False
            ):
                log.debug(
                    "[SkinMonitor] Resuming after injection disconnect (phase=%s)",
                    current_phase,
                )
                self._injection_disconnect_active = False
            else:
                return False
        
        if getattr(self.shared_state, "phase", None) == "Lobby" and getattr(
            self.shared_state, "is_swiftplay_mode", False
        ):
            return True
        
        if getattr(self.shared_state, "own_champion_locked", False):
            return True
        
        if getattr(self.shared_state, "phase", None) == "FINALIZATION":
            return True
        
        return False
    
    def force_disconnect(self) -> None:
        """Mimic legacy UIA behaviour when injection is about to occur"""
        self._injection_disconnect_active = True

