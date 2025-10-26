#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase monitoring thread
"""

# Standard library imports
import threading
import time

# Local imports
from config import INTERESTING_PHASES, PHASE_POLL_INTERVAL_DEFAULT
from lcu.client import LCU
from state.shared_state import SharedState
from ui.chroma_selector import get_chroma_selector
from utils.logging import get_logger, log_status, log_action

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
        
        # Swiftplay injection tracking
        self._injection_triggered = False
        self._last_matchmaking_state = None

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
                    # Force game mode detection in lobby phase
                    log.debug("[phase] Lobby phase detected - checking game mode...")
                    
                    # Try to detect game mode directly
                    game_mode = None
                    try:
                        if self.lcu.ok:
                            # Check multiple endpoints for Swiftplay detection
                            game_mode = self._detect_swiftplay_in_lobby()
                    except Exception as e:
                        log.debug(f"[phase] Error detecting game mode in lobby: {e}")
                    
                    # Check if this is Swiftplay mode
                    is_swiftplay = (game_mode == "SWIFTPLAY") or (self.lcu.is_swiftplay if self.lcu.ok else False)
                    log.debug(f"[phase] Swiftplay mode check: {is_swiftplay} (game_mode: {game_mode})")
                    
                    if is_swiftplay:
                        if not self.state.is_swiftplay_mode:
                            log_action(log, "Swiftplay lobby detected - triggering early skin detection", "⚡")
                            # For Swiftplay, trigger skin detection and UI immediately in lobby
                            self._handle_swiftplay_lobby()
                        else:
                            # Already in Swiftplay mode, continue monitoring
                            # Monitor matchmaking state for injection triggering
                            self._monitor_swiftplay_matchmaking()
                    else:
                        # Cleanup operations when entering regular Lobby
                        # Clear Swiftplay skin tracking if we're leaving Swiftplay mode
                        if self.state.is_swiftplay_mode:
                            log.info("[phase] Clearing Swiftplay skin tracking - leaving Swiftplay mode")
                            self.state.swiftplay_skin_tracking.clear()
                        
                        if self.injection_manager:
                            # Kill any existing runoverlay processes from previous game
                            try:
                                self.injection_manager.kill_all_runoverlay_processes()
                                log_action(log, "Killed all runoverlay processes for Lobby", "🧹")
                            except Exception as e:
                                log.warning(f"[phase] Failed to kill runoverlay processes: {e}")
                        
                        # Request UI destruction for regular Lobby
                        try:
                            from ui.user_interface import get_user_interface
                            user_interface = get_user_interface(self.state, self.skin_scraper)
                            user_interface.request_ui_destruction()
                            log_action(log, "UI destruction requested for Lobby", "🏠")
                        except Exception as e:
                            log.warning(f"[phase] Failed to request UI destruction for Lobby: {e}")
                
                elif ph == "Matchmaking":
                    # Matchmaking phase - for Swiftplay, trigger injection
                    if self.state.is_swiftplay_mode:
                        log.info("[phase] Matchmaking phase detected in Swiftplay mode - triggering injection")
                        self._monitor_swiftplay_matchmaking()
                        # Also trigger immediately in case we missed the state change
                        if not self._injection_triggered:
                            self._trigger_swiftplay_injection()
                            self._injection_triggered = True
                
                elif ph == "ChampSelect":
                    # For Swiftplay mode, run overlay injection on ChampSelect instead of GameStart
                    if self.state.is_swiftplay_mode and self.state.swiftplay_extracted_mods:
                        log.info("[phase] ChampSelect in Swiftplay mode - running overlay injection")
                        self._run_swiftplay_overlay()
                    else:
                        # Normal ChampSelect handling - state reset happens in WebSocket thread for faster response
                        # Force immediate check for locked champion when entering ChampSelect
                        # This helps UI detection restart immediately if champion is already locked
                        self.state.locked_champ_id = None  # Reset first
                        self.state.locked_champ_timestamp = 0.0  # Reset lock timestamp
                    
                elif ph == "GameStart":
                    # Don't destroy UI yet, let injection complete first
                    # UI will be destroyed when injection completes or when InProgress phase is reached
                    log_action(log, "GameStart detected - UI will be destroyed after injection", "🚀")
                
                elif ph == "InProgress":
                    # Game in progress - request UI destruction
                    try:
                        from ui.user_interface import get_user_interface
                        user_interface = get_user_interface(self.state, self.skin_scraper)
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
                        user_interface = get_user_interface(self.state, self.skin_scraper)
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
                        user_interface = get_user_interface(self.state, self.skin_scraper)
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
                    self.state.is_swiftplay_mode = False  # Reset Swiftplay flag
                
                self.last_phase = ph
            time.sleep(self.interval)
    
    def _handle_swiftplay_lobby(self):
        """Handle Swiftplay lobby - trigger early skin detection and UI"""
        try:
            # Detect game mode first
            self.lcu.refresh_if_needed()
            if not self.lcu.ok:
                log.warning("[phase] LCU not connected - cannot handle Swiftplay lobby")
                return
            
            # Get game session to detect game mode
            session = self.lcu.get("/lol-gameflow/v1/session")
            if not session:
                log.warning("[phase] No game session data available for Swiftplay")
                return
            
            # Extract game mode and map ID
            game_mode = None
            map_id = None
            if "gameData" in session:
                game_data = session.get("gameData", {})
                if "queue" in game_data:
                    queue = game_data.get("queue", {})
                    game_mode = queue.get("gameMode")
                    map_id = queue.get("mapId")
            
            # Store in shared state
            self.state.current_game_mode = game_mode
            self.state.current_map_id = map_id
            self.state.is_swiftplay_mode = True
            
            log.info(f"[phase] Swiftplay lobby - Game mode: {game_mode}, Map ID: {map_id}")
            
            # For Swiftplay, we need to check for champion selection in lobby
            # This might use different API endpoints than regular champ select
            self._check_swiftplay_champion_selection()
            
            # Clean up any existing ClickCatchers for Swiftplay mode
            self._cleanup_click_catchers_for_swiftplay()
            
            # Initialize UI for Swiftplay mode (no ClickCatchers, but UI components needed)
            try:
                from ui.user_interface import get_user_interface
                user_interface = get_user_interface(self.state, self.skin_scraper)
                if not user_interface.is_ui_initialized():
                    log.info("[phase] Initializing UI components for Swiftplay mode")
                    user_interface._pending_ui_initialization = True
            except Exception as e:
                log.warning(f"[phase] Failed to initialize UI for Swiftplay: {e}")
            
            # Start continuous monitoring for Swiftplay lobby changes
            self._start_swiftplay_monitoring()
            
            # Start matchmaking monitoring for injection triggering
            self._start_swiftplay_matchmaking_monitoring()
            
        except Exception as e:
            log.warning(f"[phase] Error handling Swiftplay lobby: {e}")
    
    def _check_swiftplay_champion_selection(self):
        """Check for champion selection in Swiftplay lobby using different API endpoints"""
        try:
            # Use the new Swiftplay-specific methods
            champion_selection = self.lcu.get_swiftplay_champion_selection()
            if champion_selection:
                log.info(f"[phase] Swiftplay champion selection found: {champion_selection}")
                self._process_swiftplay_champion_selection(champion_selection)
            else:
                log.debug("[phase] No champion selection found in Swiftplay lobby yet")
                    
        except Exception as e:
            log.warning(f"[phase] Error checking Swiftplay champion selection: {e}")
    
    def _process_swiftplay_champion_selection(self, champion_selection: dict):
        """Process champion selection data from Swiftplay lobby"""
        try:
            champion_id = champion_selection.get("championId")
            skin_id = champion_selection.get("skinId")
            
            if champion_id:
                log.info(f"[phase] Swiftplay champion selected: {champion_id}")
                self.state.locked_champ_id = champion_id
                self.state.locked_champ_timestamp = time.time()
                
                # Trigger skin scraping for the selected champion
                if self.skin_scraper:
                    self.skin_scraper.scrape_champion_skins(champion_id)
                
                # If skin is also selected, update the state
                if skin_id:
                    log.info(f"[phase] Swiftplay skin selected: {skin_id}")
                    self.state.selected_skin_id = skin_id
                    
        except Exception as e:
            log.warning(f"[phase] Error processing Swiftplay champion selection: {e}")
    
    def _process_swiftplay_data(self, endpoint: str, data):
        """Process data from Swiftplay API endpoints to find champion selection"""
        try:
            # This is where we'll need to implement the logic to extract
            # champion selection from Swiftplay lobby data
            # The exact structure will depend on what the API returns
            
            if endpoint == "/lol-lobby/v2/lobby":
                # Process lobby data for champion selection
                if isinstance(data, dict):
                    # Look for champion selection in lobby data
                    # This might be in a different structure than champ select
                    pass
                    
            elif endpoint == "/lol-lobby/v2/lobby/matchmaking/search-state":
                # Process matchmaking search state
                if isinstance(data, dict):
                    pass
                    
        except Exception as e:
            log.debug(f"[phase] Error processing Swiftplay data from {endpoint}: {e}")
    
    def _start_swiftplay_monitoring(self):
        """Start continuous monitoring for Swiftplay lobby changes"""
        try:
            # This method could be expanded to set up a timer or background task
            # to continuously check for changes in Swiftplay lobby
            log.debug("[phase] Swiftplay monitoring started - will check for changes periodically")
            
            # For now, we'll rely on the main loop to check periodically
            # In the future, this could be a separate thread or timer
            
        except Exception as e:
            log.warning(f"[phase] Error starting Swiftplay monitoring: {e}")
    
    def _cleanup_click_catchers_for_swiftplay(self):
        """Clean up existing ClickCatchers when entering Swiftplay mode"""
        try:
            log.info("[phase] Cleaning up ClickCatchers for Swiftplay mode...")
            
            # Use global cleanup function
            from ui.click_catcher import cleanup_all_click_catchers
            cleanup_all_click_catchers()
            
            # Also clean up user interface ClickCatchers
            from ui.user_interface import get_user_interface
            user_interface = get_user_interface(self.state, self.skin_scraper)
            
            if user_interface and hasattr(user_interface, 'click_catchers'):
                # Clear the ClickCatchers dictionary
                user_interface.click_catchers.clear()
                user_interface.click_catcher_hide = None
                
                log.info("[phase] User interface ClickCatchers cleared for Swiftplay mode")
            else:
                log.debug("[phase] No user interface ClickCatchers to clean up for Swiftplay mode")
                
        except Exception as e:
            log.warning(f"[phase] Error cleaning up ClickCatchers for Swiftplay: {e}")
    
    def test_swiftplay_detection(self):
        """Test method to verify Swiftplay detection is working"""
        try:
            if not self.lcu.ok:
                log.warning("[phase] LCU not connected - cannot test Swiftplay detection")
                return False
            
            # Test game mode detection
            game_mode = self.lcu.game_mode
            is_swiftplay = self.lcu.is_swiftplay
            
            log.info(f"[phase] Swiftplay test - Game mode: {game_mode}, Is Swiftplay: {is_swiftplay}")
            
            # Test Swiftplay lobby data retrieval
            lobby_data = self.lcu.get_swiftplay_lobby_data()
            if lobby_data:
                log.info(f"[phase] Swiftplay test - Lobby data retrieved: {type(lobby_data)}")
                log.info(f"[phase] Swiftplay test - Lobby data keys: {list(lobby_data.keys()) if isinstance(lobby_data, dict) else 'Not a dict'}")
            else:
                log.info("[phase] Swiftplay test - No lobby data available")
            
            # Test champion selection
            champion_selection = self.lcu.get_swiftplay_champion_selection()
            if champion_selection:
                log.info(f"[phase] Swiftplay test - Champion selection: {champion_selection}")
            else:
                log.info("[phase] Swiftplay test - No champion selection found")
            
            return True
            
        except Exception as e:
            log.warning(f"[phase] Error testing Swiftplay detection: {e}")
            return False
    
    
    def _start_swiftplay_matchmaking_monitoring(self):
        """Start monitoring matchmaking state for injection triggering"""
        try:
            log.info("[phase] Starting Swiftplay matchmaking monitoring...")
            # Initialize tracking variables
            self._last_matchmaking_state = None
            self._injection_triggered = False
            
        except Exception as e:
            log.warning(f"[phase] Error starting Swiftplay matchmaking monitoring: {e}")
    
    def _monitor_swiftplay_matchmaking(self):
        """Monitor matchmaking state and trigger injection when matchmaking starts"""
        try:
            if not self.lcu.ok or not self.injection_manager:
                return
            
            # Get current matchmaking state
            matchmaking_data = self.lcu.get("/lol-lobby/v2/lobby/matchmaking/search-state")
            if not matchmaking_data or not isinstance(matchmaking_data, dict):
                return
            
            current_state = matchmaking_data.get("searchState")
            if current_state != self._last_matchmaking_state:
                log.debug(f"[phase] Swiftplay matchmaking state changed: {self._last_matchmaking_state} → {current_state}")
                self._last_matchmaking_state = current_state
                
                # Check if matchmaking has started
                if current_state == "Searching" and not self._injection_triggered:
                    log.info("[phase] Swiftplay matchmaking started - triggering injection system")
                    self._trigger_swiftplay_injection()
                    self._injection_triggered = True
                elif current_state == "Invalid" and self._injection_triggered:
                    # Reset injection flag when matchmaking stops
                    log.debug("[phase] Swiftplay matchmaking stopped - resetting injection flag")
                    self._injection_triggered = False
                
        except Exception as e:
            log.debug(f"[phase] Error monitoring Swiftplay matchmaking: {e}")
    
    def _trigger_swiftplay_injection(self):
        """Trigger injection system for Swiftplay mode with all tracked skins"""
        try:
            log.info("[phase] Swiftplay matchmaking detected - triggering injection for all tracked skins")
            log.info(f"[phase] Skin tracking dictionary: {self.state.swiftplay_skin_tracking}")
            
            # Check if we have any tracked skins
            if not self.state.swiftplay_skin_tracking:
                log.warning("[phase] No tracked skins - cannot trigger injection")
                return
            
            # Log what will be injected
            total_skins = len(self.state.swiftplay_skin_tracking)
            log.info(f"[phase] Will inject {total_skins} skin(s) from tracking dictionary")
            
            # Extract all skins to mods directory, then inject them all together
            from utils.utilities import is_base_skin
            from pathlib import Path
            import zipfile
            import shutil
            
            chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
            
            # Ensure injector is initialized
            if not self.injection_manager:
                log.error("[phase] Injection manager not available")
                return
            
            self.injection_manager._ensure_initialized()
            
            if not self.injection_manager.injector:
                log.error("[phase] Injector not initialized")
                return
            
            # Clean mods directory first
            self.injection_manager.injector._clean_mods_dir()
            self.injection_manager.injector._clean_overlay_dir()
            
            # Extract all skin ZIPs to mods directory
            extracted_mods = []
            for champion_id, skin_id in self.state.swiftplay_skin_tracking.items():
                try:
                    # Determine if this is a base skin or chroma
                    is_base = is_base_skin(skin_id, chroma_id_map)
                    if is_base:
                        injection_name = f"skin_{skin_id}"
                        chroma_id_param = None
                    else:
                        injection_name = f"chroma_{skin_id}"
                        chroma_id_param = skin_id  # Pass chroma_id for chroma resolution
                    
                    # Find the skin ZIP file
                    zip_path = self.injection_manager.injector._resolve_zip(
                        injection_name, 
                        chroma_id=chroma_id_param, 
                        skin_name=injection_name, 
                        champion_name=None, 
                        champion_id=champion_id
                    )
                    
                    if not zip_path or not zip_path.exists():
                        log.warning(f"[phase] Skin ZIP not found: {injection_name}")
                        continue
                    
                    # Extract to mods directory
                    mod_folder = self.injection_manager.injector._extract_zip_to_mod(zip_path)
                    if mod_folder:
                        extracted_mods.append(mod_folder.name)
                        log.info(f"[phase] Extracted {injection_name} to mods directory")
                    
                except Exception as e:
                    log.error(f"[phase] Error extracting skin {skin_id}: {e}")
                    import traceback
                    log.debug(f"[phase] Traceback: {traceback.format_exc()}")
            
            if not extracted_mods:
                log.warning("[phase] No skins extracted - cannot inject")
                return
            
            # Store extracted mods for later injection on GameStart
            self.state.swiftplay_extracted_mods = extracted_mods
            log.info(f"[phase] Extracted {len(extracted_mods)} mod(s) - will inject on GameStart: {', '.join(extracted_mods)}")
            
            # Don't run overlay yet - wait for GameStart phase
                
        except Exception as e:
            log.warning(f"[phase] Error extracting Swiftplay skins: {e}")
            import traceback
            log.debug(f"[phase] Traceback: {traceback.format_exc()}")
    
    def _run_swiftplay_overlay(self):
        """Run overlay injection for Swiftplay mode with previously extracted mods"""
        try:
            if not self.state.swiftplay_extracted_mods:
                log.warning("[phase] No extracted mods available for overlay injection")
                return
            
            # Ensure injector is initialized
            if not self.injection_manager:
                log.error("[phase] Injection manager not available")
                return
            
            self.injection_manager._ensure_initialized()
            
            if not self.injection_manager.injector:
                log.error("[phase] Injector not initialized")
                return
            
            extracted_mods = self.state.swiftplay_extracted_mods
            log.info(f"[phase] Running overlay injection for {len(extracted_mods)} mod(s): {', '.join(extracted_mods)}")
            
            try:
                result = self.injection_manager.injector._mk_run_overlay(
                    extracted_mods, 
                    timeout=60, 
                    stop_callback=None, 
                    injection_manager=self.injection_manager
                )
                
                if result == 0:
                    log.info(f"[phase] ✓ Successfully injected {len(extracted_mods)} skin(s) for Swiftplay")
                else:
                    log.warning(f"[phase] ✗ Injection completed with non-zero exit code: {result}")
                    
            except Exception as e:
                log.error(f"[phase] Error during overlay injection: {e}")
                import traceback
                log.debug(f"[phase] Traceback: {traceback.format_exc()}")
            
            # Clear extracted mods after injection
            self.state.swiftplay_extracted_mods = []
                
        except Exception as e:
            log.warning(f"[phase] Error running Swiftplay overlay: {e}")
            import traceback
            log.debug(f"[phase] Traceback: {traceback.format_exc()}")
    
    
    def _detect_swiftplay_in_lobby(self):
        """Detect Swiftplay mode in lobby using multiple API endpoints"""
        try:
            # Check gameflow session first
            session = self.lcu.get("/lol-gameflow/v1/session")
            
            if session and isinstance(session, dict):
                game_data = session.get("gameData", {})
                if "queue" in game_data:
                    queue = game_data.get("queue", {})
                    game_mode = queue.get("gameMode")
                    log.debug(f"[phase] Detected game mode in lobby: {game_mode}")
                    
                    # Also check for other Swiftplay indicators
                    queue_id = queue.get("queueId")
                    log.debug(f"[phase] Queue ID: {queue_id}")
                    
                    # Check if this might be Swiftplay based on queue ID
                    if queue_id and "swift" in str(queue_id).lower():
                        log.debug(f"[phase] Potential Swiftplay detected via queue ID: {queue_id}")
                        return "SWIFTPLAY"
                    
                    if game_mode == "SWIFTPLAY":
                        log.debug(f"[phase] Swiftplay detected via gameMode: {game_mode}")
                        return game_mode
            else:
                log.debug("[phase] No game session data available in lobby")
            
            # Check lobby endpoints for Swiftplay indicators
            lobby_endpoints = [
                "/lol-lobby/v2/lobby",
                "/lol-lobby/v2/lobby/matchmaking/search-state",
                "/lol-lobby/v1/parties/me"
            ]
            
            for endpoint in lobby_endpoints:
                try:
                    data = self.lcu.get(endpoint)
                    if data and isinstance(data, dict):
                        # Look for Swiftplay indicators in lobby data
                        if "gameMode" in data and data.get("gameMode") == "SWIFTPLAY":
                            log.debug(f"[phase] Swiftplay detected in {endpoint}")
                            return "SWIFTPLAY"
                        
                        if "queueId" in data:
                            queue_id = data.get("queueId")
                            if queue_id and "swift" in str(queue_id).lower():
                                log.debug(f"[phase] Swiftplay detected via queue ID in {endpoint}: {queue_id}")
                                return "SWIFTPLAY"
                                
                except Exception as e:
                    log.debug(f"[phase] Error checking {endpoint}: {e}")
                    continue
            
            return None
            
        except Exception as e:
            log.debug(f"[phase] Error in Swiftplay detection: {e}")
            return None
