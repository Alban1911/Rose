#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase monitoring thread
"""

import time
import threading
from lcu.client import LCU
from state.shared_state import SharedState
from utils.logging import get_logger, log_status, log_action
from ui.user_interface import get_user_interface
from ui.chroma_selector import get_chroma_selector
from config import INTERESTING_PHASES, PHASE_POLL_INTERVAL_DEFAULT

log = get_logger()


class PhaseThread(threading.Thread):
    """Thread for monitoring game phase changes"""
    
    INTERESTING = INTERESTING_PHASES
    
    def __init__(self, lcu: LCU, state: SharedState, interval: float = PHASE_POLL_INTERVAL_DEFAULT, log_transitions: bool = True, injection_manager=None, skin_scraper=None, db=None):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.state = state
        self.interval = interval
        self.log_transitions = log_transitions
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
        self.db = db
        self.last_phase = None

    def run(self):
        """Main thread loop"""
        while not self.state.stop:
            try: 
                self.lcu.refresh_if_needed()
            except (OSError, ConnectionError) as e:
                log.debug(f"LCU refresh failed in phase thread: {e}")
            
            ph = self.lcu.phase if self.lcu.ok else None
            if ph is not None and ph != self.last_phase:
                if self.log_transitions and ph in self.INTERESTING:
                    log_status(log, "Phase", ph, "🎯")
                self.state.phase = ph
                
                if ph == "Lobby":
                    # Cleanup operations when entering Lobby
                    if self.injection_manager:
                        # Kill any existing runoverlay processes from previous game
                        try:
                            self.injection_manager.kill_all_runoverlay_processes()
                            log_action(log, "Killed all runoverlay processes for Lobby", "🧹")
                        except Exception as e:
                            log.warning(f"[phase] Failed to kill runoverlay processes: {e}")
                    
                    # Request UI destruction for Lobby
                    try:
                        from ui.user_interface import get_user_interface
                        user_interface = get_user_interface(self.state, self.skin_scraper, self.db)
                        user_interface.request_ui_destruction()
                        log_action(log, "UI destruction requested for Lobby", "🏠")
                    except Exception as e:
                        log.warning(f"[phase] Failed to request UI destruction for Lobby: {e}")
                
                elif ph == "ChampSelect":
                    # State reset happens in WebSocket thread for faster response
                    # Force immediate check for locked champion when entering ChampSelect
                    # This helps UI detection restart immediately if champion is already locked
                    self.state.locked_champ_id = None  # Reset first
                    self.state.locked_champ_timestamp = 0.0  # Reset lock timestamp
                        
                    
                elif ph == "GameStart":
                    # Game starting - request UI destruction
                    try:
                        from ui.user_interface import get_user_interface
                        user_interface = get_user_interface(self.state, self.skin_scraper, self.db)
                        user_interface.request_ui_destruction()
                        log_action(log, "UI destruction requested for GameStart", "🚀")
                    except Exception as e:
                        log.warning(f"[phase] Failed to request UI destruction for GameStart: {e}")
                
                elif ph == "InProgress":
                    # Game starting - request UI destruction
                    try:
                        from ui.user_interface import get_user_interface
                        user_interface = get_user_interface(self.state, self.skin_scraper, self.db)
                        user_interface.request_ui_destruction()
                        log_action(log, "UI destruction requested for InProgress", "🎮")
                    except Exception as e:
                        log.warning(f"[phase] Failed to request UI destruction for InProgress: {e}")
                    
                    # Also destroy chroma panel and button for backward compatibility
                    chroma_selector = get_chroma_selector()
                    if chroma_selector:
                        try:
                            chroma_selector.panel.request_destroy()
                            log.debug("[phase] Chroma panel destroy requested for InProgress")
                        except Exception as e:
                            log.debug(f"[phase] Error destroying chroma panel: {e}")
                
                elif ph == "EndOfGame":
                    # Game ended → request UI destruction and stop overlay process
                    try:
                        from ui.user_interface import get_user_interface
                        user_interface = get_user_interface(self.state, self.skin_scraper, self.db)
                        user_interface.request_ui_destruction()
                        log_action(log, "UI destruction requested for EndOfGame", "🏁")
                    except Exception as e:
                        log.warning(f"[phase] Failed to request UI destruction for EndOfGame: {e}")
                    
                    if self.injection_manager:
                        try:
                            self.injection_manager.stop_overlay_process()
                            log_action(log, "Stopped overlay process for EndOfGame", "🛑")
                        except Exception as e:
                            log.warning(f"[phase] Failed to stop overlay process: {e}")
                    
                else:
                    # Exit champ select or other phases → request UI destruction and reset counter/timer
                    try:
                        from ui.user_interface import get_user_interface
                        user_interface = get_user_interface(self.state, self.skin_scraper, self.db)
                        user_interface.request_ui_destruction()
                        log_action(log, f"UI destruction requested for {ph}", "🔄")
                    except Exception as e:
                        log.warning(f"[phase] Failed to request UI destruction for {ph}: {e}")
                    
                    self.state.hovered_champ_id = None
                    self.state.locked_champ_id = None  # Reset locked champion
                    self.state.locked_champ_timestamp = 0.0  # Reset lock timestamp
                    self.state.players_visible = 0
                    self.state.locks_by_cell.clear()
                    self.state.all_locked_announced = False
                    self.state.loadout_countdown_active = False
                    self.state.last_hover_written = False
                
                self.last_phase = ph
            time.sleep(self.interval)
