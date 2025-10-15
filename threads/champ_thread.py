#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Champion monitoring thread
"""

import time
import threading
from lcu.client import LCU
from database.name_db import NameDB
from state.shared_state import SharedState
from utils.logging import get_logger
from utils.chroma_selector import get_chroma_selector
from config import CHAMP_POLL_INTERVAL

log = get_logger()


class ChampThread(threading.Thread):
    """Thread for monitoring champion hover and lock"""
    
    def __init__(self, lcu: LCU, db: NameDB, state: SharedState, interval: float = CHAMP_POLL_INTERVAL, injection_manager=None, skin_scraper=None):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.db = db
        self.state = state
        self.interval = interval
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
        self.last_hover = None
        self.last_lock = None
        self.last_locked_champion_id = None  # Track previously locked champion for exchange detection

    def _handle_champion_exchange(self, old_champ_id: int, new_champ_id: int, new_champ_label: str):
        """Handle champion exchange by resetting all state and reinitializing for new champion"""
        separator = "=" * 80
        log.info(separator)
        log.info("🔄 CHAMPION EXCHANGE DETECTED (ChampThread)")
        log.info(f"   📋 From: {self.db.champ_name_by_id.get(old_champ_id, f'Champion {old_champ_id}')} (ID: {old_champ_id})")
        log.info(f"   📋 To: {new_champ_label} (ID: {new_champ_id})")
        log.info("   🔄 Resetting all state for new champion...")
        log.info(separator)
        
        # Reset OCR state
        self.state.last_hovered_skin_key = None
        self.state.last_hovered_skin_id = None
        self.state.last_hovered_skin_slug = None
        
        # Reset injection state
        self.state.injection_completed = False
        self.state.last_hover_written = False
        
        # Reset locked champion state
        self.state.locked_champ_id = new_champ_id
        self.state.locked_champ_timestamp = time.time()
        
        # Clear owned skins cache (will be refreshed for new champion)
        self.state.owned_skin_ids.clear()
        
        # Destroy chroma panel
        chroma_selector = get_chroma_selector()
        if chroma_selector and chroma_selector.panel:
            try:
                chroma_selector.panel.request_destroy()
                log.debug("[exchange] Chroma panel destroy requested")
            except Exception as e:
                log.debug(f"[exchange] Error destroying chroma panel: {e}")
        
        # Reset loadout countdown if active
        if self.state.loadout_countdown_active:
            self.state.loadout_countdown_active = False
            log.debug("[exchange] Reset loadout countdown state")
        
        # Scrape skins for new champion from LCU
        if self.skin_scraper:
            try:
                self.skin_scraper.scrape_champion_skins(new_champ_id)
                log.debug(f"[exchange] Scraped skins for {new_champ_label}")
            except Exception as e:
                log.error(f"[exchange] Failed to scrape champion skins: {e}")
        
        # Load English skin names for new champion from Data Dragon
        try:
            self.db.load_champion_skins_by_id(new_champ_id)
            log.debug(f"[exchange] Loaded English skin names for {new_champ_label}")
        except Exception as e:
            log.error(f"[exchange] Failed to load English skin names: {e}")
        
        # Notify injection manager of champion exchange
        if self.injection_manager:
            try:
                self.injection_manager.on_champion_locked(new_champ_label, new_champ_id, self.state.owned_skin_ids)
                log.debug(f"[exchange] Notified injection manager of {new_champ_label}")
            except Exception as e:
                log.error(f"[exchange] Failed to notify injection manager: {e}")
        
        # Create chroma panel widgets for new champion
        if chroma_selector:
            try:
                chroma_selector.panel.request_create()
                log.debug(f"[exchange] Requested chroma panel creation for {new_champ_label}")
            except Exception as e:
                log.error(f"[exchange] Failed to request chroma panel creation: {e}")
        
        log.info(f"[exchange] Champion exchange complete - ready for {new_champ_label}")

    def run(self):
        """Main thread loop"""
        while not self.state.stop:
            if not self.lcu.ok or self.state.phase != "ChampSelect":
                # Reset exchange tracking when exiting ChampSelect
                if self.state.phase != "ChampSelect":
                    self.last_locked_champion_id = None
                time.sleep(CHAMP_POLL_INTERVAL)
                continue
            
            cid = self.lcu.hovered_champion_id
            if cid is None:
                sel = self.lcu.my_selection or {}
                try: 
                    cid = int(sel.get("selectedChampionId") or 0) or None
                except Exception: 
                    cid = None
            
            if cid and cid != self.last_hover:
                nm = self.db.champ_name_by_id.get(cid) or f"champ_{cid}"
                log.info(f"[hover:champ] {nm} (id={cid})")
                self.state.hovered_champ_id = cid
                self.last_hover = cid
            
            # Personal lock (useful log even without WS)
            sess = self.lcu.session or {}
            try:
                my_cell = sess.get("localPlayerCellId")
                actions = sess.get("actions") or []
                locked = None
                for rnd in actions:
                    for act in rnd:
                        if act.get("actorCellId") == my_cell and act.get("type") == "pick" and act.get("completed"):
                            ch = int(act.get("championId") or 0)
                            if ch > 0: 
                                locked = ch
                if locked:
                    # Check for champion exchange (champion ID changed but we were already locked)
                    if (self.last_locked_champion_id is not None and 
                        self.last_locked_champion_id != locked and
                        self.state.locked_champ_id is not None and
                        self.state.locked_champ_id != locked):
                        # This is a champion exchange, not a new lock
                        nm = self.db.champ_name_by_id.get(locked) or f"champ_{locked}"
                        log.info(f"[champ_thread] Champion exchange detected: {nm} (from {self.last_locked_champion_id} to {locked})")
                        self._handle_champion_exchange(self.last_locked_champion_id, locked, nm)
                    elif locked != self.last_lock:
                        # This is a new champion lock (first lock or re-lock of same champion)
                        nm = self.db.champ_name_by_id.get(locked) or f"champ_{locked}"
                        log.info(f"[lock:champ] {nm} (id={locked})")
                        
                        # Scrape skins for this champion from LCU
                        if self.skin_scraper:
                            try:
                                self.skin_scraper.scrape_champion_skins(locked)
                            except Exception as e:
                                log.error(f"[lock:champ] Failed to scrape champion skins: {e}")
                        
                        # Load English skin names for this champion from Data Dragon
                        try:
                            self.db.load_champion_skins_by_id(locked)
                        except Exception as e:
                            log.error(f"[lock:champ] Failed to load English skin names: {e}")
                        
                        # Notify injection manager of champion lock
                        if self.injection_manager:
                            try:
                                self.injection_manager.on_champion_locked(nm, locked, self.state.owned_skin_ids)
                            except Exception as e:
                                log.error(f"[lock:champ] Failed to notify injection manager: {e}")
                        
                        # Create chroma panel widgets on champion lock
                        chroma_selector = get_chroma_selector()
                        if chroma_selector:
                            try:
                                chroma_selector.panel.request_create()
                                log.debug(f"[lock:champ] Requested chroma panel creation for {nm}")
                            except Exception as e:
                                log.error(f"[lock:champ] Failed to request chroma panel creation: {e}")
                    
                    # Always update the state, even for the same champion
                    self.state.locked_champ_id = locked
                    self.state.locked_champ_timestamp = time.time()  # Record lock time for OCR delay
                    self.last_lock = locked
                    self.last_locked_champion_id = locked  # Update tracking for next comparison
            except Exception:
                pass
            time.sleep(self.interval)
