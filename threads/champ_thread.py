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
from constants import CHAMP_POLL_INTERVAL

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

    def run(self):
        """Main thread loop"""
        while not self.state.stop:
            if not self.lcu.ok or self.state.phase != "ChampSelect":
                time.sleep(CHAMP_POLL_INTERVAL)
                continue
            
            cid = self.lcu.hovered_champion_id()
            if cid is None:
                sel = self.lcu.my_selection() or {}
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
            sess = self.lcu.session() or {}
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
                    # Always update the locked champion state, even if it's the same champion
                    # This ensures OCR can restart when returning to ChampSelect
                    if locked != self.last_lock:
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
                        
                        # Create chroma wheel widgets on champion lock
                        chroma_selector = get_chroma_selector()
                        if chroma_selector:
                            try:
                                chroma_selector.wheel.request_create()
                                log.debug(f"[lock:champ] Requested chroma wheel creation for {nm}")
                                
                                # Download chroma previews for this champion if not already done
                                from utils.chroma_preview_manager import get_preview_manager
                                preview_manager = get_preview_manager()
                                
                                def download_previews():
                                    preview_manager.download_champion_previews(nm)
                                
                                import threading
                                threading.Thread(target=download_previews, daemon=True, name="ChromaPreviewDownload").start()
                                
                            except Exception as e:
                                log.error(f"[lock:champ] Failed to request chroma wheel creation: {e}")
                    
                    # Always update the state, even for the same champion
                    self.state.locked_champ_id = locked
                    self.state.locked_champ_timestamp = time.time()  # Record lock time for OCR delay
                    self.last_lock = locked
            except Exception:
                pass
            time.sleep(self.interval)
