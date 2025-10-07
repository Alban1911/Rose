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
                
                if ph == "ChampSelect":
                    self.state.last_hovered_skin_key = None
                    self.state.last_hovered_skin_id = None
                    self.state.last_hovered_skin_slug = None
                    try: 
                        self.state.processed_action_ids.clear()
                    except Exception: 
                        self.state.processed_action_ids = set()
                    self.state.last_hover_written = False
                    self.state.injection_completed = False  # Reset injection flag for new game
                    
                    # Force immediate check for locked champion when entering ChampSelect
                    # This helps OCR restart immediately if champion is already locked
                    self.state.locked_champ_id = None  # Reset first
                    
                    # Kill any existing runoverlay processes when entering ChampSelect
                    if self.injection_manager:
                        try:
                            self.injection_manager.kill_all_runoverlay_processes()
                            log.info("Phase: Killed all runoverlay processes for ChampSelect")
                        except Exception as e:
                            log.warning(f"Phase: Failed to kill runoverlay processes: {e}")
                        
                        # Cancel any ongoing prebuild when entering ChampSelect
                        try:
                            if self.injection_manager._initialized and self.injection_manager.prebuilder and self.injection_manager.current_champion:
                                log.info(f"Phase: Cancelling prebuild for {self.injection_manager.current_champion} (entering ChampSelect)")
                                self.injection_manager.prebuilder.cancel_current_build()
                                # Reset injection manager's champion tracking
                                self.injection_manager.current_champion = None
                        except Exception as e:
                            log.warning(f"Phase: Failed to cancel prebuild: {e}")
                        
                    
                elif ph == "InProgress":
                    # Game starting → log last skin
                    if self.state.last_hovered_skin_key:
                        log.info(f"[launch:last-skin] {self.state.last_hovered_skin_key} (skinId={self.state.last_hovered_skin_id}, champ={self.state.last_hovered_skin_slug})")
                    else:
                        log.info("[launch:last-skin] (no hovered skin detected)")
                
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
