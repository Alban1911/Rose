#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket event thread
"""

# Standard library imports
import base64
import json
import logging
import os
import ssl
import threading
import time
import traceback
from typing import Optional

# Third-party imports
import websocket  # websocket-client

# Local imports
from config import (
    WS_PING_INTERVAL_DEFAULT, WS_PING_TIMEOUT_DEFAULT, WS_RECONNECT_DELAY,
    WS_PROBE_ITERATIONS, WS_PROBE_SLEEP_MS, TIMER_HZ_DEFAULT,
    FALLBACK_LOADOUT_MS_DEFAULT, INTERESTING_PHASES
)
from lcu.client import LCU
from lcu.utils import compute_locked
from state.shared_state import SharedState
from threads.loadout_ticker import LoadoutTicker
from ui.chroma_selector import get_chroma_selector
from utils.logging import get_logger, log_section, log_status, log_event

log = get_logger()

# Disable websocket ping logs
logging.getLogger("websocket").setLevel(logging.WARNING)


class WSEventThread(threading.Thread):
    """WebSocket event thread with WAMP + lock counter + timer"""
    
    def __init__(self, lcu: LCU, state: SharedState, ping_interval: int = WS_PING_INTERVAL_DEFAULT, 
                 ping_timeout: int = WS_PING_TIMEOUT_DEFAULT, timer_hz: int = TIMER_HZ_DEFAULT, fallback_ms: int = FALLBACK_LOADOUT_MS_DEFAULT, 
                 injection_manager=None, skin_scraper=None, app_status_callback=None, app_status=None):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.state = state
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.ws = None
        self.is_connected = False  # Track WebSocket connection status
        self.timer_hz = timer_hz
        self.fallback_ms = fallback_ms
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
        self.app_status_callback = app_status_callback
        self.app_status = app_status  # Store app_status to check if app is ready
        self.ticker: Optional[LoadoutTicker] = None
        self.last_locked_champion_id = None  # Track previously locked champion for exchange detection
        self._injection_42003_done = False  # Track if injection 42003 has been done

    def _handle_champion_exchange(self, old_champ_id: int, new_champ_id: int, new_champ_label: str):
        """Handle champion exchange by resetting all state and reinitializing for new champion"""
        separator = "=" * 80
        log.info(separator)
        log.info("🔄 CHAMPION EXCHANGE DETECTED")
        log.info(f"   📋 From: Champion {old_champ_id} (ID: {old_champ_id})")
        log.info(f"   📋 To: {new_champ_label} (ID: {new_champ_id})")
        log.info("   🔄 Resetting all state for new champion...")
        log.info(separator)
        
        # Reset skin state
        self.state.last_hovered_skin_key = None
        self.state.last_hovered_skin_id = None
        self.state.last_hovered_skin_slug = None
        
        # Reset injection state
        self.state.injection_completed = False
        self.state.last_hover_written = False
        
        # Reset locked champion state
        self.state.locked_champ_id = new_champ_id
        self.state.locked_champ_timestamp = time.time()
        
        # Ensure flag is set (exchange is a new lock of different champion)
        # Note: Exchange handler already triggers pipeline manually, so we just set the flag
        self.state.own_champion_locked = True
        
        # Reset HistoricMode state so it restarts for the new champion
        try:
            self.state.historic_mode_active = False
            self.state.historic_skin_id = None
            self.state.historic_first_detection_done = False
            # Hide Historic flag if it was visible
            try:
                from ui.user_interface import get_user_interface
                ui = get_user_interface(self.state, self.skin_scraper)
                ui.hide_historic_flag()
            except Exception:
                pass
        except Exception:
            pass

        # Clear UIA cache to detect new champion's skin
        if self.state.ui_skin_thread:
            try:
                self.state.ui_skin_thread.clear_cache()
                log.debug("[exchange] UIA cache cleared")
            except Exception as e:
                log.error(f"[exchange] Failed to clear UIA cache: {e}")
        
        # Trigger UI hiding in main thread by setting flag
        self.state.champion_exchange_triggered = True
        log.debug("[exchange] Champion exchange flag set - main thread will hide UI")
        
        # Scrape skins for new champion from LCU
        if self.skin_scraper:
            try:
                self.skin_scraper.scrape_champion_skins(new_champ_id)
                log.debug(f"[exchange] Scraped skins for {new_champ_label}")
            except Exception as e:
                log.error(f"[exchange] Failed to scrape champion skins: {e}")
        
        # Skin names are now provided by LCU API - no need to load from Data Dragon
        
        # Notify injection manager of champion exchange
        if self.injection_manager:
            try:
                self.injection_manager.on_champion_locked(new_champ_label, new_champ_id, self.state.owned_skin_ids)
                log.debug(f"[exchange] Notified injection manager of {new_champ_label}")
            except Exception as e:
                log.error(f"[exchange] Failed to notify injection manager: {e}")

        # Show ClickBlocker during local champion exchange to prevent accidental clicks
        try:
            from ui.user_interface import get_user_interface
            ui = get_user_interface(self.state, self.skin_scraper)
            if ui:
                ui._try_show_click_blocker()
        except Exception:
            pass
        
        log.info(f"[exchange] Champion exchange complete - ready for {new_champ_label}")

    def _on_own_champion_locked(self, champion_id: int, champion_label: str, old_champ_id: Optional[int] = None):
        """Handle own champion lock event - triggers detection/UI pipeline if needed
        
        Args:
            champion_id: ID of the locked champion
            champion_label: Label/name of the locked champion
            old_champ_id: Previous champion ID (before update) for exchange detection
            
        Pipeline triggers when:
        - First lock (own_champion_locked is False)
        - Champion exchange (own_champion_locked is True but champion_id changed)
        Pipeline does NOT trigger when:
        - Re-lock of same champion (own_champion_locked is True and same champion_id)
        """
        # Check if pipeline should trigger
        should_trigger = False
        
        if not self.state.own_champion_locked:
            # First lock - always trigger
            should_trigger = True
            log.debug(f"[lock:champ] First champion lock detected - triggering pipeline")
        elif old_champ_id is not None and old_champ_id != champion_id:
            # Champion exchange - trigger pipeline for new champion
            should_trigger = True
            log.debug(f"[lock:champ] Champion exchange detected (old={old_champ_id}, new={champion_id}) - triggering pipeline")
        elif old_champ_id is not None and old_champ_id == champion_id:
            # Re-lock of same champion - skip pipeline
            log.debug(f"[lock:champ] Re-lock of same champion ({champion_id}) - skipping pipeline")
        else:
            # Fallback: if old_champ_id is None, check against current locked_champ_id
            # This handles edge cases where old_champ_id wasn't provided
            if self.state.locked_champ_id != champion_id:
                should_trigger = True
                log.debug(f"[lock:champ] Champion change detected (current={self.state.locked_champ_id}, new={champion_id}) - triggering pipeline")
            else:
                log.debug(f"[lock:champ] Re-lock of same champion ({champion_id}) - skipping pipeline")
        
        # Set flag to True
        self.state.own_champion_locked = True
        
        # Trigger pipeline if needed
        if should_trigger:
            separator = "=" * 80
            log.info(separator)
            log.info(f"🎮 YOUR CHAMPION LOCKED")
            log.info(f"   📋 Champion: {champion_label}")
            log.info(f"   📋 ID: {champion_id}")
            log.info(separator)
            
            # Clear UIA cache to ensure fresh detection (prevents using stale cached elements)
            if self.state.ui_skin_thread:
                try:
                    self.state.ui_skin_thread.clear_cache()
                    log.debug("[lock:champ] UIA cache cleared")
                except Exception as e:
                    log.error(f"[lock:champ] Failed to clear UIA cache: {e}")
            
            # Scrape skins for this champion from LCU
            if self.skin_scraper:
                try:
                    self.skin_scraper.scrape_champion_skins(champion_id)
                except Exception as e:
                    log.error(f"[lock:champ] Failed to scrape champion skins: {e}")
            
            # Notify injection manager of champion lock
            if self.injection_manager:
                try:
                    self.injection_manager.on_champion_locked(champion_label, champion_id, self.state.owned_skin_ids)
                except Exception as e:
                    log.error(f"[lock:champ] Failed to notify injection manager: {e}")
            
            # Create chroma panel widgets on champion lock
            chroma_selector = get_chroma_selector()
            if chroma_selector:
                try:
                    chroma_selector.panel.request_create()
                    log.debug(f"[lock:champ] Requested chroma panel creation for {champion_label}")
                except Exception as e:
                    log.error(f"[lock:champ] Failed to request chroma panel creation: {e}")
            
            # Create ClickCatchers on champion lock (when not in Swiftplay)
            from ui.user_interface import get_user_interface
            user_interface = get_user_interface(self.state, self.skin_scraper)
            if user_interface:
                try:
                    user_interface.create_click_catchers()
                    log.debug(f"[lock:champ] Requested ClickCatcher creation for {champion_label}")
                except Exception as e:
                    log.error(f"[lock:champ] Failed to create ClickCatchers: {e}")

    def _maybe_start_timer(self, sess: dict):
        """Start timer if conditions are met - ONLY on FINALIZATION phase"""
        t = (sess.get("timer") or {})
        phase_timer = str((t.get("phase") or "")).upper()
        left_ms = int(t.get("adjustedTimeLeftInPhase") or 0)
        should_start = False
        probe_used = False
        
        # ONLY start timer on FINALIZATION phase (final countdown before game start)
        # This prevents starting too early when all champions are locked but bans are still in progress
        if phase_timer == "FINALIZATION":
            # Update phase to FINALIZATION if we're currently in ChampSelect
            # This ensures the phase transition happens even if the websocket event doesn't fire
            # Note: own_champion_locked flag can coexist with FINALIZATION phase
            if self.state.phase == "ChampSelect":
                if self.state.phase != "FINALIZATION":
                    log_status(log, "Phase", "FINALIZATION", "🎯")
                    self.state.phase = "FINALIZATION"
            
            # If timer value is not ready yet, probe a few times to give LCU time to publish it
            if left_ms <= 0:
                # Small 0.5s window to let LCU publish a non-zero timer
                for _ in range(WS_PROBE_ITERATIONS):  # 8 * 60ms ~= 480ms
                    s2 = self.lcu.session or {}
                    t2 = (s2.get("timer") or {})
                    phase_timer_probe = str((t2.get("phase") or "")).upper()
                    left_ms = int(t2.get("adjustedTimeLeftInPhase") or 0)
                    # Only accept timer if still in FINALIZATION phase
                    if phase_timer_probe == "FINALIZATION" and left_ms > 0:
                        probe_used = True
                        break
                    time.sleep(WS_PROBE_SLEEP_MS / 1000.0)
            
            # Start timer only if we have a positive value
            if left_ms > 0:
                should_start = True

        if should_start:
            with self.state.timer_lock:
                if not self.state.loadout_countdown_active:
                    self.state.loadout_left0_ms = left_ms
                    self.state.loadout_t0 = time.monotonic()
                    self.state.ticker_seq = (self.state.ticker_seq or 0) + 1
                    self.state.current_ticker = self.state.ticker_seq
                    self.state.loadout_countdown_active = True
                    mode = "finalization"  # Always finalization mode now (only starts on FINALIZATION phase)
                    log_event(log, f"Loadout ticker started", "⏰", {
                        "ID": self.state.current_ticker,
                        "Mode": mode,
                        "Remaining": f"{left_ms}ms ({left_ms/1000:.3f}s)",
                        "Hz": self.timer_hz,
                        "Phase": phase_timer
                    })
                    if self.ticker is None or not self.ticker.is_alive():
                        self.ticker = LoadoutTicker(self.lcu, self.state, self.timer_hz, self.fallback_ms, ticker_id=self.state.current_ticker, mode=mode, injection_manager=self.injection_manager, skin_scraper=self.skin_scraper)
                        self.ticker.start()

    def _handle_api_event(self, payload: dict):
        """Handle API event from WebSocket"""
        uri = payload.get("uri")
        if not uri: 
            return
        
        if uri == "/lol-gameflow/v1/gameflow-phase":
            ph = payload.get("data")
            # Phase transitions are handled by phase_thread
            # own_champion_locked flag can coexist with any phase
            if isinstance(ph, str) and ph != self.state.phase and ph is not None:
                if ph in INTERESTING_PHASES:
                    log_status(log, "Phase", ph, "🎯")
                self.state.phase = ph
                
                if ph == "ChampSelect":
                    # Detect game mode FIRST to get accurate is_swiftplay_mode flag
                    self._detect_game_mode()
                    
                    if self.state.is_swiftplay_mode:
                        log.debug("[WS] ChampSelect in Swiftplay mode - skipping normal reset")
                    else:
                        log_event(log, "Entering ChampSelect - resetting state for new game", "🎮")
                        # Reset skin detection state
                        self.state.last_hovered_skin_key = None
                        self.state.last_hovered_skin_id = None
                        self.state.last_hovered_skin_slug = None
                        self.state.ui_last_text = None  # Reset UI detected skin name
                        self.state.ui_skin_id = None  # Reset UI detected skin ID
                        # Reset LCU skin selection
                        self.state.selected_skin_id = None  # Reset LCU selected skin
                        self.state.owned_skin_ids.clear()  # Clear owned skins (will be refreshed immediately)
                        self.state.last_hover_written = False
                        # Reset injection and countdown state
                        self.state.injection_completed = False  # Reset injection flag for new game
                        self.state.loadout_countdown_active = False  # Reset countdown state
                        self.ticker = None  # Clear ticker reference to ensure new timer can start
                        # Reset champion lock state for new game
                        self.state.locked_champ_id = None
                        self.state.locked_champ_timestamp = 0.0  # Reset timestamp for new game
                        # Reset random skin state
                        self.state.random_skin_name = None
                        self.state.random_skin_id = None
                        self.state.random_mode_active = False
                        # Reset historic mode state
                        self.state.historic_mode_active = False
                        self.state.historic_skin_id = None
                        self.state.historic_first_detection_done = False
                        self.last_locked_champion_id = None  # Reset exchange tracking for new game
                        self.state.champion_exchange_triggered = False  # Reset champion exchange flag
                        
                        # Signal main thread to reset skin notification debouncing
                        self.state.reset_skin_notification = True
                        try: 
                            self.state.processed_action_ids.clear()
                        except Exception: 
                            self.state.processed_action_ids = set()
                        
                        # Request UI initialization when entering ChampSelect
                        try:
                            from ui.user_interface import get_user_interface
                            user_interface = get_user_interface(self.state, self.skin_scraper)
                            # Reset skin state for new ChampSelect
                            user_interface.reset_skin_state()
                            # Force UI reinitialization to rebuild for current game mode and resolution
                            user_interface._force_reinitialize = True
                            user_interface.request_ui_initialization()
                            log_event(log, "UI reinitialization requested for ChampSelect", "🎨")
                        except Exception as e:
                            log.warning(f"Failed to request UI initialization for ChampSelect: {e}")
                    
                    # Load owned skins immediately when entering ChampSelect
                    try:
                        owned_skins = self.lcu.owned_skins()
                        log.debug(f"[WS] Raw owned skins response: {owned_skins}")
                        if owned_skins and isinstance(owned_skins, list):
                            self.state.owned_skin_ids = set(owned_skins)
                            log.info(f"[WS] Loaded {len(self.state.owned_skin_ids)} owned skins from inventory")
                        else:
                            log.warning(f"[WS] Failed to fetch owned skins from LCU - no data returned (response: {owned_skins})")
                    except Exception as e:
                        log.warning(f"[WS] Error fetching owned skins: {e}")
                    
                    log.debug("[WS] State reset complete - ready for new champion select")
                
                elif ph == "FINALIZATION":
                    # FINALIZATION phase - ClickCatcherHide creation now handled when own champion is locked
                    log_event(log, "Entering FINALIZATION phase", "🎯")
                        
                elif ph == "InProgress":
                    # Game starting → log last skin
                    if self.state.last_hovered_skin_key:
                        log_section(log, f"Game Starting - Last Detected Skin: {self.state.last_hovered_skin_key.upper()}", "🎮", {
                            "Champion": self.state.last_hovered_skin_slug,
                            "SkinID": self.state.last_hovered_skin_id
                        })
                    else:
                        log_event(log, "No hovered skin detected", "ℹ️")
                
                else:
                    # Exit → reset locks/timer
                    self.state.hovered_champ_id = None
                    self.state.players_visible = 0
                    self.state.locks_by_cell.clear()
                    self.state.all_locked_announced = False
                    self.state.loadout_countdown_active = False
                    self.ticker = None  # Clear ticker reference to ensure new timer can start
        
        elif uri == "/lol-champ-select/v1/hovered-champion-id":
            cid = payload.get("data")
            try: 
                cid = int(cid) if cid is not None else None
            except Exception: 
                cid = None
            if cid and cid != self.state.hovered_champ_id:
                nm = f"champ_{cid}"
                log_status(log, "Champion hovered", f"{nm} (ID: {cid})", "👆")
                self.state.hovered_champ_id = cid
        
        elif uri == "/lol-champ-select/v1/session":
            sess = payload.get("data") or {}
            self.state.local_cell_id = sess.get("localPlayerCellId", self.state.local_cell_id)
            
            # Track selected skin ID from myTeam (owned skin selected in LCU)
            if self.state.local_cell_id is not None:
                my_team = sess.get("myTeam") or []
                for player in my_team:
                    if player.get("cellId") == self.state.local_cell_id:
                        selected_skin = player.get("selectedSkinId")
                        if selected_skin is not None:
                            self.state.selected_skin_id = int(selected_skin)
                        break
            
            # Visible players (distinct cellIds)
            seen = set()
            for side in (sess.get("myTeam") or [], sess.get("theirTeam") or []):
                for p in side or []:
                    cid = p.get("cellId")
                    if cid is not None: 
                        seen.add(int(cid))
            if not seen:
                for rnd in (sess.get("actions") or []):
                    for a in rnd or []:
                        cid = a.get("actorCellId")
                        if cid is not None: 
                            seen.add(int(cid))
            
            count_visible = len(seen)
            if count_visible != self.state.players_visible and count_visible > 0:
                self.state.players_visible = count_visible
                log_status(log, "Players", count_visible, "👥")
            
            # Lock counter: diff cellId → championId
            new_locks = compute_locked(sess)
            prev_cells = set(self.state.locks_by_cell.keys())
            curr_cells = set(new_locks.keys())
            added = sorted(list(curr_cells - prev_cells))
            removed = sorted(list(prev_cells - curr_cells))
            
            # Check for champion exchanges in existing locks (not just new locks)
            if self.state.local_cell_id is not None:
                my_cell_id = int(self.state.local_cell_id)
                if my_cell_id in new_locks:
                    new_champ_id = new_locks[my_cell_id]
                    # Debug logging for exchange detection
                    log.debug(f"[exchange_debug] my_cell_id={my_cell_id}, new_champ_id={new_champ_id}, last_locked_champion_id={self.last_locked_champion_id}, state.locked_champ_id={self.state.locked_champ_id}")
                    
                    # Check if this is an exchange (champion ID changed but we were already locked)
                    if (self.last_locked_champion_id is not None and 
                        self.last_locked_champion_id != new_champ_id and
                        self.state.locked_champ_id is not None and
                        self.state.locked_champ_id != new_champ_id):
                        # This is a champion exchange
                        champ_label = f"#{new_champ_id}"  # Use ID since we don't have database
                        log_event(log, f"Champion exchange detected: {champ_label}", "🔄", {"From": self.last_locked_champion_id, "To": new_champ_id})
                        self._handle_champion_exchange(self.last_locked_champion_id, new_champ_id, champ_label)
                        # Update tracking
                        self.last_locked_champion_id = new_champ_id
                    else:
                        # This is a new champion lock (first lock or re-lock of same champion)
                        champ_label = f"#{new_champ_id}"
                        log.info(f"   📋 Locked: {len(curr_cells)}/{self.state.players_visible}")
                        
                        # Store old champion ID before update for exchange detection
                        old_champ_id = self.state.locked_champ_id
                        
                        self.state.locked_champ_id = new_champ_id
                        self.state.locked_champ_timestamp = time.time()  # Record lock time
                        # Note: Historic Mode is only reset on champion exchange (handled in _handle_champion_exchange)
                        # We don't reset it here because the same champion can lock multiple times during ChampSelect
                        # and Historic Mode should persist across these re-locks
                        
                        # Trigger pipeline using flag-based system
                        self._on_own_champion_locked(new_champ_id, champ_label, old_champ_id)
                        
                        # Update tracking
                        self.last_locked_champion_id = new_champ_id
            
            for cid in added:
                ch = new_locks[cid]
                # Use champion ID as label since we don't have database
                champ_label = f"#{ch}"
                log_event(log, f"Champion locked: {champ_label}", "🔒", {"Locked": f"{len(curr_cells)}/{self.state.players_visible}"})
                log.debug(f"[lock_debug] Processing lock: cid={cid}, ch={ch}, local_cell_id={self.state.local_cell_id}")
                # Champion lock processing is now handled in the exchange detection section above
                # This loop only logs other players' champion locks
            
            for cid in removed:
                ch = self.state.locks_by_cell.get(cid, 0)
                champ_label = f"#{ch}"
                log_event(log, f"Champion unlocked: {champ_label}", "🔓", {"Locked": f"{len(curr_cells)}/{self.state.players_visible}"})
            
            self.state.locks_by_cell = new_locks
            
            # ALL LOCKED
            total = self.state.players_visible
            locked_count = len(self.state.locks_by_cell)
            if total > 0 and locked_count >= total and not self.state.all_locked_announced:
                log.info(f"[locks] ALL LOCKED ({locked_count}/{total})")
                self.state.all_locked_announced = True
            if locked_count < total:
                self.state.all_locked_announced = False
            
            # Timer
            self._maybe_start_timer(sess)

    def _on_open(self, ws):
        """WebSocket connection opened"""
        separator = "=" * 80
        log.info(separator)
        log.info("🔌 WEBSOCKET CONNECTED")
        log.info("   📋 Status: Active")
        log.info(separator)
        
        # Mark WebSocket as connected
        self.is_connected = True
        
        # Update app status to reflect LCU connection
        if self.app_status_callback:
            self.app_status_callback()
        
        # Inject skin 42003 when websocket connects (runs in background, waits for app to be ready)
        if not self._injection_42003_done and self.injection_manager:
            def injection_42003_thread():
                """Background thread to inject skin 42003 when websocket connects"""
                try:
                    # Wait for app to be ready (with timeout)
                    max_wait_app_ready = 60  # Wait up to 60 seconds for app to be ready
                    wait_start = time.time()
                    while (not self.app_status or not self.app_status.is_ready) and \
                          (time.time() - wait_start < max_wait_app_ready):
                        time.sleep(0.5)  # Check every 500ms
                    
                    if not self.app_status or not self.app_status.is_ready:
                        log.warning("[INJECT] App not ready within timeout, skipping skin 42003 injection")
                        return
                    
                    # Ensure injection system is initialized
                    if not self.injection_manager._initialized:
                        self.injection_manager._ensure_initialized()
                    
                    # Wait for initialization if needed
                    max_wait_init = 5
                    wait_start_init = time.time()
                    while (not self.injection_manager._initialized or 
                           not self.injection_manager.injector or 
                           not self.injection_manager.injector.game_dir) and \
                          (time.time() - wait_start_init < max_wait_init):
                        time.sleep(0.1)
                    
                    if (not self.injection_manager._initialized or 
                        not self.injection_manager.injector or 
                        not self.injection_manager.injector.game_dir):
                        log.warning("[INJECT] Injection system not ready, skipping skin 42003 injection")
                        return
                    
                    # Ensure tools folder is set up in game directory (tools_RANDOMVALUE)
                    log.info("[INJECT] Setting up tools folder in game directory...")
                    try:
                        self.injection_manager.rename_tools_folder()
                    except Exception as e:
                        log.warning(f"[INJECT] Failed to set up tools folder: {e}")
                        return
                    
                    log.info("[INJECT] Injecting skin 42003 on websocket connection...")
                    # Inject using skin ID format (hardcoded, not using shared state)
                    skin_id = 42003
                    from utils.utilities import get_champion_id_from_skin_id
                    champion_id = get_champion_id_from_skin_id(skin_id)
                    skin_name = f"skin_{skin_id}"
                    
                    # Start injection in a separate thread since it's blocking
                    def injection_exec_thread():
                        try:
                            self.injection_manager.injector.inject_skin(
                                skin_name, 
                                injection_manager=self.injection_manager, 
                                champion_id=champion_id
                            )
                        except Exception as e:
                            log.error(f"[INJECT] Injection thread error: {e}")
                    
                    threading.Thread(target=injection_exec_thread, daemon=True).start()
                    
                    # Wait for overlay process to start (poll for it)
                    max_wait_overlay = 30  # Wait up to 30 seconds for overlay to start
                    wait_start_overlay = time.time()
                    overlay_started = False
                    while time.time() - wait_start_overlay < max_wait_overlay:
                        if (self.injection_manager.injector and 
                            self.injection_manager.injector.current_overlay_process is not None):
                            overlay_started = True
                            log.info("[INJECT] Overlay process started, waiting 1 second before killing...")
                            break
                        time.sleep(0.1)  # Check every 100ms
                    
                    if overlay_started:
                        # Wait 1 second after overlay starts
                        time.sleep(1.0)
                        log.info("[INJECT] Killing overlay process after 1 second...")
                        self.injection_manager.stop_overlay_process()
                        
                        # Rename tools folder after injection (cleanup)
                        log.info("[INJECT] Renaming tools folder after injection...")
                        try:
                            self.injection_manager.rename_tools_folder()
                        except Exception as e:
                            log.warning(f"[INJECT] Failed to rename tools folder after injection: {e}")
                        
                        self._injection_42003_done = True  # Mark as done to prevent re-injection
                    else:
                        log.warning("[INJECT] Overlay process did not start within timeout")
                except Exception as e:
                    log.error(f"[INJECT] Error in skin 42003 injection thread: {e}")
            
            # Start injection thread (non-blocking)
            threading.Thread(target=injection_42003_thread, daemon=True).start()
        
        try: 
            ws.send('[5,"OnJsonApiEvent"]')
        except Exception as e: 
            log.debug(f"WebSocket: Subscribe error: {e}")
        

    def _on_message(self, ws, msg):
        """WebSocket message received"""
        try:
            data = json.loads(msg)
            if isinstance(data, list) and len(data) >= 3:
                if data[0] == 8 and isinstance(data[2], dict):
                    self._handle_api_event(data[2])
                return
            if isinstance(data, dict) and "uri" in data:
                self._handle_api_event(data)
        except Exception:
            pass

    def _on_error(self, ws, err):
        """WebSocket error"""
        log.debug(f"WebSocket: Error: {err}")

    def _on_close(self, ws, status, msg):
        """WebSocket connection closed"""
        separator = "=" * 80
        log.info(separator)
        log.info("🔌 WEBSOCKET DISCONNECTED")
        log.info(f"   📋 Status Code: {status}")
        log.info(f"   📋 Message: {msg}")
        log.info(separator)
        
        # Mark WebSocket as disconnected
        self.is_connected = False
        
        # Reset injection flag so it can run again on next connection
        self._injection_42003_done = False
        
        # Update app status to reflect LCU disconnection
        if self.app_status_callback:
            self.app_status_callback()

    def run(self):
        """Main WebSocket loop"""
        if websocket is None: 
            return
        
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.pop(k, None)
        
        while not self.state.stop:
            self.lcu.refresh_if_needed()
            if not self.lcu.ok:
                time.sleep(WS_RECONNECT_DELAY)
                continue
            
            url = f"wss://127.0.0.1:{self.lcu.port}/"
            origin = f"https://127.0.0.1:{self.lcu.port}"
            token = base64.b64encode(f"riot:{self.lcu.pw}".encode("utf-8")).decode("ascii")
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            try:
                self.ws = websocket.WebSocketApp(
                    url,
                    header=[f"Authorization: Basic {token}"],
                    subprotocols=["wamp"],
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self.ws.run_forever(
                    origin=origin,
                    sslopt={"context": ctx},
                    http_proxy_host=None,
                    http_proxy_port=None,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                )
            except Exception as e:
                log.debug(f"[ws] exception: {e}")
            
            # Check if we should stop before reconnecting
            if self.state.stop:
                break
            time.sleep(WS_RECONNECT_DELAY)
        
        # Ensure WebSocket is closed on thread exit
        if self.ws:
            try:
                self.ws.close()
                log.debug("[ws] WebSocket closed on thread exit")
            except Exception:
                pass
    
    def _detect_game_mode(self):
        """Detect game mode once when entering champion select"""
        
        # CRITICAL: Reset swiftplay flag to False first, then set to True only if actually detected
        # This prevents the flag from persisting between games if detection fails
        old_swiftplay_mode = self.state.is_swiftplay_mode
        self.state.is_swiftplay_mode = False  # Default to non-swiftplay mode
        
        try:
            if not self.lcu.ok:
                log.info("[WS] LCU not connected - cannot detect game mode, defaulting to non-swiftplay")
                if old_swiftplay_mode:
                    log.info(f"[WS] Swiftplay mode flag reset: {old_swiftplay_mode} → False")
                return
            
            # Get game session data
            session = self.lcu.get("/lol-gameflow/v1/session")
            if not session:
                log.info("[WS] No game session data available, defaulting to non-swiftplay")
                if old_swiftplay_mode:
                    log.info(f"[WS] Swiftplay mode flag reset: {old_swiftplay_mode} → False")
                return
            
            # Extract game mode and map ID from the correct location
            game_mode = None
            map_id = None
            queue_id = None
            
            # Try multiple locations for queue ID
            # First try: gameData.queue.queueId
            if "gameData" in session:
                game_data = session.get("gameData", {})
                if "queue" in game_data:
                    queue = game_data.get("queue", {})
                    game_mode = queue.get("gameMode")
                    map_id = queue.get("mapId")
                    queue_id = queue.get("queueId")
            
            # Second try: session.queueId
            if queue_id is None:
                queue_id = session.get("queueId")
            
            # Third try: Check champ select session
            if queue_id is None:
                champ_session = self.lcu.get("/lol-champ-select/v1/session")
                if champ_session and isinstance(champ_session, dict):
                    queue_id = champ_session.get("queueId")
            
            # Store in shared state
            self.state.current_game_mode = game_mode
            self.state.current_map_id = map_id
            self.state.current_queue_id = queue_id
            
            # Update is_swiftplay_mode flag based on detected game mode
            # This ensures the flag is correct when entering ChampSelect
            self.state.is_swiftplay_mode = (game_mode == "SWIFTPLAY")
            
            if old_swiftplay_mode != self.state.is_swiftplay_mode:
                log.info(f"[WS] Swiftplay mode flag updated: {old_swiftplay_mode} → {self.state.is_swiftplay_mode}")
            
            # Log queue ID when entering ChampSelect
            log.info(f"[WS] Queue ID: {queue_id}")
            
            # Log the detection result
            if map_id == 12 or game_mode == "ARAM":
                log.info("[WS] ARAM mode detected - chroma panel will use ARAM background")
            elif map_id == 11 or game_mode == "CLASSIC":
                log.info("[WS] Summoner's Rift mode detected - chroma panel will use SR background")
            elif game_mode == "SWIFTPLAY":
                log.info("[WS] Swiftplay mode detected - will trigger early skin detection in lobby")
                log.info("[WS] Swiftplay mode: Champion selection and skin detection will happen in lobby phase")
            else:
                log.info(f"[WS] Unknown game mode ({game_mode}, Map ID: {map_id}) - defaulting to SR background")
                
        except Exception as e:
            log.warning(f"[WS] Error detecting game mode: {e}")
            log.warning(f"[WS] Traceback: {traceback.format_exc()}")
            # Ensure swiftplay flag is still False after error (it was already set at method start)
    
    def stop(self):
        """Stop the WebSocket thread gracefully"""
        if self.ws:
            try:
                self.ws.close()
                log.debug("[ws] WebSocket close requested")
            except Exception:
                pass
