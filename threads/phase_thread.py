#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase monitoring thread
"""

import time
import threading
from lcu.client import LCU
from state.shared_state import SharedState
from utils.logging import get_logger
from utils.chroma_selector import get_chroma_selector
from constants import INTERESTING_PHASES, PHASE_POLL_INTERVAL_DEFAULT

log = get_logger()


class PhaseThread(threading.Thread):
    """Thread for monitoring game phase changes"""
    
    INTERESTING = INTERESTING_PHASES
    
    def __init__(self, lcu: LCU, state: SharedState, interval: float = PHASE_POLL_INTERVAL_DEFAULT, log_transitions: bool = True, injection_manager=None):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.state = state
        self.interval = interval
        self.log_transitions = log_transitions
        self.injection_manager = injection_manager
        self.last_phase = None

    def run(self):
        """Main thread loop"""
        while not self.state.stop:
            try: 
                self.lcu.refresh_if_needed()
            except Exception: 
                pass
            
            ph = self.lcu.phase() if self.lcu.ok else None
            if ph is not None and ph != self.last_phase:
                if self.log_transitions and ph in self.INTERESTING:
                    log.info(f"[phase] {ph}")
                self.state.phase = ph
                
                if ph == "Lobby":
                    # Cleanup operations when entering Lobby
                    if self.injection_manager:
                        # Kill any existing runoverlay processes from previous game
                        try:
                            self.injection_manager.kill_all_runoverlay_processes()
                            log.info("Phase: Killed all runoverlay processes for Lobby")
                        except Exception as e:
                            log.warning(f"Phase: Failed to kill runoverlay processes: {e}")
                    
                    # Destroy chroma wheel and button
                    chroma_selector = get_chroma_selector()
                    if chroma_selector:
                        try:
                            chroma_selector.wheel.request_destroy()
                            log.debug("[phase] Chroma wheel destroy requested for Lobby")
                        except Exception as e:
                            log.debug(f"[phase] Error destroying chroma wheel: {e}")
                
                elif ph == "ChampSelect":
                    log.info("[phase] Entering ChampSelect - resetting state for new game")
                    self.state.last_hovered_skin_key = None
                    self.state.last_hovered_skin_id = None
                    self.state.last_hovered_skin_slug = None
                    self.state.selected_skin_id = None  # Reset LCU selected skin
                    self.state.owned_skin_ids.clear()  # Clear owned skins (will be refreshed on champion lock)
                    try: 
                        self.state.processed_action_ids.clear()
                    except Exception: 
                        self.state.processed_action_ids = set()
                    self.state.last_hover_written = False
                    self.state.injection_completed = False  # Reset injection flag for new game
                    self.state.loadout_countdown_active = False  # Reset countdown state
                    log.debug("[phase] State reset complete - ready for new champion select")
                    
                    # Force immediate check for locked champion when entering ChampSelect
                    # This helps OCR restart immediately if champion is already locked
                    self.state.locked_champ_id = None  # Reset first
                        
                    
                elif ph == "InProgress":
                    # Game starting - destroy chroma wheel and button
                    chroma_selector = get_chroma_selector()
                    if chroma_selector:
                        try:
                            chroma_selector.wheel.request_destroy()
                            log.debug("[phase] Chroma wheel destroy requested for InProgress")
                        except Exception as e:
                            log.debug(f"[phase] Error destroying chroma wheel: {e}")
                
                elif ph == "EndOfGame":
                    # Game ended → stop overlay process
                    if self.injection_manager:
                        try:
                            self.injection_manager.stop_overlay_process()
                            log.info("Phase: Stopped overlay process for EndOfGame")
                        except Exception as e:
                            log.warning(f"Phase: Failed to stop overlay process: {e}")
                    
                else:
                    # Exit champ select → reset counter/timer
                    self.state.hovered_champ_id = None
                    self.state.locked_champ_id = None  # Reset locked champion
                    self.state.players_visible = 0
                    self.state.locks_by_cell.clear()
                    self.state.all_locked_announced = False
                    self.state.loadout_countdown_active = False
                    self.state.last_hover_written = False
                
                self.last_phase = ph
            time.sleep(self.interval)
