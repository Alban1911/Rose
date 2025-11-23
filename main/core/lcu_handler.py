#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU disconnection handler
"""

from state import SharedState, AppStatus
from lcu import LCUSkinScraper
from utils.core.logging import get_logger

log = get_logger()


def create_lcu_disconnection_handler(state: SharedState, skin_scraper: LCUSkinScraper, app_status: AppStatus):
    """Create and return LCU disconnection handler function"""
    def on_lcu_disconnected():
        """Handle LCU disconnection - reset UI detection status"""
        log.info("[Main] LCU disconnected - resetting UI state")

        # Reset shared state fields that influence UI detection
        state.phase = None
        state.hovered_champ_id = None
        state.locked_champ_id = None
        state.locked_champ_timestamp = 0.0
        state.own_champion_locked = False
        state.players_visible = 0
        state.all_locked_announced = False
        state.loadout_countdown_active = False
        state.loadout_t0 = 0.0
        state.loadout_left0_ms = 0
        state.last_remain_ms = 0
        state.last_hover_written = False
        state.selected_skin_id = None
        state.selected_chroma_id = None
        state.selected_form_path = None
        state.pending_chroma_selection = False
        state.chroma_panel_open = False
        state.reset_skin_notification = True
        state.current_game_mode = None
        state.current_map_id = None
        state.current_queue_id = None
        state.chroma_panel_skin_name = None
        state.is_swiftplay_mode = False
        state.random_mode_active = False
        state.random_skin_name = None
        state.random_skin_id = None
        state.historic_mode_active = False
        state.historic_skin_id = None
        state.historic_first_detection_done = False
        state.ui_skin_id = None
        state.ui_last_text = None
        state.last_hovered_skin_key = None
        state.last_hovered_skin_id = None
        state.last_hovered_skin_slug = None
        state.champion_exchange_triggered = False
        state.injection_completed = False

        # Clear collection state safely
        try:
            state.locks_by_cell.clear()
        except Exception:
            state.locks_by_cell = {}
        try:
            state.processed_action_ids.clear()
        except Exception:
            state.processed_action_ids = set()
        try:
            state.owned_skin_ids.clear()
        except Exception:
            state.owned_skin_ids = set()
        try:
            state.swiftplay_skin_tracking.clear()
        except Exception:
            state.swiftplay_skin_tracking = {}
        try:
            state.swiftplay_extracted_mods.clear()
        except Exception:
            state.swiftplay_extracted_mods = []

        # Reset UI detection thread cache/connection
        if getattr(state, "ui_skin_thread", None) is not None:
            try:
                state.ui_skin_thread.clear_cache()
                if hasattr(state.ui_skin_thread, "connection"):
                    state.ui_skin_thread.connection.disconnect()
                state.ui_skin_thread.detection_available = False
                state.ui_skin_thread.detection_attempts = 0
            except Exception as e:
                log.debug(f"[Main] Failed to reset skin monitor thread after disconnection: {e}")

        # Tear down any existing UI overlay so it can be recreated cleanly
        try:
            from ui.core.user_interface import get_user_interface

            user_interface = get_user_interface(state, skin_scraper)
            if user_interface.state is not state:
                user_interface.state = state
            if skin_scraper and user_interface.skin_scraper is not skin_scraper:
                user_interface.skin_scraper = skin_scraper

            try:
                user_interface.reset_skin_state()
            except Exception as e:
                log.debug(f"[Main] Failed to reset UI skin state on disconnection: {e}")

            try:
                user_interface.request_ui_destruction()
            except Exception as e:
                log.debug(f"[Main] Failed to request UI destruction on disconnection: {e}")
        except Exception as e:
            log.debug(f"[Main] Unable to access UI instance during disconnection: {e}")

        # Update tray status (forces icon refresh if needed)
        if app_status:
            try:
                app_status.update_status(force=True)
            except Exception as e:
                log.debug(f"[Main] Failed to update app status after disconnection: {e}")
    
    return on_lcu_disconnected

