#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase Handler
Handles phase-specific logic and UI management
"""

import logging
from lcu import LCU
from state import SharedState
from ui.chroma.selector import get_chroma_selector
from utils.core.logging import get_logger, log_action

log = get_logger()


class PhaseHandler:
    """Handles phase-specific logic"""
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        injection_manager=None,
        skin_scraper=None,
        swiftplay_handler=None,
    ):
        """Initialize phase handler
        
        Args:
            lcu: LCU client instance
            state: Shared application state
            injection_manager: Injection manager instance
            skin_scraper: Skin scraper instance
            swiftplay_handler: Swiftplay handler instance
        """
        self.lcu = lcu
        self.state = state
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
        self.swiftplay_handler = swiftplay_handler
    
    def handle_phase_change(self, phase: str, previous_phase: str):
        """Handle phase change"""
        if phase == "Matchmaking":
            if self.state.is_swiftplay_mode:
                log.info("[phase] Matchmaking phase detected in Swiftplay mode - triggering injection")
                if self.swiftplay_handler:
                    self.swiftplay_handler.monitor_swiftplay_matchmaking()
                    if not self.swiftplay_handler._injection_triggered:
                        self.swiftplay_handler.trigger_swiftplay_injection()
                        self.swiftplay_handler._injection_triggered = True
        
        elif phase == "ChampSelect":
            log.debug(f"[phase] ChampSelect detected - is_swiftplay_mode={self.state.is_swiftplay_mode}, extracted_mods={len(self.state.swiftplay_extracted_mods)}")
            if self.state.is_swiftplay_mode and self.state.swiftplay_extracted_mods:
                log.info("[phase] ChampSelect in Swiftplay mode - running overlay injection")
                # Also ensure UI is initialized for Swiftplay mode (needed for overlay detection)
                try:
                    from ui.core.user_interface import get_user_interface
                    user_interface = get_user_interface(self.state, self.skin_scraper)
                    if not user_interface.is_ui_initialized() and not user_interface._pending_ui_initialization:
                        log.info("[phase] ChampSelect in Swiftplay mode - requesting UI initialization for overlay detection")
                        user_interface.request_ui_initialization()
                except Exception as e:
                    log.warning(f"[phase] Failed to request UI initialization in Swiftplay ChampSelect: {e}")
                if self.swiftplay_handler:
                    self.swiftplay_handler.run_swiftplay_overlay()
            else:
                # Normal ChampSelect handling
                self.state.locked_champ_id = None
                self.state.locked_champ_timestamp = 0.0
                self.state.champion_exchange_triggered = False
                self.state.own_champion_locked = False
                
                # Backup UI initialization
                try:
                    from ui.core.user_interface import get_user_interface
                    user_interface = get_user_interface(self.state, self.skin_scraper)
                    if not user_interface.is_ui_initialized() and not user_interface._pending_ui_initialization:
                        log.info("[phase] ChampSelect detected - requesting UI initialization (backup)")
                        user_interface.request_ui_initialization()
                except Exception as e:
                    log.warning(f"[phase] Failed to request UI initialization in ChampSelect: {e}")
        
        elif phase == "GameStart":
            log_action(log, "GameStart detected - UI will be destroyed after injection", "🚀")
        
        elif phase == "InProgress":
            self._handle_in_progress()
        
        elif phase == "EndOfGame":
            self._handle_end_of_game()
        
        elif phase == "ReadyCheck":
            if not self.state.is_swiftplay_mode:
                self._request_ui_destruction()
        
        else:
            # Exit champ select or other phases
            if not self.state.is_swiftplay_mode and phase is not None:
                self._request_ui_destruction()
                self._reset_state()
        
        # Handle lobby exit
        # Don't cleanup Swiftplay if we're transitioning to Matchmaking/ChampSelect (need extracted mods)
        if previous_phase == "Lobby" and phase != "Lobby":
            if self.state.is_swiftplay_mode and self.swiftplay_handler:
                # Only cleanup if we're not going to Matchmaking/ChampSelect (where we need extracted mods)
                if phase not in ["Matchmaking", "ChampSelect", "FINALIZATION"]:
                    self.swiftplay_handler.cleanup_swiftplay_exit()
    
    def _handle_in_progress(self):
        """Handle InProgress phase"""
        try:
            from ui.core.user_interface import get_user_interface
            user_interface = get_user_interface(self.state, self.skin_scraper)
            user_interface.request_ui_destruction()
            log_action(log, "UI destruction requested for InProgress", "")
        except Exception as e:
            log.warning(f"[phase] Failed to request UI destruction for InProgress: {e}")
        
        # Destroy chroma panel
        chroma_selector = get_chroma_selector()
        if chroma_selector:
            try:
                chroma_selector.panel.request_destroy()
                log.debug("[phase] Chroma panel destroy requested for InProgress")
            except Exception as e:
                log.debug(f"[phase] Error destroying chroma panel: {e}")
    
    def _handle_end_of_game(self):
        """Handle EndOfGame phase"""
        try:
            from ui.core.user_interface import get_user_interface
            user_interface = get_user_interface(self.state, self.skin_scraper)
            user_interface.request_ui_destruction()
            log_action(log, "UI destruction requested for EndOfGame", "")
        except Exception as e:
            log.warning(f"[phase] Failed to request UI destruction for EndOfGame: {e}")
        
        if self.injection_manager:
            try:
                self.injection_manager.stop_overlay_process()
                log_action(log, "Stopped overlay process for EndOfGame", "🛑")
            except Exception as e:
                log.warning(f"[phase] Failed to stop overlay process: {e}")
    
    def _request_ui_destruction(self):
        """Request UI destruction"""
        try:
            from ui.core.user_interface import get_user_interface
            user_interface = get_user_interface(self.state, self.skin_scraper)
            user_interface.request_ui_destruction()
            log_action(log, "UI destruction requested", "")
        except Exception as e:
            log.warning(f"[phase] Failed to request UI destruction: {e}")
    
    def _reset_state(self):
        """Reset state for phase exit"""
        self.state.hovered_champ_id = None
        self.state.locked_champ_id = None
        self.state.locked_champ_timestamp = 0.0
        self.state.players_visible = 0
        self.state.locks_by_cell.clear()
        self.state.all_locked_announced = False
        self.state.loadout_countdown_active = False
        self.state.last_hover_written = False
        self.state.is_swiftplay_mode = False

