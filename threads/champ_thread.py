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

log = get_logger()


class ChampThread(threading.Thread):
    """Thread for monitoring champion hover and lock"""
    
    def __init__(self, lcu: LCU, db: NameDB, state: SharedState, interval: float = 0.25):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.db = db
        self.state = state
        self.interval = interval
        self.last_hover = None
        self.last_lock = None

    def run(self):
        """Main thread loop"""
        while not self.state.stop:
            if not self.lcu.ok or self.state.phase != "ChampSelect":
                time.sleep(0.25)
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
                if locked and locked != self.last_lock:
                    nm = self.db.champ_name_by_id.get(locked) or f"champ_{locked}"
                    log.info(f"[lock:champ] {nm} (id={locked})")
                    self.state.locked_champ_id = locked
                    self.last_lock = locked
            except Exception:
                pass
            time.sleep(self.interval)
