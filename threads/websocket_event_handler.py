#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket Event Handler
Handles routing and processing of WebSocket API events
"""

import json
import logging
from typing import Optional

from config import INTERESTING_PHASES
from lcu.client import LCU
from lcu.utils import compute_locked
from state.shared_state import SharedState
from utils.logging import get_logger, log_status, log_event

log = get_logger()


class WebSocketEventHandler:
    """Handles routing and processing of WebSocket API events"""
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        champion_lock_handler=None,
        game_mode_detector=None,
        timer_manager=None,
        injection_manager=None,
    ):
        """Initialize event handler
        
        Args:
            lcu: LCU client instance
            state: Shared application state
            champion_lock_handler: Handler for champion lock events
            game_mode_detector: Game mode detector instance
            timer_manager: Timer manager instance
            injection_manager: Injection manager instance
        """
        self.lcu = lcu
        self.state = state
        self.champion_lock_handler = champion_lock_handler
        self.game_mode_detector = game_mode_detector
        self.timer_manager = timer_manager
        self.injection_manager = injection_manager
    
    def handle_message(self, ws, msg):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(msg)
            if isinstance(data, list) and len(data) >= 3:
                if data[0] == 8 and isinstance(data[2], dict):
                    self.handle_api_event(data[2])
                return
            if isinstance(data, dict) and "uri" in data:
                self.handle_api_event(data)
        except Exception:
            pass
    
    def handle_api_event(self, payload: dict):
        """Handle API event from WebSocket"""
        uri = payload.get("uri")
        if not uri:
            return
        
        if uri == "/lol-gameflow/v1/gameflow-phase":
            self._handle_phase_event(payload)
        elif uri == "/lol-champ-select/v1/hovered-champion-id":
            self._handle_hovered_champion_event(payload)
        elif uri == "/lol-champ-select/v1/session":
            self._handle_session_event(payload)
    
    def _handle_phase_event(self, payload: dict):
        """Handle gameflow phase event"""
        ph = payload.get("data")
        # Phase transitions are handled by phase_thread
        # own_champion_locked flag can coexist with any phase
        if isinstance(ph, str) and ph != self.state.phase and ph is not None:
            if ph in INTERESTING_PHASES:
                log_status(log, "Phase", ph, "🎯")
            self.state.phase = ph
            
            if ph == "ChampSelect":
                # Detect game mode FIRST to get accurate is_swiftplay_mode flag
                if self.game_mode_detector:
                    self.game_mode_detector.detect_game_mode()
                
                # Refresh injection threshold
                if self.injection_manager:
                    try:
                        new_threshold = self.injection_manager.refresh_injection_threshold()
                        log.info(f"[WS] Injection threshold refreshed for ChampSelect: {new_threshold:.2f}s")
                    except Exception as exc:  # noqa: BLE001
                        log.warning(f"[WS] Failed to refresh injection threshold in ChampSelect: {exc}")
                
                if self.state.is_swiftplay_mode:
                    log.debug("[WS] ChampSelect in Swiftplay mode - skipping normal reset")
                else:
                    self._handle_champ_select_entry()
            
            elif ph == "FINALIZATION":
                log_event(log, "Entering FINALIZATION phase", "🎯")
            
            elif ph == "InProgress":
                self._handle_in_progress_entry()
            
            else:
                # Exit → reset locks/timer
                self._handle_phase_exit()
    
    def _handle_champ_select_entry(self):
        """Handle entering ChampSelect phase"""
        log_event(log, "Entering ChampSelect - resetting state for new game", "🎮")
        
        # Reset skin detection state
        self.state.last_hovered_skin_key = None
        self.state.last_hovered_skin_id = None
        self.state.last_hovered_skin_slug = None
        self.state.ui_last_text = None
        self.state.ui_skin_id = None
        
        # Reset LCU skin selection
        self.state.selected_skin_id = None
        self.state.owned_skin_ids.clear()
        self.state.last_hover_written = False
        
        # Reset injection and countdown state
        self.state.injection_completed = False
        self.state.loadout_countdown_active = False
        
        # Reset champion lock state for new game
        self.state.locked_champ_id = None
        self.state.locked_champ_timestamp = 0.0
        self.state.own_champion_locked = False
        
        # Broadcast champion unlock state to JavaScript
        try:
            if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                self.state.ui_skin_thread._broadcast_champion_locked(False)
        except Exception as e:
            log.debug(f"[ws] Failed to broadcast champion unlock state: {e}")
        
        # Reset random skin state
        self.state.random_skin_name = None
        self.state.random_skin_id = None
        self.state.random_mode_active = False
        
        # Reset historic mode state
        self.state.historic_mode_active = False
        self.state.historic_skin_id = None
        self.state.historic_first_detection_done = False
        
        # Reset exchange tracking
        if self.champion_lock_handler:
            self.champion_lock_handler.last_locked_champion_id = None
        self.state.champion_exchange_triggered = False
        
        # Signal main thread to reset skin notification debouncing
        self.state.reset_skin_notification = True
        try:
            self.state.processed_action_ids.clear()
        except Exception:
            self.state.processed_action_ids = set()
        
        # Request UI initialization when entering ChampSelect
        try:
            from ui.core.user_interface import get_user_interface
            user_interface = get_user_interface(self.state, None)  # skin_scraper not needed here
            user_interface.reset_skin_state()
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
    
    def _handle_in_progress_entry(self):
        """Handle entering InProgress phase"""
        from utils.logging import log_section
        
        if self.state.last_hovered_skin_key:
            log_section(log, f"Game Starting - Last Detected Skin: {self.state.last_hovered_skin_key.upper()}", "🎮", {
                "Champion": self.state.last_hovered_skin_slug,
                "SkinID": self.state.last_hovered_skin_id
            })
        else:
            log_event(log, "No hovered skin detected", "ℹ️")
    
    def _handle_phase_exit(self):
        """Handle exiting a phase"""
        self.state.hovered_champ_id = None
        self.state.players_visible = 0
        self.state.locks_by_cell.clear()
        self.state.all_locked_announced = False
        self.state.loadout_countdown_active = False
    
    def _handle_hovered_champion_event(self, payload: dict):
        """Handle hovered champion ID event"""
        cid = payload.get("data")
        try:
            cid = int(cid) if cid is not None else None
        except Exception:
            cid = None
        
        if cid and cid != self.state.hovered_champ_id:
            nm = f"champ_{cid}"
            log_status(log, "Champion hovered", f"{nm} (ID: {cid})", "👆")
            self.state.hovered_champ_id = cid
    
    def _handle_session_event(self, payload: dict):
        """Handle champion select session event"""
        sess = payload.get("data") or {}
        self.state.local_cell_id = sess.get("localPlayerCellId", self.state.local_cell_id)
        
        # Track selected skin ID from myTeam
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
        if self.champion_lock_handler:
            self.champion_lock_handler.handle_session_locks(sess)
        
        # Timer
        if self.timer_manager:
            self.timer_manager.maybe_start_timer(sess)

