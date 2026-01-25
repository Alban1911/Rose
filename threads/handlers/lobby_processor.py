#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lobby Processor
Processes lobby state and detects Swiftplay mode
"""

import logging
import time
from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger, log_action

log = get_logger()

SWIFTPLAY_MODES = {"SWIFTPLAY", "BRAWL"}


class LobbyProcessor:
    """Processes lobby state and detects Swiftplay mode"""
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        injection_manager=None,
        skin_scraper=None,
        swiftplay_handler=None,
    ):
        """Initialize lobby processor
        
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
        
        # Lobby mode monitoring (poll at 5 Hz)
        self._lobby_mode_check_interval = 0.2
        self._last_lobby_check = 0.0
        self._last_lobby_mode = None
        self._last_lobby_queue = None
        self._last_logged_mode = None
        self._last_logged_queue = None
    
    def process_lobby_state(self, force: bool = False):
        """Monitor lobby state and detect Swiftplay mode changes."""
        now = time.time()
        if not force and (now - self._last_lobby_check) < self._lobby_mode_check_interval:
            return

        self._last_lobby_check = now

        detected_mode = None
        detected_queue = None

        try:
            if self.lcu.ok and self.swiftplay_handler:
                detected_mode, detected_queue = self.swiftplay_handler.detect_swiftplay_in_lobby()
        except Exception as e:
            log.debug(f"[phase] Error detecting game mode in lobby: {e}")

        if detected_mode:
            self.state.current_game_mode = detected_mode
        if detected_queue is not None:
            self.state.current_queue_id = detected_queue

        is_swiftplay = False
        if detected_mode and isinstance(detected_mode, str) and detected_mode.upper() in SWIFTPLAY_MODES:
            is_swiftplay = True
        elif detected_mode is None and self.lcu.ok and self.lcu.is_swiftplay:
            is_swiftplay = True
            fallback_mode = self.lcu.game_mode
            if fallback_mode and isinstance(fallback_mode, str) and fallback_mode.upper() in SWIFTPLAY_MODES:
                detected_mode = fallback_mode

        previous_mode = self._last_lobby_mode
        previous_queue = self._last_lobby_queue
        swiftplay_previous = self.state.is_swiftplay_mode

        mode_changed = detected_mode is not None and detected_mode != previous_mode
        queue_changed = detected_queue is not None and detected_queue != previous_queue
        swiftplay_changed = is_swiftplay != swiftplay_previous

        effective_mode = detected_mode if detected_mode is not None else (
            self.lcu.game_mode if (is_swiftplay and self.lcu.ok and self.lcu.game_mode) else previous_mode
        )

        if mode_changed or queue_changed or swiftplay_changed:
            prev_mode_label = previous_mode or "UNKNOWN"
            new_mode_label = effective_mode or prev_mode_label
            prev_queue_label = previous_queue if previous_queue is not None else "-"
            new_queue_label = detected_queue if detected_queue is not None else prev_queue_label
            log.info(f"[phase] Lobby game mode updated: {prev_mode_label} → {new_mode_label} (queue: {prev_queue_label} → {new_queue_label})")

        if is_swiftplay:
            if swiftplay_changed or force or mode_changed or queue_changed:
                if not swiftplay_previous:
                    mode_label = (effective_mode or "Swiftplay").upper()
                    log_action(log, f"{mode_label} lobby detected - triggering early skin detection", "⚡")
                if self.swiftplay_handler:
                    self.swiftplay_handler.handle_swiftplay_lobby()
            else:
                # Already in Swiftplay mode, continue monitoring
                if self.swiftplay_handler:
                    self.swiftplay_handler.monitor_swiftplay_matchmaking()
                    self.swiftplay_handler.poll_swiftplay_champion_selection()
        else:
            if swiftplay_previous and (swiftplay_changed or force or mode_changed or queue_changed):
                if self.swiftplay_handler:
                    self.swiftplay_handler.cleanup_swiftplay_exit()

            if swiftplay_changed or force or mode_changed or queue_changed:
                if self.injection_manager:
                    try:
                        self.injection_manager.kill_all_runoverlay_processes()
                        log_action(log, "Killed all runoverlay processes for Lobby", "")
                    except Exception as e:
                        log.warning(f"[phase] Failed to kill runoverlay processes: {e}")

                try:
                    from ui.core.user_interface import get_user_interface
                    user_interface = get_user_interface(self.state, self.skin_scraper)
                    user_interface.request_ui_destruction()
                    log_action(log, "UI destruction requested for Lobby", "")
                except Exception as e:
                    log.warning(f"[phase] Failed to request UI destruction for Lobby: {e}")

            self.state.is_swiftplay_mode = False

        if effective_mode is not None:
            self._last_lobby_mode = effective_mode
        if detected_queue is not None:
            self._last_lobby_queue = detected_queue
        if effective_mode is not None:
            self._last_logged_mode = effective_mode
        if detected_queue is not None:
            self._last_logged_queue = detected_queue
    
    def reset_lobby_tracking(self):
        """Reset lobby tracking when leaving the lobby phase"""
        self._last_lobby_mode = None
        self._last_lobby_queue = None
        self._last_lobby_check = 0.0

