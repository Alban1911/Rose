#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Champion Lock Handler
Handles champion lock and exchange detection
"""

import logging
import time
from typing import Optional

from lcu import LCU, compute_locked
from state import SharedState
from ui.chroma.selector import get_chroma_selector
from utils.core.logging import get_logger, log_status, log_event

log = get_logger()


class ChampionLockHandler:
    """Handles champion lock and exchange detection"""
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        injection_manager=None,
        skin_scraper=None,
    ):
        """Initialize champion lock handler
        
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
        self.last_locked_champion_id: Optional[int] = None
    
    def handle_session_locks(self, sess: dict):
        """Handle champion locks from session data"""
        new_locks = compute_locked(sess)
        prev_cells = set(self.state.locks_by_cell.keys())
        curr_cells = set(new_locks.keys())
        added = sorted(list(curr_cells - prev_cells))
        removed = sorted(list(prev_cells - curr_cells))
        
        # Check for champion exchanges in existing locks
        if self.state.local_cell_id is not None:
            my_cell_id = int(self.state.local_cell_id)
            if my_cell_id in new_locks:
                new_champ_id = new_locks[my_cell_id]
                
                log.debug(f"[exchange_debug] my_cell_id={my_cell_id}, new_champ_id={new_champ_id}, last_locked_champion_id={self.last_locked_champion_id}, state.locked_champ_id={self.state.locked_champ_id}")
                
                # Check if this is an exchange
                if (self.last_locked_champion_id is not None and
                    self.last_locked_champion_id != new_champ_id and
                    self.state.locked_champ_id is not None and
                    self.state.locked_champ_id != new_champ_id):
                    # Champion exchange
                    champ_label = f"#{new_champ_id}"
                    log_event(log, f"Champion exchange detected: {champ_label}", "", {"From": self.last_locked_champion_id, "To": new_champ_id})
                    self.handle_champion_exchange(self.last_locked_champion_id, new_champ_id, champ_label)
                    self.last_locked_champion_id = new_champ_id
                else:
                    # New champion lock
                    champ_label = f"#{new_champ_id}"
                    log.info(f"   Locked: {len(curr_cells)}/{self.state.players_visible}")
                    
                    old_champ_id = self.state.locked_champ_id
                    
                    self.state.locked_champ_id = new_champ_id
                    self.state.locked_champ_timestamp = time.time()
                    
                    # Trigger pipeline
                    self.on_own_champion_locked(new_champ_id, champ_label, old_champ_id)
                    
                    self.last_locked_champion_id = new_champ_id
        
        # Log other players' locks
        for cid in added:
            ch = new_locks[cid]
            champ_label = f"#{ch}"
            log_event(log, f"Champion locked: {champ_label}", "🔒", {"Locked": f"{len(curr_cells)}/{self.state.players_visible}"})
        
        for cid in removed:
            ch = self.state.locks_by_cell.get(cid, 0)
            champ_label = f"#{ch}"
            log_event(log, f"Champion unlocked: {champ_label}", "", {"Locked": f"{len(curr_cells)}/{self.state.players_visible}"})
        
        self.state.locks_by_cell = new_locks
        
        # ALL LOCKED
        total = self.state.players_visible
        locked_count = len(self.state.locks_by_cell)
        if total > 0 and locked_count >= total and not self.state.all_locked_announced:
            log.info(f"[locks] ALL LOCKED ({locked_count}/{total})")
            self.state.all_locked_announced = True
        if locked_count < total:
            self.state.all_locked_announced = False
    
    def handle_champion_exchange(self, old_champ_id: int, new_champ_id: int, new_champ_label: str):
        """Handle champion exchange by resetting all state and reinitializing for new champion"""
        separator = "=" * 80
        log.info(separator)
        log.info("CHAMPION EXCHANGE DETECTED")
        log.info(f"   From: Champion {old_champ_id} (ID: {old_champ_id})")
        log.info(f"   To: {new_champ_label} (ID: {new_champ_id})")
        log.info("   Resetting all state for new champion...")
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
        self.state.own_champion_locked = True
        
        # Reset HistoricMode state
        try:
            self.state.historic_mode_active = False
            self.state.historic_skin_id = None
            self.state.historic_first_detection_done = False
        except Exception:
            pass
        
        # Clear cache
        if self.state.ui_skin_thread:
            try:
                self.state.ui_skin_thread.clear_cache()
            except Exception as e:
                log.error(f"[exchange] Failed to clear cache: {e}")
        
        # Trigger UI hiding
        self.state.champion_exchange_triggered = True
        log.debug("[exchange] Champion exchange flag set - main thread will hide UI")
        
        # Scrape skins for new champion
        if self.skin_scraper:
            try:
                self.skin_scraper.scrape_champion_skins(new_champ_id)
                log.debug(f"[exchange] Scraped skins for {new_champ_label}")
            except Exception as e:
                log.error(f"[exchange] Failed to scrape champion skins: {e}")
        
        # Notify injection manager
        if self.injection_manager:
            try:
                self.injection_manager.on_champion_locked(new_champ_label, new_champ_id, self.state.owned_skin_ids)
                log.debug(f"[exchange] Notified injection manager of {new_champ_label}")
            except Exception as e:
                log.error(f"[exchange] Failed to notify injection manager: {e}")
        
        # Show ClickBlocker
        try:
            from ui.core.user_interface import get_user_interface
            ui = get_user_interface(self.state, self.skin_scraper)
            if ui:
                ui._try_show_click_blocker()
        except Exception:
            pass
        
        log.info(f"[exchange] Champion exchange complete - ready for {new_champ_label}")
    
    def on_own_champion_locked(self, champion_id: int, champion_label: str, old_champ_id: Optional[int] = None):
        """Handle own champion lock event - triggers detection/UI pipeline if needed"""
        # Check if pipeline should trigger
        should_trigger = False
        
        if not self.state.own_champion_locked:
            should_trigger = True
            log.debug(f"[lock:champ] First champion lock detected - triggering pipeline")
        elif old_champ_id is not None and old_champ_id != champion_id:
            should_trigger = True
            log.debug(f"[lock:champ] Champion exchange detected (old={old_champ_id}, new={champion_id}) - triggering pipeline")
        elif old_champ_id is not None and old_champ_id == champion_id:
            log.debug(f"[lock:champ] Re-lock of same champion ({champion_id}) - skipping pipeline")
        else:
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
            log.info(f"YOUR CHAMPION LOCKED")
            log.info(f"   Champion: {champion_label}")
            log.info(f"   ID: {champion_id}")
            log.info(separator)
            
            # Clear cache
            if self.state.ui_skin_thread:
                try:
                    self.state.ui_skin_thread.clear_cache()
                except Exception as e:
                    log.error(f"[lock:champ] Failed to clear cache: {e}")
            
            # Scrape skins
            if self.skin_scraper:
                try:
                    self.skin_scraper.scrape_champion_skins(champion_id)
                except Exception as e:
                    log.error(f"[lock:champ] Failed to scrape champion skins: {e}")
            
            # Notify injection manager
            if self.injection_manager:
                try:
                    self.injection_manager.on_champion_locked(champion_label, champion_id, self.state.owned_skin_ids)
                except Exception as e:
                    log.error(f"[lock:champ] Failed to notify injection manager: {e}")
            
            # Create chroma panel
            chroma_selector = get_chroma_selector()
            if chroma_selector:
                try:
                    chroma_selector.panel.request_create()
                    log.debug(f"[lock:champ] Requested chroma panel creation for {champion_label}")
                except Exception as e:
                    log.error(f"[lock:champ] Failed to request chroma panel creation: {e}")
            
            # Reset historic mode state
            self.state.historic_mode_active = False
            self.state.historic_skin_id = None
            self.state.historic_first_detection_done = False
            log.debug(f"[lock:champ] Reset historic mode state for new champion lock")
            
            # Broadcast deactivated state
            try:
                if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                    self.state.ui_skin_thread._broadcast_historic_state()
            except Exception as e:
                log.debug(f"[lock:champ] Failed to broadcast historic state reset: {e}")
            
            # Broadcast champion lock state
            try:
                if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                    self.state.ui_skin_thread._broadcast_champion_locked(True)
            except Exception as e:
                log.debug(f"[lock:champ] Failed to broadcast champion lock state: {e}")

