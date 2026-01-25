#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase monitoring thread
"""

import threading
import time

from config import INTERESTING_PHASES, PHASE_POLL_INTERVAL_DEFAULT
from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger, log_status

from ..handlers.swiftplay_handler import SwiftplayHandler
from ..handlers.phase_handler import PhaseHandler
from ..handlers.lobby_processor import LobbyProcessor

log = get_logger()


class PhaseThread(threading.Thread):
    """Thread for monitoring game phase changes"""
    
    INTERESTING = INTERESTING_PHASES
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        interval: float = PHASE_POLL_INTERVAL_DEFAULT,
        log_transitions: bool = True,
        injection_manager=None,
        skin_scraper=None,
        db=None,
    ):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.state = state
        self.interval = interval
        self.log_transitions = log_transitions
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
        self.db = db
        self.last_phase = None
        
        # Initialize handlers
        self.swiftplay_handler = SwiftplayHandler(lcu, state, injection_manager, skin_scraper)
        self.phase_handler = PhaseHandler(lcu, state, injection_manager, skin_scraper, self.swiftplay_handler)
        self.lobby_processor = LobbyProcessor(lcu, state, injection_manager, skin_scraper, self.swiftplay_handler)

    def run(self):
        """Main thread loop"""
        while not self.state.stop:
            try:
                self.lcu.refresh_if_needed()
            except (OSError, ConnectionError) as e:
                log.debug(f"LCU refresh failed in phase thread: {e}")
            
            ph = self.lcu.phase if self.lcu.ok else None
            if ph == "None":
                ph = None
            
            # If phase is unknown (None), skip handling
            if ph is None:
                self.state.phase = None
                # Don't cleanup Swiftplay if we have extracted mods waiting for injection
                # This can happen during phase transitions (e.g., Matchmaking -> ChampSelect)
                has_extracted_mods = self.state.swiftplay_extracted_mods and len(self.state.swiftplay_extracted_mods) > 0
                if self.state.is_swiftplay_mode and not has_extracted_mods:
                    self.swiftplay_handler.cleanup_swiftplay_exit()
                elif not self.state.is_swiftplay_mode and self.state.swiftplay_extracted_mods:
                    self.state.swiftplay_extracted_mods = []

                time.sleep(self.interval)
                continue

            phase_changed = (ph != self.last_phase)

            if ph == "Lobby":
                self.lobby_processor.process_lobby_state(force=phase_changed)
                # Broadcast phase change to JavaScript plugins
                if phase_changed:
                    try:
                        ui_thread = getattr(self.state, "ui_skin_thread", None)
                        if ui_thread:
                            ui_thread._broadcast_phase_change("Lobby")
                    except Exception as e:
                        log.debug(f"[phase] Failed to broadcast phase change to JavaScript: {e}")

            if phase_changed:
                # Broadcast phase change to JavaScript plugins
                if ph in ["ChampSelect", "FINALIZATION", "Lobby"]:
                    try:
                        ui_thread = getattr(self.state, "ui_skin_thread", None)
                        if ui_thread:
                            ui_thread._broadcast_phase_change(ph)
                    except Exception as e:
                        log.debug(f"[phase] Failed to broadcast phase change to JavaScript: {e}")
                
                # Log phase transition
                if ph is not None and self.log_transitions and ph in self.INTERESTING:
                    log_status(log, "Phase", ph, "")
                
                # Update phase
                if ph is not None:
                    self.state.phase = ph
                
                # Handle phase change
                self.phase_handler.handle_phase_change(ph, self.last_phase)
                
                # Reset lobby tracking when leaving lobby
                if self.last_phase == "Lobby" and ph != "Lobby":
                    self.lobby_processor.reset_lobby_tracking()

                self.last_phase = ph
            elif ph == "Lobby":
                # Phase unchanged but still in lobby – continue monitoring
                self.lobby_processor.process_lobby_state(force=False)
            
            time.sleep(self.interval)
