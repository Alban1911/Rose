#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Swiftplay Handler
Handles Swiftplay mode detection and injection
"""

import logging
import threading
import time
from typing import Optional

from lcu import LCU
from lcu.core.lockfile import SWIFTPLAY_MODES, SWIFTPLAY_QUEUE_ID
from state import SharedState
from utils.core.logging import get_logger, log_action

log = get_logger()


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
        self._overlay_done = False  # Set True after overlay completes successfully
        self._last_matchmaking_state = None
        self._swiftplay_champ_check_interval = 0.5
        self._last_swiftplay_champ_check = 0.0
        self._overlay_lock = threading.Lock()
        self._last_detect_result: tuple[Optional[str], Optional[int]] = (None, None)
        self._last_sync_active_ids: Optional[frozenset] = None
        self._last_injected_tracking: dict = {}  # snapshot of tracking at last successful extraction
        self._user_changed_since_inject: set = set()  # champion IDs explicitly changed by user after last injection
    
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
                        # Check top-level gameMode
                        if "gameMode" in data and isinstance(data.get("gameMode"), str):
                            mode_value = data.get("gameMode")
                            if mode_value.upper() in SWIFTPLAY_MODES:
                                game_mode = mode_value

                        # Check top-level queueId
                        if "queueId" in data:
                            endpoint_queue = data.get("queueId")
                            if endpoint_queue is not None:
                                queue_id = endpoint_queue

                        # Check nested gameConfig (where queueId actually lives in /lol-lobby/v2/lobby)
                        game_config = data.get("gameConfig", {})
                        if isinstance(game_config, dict):
                            if "gameMode" in game_config and isinstance(game_config.get("gameMode"), str):
                                mode_value = game_config.get("gameMode")
                                if mode_value.upper() in SWIFTPLAY_MODES:
                                    game_mode = mode_value
                            if "queueId" in game_config:
                                config_queue = game_config.get("queueId")
                                if config_queue is not None:
                                    queue_id = config_queue

                except Exception as e:
                    log.debug(f"[phase] Error checking {endpoint}: {e}")
                    continue

            # Queue ID 480 fallback when game_mode is None/unknown
            if queue_id == SWIFTPLAY_QUEUE_ID and (not game_mode or game_mode.upper() not in SWIFTPLAY_MODES):
                game_mode = "SWIFTPLAY"

            result = (game_mode, queue_id)
            if result != self._last_detect_result:
                log.debug(f"[phase] detect_swiftplay result: mode={game_mode}, queue={queue_id}")
                self._last_detect_result = result
            return game_mode, queue_id

        except Exception as e:
            log.debug(f"[phase] Error in Swiftplay detection: {e}")
            return None, None
    
    def handle_swiftplay_lobby(self, detected_mode: Optional[str] = None, detected_queue: Optional[int] = None):
        """Handle Swiftplay lobby - trigger early skin detection and UI

        Args:
            detected_mode: Game mode already detected by the caller (avoids redundant API calls)
            detected_queue: Queue ID already detected by the caller
        """
        try:
            # Use pre-detected values or fall back to API lookup
            game_mode = detected_mode
            map_id = None

            if not game_mode:
                self.lcu.refresh_if_needed()
                if not self.lcu.ok:
                    log.warning("[phase] LCU not connected - cannot handle Swiftplay lobby")
                    return

                session = self.lcu.get("/lol-gameflow/v1/session")
                if session and isinstance(session, dict):
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
            
            # Start matchmaking monitoring
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
    
    def _cleanup_click_catchers_for_swiftplay(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _start_swiftplay_matchmaking_monitoring(self):
        """Start monitoring matchmaking state for injection triggering"""
        try:
            log.info(f"[phase] Starting Swiftplay matchmaking monitoring (overlay_done={self._overlay_done}, injection_triggered={self._injection_triggered})")
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
                    hover_at = getattr(self.state, "_find_match_hover_at", None)
                    if hover_at:
                        delta_ms = (time.perf_counter() - hover_at) * 1000
                        log.info(f"[phase] Hover → Queue delay: {delta_ms:.0f}ms")
                        self.state._find_match_hover_at = None
                    log.info("[phase] Swiftplay matchmaking started - triggering injection system")
                    self.trigger_swiftplay_injection()
                    self._injection_triggered = True
                elif current_state == "Invalid" and self._injection_triggered:
                    log.debug("[phase] Swiftplay matchmaking stopped - resetting injection flag")
                    self._injection_triggered = False
        except Exception as e:
            log.debug(f"[phase] Error monitoring Swiftplay matchmaking: {e}")
    
    def poll_swiftplay_champion_selection(self):
        """Periodically poll Swiftplay champion selection and detect swaps."""
        now = time.time()
        if (now - self._last_swiftplay_champ_check) < self._swiftplay_champ_check_interval:
            return

        self._last_swiftplay_champ_check = now

        # Always check for champion swaps to keep tracking dict clean
        self._sync_tracking_with_lobby()

        # Skip champion lock polling if we already recorded one
        if self.state.own_champion_locked and self.state.locked_champ_id:
            return

        try:
            champion_selection = self.lcu.get_swiftplay_champion_selection()
            if champion_selection:
                self._process_swiftplay_champion_selection(champion_selection)
        except Exception as e:
            log.debug(f"[phase] Error polling Swiftplay champion selection: {e}")

    def _sync_tracking_with_lobby(self):
        """Remove tracked skins for champions no longer in lobby slots."""
        if not self.state.swiftplay_skin_tracking:
            return

        try:
            # Skip the API call if tracking keys match the last known lobby state
            tracking_keys = frozenset(self.state.swiftplay_skin_tracking)
            if self._last_sync_active_ids is not None and tracking_keys.issubset(self._last_sync_active_ids):
                return

            active_ids = self._get_active_lobby_champion_ids()
            if not active_ids:
                return

            self._last_sync_active_ids = frozenset(active_ids)

            with self.state.swiftplay_lock:
                stale = set(self.state.swiftplay_skin_tracking) - active_ids
                if stale:
                    for cid in stale:
                        self.state.swiftplay_skin_tracking.pop(cid, None)
                    log.info(f"[phase] Champion swap detected - removed {stale} from skin tracking")
        except Exception as e:
            log.debug(f"[phase] Error syncing tracking with lobby: {e}")
    
    def mark_champion_changed(self, champion_id: int):
        """Mark a champion as explicitly changed by the user since last injection."""
        self._user_changed_since_inject.add(champion_id)

    def force_base_skins_if_needed(self):
        """Force base skins for all tracked champions.

        Called directly from the message handler when the user hovers
        the Find-Match button, so the PUT happens while the lobby is
        still editable.
        """
        tracking = self.state.swiftplay_skin_tracking
        if not tracking:
            log.debug("[phase] force_base_skins: no tracked skins, nothing to force")
            return

        try:
            owned = getattr(self.state, "owned_skin_ids", None) or set()
            log.info(f"[phase] force_base_skins: {len(tracking)} champion(s) tracked, {len(owned)} owned skins")
            self.lcu.force_swiftplay_base_skins(tracking, owned)
        except Exception as e:
            log.warning(f"[phase] Error forcing base skins: {e}")

    def cleanup_swiftplay_exit(self):
        """Clear Swiftplay-specific state when leaving the lobby."""
        with self.state.swiftplay_lock:
            try:
                log.info("[phase] Clearing Swiftplay skin tracking - leaving Swiftplay mode")

                try:
                    self.state.swiftplay_skin_tracking.clear()
                except Exception:
                    self.state.swiftplay_skin_tracking = {}

                # Always clear extracted mods on cleanup - if cleanup is called, the
                # Swiftplay session is over and any leftover mods are orphaned.
                try:
                    self.state.swiftplay_extracted_mods.clear()
                except Exception:
                    self.state.swiftplay_extracted_mods = []

                # Reset UI-related shared state
                self.state.ui_skin_id = None
                self.state.ui_last_text = None
                self.state.last_hovered_skin_id = None
                self.state.last_hovered_skin_key = None
                self.state.selected_skin_display_name = None

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
                self._overlay_done = False
                self._last_swiftplay_champ_check = 0.0
                self._last_detect_result = (None, None)
                self._last_sync_active_ids = None
                self._last_injected_tracking = {}
                self._user_changed_since_inject = set()

                # Ensure Swiftplay flag and queue ID are cleared
                self.state.is_swiftplay_mode = False
                self.state.current_queue_id = None

            except Exception as e:
                log.warning(f"[phase] Error while cleaning up Swiftplay state: {e}")
    
    def _get_active_lobby_champion_ids(self) -> Optional[set]:
        """Return the set of champion IDs currently in the player's lobby slots.

        Returns None if the data cannot be retrieved (caller should fall back
        to injecting everything in the tracking dict).
        """
        try:
            dual = self.lcu.get_swiftplay_dual_champion_selection()
            if not dual or not dual.get("champions"):
                return None
            ids = set()
            for champ in dual["champions"]:
                cid = champ.get("championId")
                if cid and int(cid) > 0:
                    ids.add(int(cid))
            return ids if ids else None
        except Exception as e:
            log.debug(f"[phase] Failed to get active lobby champion IDs: {e}")
            return None

    def trigger_swiftplay_injection(self):
        """Trigger injection system for Swiftplay mode with all tracked skins"""
        with self.state.swiftplay_lock:
            try:
                log.info("[phase] Swiftplay matchmaking detected - triggering injection for all tracked skins")
                log.info(f"[phase] Skin tracking dictionary: {self.state.swiftplay_skin_tracking}")

                # Restore previously injected skins for champions that still have
                # a base skin in tracking (e.g. after force_base_skins reset the UI
                # and the skin processor picked up the base skin).
                # Skip champions the user explicitly browsed since last injection.
                if self._last_injected_tracking:
                    for cid, prev_skin in self._last_injected_tracking.items():
                        if cid in self._user_changed_since_inject:
                            continue
                        current = self.state.swiftplay_skin_tracking.get(cid)
                        if current is not None and current == int(cid) * 1000 and prev_skin != current:
                            log.info(f"[phase] Restoring previous skin for champion {cid}: {current} → {prev_skin}")
                            self.state.swiftplay_skin_tracking[cid] = prev_skin

                if not self.state.swiftplay_skin_tracking:
                    log.warning("[phase] No tracked skins - cannot trigger injection")
                    return

                # Filter tracking dict to only include champions currently in lobby slots
                # Reuse cached IDs from _sync_tracking_with_lobby if available
                active_champion_ids = (
                    set(self._last_sync_active_ids) if self._last_sync_active_ids
                    else self._get_active_lobby_champion_ids()
                )
                if active_champion_ids:
                    stale = set(self.state.swiftplay_skin_tracking) - active_champion_ids
                    if stale:
                        # Remove stale entries in-place to avoid replacing the dict reference
                        for stale_cid in stale:
                            self.state.swiftplay_skin_tracking.pop(stale_cid, None)
                        log.info(f"[phase] Pruned {len(stale)} stale champion(s) from tracking: {stale}")
                    filtered_tracking = dict(self.state.swiftplay_skin_tracking)
                else:
                    log.debug("[phase] Could not determine active lobby champions - injecting all tracked skins")
                    filtered_tracking = dict(self.state.swiftplay_skin_tracking)

                if not filtered_tracking:
                    log.warning("[phase] No tracked skins for active champions - cannot trigger injection")
                    return

                total_skins = len(filtered_tracking)
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

                # Clean mods directory
                self.injection_manager.injector._clean_mods_dir()
                self.injection_manager.injector._clean_overlay_dir()

                # Extract all skin ZIPs to mods directory
                extracted_mods = []
                for champion_id, skin_id in filtered_tracking.items():
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

                if not extracted_mods:
                    log.warning("[phase] No mods extracted - cannot inject")
                    return

                # Store extracted mods for later injection
                self.state.swiftplay_extracted_mods = extracted_mods
                self._last_injected_tracking = dict(filtered_tracking)
                self._user_changed_since_inject.clear()
                log.info(f"[phase] Extracted {len(extracted_mods)} skin(s) - will inject on GameStart: {', '.join(extracted_mods)}")

            except Exception as e:
                log.warning(f"[phase] Error extracting Swiftplay skins: {e}")
                import traceback
                log.debug(f"[phase] Traceback: {traceback.format_exc()}")
    
    def run_swiftplay_overlay(self):
        """Run overlay injection for Swiftplay mode with previously extracted mods"""
        with self._overlay_lock:
            try:
                # Atomically snapshot and clear the mods list so no other thread
                # can attempt injection with the same mods concurrently.
                with self.state.swiftplay_lock:
                    if self._overlay_done:
                        log.debug("[phase] Overlay already completed - skipping duplicate call")
                        return
                    if not self.state.swiftplay_extracted_mods:
                        log.debug("[phase] No extracted mods available for overlay injection")
                        return
                    extracted_mods = list(self.state.swiftplay_extracted_mods)
                    self.state.swiftplay_extracted_mods.clear()

                if not self.injection_manager:
                    log.error("[phase] Injection manager not available")
                    return

                self.injection_manager._ensure_initialized()

                if not self.injection_manager.injector:
                    log.error("[phase] Injector not initialized")
                    return

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
                        log.info(f"[phase] Successfully injected {len(extracted_mods)} skin(s) for Swiftplay")
                        self._overlay_done = True
                    else:
                        log.warning(f"[phase] Injection completed with non-zero exit code: {result}")
                except Exception as e:
                    log.error(f"[phase] Error during overlay injection: {e}")
                    import traceback
                    log.debug(f"[phase] Traceback: {traceback.format_exc()}")

            except Exception as e:
                log.warning(f"[phase] Error running Swiftplay overlay: {e}")
                import traceback
                log.debug(f"[phase] Traceback: {traceback.format_exc()}")
