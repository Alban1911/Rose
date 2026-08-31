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
from lcu import LCU, compute_locked
from state import SharedState
from utils.core.classic_mode_ids import (
    is_classic_mode,
    is_classic_skin_id,
    resource_champion_id,
    resource_skin_id,
    resolve_default_skin_id,
)
from utils.core.logging import get_logger, log_status, log_event
from injection.config.base_skin_tracker import (
    on_skin_confirmed as _on_skin_confirmed,
    on_champ_select_exit as _on_champ_select_exit,
)

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
        swiftplay_handler=None,
    ):
        """Initialize event handler

        Args:
            lcu: LCU client instance
            state: Shared application state
            champion_lock_handler: Handler for champion lock events
            game_mode_detector: Game mode detector instance
            timer_manager: Timer manager instance
            injection_manager: Injection manager instance
            swiftplay_handler: Swiftplay handler instance for overlay injection
        """
        self.lcu = lcu
        self.state = state
        self.champion_lock_handler = champion_lock_handler
        self.game_mode_detector = game_mode_detector
        self.timer_manager = timer_manager
        self.injection_manager = injection_manager
        self.swiftplay_handler = swiftplay_handler
        self._ws_last_phase = None
    
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
        if isinstance(ph, str) and ph != self._ws_last_phase and ph is not None:
            if ph in INTERESTING_PHASES:
                log_status(log, "Phase", ph, "")
            prev_phase = self._ws_last_phase
            self._ws_last_phase = ph
            self.state.phase = ph

            from threads.handlers.champ_select_reset import note_phase_for_reset
            note_phase_for_reset(self.state, ph)

            # If leaving ChampSelect, record a timeout for any pending base skin confirmation
            if prev_phase == "ChampSelect" and ph != "ChampSelect":
                try:
                    _on_champ_select_exit()
                except Exception:
                    pass
            
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
                    if self.state.swiftplay_extracted_mods and self.swiftplay_handler:
                        import threading
                        log.info("[WS] Triggering Swiftplay overlay injection from WebSocket handler")
                        threading.Thread(
                            target=self.swiftplay_handler.run_swiftplay_overlay,
                            daemon=True,
                            name="SwiftplayOverlay-WS",
                        ).start()
                else:
                    self._handle_champ_select_entry()
            
            elif ph == "FINALIZATION":
                log_event(log, "Entering FINALIZATION phase", "")
            
            elif ph == "InProgress":
                self._handle_in_progress_entry()
            
            else:
                # Exit → reset locks/timer
                self._handle_phase_exit()
    
    def _handle_champ_select_entry(self):
        """Handle entering ChampSelect phase"""
        from threads.handlers.champ_select_reset import perform_champ_select_reset
        perform_champ_select_reset(self.state, self.lcu)
        return

        log_event(log, "Entering ChampSelect - resetting state for new game", "")
        
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

        # Clear custom mod selection from previous game so the mod-name popup
        # doesn't re-appear until the user (or historic auto-select) picks it.
        self.state.selected_custom_mod = None
        
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
            log_event(log, "UI reinitialization requested for ChampSelect", "")
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
        from utils.core.logging import log_section

        if is_classic_mode(getattr(self.state, "current_game_mode", None)):
            classic_target = (
                getattr(self.state, "classic_visual_skin_id", None)
                or getattr(self.state, "historic_skin_id", None)
                or getattr(self.state, "selected_skin_id", None)
            )
            log_section(
                log,
                "Classic Game Starting",
                "",
                {
                    "TargetSkinID": classic_target,
                    "LCUSkinID": getattr(self.state, "selected_lcu_skin_id", None),
                    "CarrierSkinID": getattr(self.state, "classic_default_skin_id", None),
                    "HistoricMode": getattr(self.state, "historic_mode_active", False),
                },
            )
            log.info(
                "[CLASSIC:INJECT] game starting target=%s lcu=%s carrier=%s historic=%s",
                classic_target,
                getattr(self.state, "selected_lcu_skin_id", None),
                getattr(self.state, "classic_default_skin_id", None),
                getattr(self.state, "historic_mode_active", False),
            )
            return
        
        if self.state.last_hovered_skin_key:
            log_section(log, f"Game Starting - Last Detected Skin: {self.state.last_hovered_skin_key.upper()}", "", {
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

        raw_selected_skin = None
        if self.state.local_cell_id is not None:
            my_team = sess.get("myTeam") or []
            for player in my_team:
                if player.get("cellId") == self.state.local_cell_id:
                    raw_selected_skin = player.get("selectedSkinId")
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
            log_status(log, "Players", count_visible, "")
        
        # Lock counter: diff cellId → championId
        if self.champion_lock_handler:
            self.champion_lock_handler.handle_session_locks(sess)

        if raw_selected_skin is not None:
            self._update_selected_skin(raw_selected_skin)
        
        # Timer
        if self.timer_manager:
            self.timer_manager.maybe_start_timer(sess)

    def _update_selected_skin(self, raw_skin_id) -> None:
        """Track server and resource IDs without conflating local projection."""
        try:
            raw_skin_id = int(raw_skin_id)
        except (TypeError, ValueError):
            return

        previous_lcu_skin_id = self.state.selected_lcu_skin_id
        self.state.selected_lcu_skin_id = raw_skin_id
        if not is_classic_mode(self.state.current_game_mode):
            self.state.selected_skin_id = raw_skin_id
            try:
                _on_skin_confirmed(raw_skin_id)
            except Exception:
                pass
            return

        if not is_classic_skin_id(raw_skin_id):
            log.warning("Ignoring invalid Classic Mode skin ID: %s", raw_skin_id)
            return

        champion_id = resource_champion_id(raw_skin_id // 1000)
        locked_champion = self.state.locked_champ_id
        if locked_champion and int(locked_champion) != champion_id:
            log.debug("Ignoring stale Classic Mode selection for champion %s", champion_id)
            return

        if self.state.classic_champion_id != champion_id:
            try:
                catalog_ids = self.lcu.get(
                    "/lol-lobby-team-builder/champ-select/v1/pickable-skin-ids"
                )
            except Exception:
                catalog_ids = None
            try:
                default_skin_id = resolve_default_skin_id(
                    champion_id, catalog_ids, raw_skin_id
                )
            except ValueError as exc:
                log.warning("Cannot resolve Classic Mode default: %s", exc)
                self.state.clear_classic_mode()
                return
            self.state.classic_champion_id = champion_id
            self.state.classic_default_skin_id = default_skin_id

        selected_skin_id = resource_skin_id(raw_skin_id)
        owned = {resource_skin_id(value) for value in (self.state.owned_skin_ids or ())}
        projected_skin_id = self.state.classic_visual_skin_id
        if projected_skin_id is None:
            self.state.classic_selected_skin_owned = (
                selected_skin_id == self.state.classic_default_skin_id
                or selected_skin_id in owned
            )
        if previous_lcu_skin_id != raw_skin_id:
            log.info(
                "[CLASSIC:LCU] observed raw=%s skin=%s projected=%s owned=%s default=%s",
                raw_skin_id,
                selected_skin_id,
                projected_skin_id or "none",
                self.state.classic_selected_skin_owned,
                self.state.classic_default_skin_id,
            )
        if (
            projected_skin_id is not None
            and selected_skin_id == self.state.classic_default_skin_id
        ):
            log.debug(
                "[CLASSIC:LCU] Preserving visual skin %s while LCU stays on default %s",
                projected_skin_id,
                selected_skin_id,
            )
            return

        self.state.selected_skin_id = selected_skin_id
        try:
            _on_skin_confirmed(selected_skin_id)
        except Exception:
            pass
