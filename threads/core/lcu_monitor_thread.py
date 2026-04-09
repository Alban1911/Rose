#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU connection monitoring thread for language detection
"""

import json
import time
import threading
from typing import Callable, Optional
from lcu import LCU, compute_locked
from state import SharedState
from utils.core.logging import get_logger, log_status
from config import LCU_MONITOR_INTERVAL

log = get_logger()


class LCUMonitorThread(threading.Thread):
    """Thread for monitoring LCU connection and language changes"""
    
    def __init__(self, lcu: LCU, state: SharedState, language_callback: Callable[[str], None], ws_thread=None, 
                 db=None, skin_scraper=None, injection_manager=None, disconnect_callback: Optional[Callable[[], None]] = None):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.state = state
        self.language_callback = language_callback
        self.disconnect_callback = disconnect_callback
        self.ws_thread = ws_thread
        self.db = db  # Optional: for champion name lookup
        self.skin_scraper = skin_scraper  # Optional: for skin scraping on lock
        self.injection_manager = injection_manager  # Optional: for injection notification
        self.last_lcu_ok = False
        self.last_language = None
        self.waiting_for_connection = False
        self.ws_connected = False
        self.language_initialized = False  # Track if language was successfully detected after reconnection
        self.last_language_check = 0.0  # Timestamp of last language check
        self.language_retry_count = 0  # Track consecutive language detection failures
        self.max_language_retries = 5  # Force reconnect after this many failures

    def run(self):
        """Main monitoring loop"""
        while not self.state.stop:
            try:
                current_lcu_ok = self.lcu.ok
                current_ws_connected = self._is_ws_connected()
                
                # Connection lost
                if self.last_lcu_ok and not current_lcu_ok:
                    log.info("LCU connection lost - waiting for reconnection...")
                    self.waiting_for_connection = True
                    self.last_language = None
                    self.ws_connected = False
                    self.language_initialized = False
                    
                    # Notify about disconnection to reset app status
                    if self.disconnect_callback:
                        self.disconnect_callback()
                
                # Connection restored
                elif not self.last_lcu_ok and current_lcu_ok:
                    if self.waiting_for_connection:
                        log.info("LCU reconnected - waiting for WebSocket...")
                        self.waiting_for_connection = False
                
                # WebSocket connected after LCU reconnection
                elif current_lcu_ok and current_ws_connected and not self.ws_connected:
                    log.info("WebSocket connected - detecting language...")
                    self.ws_connected = True

                    # Brief wait for LCU API to stabilize after WebSocket connects
                    time.sleep(1.0)

                    # Try to detect language (will retry via the retry loop below if this fails)
                    self._try_detect_language()

                    # Check initial champion select state (for issue #29: app starting after lock)
                    self._check_initial_champion_state()
                
                # Language not yet initialized - retry detection
                elif current_lcu_ok and current_ws_connected and self.ws_connected and not self.language_initialized:
                    now = time.time()
                    # Retry every 2 seconds if language detection failed
                    if now - self.last_language_check >= 2.0:
                        log.info("Retrying language detection...")
                        self._try_detect_language()
                
                # Periodic language change check (every 30 seconds when stable)
                elif current_lcu_ok and current_ws_connected and self.ws_connected and self.language_initialized:
                    now = time.time()
                    if now - self.last_language_check >= 30.0:
                        self._check_language_change()
                
                # WebSocket disconnected
                elif not current_ws_connected and self.ws_connected:
                    self.ws_connected = False
                
                # Still waiting for connection
                elif not current_lcu_ok and self.waiting_for_connection:
                    # Refresh connection periodically
                    self.lcu.refresh_if_needed()

                if current_lcu_ok and current_ws_connected:
                    self._maybe_recover_locked_champ_select_state()
                 
                self.last_lcu_ok = current_lcu_ok
                 
            except Exception as e:
                log.debug(f"LCU monitor error: {e}")
            
            time.sleep(LCU_MONITOR_INTERVAL)

    def _try_detect_language(self):
        """Try to detect and initialize language from LCU"""
        self.last_language_check = time.time()

        try:
            log.info("[LCU] Detecting client language...")
            new_language = self.lcu.client_language
            if new_language:
                if new_language != self.last_language:
                    log.info(f"[LCU] Language detected: {new_language}")
                else:
                    log.info(f"[LCU] Language confirmed: {new_language}")

                # Reset retry count on success
                self.language_retry_count = 0

                # Update database language if available
                if self.db:
                    log.info(f"[LCU] Updating database for language: {new_language}")
                    self.db.update_language(new_language)

                # Always call callback on reconnection to ensure UI detection is reinitialized
                self.last_language = new_language
                self.language_initialized = True
                if self.language_callback:
                    self.language_callback(new_language)
            else:
                self.language_retry_count += 1
                log.warning(f"[LCU] Failed to get LCU language - client returned None (attempt {self.language_retry_count}/{self.max_language_retries})")

                # After max retries, stop retrying — the app works without language
                # detection (phases, skins, injection all work via WebSocket).
                # Forcing a reconnect here disrupts the working WebSocket connection.
                if self.language_retry_count >= self.max_language_retries:
                    log.warning("[LCU] Language detection unavailable after max retries - proceeding without it")
                    self.language_initialized = True  # Stop retrying
                    self.language_retry_count = 0
        except Exception as e:
            log.warning(f"[LCU] Failed to get LCU language: {e}")
    
    def _check_language_change(self):
        """Periodically check if language has changed"""
        self.last_language_check = time.time()
        
        try:
            current_language = self.lcu.client_language
            if current_language and current_language != self.last_language:
                log.info(f"[LCU] Language changed during session: {self.last_language} → {current_language}")
                
                # Update database language if available
                if self.db:
                    log.info(f"[LCU] Updating database for language change: {current_language}")
                    self.db.update_language(current_language)
                
                self.last_language = current_language
                if self.language_callback:
                    self.language_callback(current_language)
        except Exception as e:
            log.debug(f"[LCU] Error checking language change: {e}")
    
    def _check_initial_champion_state(self):
        """Check if we're already in ChampSelect with a locked champion (Issue #29)
        
        This handles the case where the app is launched after the user has already
        locked in a champion.
        """
        try:
            # Only check if we're in ChampSelect
            phase = self.lcu.phase if self.lcu.ok else None
            if phase != "ChampSelect":
                return
            
            # Get current session
            sess = self.lcu.session or {}
            if not sess:
                return
            
            # Get local player's cell ID
            my_cell = sess.get("localPlayerCellId")
            if my_cell is None:
                return
            self.state.local_cell_id = my_cell
            
            # Check if there are any locked champions
            locked_champions = compute_locked(sess)
            
            # Check if the local player has locked a champion
            if my_cell in locked_champions:
                locked_champ_id = locked_champions[my_cell]
                
                if self._needs_late_lock_bootstrap(locked_champ_id):
                    self._bootstrap_late_locked_champion(
                        locked_champ_id=locked_champ_id,
                        locked_champions=locked_champions,
                    )
        except Exception as e:
            log.debug(f"Error checking initial champion state: {e}")

    def _maybe_recover_locked_champ_select_state(self) -> None:
        """Retry late-lock recovery while a locked Champ Select session is active."""
        try:
            if getattr(self.state, "phase", None) != "ChampSelect":
                return

            if self.state.own_champion_locked and self.state.locked_champ_id is not None:
                return

            self._check_initial_champion_state()
        except Exception as e:
            log.debug(f"[init-state] Error retrying late lock recovery: {e}")

    def _needs_late_lock_bootstrap(self, locked_champ_id: int) -> bool:
        """Return True when late-start lock recovery still needs to run."""
        return (
            self.state.locked_champ_id != locked_champ_id
            or not self.state.own_champion_locked
        )

    def _bootstrap_late_locked_champion(self, locked_champ_id: int, locked_champions: dict) -> None:
        """Restore the same state a normal champion-lock event would set up."""
        champ_name = f"champ_{locked_champ_id}"
        log_status(
            log,
            "Initial state: Champion already locked",
            f"{champ_name} (ID: {locked_champ_id})",
            "",
        )

        self.state.phase = "ChampSelect"
        self.state.locked_champ_id = locked_champ_id
        self.state.locked_champ_timestamp = time.time()
        self.state.own_champion_locked = True
        self.state.locks_by_cell = dict(locked_champions)

        self.state.historic_mode_active = False
        self.state.historic_skin_id = None
        self.state.historic_first_detection_done = False
        log.debug("[init-state] Reset historic mode state for initial champion lock")

        self._broadcast_historic_reset()
        self._scrape_locked_champion_skins(locked_champ_id)
        self._notify_injection_manager(champ_name, locked_champ_id)
        self._sync_ui_for_late_lock()

        log.info(
            f"[init-state] App will start after initialization (champion: {champ_name})"
        )

    def _broadcast_historic_reset(self) -> None:
        """Hide historic-mode UI after late-start lock recovery."""
        ui_thread = getattr(self.state, "ui_skin_thread", None)
        if not ui_thread:
            return
        try:
            ui_thread._broadcast_historic_state()
        except Exception as e:
            log.debug(f"[init-state] Failed to broadcast historic state reset: {e}")

    def _scrape_locked_champion_skins(self, locked_champ_id: int) -> None:
        """Warm the skin scraper for the locked champion."""
        if not self.skin_scraper:
            return
        try:
            self.skin_scraper.scrape_champion_skins(locked_champ_id)
        except Exception as e:
            log.debug(f"[init-state] Failed to scrape champion skins: {e}")

    def _notify_injection_manager(self, champ_name: str, locked_champ_id: int) -> None:
        """Backfill the injection manager with the locked champion."""
        if not self.injection_manager:
            return
        try:
            self.injection_manager.on_champion_locked(
                champ_name,
                locked_champ_id,
                self.state.owned_skin_ids,
            )
        except Exception as e:
            log.debug(f"[init-state] Failed to notify injection manager: {e}")

    def _sync_ui_for_late_lock(self) -> None:
        """Broadcast late lock state to JS and replay any cached skin name."""
        ui_thread = getattr(self.state, "ui_skin_thread", None)
        if not ui_thread:
            return

        try:
            ui_thread._broadcast_phase_change("ChampSelect")
        except Exception as e:
            log.debug(f"[init-state] Failed to broadcast ChampSelect phase: {e}")

        try:
            ui_thread._broadcast_champion_locked(True)
        except Exception as e:
            log.debug(f"[init-state] Failed to broadcast champion lock state: {e}")

        self._replay_cached_skin_name(ui_thread)

    def _replay_cached_skin_name(self, ui_thread) -> None:
        """Replay the cached skin name if the first sync was ignored before lock state existed."""
        cached_skin_name = (getattr(self.state, "ui_last_text", "") or "").strip()
        if not cached_skin_name:
            return

        try:
            log.info(
                "[init-state] Replaying cached skin after late lock bootstrap: '%s'",
                cached_skin_name,
            )
            ui_thread.message_handler.handle_message(json.dumps({
                "skin": cached_skin_name,
                "originalName": cached_skin_name,
                "timestamp": int(time.time() * 1000),
            }))
        except Exception as e:
            log.debug(f"[init-state] Failed to replay cached skin state: {e}")
    
    def _is_ws_connected(self) -> bool:
        """Check if WebSocket is connected"""
        if not self.ws_thread:
            return True  # If no WS thread, consider it always connected
        
        # Use the is_connected flag from WebSocket thread
        return getattr(self.ws_thread, 'is_connected', False)
