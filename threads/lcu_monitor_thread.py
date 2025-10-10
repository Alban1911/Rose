#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU connection monitoring thread for language detection
"""

import time
import threading
from typing import Callable, Optional
from lcu.client import LCU
from lcu.utils import compute_locked
from state.shared_state import SharedState
from utils.logging import get_logger, log_status
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
                    
                    # Wait a bit for WebSocket to stabilize before fetching data
                    time.sleep(0.5)
                    
                    # Load owned skins once at startup/reconnection (with retry and longer delay)
                    self._load_owned_skins_with_retry(max_retries=5, retry_delay=1.5)
                    
                    # Try to detect language (will retry if this fails)
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
                
                self.last_lcu_ok = current_lcu_ok
                
            except Exception as e:
                log.debug(f"LCU monitor error: {e}")
            
            time.sleep(LCU_MONITOR_INTERVAL)
    
    def _load_owned_skins_with_retry(self, max_retries: int = 3, retry_delay: float = 1.0):
        """Load owned skins with retry logic (LCU may not be fully ready immediately after connection)
        
        Args:
            max_retries: Maximum number of retry attempts
            retry_delay: Delay in seconds between retries
        """
        for attempt in range(max_retries):
            try:
                owned_skins = self.lcu.owned_skins()
                if owned_skins and isinstance(owned_skins, list):
                    self.state.owned_skin_ids = set(owned_skins)
                    log.info(f"[LCU] Loaded {len(self.state.owned_skin_ids)} owned skins from inventory")
                    return  # Success
                else:
                    if attempt < max_retries - 1:
                        log.debug(f"[LCU] Failed to fetch owned skins (attempt {attempt + 1}/{max_retries}), retrying...")
                        time.sleep(retry_delay)
                    else:
                        log.warning("[LCU] Failed to fetch owned skins from LCU after all retries")
            except Exception as e:
                if attempt < max_retries - 1:
                    log.debug(f"[LCU] Error fetching owned skins (attempt {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_delay)
                else:
                    log.warning(f"[LCU] Error fetching owned skins after all retries: {e}")
    
    def _try_detect_language(self):
        """Try to detect and initialize language from LCU"""
        self.last_language_check = time.time()
        
        try:
            new_language = self.lcu.client_language
            if new_language:
                if new_language != self.last_language:
                    log.info(f"Language detected after reconnection: {new_language}")
                else:
                    log.info(f"Language confirmed after reconnection: {new_language}")
                
                # Always call callback on reconnection to ensure OCR is reinitialized
                self.last_language = new_language
                self.language_initialized = True
                self.language_callback(new_language)
            else:
                log.warning("Failed to get LCU language - client returned None")
        except Exception as e:
            log.warning(f"Failed to get LCU language: {e}")
    
    def _check_language_change(self):
        """Periodically check if language has changed"""
        self.last_language_check = time.time()
        
        try:
            current_language = self.lcu.client_language
            if current_language and current_language != self.last_language:
                log.info(f"Language changed during session: {self.last_language} → {current_language}")
                self.last_language = current_language
                self.language_callback(current_language)
        except Exception as e:
            log.debug(f"Error checking language change: {e}")
    
    def _check_initial_champion_state(self):
        """Check if we're already in ChampSelect with a locked champion (Issue #29)
        
        This handles the case where the app is launched after the user has already
        locked in a champion. Without this check, OCR would never start.
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
            
            # Check if there are any locked champions
            locked_champions = compute_locked(sess)
            
            # Check if the local player has locked a champion
            if my_cell in locked_champions:
                locked_champ_id = locked_champions[my_cell]
                
                # Only update if not already set (avoid duplicate processing)
                if self.state.locked_champ_id != locked_champ_id:
                    champ_name = self.db.champ_name_by_id.get(locked_champ_id) if self.db else f"champ_{locked_champ_id}"
                    
                    log_status(log, "Initial state: Champion already locked", f"{champ_name} (ID: {locked_champ_id})", "✅")
                    
                    # Set the locked champion state
                    self.state.locked_champ_id = locked_champ_id
                    self.state.locked_champ_timestamp = time.time()
                    
                    # Scrape skins for this champion from LCU
                    if self.skin_scraper:
                        try:
                            self.skin_scraper.scrape_champion_skins(locked_champ_id)
                        except Exception as e:
                            log.debug(f"[init-state] Failed to scrape champion skins: {e}")
                    
                    # Load English skin names for this champion from Data Dragon
                    if self.db:
                        try:
                            self.db.load_champion_skins_by_id(locked_champ_id)
                        except Exception as e:
                            log.debug(f"[init-state] Failed to load English skin names: {e}")
                    
                    # Notify injection manager of champion lock
                    if self.injection_manager:
                        try:
                            self.injection_manager.on_champion_locked(champ_name, locked_champ_id, self.state.owned_skin_ids)
                        except Exception as e:
                            log.debug(f"[init-state] Failed to notify injection manager: {e}")
                    
                    log.info(f"[init-state] OCR will start after app initialization (champion: {champ_name})")
        except Exception as e:
            log.debug(f"Error checking initial champion state: {e}")
    
    def _is_ws_connected(self) -> bool:
        """Check if WebSocket is connected"""
        if not self.ws_thread:
            return True  # If no WS thread, consider it always connected
        
        try:
            # Check if WebSocket exists and is connected
            return (hasattr(self.ws_thread, 'ws') and 
                    self.ws_thread.ws is not None and
                    hasattr(self.ws_thread.ws, 'sock') and
                    self.ws_thread.ws.sock is not None)
        except Exception:
            return False
