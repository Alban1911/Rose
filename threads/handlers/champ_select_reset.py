#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single source of truth for the per-game ChampSelect reset."""

import logging

log = logging.getLogger(__name__)

_CHAMP_SELECT_PHASES = {"ChampSelect", "FINALIZATION"}


def note_phase_for_reset(state, phase) -> None:
    """Re-arm the reset guard after leaving ChampSelect/FINALIZATION."""
    if phase not in _CHAMP_SELECT_PHASES:
        state.champ_select_reset_done = False


def perform_champ_select_reset(state, lcu) -> bool:
    """Reset per-game state once for the current ChampSelect phase."""
    if getattr(state, "champ_select_reset_done", False):
        return False
    state.champ_select_reset_done = True
    state.champ_select_generation = getattr(state, "champ_select_generation", 0) + 1

    log.info("[reset] Entering ChampSelect - resetting state for new game")
    state.last_hovered_skin_key = None
    state.last_hovered_skin_id = None
    state.last_hovered_skin_slug = None
    state.ui_last_text = None
    state.ui_skin_id = None
    state.ui_last_text_champion_id = None
    state.ui_last_text_generation = -1
    state.ui_last_text_timestamp = 0.0
    state.selected_skin_id = None
    try:
        state.owned_skin_ids.clear()
    except Exception:
        state.owned_skin_ids = set()

    state.last_hover_written = False
    state.injection_completed = False
    state.loadout_countdown_active = False
    state.locked_champ_id = None
    state.locked_champ_timestamp = 0.0
    state.own_champion_locked = False
    state.reset_last_locked = True
    state.random_skin_name = None
    state.random_skin_id = None
    state.random_mode_active = False
    state.historic_mode_active = False
    state.historic_skin_id = None
    state.historic_first_detection_done = False
    state.selected_custom_mod = None
    state.champion_exchange_triggered = False
    state.reset_skin_notification = True

    try:
        state.processed_action_ids.clear()
    except Exception:
        state.processed_action_ids = set()

    try:
        if getattr(state, "ui_skin_thread", None):
            state.ui_skin_thread._broadcast_champion_locked(False)
    except Exception as exc:
        log.debug("[reset] Failed to broadcast champion unlock state: %s", exc)

    try:
        from ui.core.user_interface import get_user_interface
        user_interface = get_user_interface(state, None)
        user_interface.reset_skin_state()
        user_interface._force_reinitialize = True
        user_interface.request_ui_initialization()
    except Exception as exc:
        log.warning("[reset] Failed to request UI initialization: %s", exc)

    try:
        owned_skins = lcu.owned_skins() if lcu else None
        if owned_skins and isinstance(owned_skins, list):
            state.owned_skin_ids = set(owned_skins)
        else:
            log.warning("[reset] Failed to fetch owned skins from LCU")
    except Exception as exc:
        log.warning("[reset] Error fetching owned skins: %s", exc)

    return True
