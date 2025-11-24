#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Swiftplay Handler
Handles Swiftplay mode detection and injection
"""

import logging
import time
from typing import Optional

from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger, log_action

log = get_logger()

SWIFTPLAY_MODES = {"SWIFTPLAY", "BRAWL"}


class SwiftplayHandler:
    """Handles Swiftplay mode detection and injection"""
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        injection_manager=None,
        skin_scraper=None,
    ):
        """Initialize Swiftplay handler
        
        Args:
            lcu: LCU client instance
            state: Shared application state
            injection_manager: Injection manager instance
            skin_scraper: Skin scraper instance
        """
        self.lcu = lcu
        self.state = state
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
        
        # Swiftplay injection tracking
        self._injection_triggered = False
        self._last_matchmaking_state = None
        self._swiftplay_champ_check_interval = 0.5
        self._last_swiftplay_champ_check = 0.0
    
    def detect_swiftplay_in_lobby(self) -> tuple[Optional[str], Optional[int]]:
        """Detect lobby game mode using multiple API endpoints."""
        try:
            game_mode = None
            queue_id = None

            # Check gameflow session first
            session = self.lcu.get("/lol-gameflow/v1/session")

            if session and isinstance(session, dict):
                game_data = session.get("gameData", {})
                if "queue" in game_data:
                    queue = game_data.get("queue", {})
                    game_mode = queue.get("gameMode") or game_mode
                    queue_id = queue.get("queueId") or queue_id

                    if queue_id and isinstance(queue_id, (str, int)):
                        queue_str = str(queue_id).lower()
                        if "swift" in queue_str and game_mode != "SWIFTPLAY":
                            game_mode = "SWIFTPLAY"
                        elif "brawl" in queue_str and game_mode != "BRAWL":
                            game_mode = "BRAWL"

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
                        if "gameMode" in data and isinstance(data.get("gameMode"), str):
                            mode_value = data.get("gameMode")
                            if mode_value.upper() in SWIFTPLAY_MODES:
                                game_mode = mode_value

                        if "queueId" in data:
                            endpoint_queue = data.get("queueId")
                            if endpoint_queue is not None:
                                queue_id = endpoint_queue
                                queue_str = str(endpoint_queue).lower()
                                if "swift" in queue_str:
                                    game_mode = game_mode or "SWIFTPLAY"
                                elif "brawl" in queue_str:
                                    game_mode = game_mode or "BRAWL"

                except Exception as e:
                    log.debug(f"[phase] Error checking {endpoint}: {e}")
                    continue

            return game_mode, queue_id

        except Exception as e:
            log.debug(f"[phase] Error in Swiftplay detection: {e}")
            return None, None
    
    def handle_swiftplay_lobby(self):
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
            self._last_swiftplay_champ_check = 0.0

            # Ensure UIA thread can reconnect for Swiftplay lobby monitoring
            ui_thread = getattr(self.state, "ui_skin_thread", None)
            if ui_thread is not None and hasattr(ui_thread, "_injection_disconnect_active"):
                ui_thread._injection_disconnect_active = False
                if hasattr(ui_thread, "stop_event") and getattr(ui_thread, "stop_event"):
                    try:
                        ui_thread.stop_event.clear()
                    except Exception:
                        pass
            
            log.info(f"[phase] Swiftplay lobby - Game mode: {game_mode}, Map ID: {map_id}")
            
            # Check for champion selection in lobby
            self._check_swiftplay_champion_selection()
            
            # Clean up any existing ClickCatchers for Swiftplay mode
            self._cleanup_click_catchers_for_swiftplay()
            
            # Initialize UI for Swiftplay mode
            try:
                from ui.core.user_interface import get_user_interface
                user_interface = get_user_interface(self.state, self.skin_scraper)
                if not user_interface.is_ui_initialized():
                    log.info("[phase] Initializing UI components for Swiftplay mode")
                    user_interface._pending_ui_initialization = True
            except Exception as e:
                log.warning(f"[phase] Failed to initialize UI for Swiftplay: {e}")
            
            # Start continuous monitoring
            self._start_swiftplay_monitoring()
            self._start_swiftplay_matchmaking_monitoring()
            
        except Exception as e:
            log.warning(f"[phase] Error handling Swiftplay lobby: {e}")
    
    def _check_swiftplay_champion_selection(self):
        """Check for champion selection in Swiftplay lobby"""
        try:
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
                self.state.own_champion_locked = True
                
                # Trigger skin scraping
                if self.skin_scraper:
                    self.skin_scraper.scrape_champion_skins(champion_id)
                
                # If skin is also selected, update the state
                if skin_id:
                    log.info(f"[phase] Swiftplay skin selected: {skin_id}")
                    self.state.selected_skin_id = skin_id
        except Exception as e:
            log.warning(f"[phase] Error processing Swiftplay champion selection: {e}")
    
    def _start_swiftplay_monitoring(self):
        """Start continuous monitoring for Swiftplay lobby changes"""
        log.debug("[phase] Swiftplay monitoring started - will check for changes periodically")
    
    def _cleanup_click_catchers_for_swiftplay(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _start_swiftplay_matchmaking_monitoring(self):
        """Start monitoring matchmaking state for injection triggering"""
        try:
            log.info("[phase] Starting Swiftplay matchmaking monitoring...")
            self._last_matchmaking_state = None
            self._injection_triggered = False
        except Exception as e:
            log.warning(f"[phase] Error starting Swiftplay matchmaking monitoring: {e}")
    
    def monitor_swiftplay_matchmaking(self):
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
                    self.trigger_swiftplay_injection()
                    self._injection_triggered = True
                elif current_state == "Invalid" and self._injection_triggered:
                    log.debug("[phase] Swiftplay matchmaking stopped - resetting injection flag")
                    self._injection_triggered = False
        except Exception as e:
            log.debug(f"[phase] Error monitoring Swiftplay matchmaking: {e}")
    
    def poll_swiftplay_champion_selection(self):
        """Periodically poll Swiftplay champion selection until we detect our lock."""
        now = time.time()
        if (now - self._last_swiftplay_champ_check) < self._swiftplay_champ_check_interval:
            return

        self._last_swiftplay_champ_check = now

        # Skip polling if we already recorded a champion lock
        if self.state.own_champion_locked and self.state.locked_champ_id:
            return

        try:
            champion_selection = self.lcu.get_swiftplay_champion_selection()
            if champion_selection:
                self._process_swiftplay_champion_selection(champion_selection)
        except Exception as e:
            log.debug(f"[phase] Error polling Swiftplay champion selection: {e}")
    
    def cleanup_swiftplay_exit(self):
        """Clear Swiftplay-specific state when leaving the lobby."""
        try:
            log.info("[phase] Clearing Swiftplay skin tracking - leaving Swiftplay mode")

            try:
                self.state.swiftplay_skin_tracking.clear()
            except Exception:
                self.state.swiftplay_skin_tracking = {}

            # Don't clear extracted_mods if we're still in Swiftplay mode and haven't built overlay yet
            # Only clear if we're actually leaving Swiftplay mode (phase is None or not Swiftplay-related)
            current_phase = getattr(self.state, 'phase', None)
            if current_phase not in ["Matchmaking", "ChampSelect", "FINALIZATION"]:
                try:
                    self.state.swiftplay_extracted_mods.clear()
                except Exception:
                    self.state.swiftplay_extracted_mods = []

            # Reset UI-related shared state
            self.state.ui_skin_id = None
            self.state.ui_last_text = None
            self.state.last_hovered_skin_id = None
            self.state.last_hovered_skin_key = None

            # Reset champion lock state
            self.state.own_champion_locked = False
            self.state.locked_champ_id = None
            self.state.locked_champ_timestamp = 0.0

            # Stop detection and clear its caches
            ui_thread = getattr(self.state, "ui_skin_thread", None)
            if ui_thread is not None:
                try:
                    ui_thread.clear_cache()
                except Exception as e:
                    log.debug(f"[phase] Failed to clear cache after Swiftplay exit: {e}")

                try:
                    connection = getattr(ui_thread, "connection", None)
                    if connection and hasattr(connection, "is_connected") and connection.is_connected():
                        connection.disconnect()
                except Exception as e:
                    log.debug(f"[phase] Failed to disconnect after Swiftplay exit: {e}")

                ui_thread.detection_available = False
                ui_thread.detection_attempts = 0
                if hasattr(ui_thread, "stop_event"):
                    try:
                        ui_thread.stop_event.clear()
                    except Exception:
                        pass
                if hasattr(ui_thread, "_injection_disconnect_active"):
                    ui_thread._injection_disconnect_active = False
                if hasattr(ui_thread, "_last_phase"):
                    ui_thread._last_phase = None

            # Reset matchmaking helpers
            self._last_matchmaking_state = None
            self._injection_triggered = False
            self._last_swiftplay_champ_check = 0.0

            # Ensure Swiftplay flag is cleared
            self.state.is_swiftplay_mode = False

        except Exception as e:
            log.warning(f"[phase] Error while cleaning up Swiftplay state: {e}")
    
    def trigger_swiftplay_injection(self):
        """Trigger injection system for Swiftplay mode with all tracked skins"""
        try:
            log.info("[phase] Swiftplay matchmaking detected - triggering injection for all tracked skins")
            log.info(f"[phase] Skin tracking dictionary: {self.state.swiftplay_skin_tracking}")
            
            if not self.state.swiftplay_skin_tracking:
                log.warning("[phase] No tracked skins - cannot trigger injection")
                return
            
            total_skins = len(self.state.swiftplay_skin_tracking)
            log.info(f"[phase] Will inject {total_skins} skin(s) from tracking dictionary")
            
            from utils.core.utilities import is_base_skin
            from pathlib import Path
            import zipfile
            import shutil
            
            chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
            
            if not self.injection_manager:
                log.error("[phase] Injection manager not available")
                return
            
            self.injection_manager._ensure_initialized()
            
            if not self.injection_manager.injector:
                log.error("[phase] Injector not initialized")
                return
            
            # Extract user mods first
            try:
                self.injection_manager.injector._extract_user_mods()
            except Exception as e:
                log.warning(f"[phase] Failed to extract user mods: {e}")
            
            # Clean mods directory
            self.injection_manager.injector._clean_mods_dir()
            self.injection_manager.injector._clean_overlay_dir()
            
            # Extract all skin ZIPs to mods directory
            extracted_mods = []
            for champion_id, skin_id in self.state.swiftplay_skin_tracking.items():
                try:
                    is_base = is_base_skin(skin_id, chroma_id_map)
                    if is_base:
                        injection_name = f"skin_{skin_id}"
                        chroma_id_param = None
                    else:
                        injection_name = f"chroma_{skin_id}"
                        chroma_id_param = skin_id
                    
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
                    
                    mod_folder = self.injection_manager.injector._extract_zip_to_mod(zip_path)
                    if mod_folder:
                        extracted_mods.append(mod_folder.name)
                        log.info(f"[phase] Extracted {injection_name} to mods directory")
                except Exception as e:
                    log.error(f"[phase] Error extracting skin {skin_id}: {e}")
                    import traceback
                    log.debug(f"[phase] Traceback: {traceback.format_exc()}")
            
            # Copy installed mods
            installed_mods = self.injection_manager.injector._copy_installed_mods_to_mods_dir()
            
            # Combine mods
            all_mods = extracted_mods + installed_mods
            
            if not all_mods:
                log.warning("[phase] No mods extracted - cannot inject")
                return
            
            # Store extracted mods for later injection
            self.state.swiftplay_extracted_mods = all_mods
            if installed_mods:
                log.info(f"[phase] Extracted {len(extracted_mods)} skin(s) + {len(installed_mods)} installed mod(s) - will inject on GameStart: {', '.join(all_mods)}")
            else:
                log.info(f"[phase] Extracted {len(extracted_mods)} skin(s) - will inject on GameStart: {', '.join(extracted_mods)}")
                
        except Exception as e:
            log.warning(f"[phase] Error extracting Swiftplay skins: {e}")
            import traceback
            log.debug(f"[phase] Traceback: {traceback.format_exc()}")
    
    def run_swiftplay_overlay(self):
        """Run overlay injection for Swiftplay mode with previously extracted mods"""
        try:
            if not self.state.swiftplay_extracted_mods:
                log.warning("[phase] No extracted mods available for overlay injection")
                return
            
            if not self.injection_manager:
                log.error("[phase] Injection manager not available")
                return
            
            self.injection_manager._ensure_initialized()
            
            if not self.injection_manager.injector:
                log.error("[phase] Injector not initialized")
                return
            
            extracted_mods = self.state.swiftplay_extracted_mods
            log.info(f"[phase] Running overlay injection for {len(extracted_mods)} mod(s): {', '.join(extracted_mods)}")
            
            # Start game monitor to prevent game from starting before overlay is ready
            if not self.injection_manager._monitor_active:
                log.info("[phase] Starting game monitor for Swiftplay overlay injection")
                self.injection_manager._start_monitor()
            
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

