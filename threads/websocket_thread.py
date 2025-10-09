#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket event thread
"""

import os
import json
import time
import ssl
import base64
import threading
from typing import Optional
from lcu.client import LCU
from lcu.utils import compute_locked
from database.name_db import NameDB
from state.shared_state import SharedState
from threads.loadout_ticker import LoadoutTicker
from utils.logging import get_logger, log_section, log_status, log_event
from utils.chroma_selector import get_chroma_selector
from constants import (
    WS_PING_INTERVAL_DEFAULT, WS_PING_TIMEOUT_DEFAULT, WS_RECONNECT_DELAY,
    WS_PROBE_ITERATIONS, WS_PROBE_SLEEP_MS, TIMER_HZ_DEFAULT,
    FALLBACK_LOADOUT_MS_DEFAULT, INTERESTING_PHASES
)

log = get_logger()

# Optional WebSocket import
try:
    import websocket  # websocket-client  # pyright: ignore[reportMissingImports]
    # Disable websocket ping logs
    import logging
    logging.getLogger("websocket").setLevel(logging.WARNING)
except Exception:
    websocket = None


class WSEventThread(threading.Thread):
    """WebSocket event thread with WAMP + lock counter + timer"""
    
    def __init__(self, lcu: LCU, db: NameDB, state: SharedState, ping_interval: int = WS_PING_INTERVAL_DEFAULT, 
                 ping_timeout: int = WS_PING_TIMEOUT_DEFAULT, timer_hz: int = TIMER_HZ_DEFAULT, fallback_ms: int = FALLBACK_LOADOUT_MS_DEFAULT, 
                 injection_manager=None, skin_scraper=None):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.db = db
        self.state = state
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.ws = None
        self.timer_hz = timer_hz
        self.fallback_ms = fallback_ms
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
        self.ticker: Optional[LoadoutTicker] = None

    def _maybe_start_timer(self, sess: dict):
        """Start timer if conditions are met"""
        t = (sess.get("timer") or {})
        phase_timer = str((t.get("phase") or "")).upper()
        left_ms = int(t.get("adjustedTimeLeftInPhase") or 0)
        total = self.state.players_visible
        locked_count = len(self.state.locks_by_cell)
        should_start = False
        probe_used = False
        
        # FINALIZATION → top priority
        if phase_timer == "FINALIZATION" and left_ms > 0:
            should_start = True
        # All locked: try to READ LCU timer (short grace window) before fallback
        elif (total > 0 and locked_count >= total):
            if left_ms <= 0:
                # Small 0.5s window to let LCU publish a non-zero timer
                for _ in range(WS_PROBE_ITERATIONS):  # 8 * 60ms ~= 480ms
                    s2 = self.lcu.session() or {}
                    t2 = (s2.get("timer") or {})
                    left_ms = int(t2.get("adjustedTimeLeftInPhase") or 0)
                    if left_ms > 0:
                        probe_used = True
                        break
                    time.sleep(WS_PROBE_SLEEP_MS / 1000.0)
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
                    mode = ("finalization" if (phase_timer == "FINALIZATION" and left_ms > 0) else "lcu-probe")
                    log_event(log, f"Loadout ticker started", "⏰", {
                        "ID": self.state.current_ticker,
                        "Mode": mode,
                        "Remaining": f"{left_ms}ms ({left_ms/1000:.3f}s)",
                        "Hz": self.timer_hz
                    })
                    if self.ticker is None or not self.ticker.is_alive():
                        self.ticker = LoadoutTicker(self.lcu, self.state, self.timer_hz, self.fallback_ms, ticker_id=self.state.current_ticker, mode=mode, db=self.db, injection_manager=self.injection_manager)
                        self.ticker.start()

    def _handle_api_event(self, payload: dict):
        """Handle API event from WebSocket"""
        uri = payload.get("uri")
        if not uri: 
            return
        
        if uri == "/lol-gameflow/v1/gameflow-phase":
            ph = payload.get("data")
            if isinstance(ph, str) and ph != self.state.phase:
                if ph in INTERESTING_PHASES:
                    log_status(log, "Phase", ph, "🎯")
                self.state.phase = ph
                
                if ph == "ChampSelect":
                    log_event(log, "Entering ChampSelect - resetting state for new game", "🎮")
                    self.state.last_hovered_skin_key = None
                    self.state.last_hovered_skin_id = None
                    self.state.last_hovered_skin_slug = None
                    self.state.selected_skin_id = None  # Reset LCU selected skin
                    self.state.owned_skin_ids.clear()  # Clear owned skins (will be refreshed on champion lock)
                    self.state.last_hover_written = False
                    self.state.injection_completed = False  # Reset injection flag for new game
                    self.state.loadout_countdown_active = False  # Reset countdown state
                    self.state.locked_champ_timestamp = 0.0  # Reset lock timestamp
                    try: 
                        self.state.processed_action_ids.clear()
                    except Exception: 
                        self.state.processed_action_ids = set()
                    log.debug("[WS] State reset complete - ready for new champion select")
                        
                
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
        
        elif uri == "/lol-champ-select/v1/hovered-champion-id":
            cid = payload.get("data")
            try: 
                cid = int(cid) if cid is not None else None
            except Exception: 
                cid = None
            if cid and cid != self.state.hovered_champ_id:
                nm = self.db.champ_name_by_id.get(cid) or f"champ_{cid}"
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
            
            for cid in added:
                ch = new_locks[cid]
                # Readable label if available
                champ_label = self.db.champ_name_by_id.get(int(ch), f"#{ch}")
                log_event(log, f"Champion locked: {champ_label}", "🔒", {"Locked": f"{len(curr_cells)}/{self.state.players_visible}"})
                if self.state.local_cell_id is not None and cid == int(self.state.local_cell_id):
                    log_status(log, "Your champion locked", f"{champ_label} (ID: {ch})", "✅")
                    self.state.locked_champ_id = int(ch)
                    self.state.locked_champ_timestamp = time.time()  # Record lock time for OCR delay
                    
                    # Scrape skins for this champion from LCU
                    if self.skin_scraper:
                        try:
                            self.skin_scraper.scrape_champion_skins(int(ch))
                        except Exception as e:
                            log.error(f"[lock:champ] Failed to scrape champion skins: {e}")
                    
                    # Load English skin names for this champion from Data Dragon
                    try:
                        self.db.load_champion_skins_by_id(int(ch))
                    except Exception as e:
                        log.error(f"[lock:champ] Failed to load English skin names: {e}")
                    
                    # Notify injection manager of champion lock
                    if self.injection_manager:
                        try:
                            self.injection_manager.on_champion_locked(champ_label, ch, self.state.owned_skin_ids)
                        except Exception as e:
                            log.error(f"[lock:champ] Failed to notify injection manager: {e}")
                    
                    # Create chroma wheel widgets on champion lock
                    chroma_selector = get_chroma_selector()
                    if chroma_selector:
                        try:
                            chroma_selector.wheel.request_create()
                            log.debug(f"[lock:champ] Requested chroma wheel creation for {champ_label}")
                            
                            # Download chroma previews for this champion if not already done
                            from utils.chroma_preview_manager import get_preview_manager
                            preview_manager = get_preview_manager()
                            
                            def download_previews():
                                preview_manager.download_champion_previews(champ_label)
                            
                            import threading
                            threading.Thread(target=download_previews, daemon=True, name="ChromaPreviewDownload").start()
                            
                        except Exception as e:
                            log.error(f"[lock:champ] Failed to request chroma wheel creation: {e}")
            
            for cid in removed:
                ch = self.state.locks_by_cell.get(cid, 0)
                champ_label = self.db.champ_name_by_id.get(int(ch), f"#{ch}")
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
        log.info("WebSocket: Connected")
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
        log.debug(f"WebSocket: Closed: {status} {msg}")

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
    
    def stop(self):
        """Stop the WebSocket thread gracefully"""
        if self.ws:
            try:
                self.ws.close()
                log.debug("[ws] WebSocket close requested")
            except Exception:
                pass
