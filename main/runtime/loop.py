#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main application loop
"""

import time
from typing import Any

from state import SharedState
from lcu import LCUSkinScraper
from utils.core.logging import get_logger, log_section
from config import MAIN_LOOP_SLEEP, MAIN_LOOP_STALL_THRESHOLD_S, CHROMA_PANEL_PROCESSING_THRESHOLD_S

log = get_logger()

# Module-level state for loop tracking
_loop_state: dict[str, Any] = {}


def run_main_loop(state: SharedState, skin_scraper: LCUSkinScraper) -> None:
    """Run the main application loop"""
    last_phase = None
    last_loop_time = time.time()
    
    try:
        while not state.stop:
            loop_start = time.time()
            
            # Watchdog: detect if previous loop took too long
            time_since_last_loop = loop_start - last_loop_time
            if time_since_last_loop > MAIN_LOOP_STALL_THRESHOLD_S:
                log.warning(f"Main loop stall detected: {time_since_last_loop:.1f}s since last iteration")
            last_loop_time = loop_start
            
            # Check if we should stop (extra check with logging)
            if state.stop:
                log.debug("[DEBUG] Main loop detected stop flag - exiting")
                break
            
            ph = state.phase
            if ph != last_phase:
                last_phase = ph
            
            # Check for skin changes and notify UI (modular architecture)
            try:
                _process_ui_updates(state, skin_scraper)
            except Exception as e:
                log.debug(f"UI processing error: {e}")
            
            time.sleep(MAIN_LOOP_SLEEP)
    except KeyboardInterrupt:
        log_section(log, "Shutting Down (Keyboard Interrupt)", "⚠️")
        log.debug(f"[DEBUG] Keyboard interrupt - setting state.stop = True")
        state.stop = True
    finally:
        log.debug(f"[DEBUG] Finally block - setting state.stop = True")
        state.stop = True


def _process_ui_updates(state: SharedState, skin_scraper: LCUSkinScraper) -> None:
    """Process UI updates in the main loop"""
    # For Swiftplay mode, use ui_skin_id and calculate champion_id from skin_id
    # For regular mode, use last_hovered_skin_id and locked_champ_id
    if state.is_swiftplay_mode and state.ui_skin_id:
        current_skin_id = state.ui_skin_id
        current_skin_name = state.ui_last_text or f"Skin {current_skin_id}"
        # Calculate champion ID from skin ID for Swiftplay
        from utils.core.utilities import get_champion_id_from_skin_id
        champion_id = get_champion_id_from_skin_id(current_skin_id)
        champion_name = None
        # Load champion data if not already loaded
        if skin_scraper:
            if not skin_scraper.cache.is_loaded_for_champion(champion_id):
                skin_scraper.scrape_champion_skins(champion_id)
            if skin_scraper.cache.is_loaded_for_champion(champion_id):
                champion_name = skin_scraper.cache.champion_name
    elif state.last_hovered_skin_id and state.locked_champ_id:
        current_skin_id = state.last_hovered_skin_id
        current_skin_name = state.last_hovered_skin_key
        
        # Get champion name from LCU skin scraper cache
        champion_name = None
        if skin_scraper and skin_scraper.cache.is_loaded_for_champion(state.locked_champ_id):
            champion_name = skin_scraper.cache.champion_name
    else:
        current_skin_id = None
        champion_id = None
        champion_name = None
        current_skin_name = None
    
    # Check if UI should be hidden in Swiftplay mode when detection is lost
    # But only if we don't have extracted mods waiting for overlay injection
    # (i.e., overlay hasn't been built yet, so we should wait for it)
    if state.is_swiftplay_mode and state.ui_skin_id is None:
        # Don't hide UI if we have extracted mods waiting for overlay injection
        # This means we're in Matchmaking/ChampSelect and overlay hasn't been built yet
        has_extracted_mods = state.swiftplay_extracted_mods and len(state.swiftplay_extracted_mods) > 0
        if not has_extracted_mods:
            # Use a flag to avoid spamming hide() calls
            if not _loop_state.get('swiftplay_ui_hidden'):
                try:
                    from ui.core.user_interface import get_user_interface
                    user_interface = get_user_interface(state, skin_scraper)
                    if user_interface.is_ui_initialized():
                        if user_interface.chroma_ui:
                            user_interface.chroma_ui.hide()
                        # Reset skin state so skins can be shown again after being hidden
                        with user_interface.lock:
                            user_interface.current_skin_id = None
                            user_interface.current_skin_name = None
                            user_interface.current_champion_name = None
                            user_interface.current_champion_id = None
                        _loop_state['swiftplay_ui_hidden'] = True
                        log.debug("[MAIN] Hiding UI - no skin detected in Swiftplay mode (reset skin state)")
                except Exception as e:
                    log.debug(f"[MAIN] Error hiding UI: {e}")
        else:
            # Reset the hidden flag if we have extracted mods (overlay might be building)
            _loop_state['swiftplay_ui_hidden'] = False
    
    if current_skin_id:
        # Check if we need to reset skin notification debouncing
        if state.reset_skin_notification:
            _loop_state.pop('last_notified_skin_id', None)
            state.reset_skin_notification = False
            log.debug("[MAIN] Reset skin notification debouncing for new ChampSelect")
        
        # Check if this is a new skin (debouncing at main loop level)
        last_notified = _loop_state.get('last_notified_skin_id')
        should_notify = (last_notified is None or last_notified != current_skin_id)
        
        if should_notify:
            # Notify UserInterface of the skin change
            try:
                # Get the user interface that was already initialized
                from ui.core.user_interface import get_user_interface
                user_interface = get_user_interface(state, skin_scraper)
                if user_interface.is_ui_initialized():
                    # Use the correct champion_id (either from Swiftplay or regular mode)
                    champ_id_for_ui = champion_id if state.is_swiftplay_mode else state.locked_champ_id
                    user_interface.show_skin(current_skin_id, current_skin_name or f"Skin {current_skin_id}", champion_name, champ_id_for_ui)
                    log.info(f"[MAIN] Notified UI of skin change: {current_skin_id} - '{current_skin_name}'")
                    # Track the last notified skin
                    _loop_state['last_notified_skin_id'] = current_skin_id
                    # Reset hide flag since we're showing a skin
                    _loop_state.pop('swiftplay_ui_hidden', None)
                    log.debug("[MAIN] Reset UI hide flag - skin detected")
                else:
                    # Only log once per skin to avoid spam
                    if _loop_state.get('ui_not_initialized_logged') != current_skin_id:
                        log.debug(f"[MAIN] UI not initialized yet - skipping skin notification for {current_skin_id}")
                        _loop_state['ui_not_initialized_logged'] = current_skin_id
            except Exception as e:
                log.error(f"[MAIN] Failed to notify UI: {e}")
    
    # Process pending UI initialization and requests
    from ui.core.user_interface import get_user_interface
    user_interface = get_user_interface(state, skin_scraper)
    
    # Process pending UI operations first (must be done in main thread)
    if user_interface.has_pending_operations():
        log.debug("[MAIN] Processing pending UI operations")
    user_interface.process_pending_operations()
    
    # Handle champion exchange - hide UI elements (must be done in main thread)
    if state.champion_exchange_triggered:
        try:
            state.champion_exchange_triggered = False  # Reset flag
            if user_interface.is_ui_initialized():
                log.info("[MAIN] Champion exchange detected - hiding UI elements")
                
                # Chroma button is handled by JavaScript plugin - no need to hide Python button
        except Exception as e:
            log.error(f"[MAIN] Failed to hide UI during champion exchange: {e}")
    
    if user_interface.is_ui_initialized() and user_interface.chroma_ui and user_interface.chroma_ui.chroma_selector and user_interface.chroma_ui.chroma_selector.panel:
        chroma_start = time.time()
        user_interface.chroma_ui.chroma_selector.panel.process_pending()
        # Update positions to follow League window
        user_interface.chroma_ui.chroma_selector.panel.update_positions()
        chroma_elapsed = time.time() - chroma_start
        if chroma_elapsed > CHROMA_PANEL_PROCESSING_THRESHOLD_S:
            log.warning(f"[WATCHDOG] Chroma panel processing took {chroma_elapsed:.2f}s")
    
    # Check for resolution changes and update UI components
    if user_interface.is_ui_initialized():
        user_interface.check_resolution_and_update()

