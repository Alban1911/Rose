#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Loadout countdown ticker thread
"""

import time
import threading
from lcu.client import LCU
from state.shared_state import SharedState
# NameDB no longer needed - LCU provides all data
from utils.logging import get_logger, log_action
# Note: normalize_text removed - using simple normalization instead
from config import (
    TIMER_HZ_MIN, TIMER_HZ_MAX, TIMER_POLL_PERIOD_S,
    SKIN_THRESHOLD_MS_DEFAULT,
    BASE_SKIN_VERIFICATION_WAIT_S,
    LOG_SEPARATOR_WIDTH
)

log = get_logger()


class LoadoutTicker(threading.Thread):
    """High-frequency loadout countdown ticker"""
    
    def __init__(self, lcu: LCU, state: SharedState, hz: int, fallback_ms: int, 
                 ticker_id: int, mode: str = "auto", injection_manager=None, skin_scraper=None):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.state = state
        self.hz = max(TIMER_HZ_MIN, min(TIMER_HZ_MAX, int(hz)))
        self.fallback_ms = max(0, int(fallback_ms))
        self.ticker_id = int(ticker_id)
        self.mode = mode
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper

    def run(self):
        """Main ticker loop"""
        # Exit immediately if another ticker has taken control
        if getattr(self.state, 'current_ticker', 0) != self.ticker_id:
            return
        
        # Local variables to avoid cross-resets if multiple tickers existed accidentally
        left0_ms = self.state.loadout_left0_ms
        t0 = self.state.loadout_t0
        # Absolute deadline in monotonic time (strict, non-increasing)
        deadline = t0 + (left0_ms / 1000.0)
        prev_remain_ms = 10**9
        poll_period_s = TIMER_POLL_PERIOD_S
        last_poll = 0.0
        last_bucket = None
        
        # Continue loop if injection is not completed yet (even if phase changed to GameStart/InProgress)
        while (not self.state.stop) and (self.state.phase in ["ChampSelect", "FINALIZATION", "GameStart", "InProgress"]) and self.state.loadout_countdown_active and (self.state.current_ticker == self.ticker_id) and not self.state.injection_completed:
            now = time.monotonic()
            
            # Periodic LCU resync
            if (now - last_poll) >= poll_period_s:
                last_poll = now
                sess = self.lcu.session or {}
                t = (sess.get("timer") or {})
                phase = str((t.get("phase") or "")).upper()
                left_ms = int(t.get("adjustedTimeLeftInPhase") or 0)
                
                # Check if phase changed to FINALIZATION and trigger phase handler
                if phase == "FINALIZATION" and self.state.phase != "FINALIZATION":
                    log.info(f"[loadout] Phase transition detected: {self.state.phase} → FINALIZATION")
                    self.state.phase = "FINALIZATION"
                    
                    # Trigger FINALIZATION phase handler in main thread
                    try:
                        from ui.user_interface import get_user_interface
                        user_interface = get_user_interface(self.state, self.skin_scraper)
                        # Defer to main thread to avoid PyQt6 thread issues
                        user_interface._pending_click_catcher_creation = True
                        log.info("[loadout] ClickCatcherHide creation deferred to main thread for FINALIZATION")
                    except Exception as e:
                        log.warning(f"[loadout] Failed to defer ClickCatcherHide creation for FINALIZATION: {e}")
                
                if phase == "FINALIZATION" and left_ms > 0:
                    cand_deadline = time.monotonic() + (left_ms / 1000.0)
                    if cand_deadline < deadline:
                        deadline = cand_deadline
            
            # Local countdown
            remain_ms = int((deadline - time.monotonic()) * 1000.0)
            if remain_ms < 0:
                remain_ms = 0
            
            # Anti-jitter clamp: never go up
            if remain_ms > prev_remain_ms:
                remain_ms = prev_remain_ms
            prev_remain_ms = remain_ms
            
            # Store remaining time in shared state for UI detection thread
            self.state.last_remain_ms = remain_ms
            
            bucket = remain_ms // 1000
            if bucket != last_bucket:
                last_bucket = bucket
                seconds_remaining = int(remain_ms // 1000)
                log.info(f"[loadout #{self.ticker_id}] T-{seconds_remaining}s")
                
                # Notify injection manager of countdown (for starting persistent game monitor at T-1)
                if self.injection_manager:
                    try:
                        self.injection_manager.on_loadout_countdown(seconds_remaining)
                    except Exception as e:
                        log.debug(f"[loadout] countdown notification failed: {e}")
            
            # Write last hovered skin at T<=threshold (configurable)
            thresh = int(getattr(self.state, 'skin_write_ms', SKIN_THRESHOLD_MS_DEFAULT) or SKIN_THRESHOLD_MS_DEFAULT)
            if remain_ms <= thresh and not self.state.last_hover_written:
                raw = self.state.last_hovered_skin_key or self.state.last_hovered_skin_slug \
                    or (str(self.state.last_hovered_skin_id) if self.state.last_hovered_skin_id else None)
                
                # Build clean label: "<Skin> <Champion>" without duplication or inversion
                final_label = None
                try:
                    champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                    # Get champion name from LCU skin scraper cache
                    cname = ""
                    if champ_id and self.skin_scraper and self.skin_scraper.cache.is_loaded_for_champion(champ_id):
                        cname = self.skin_scraper.cache.champion_name or ""

                    # 1) Base: get skin name from LCU → ex: "Blood Lord"
                    base = ""
                    if self.state.last_hovered_skin_id and self.skin_scraper and self.skin_scraper.cache.is_loaded_for_champion(champ_id):
                        skin_data = self.skin_scraper.cache.get_skin_by_id(self.state.last_hovered_skin_id)
                        if skin_data:
                            base = skin_data.get('skinName', '').strip()
                    
                    if not base:
                        base = (raw or "").strip()

                    # Normalize spaces and apostrophes (NBSP etc.)
                    base_clean = base.replace(" ", " ").replace("'", "'")
                    c_clean = (cname or "").replace(" ", " ").replace("'", "'")

                    # 2) If label starts with champion (ex: "Vladimir Blood Lord"), remove prefix
                    if c_clean and base_clean.lower().startswith(c_clean.lower() + " "):
                        base_clean = base_clean[len(c_clean) + 1:].lstrip()
                    # 3) If label ends with champion (rare), remove suffix
                    elif c_clean and base_clean.lower().endswith(" " + c_clean.lower()):
                        base_clean = base_clean[:-(len(c_clean) + 1)].rstrip()

                    # 4) If champion name is already included in the middle (ex: "K/DA ALL OUT Seraphine Indie"), don't add it
                    nb = base_clean.lower().strip() if base_clean else ""
                    nc = c_clean.lower().strip() if c_clean else ""
                    if nc and (nc in nb.split()):
                        final_label = base_clean
                    else:
                        final_label = (base_clean + (" " + c_clean if c_clean else "")).strip()
                except Exception:
                    final_label = raw or ""

                # Check if random mode is active
                random_mode_active = getattr(self.state, 'random_mode_active', False)
                random_skin_name = getattr(self.state, 'random_skin_name', None)
                log.debug(f"[inject] Random mode check: active={random_mode_active}, name={random_skin_name}")
                
                if random_mode_active and random_skin_name:
                    random_skin_id = getattr(self.state, 'random_skin_id', None)
                    # For random mode, use ID-based approach instead of name
                    if random_skin_id:
                        # Check if this is a chroma or base skin
                        if self.skin_scraper and self.skin_scraper.cache and random_skin_id in self.skin_scraper.cache.chroma_id_map:
                            # This is a chroma - use the chroma ID directly
                            name = f"chroma_{random_skin_id}"
                            log.info(f"[RANDOM] Injecting random chroma: {random_skin_name} (ID: {random_skin_id})")
                        else:
                            # This is a base skin - use the skin ID directly
                            name = f"skin_{random_skin_id}"
                            log.info(f"[RANDOM] Injecting random skin: {random_skin_name} (ID: {random_skin_id})")
                    else:
                        # No random skin ID available - this is an error condition
                        log.error(f"[RANDOM] No random skin ID available for injection - this should not happen")
                        log.error(f"[RANDOM] State: random_skin_id={getattr(self.state, 'random_skin_id', None)}")
                        log.error(f"[RANDOM] State: random_skin_name={getattr(self.state, 'random_skin_name', None)}")
                        name = None
                else:
                    # For injection, we MUST use skin ID - no fallbacks allowed
                    skin_id = getattr(self.state, 'last_hovered_skin_id', None)
                    if skin_id:
                        # Use utility functions to determine if this is a base skin or chroma
                        chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
                        from utils.utilities import is_base_skin, get_base_skin_id_for_chroma
                        
                        if is_base_skin(skin_id, chroma_id_map):
                            # This is a base skin - use the skin ID directly
                            name = f"skin_{skin_id}"
                            log.debug(f"[inject] Using base skin ID from state: '{name}' (ID: {skin_id})")
                        else:
                            # This is a chroma - use the chroma ID directly with chroma_ prefix
                            name = f"chroma_{skin_id}"
                            log.debug(f"[inject] Using chroma ID from state: '{name}' (chroma: {skin_id})")
                    else:
                        # No skin ID available - this is an error condition
                        log.error(f"[inject] No skin ID available for injection - this should not happen")
                        log.error(f"[inject] State: last_hovered_skin_id={getattr(self.state, 'last_hovered_skin_id', None)}")
                        log.error(f"[inject] State: last_hovered_skin_key={getattr(self.state, 'last_hovered_skin_key', None)}")
                        name = None
                
                log.debug(f"[inject] Final name variable: '{name}'")
                
                if name:
                    # Mark that we've processed the last hovered skin for injection
                    self.state.last_hover_written = True
                    log.info("=" * LOG_SEPARATOR_WIDTH)
                    log.info(f"💉 PREPARING INJECTION >>> {name.upper()} <<<")
                    log.info(f"   ⏱️  Loadout Timer: #{self.ticker_id}")
                    log.info("=" * LOG_SEPARATOR_WIDTH)
                    
                    try:
                        # Smart injection logic: only inject if user doesn't own the hovered skin
                        ui_skin_id = self.state.last_hovered_skin_id
                        lcu_skin_id = self.state.selected_skin_id
                        owned_skin_ids = self.state.owned_skin_ids
                        
                        # Skip injection for base skins
                        if ui_skin_id == 0:
                            log.info(f"[inject] skipping base skin injection (skinId=0)")
                            # Resume game if persistent monitor suspended it
                            if self.injection_manager:
                                try:
                                    self.injection_manager.resume_if_suspended()
                                except Exception as e:
                                    log.warning(f"[inject] Failed to resume game after skipping base skin: {e}")
                        # Force owned skins/chromas instead of injecting (since owned, we can select them normally)
                        elif ui_skin_id in owned_skin_ids:
                            log.info(f"[inject] User owns this skin/chroma (skinId={ui_skin_id}), forcing selection via LCU")
                            
                            # Force the owned skin/chroma using LCU API (same mechanism as base skin forcing)
                            champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                            if champ_id and self.lcu:
                                target_skin_id = ui_skin_id
                                log.info(f"[inject] Forcing owned skin/chroma (skinId={target_skin_id})")
                                
                                forced_successfully = False
                                
                                # Find the user's action ID to update
                                try:
                                    sess = self.lcu.session or {}  # session is a property, not a method!
                                    actions = sess.get("actions") or []
                                    my_cell = self.state.local_cell_id
                                    
                                    action_found = False
                                    is_action_completed = False
                                    
                                    for rnd in actions:
                                        for act in rnd:
                                            if act.get("actorCellId") == my_cell and act.get("type") == "pick":
                                                action_id = act.get("id")
                                                is_action_completed = act.get("completed", False)
                                                action_found = True
                                                
                                                # Try action-based approach first if not completed
                                                if not is_action_completed:
                                                    if action_id is not None:
                                                        if self.lcu.set_selected_skin(action_id, target_skin_id):
                                                            log.info(f"[inject] ✓ Owned skin/chroma forced via action")
                                                            forced_successfully = True
                                                        else:
                                                            log.debug(f"[inject] Action-based approach failed")
                                                break
                                        if action_found:
                                            break
                                    
                                    # If action-based approach failed, try my-selection endpoint
                                    if not forced_successfully:
                                        if self.lcu.set_my_selection_skin(target_skin_id):
                                            log.info(f"[inject] ✓ Owned skin/chroma forced via my-selection")
                                            forced_successfully = True
                                        else:
                                            log.warning(f"[inject] ✗ Failed to force owned skin/chroma")
                                    
                                    # Verify the change was applied
                                    if forced_successfully:
                                        # Skip verification wait in random mode for faster injection
                                        if not getattr(self.state, 'random_mode_active', False):
                                            time.sleep(BASE_SKIN_VERIFICATION_WAIT_S)
                                            verify_sess = self.lcu.session or {}  # session is a property, not a method!
                                            verify_team = verify_sess.get("myTeam") or []
                                            for player in verify_team:
                                                if player.get("cellId") == my_cell:
                                                    current_skin = player.get("selectedSkinId")
                                                    if current_skin == target_skin_id:
                                                        log.info(f"[inject] ✓ Owned skin/chroma verified: {current_skin}")
                                                    else:
                                                        log.warning(f"[inject] Verification failed: {current_skin} != {target_skin_id}")
                                                    break
                                        else:
                                            log.info(f"[inject] Skipping verification wait in random mode")
                                    
                                except Exception as e:
                                    log.warning(f"[inject] Error forcing owned skin/chroma: {e}")
                            
                            # Resume game if persistent monitor suspended it
                            if self.injection_manager:
                                try:
                                    self.injection_manager.resume_if_suspended()
                                except Exception as e:
                                    log.warning(f"[inject] Failed to resume game after forcing owned skin: {e}")
                        # Inject if user doesn't own the hovered skin
                        elif self.injection_manager:
                            try:
                                # Note: Chroma selection is now handled via the name format (chroma_ prefix)
                                # No need for separate chroma_id parameter
                                
                                # Force base skin selection via LCU before injecting
                                # This ensures LCU has the correct state for injection to work properly
                                champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                                if champ_id:
                                    base_skin_id = champ_id * 1000
                                    
                                    # Read the ACTUAL current selection from LCU session (not state variable)
                                    # This handles cases where user selected an owned skin then hovered over an unowned skin
                                    actual_lcu_skin_id = None
                                    try:
                                        sess = self.lcu.session or {}
                                        my_team = sess.get("myTeam") or []
                                        my_cell = self.state.local_cell_id
                                        for player in my_team:
                                            if player.get("cellId") == my_cell:
                                                actual_lcu_skin_id = player.get("selectedSkinId")
                                                if actual_lcu_skin_id is not None:
                                                    actual_lcu_skin_id = int(actual_lcu_skin_id)
                                                break
                                    except Exception as e:
                                        log.debug(f"[inject] Failed to read actual LCU skin ID: {e}")
                                    
                                    # Only force base skin if current ACTUAL selection is not already base skin
                                    if actual_lcu_skin_id is None or actual_lcu_skin_id != base_skin_id:
                                        log.info(f"[inject] Forcing base skin (skinId={base_skin_id}, was {actual_lcu_skin_id})")
                                        
                                        # Hide chroma border/wheel immediately when forcing base skin
                                        log.debug(f"[inject] About to hide UI components")
                                        try:
                                            log.debug(f"[inject] Importing user_interface")
                                            from ui.user_interface import get_user_interface
                                            log.debug(f"[inject] Getting user interface instance")
                                            user_interface = get_user_interface(self.state, self.skin_scraper)
                                            log.debug(f"[inject] Checking if UI is initialized: {user_interface.is_ui_initialized()}")
                                            if user_interface.is_ui_initialized():
                                                log.debug(f"[inject] Scheduling hide_all() on main thread")
                                                # Schedule UI hiding on main thread to avoid PyQt6 thread issues
                                                user_interface._schedule_hide_all_on_main_thread()
                                                log.debug(f"[inject] hide_all() scheduled")
                                                
                                                log.info("[inject] UI hiding scheduled - base skin forced for injection")
                                            else:
                                                log.debug(f"[inject] UI not initialized, skipping hide")
                                        except Exception as e:
                                            log.warning(f"[inject] Failed to schedule UI hide: {e}")
                                            import traceback
                                            log.warning(f"[inject] UI hide traceback: {traceback.format_exc()}")
                                        
                                        log.debug(f"[inject] UI hiding block completed")
                                        
                                        base_skin_set_successfully = False
                                        
                                        log.debug(f"[inject] Starting base skin forcing process")
                                        log.debug(f"[inject] LCU ok: {self.lcu.ok}, phase: {self.state.phase}")
                                        # Find the user's action ID to update
                                        try:
                                            sess = self.lcu.session or {}  # session is a property, not a method!
                                            log.debug(f"[inject] Got LCU session, actions: {sess.get('actions')}")
                                            actions = sess.get("actions") or []
                                            my_cell = self.state.local_cell_id
                                            
                                            action_found = False
                                            is_action_completed = False
                                            
                                            for rnd in actions:
                                                for act in rnd:
                                                    if act.get("actorCellId") == my_cell and act.get("type") == "pick":
                                                        action_id = act.get("id")
                                                        is_action_completed = act.get("completed", False)
                                                        action_found = True
                                                        
                                                        # Try action-based approach first if not completed
                                                        if not is_action_completed:
                                                            if action_id is not None:
                                                                if self.lcu.set_selected_skin(action_id, base_skin_id):
                                                                    log.info(f"[inject] ✓ Base skin forced via action")
                                                                    base_skin_set_successfully = True
                                                                else:
                                                                    log.debug(f"[inject] Action-based approach failed")
                                                        break
                                                if action_found:
                                                    break
                                            
                                            # If action-based approach failed, try my-selection endpoint
                                            if not base_skin_set_successfully:
                                                if self.lcu.set_my_selection_skin(base_skin_id):
                                                    log.info(f"[inject] ✓ Base skin forced via my-selection")
                                                    base_skin_set_successfully = True
                                                else:
                                                    log.warning(f"[inject] ✗ Failed to force base skin")
                                            
                                            # Verify the change was applied
                                            if base_skin_set_successfully:
                                                # Skip verification wait in random mode for faster injection
                                                if not getattr(self.state, 'random_mode_active', False):
                                                    time.sleep(BASE_SKIN_VERIFICATION_WAIT_S)
                                                    verify_sess = self.lcu.session or {}  # session is a property, not a method!
                                                    verify_team = verify_sess.get("myTeam") or []
                                                    for player in verify_team:
                                                        if player.get("cellId") == my_cell:
                                                            current_skin = player.get("selectedSkinId")
                                                            if current_skin != base_skin_id:
                                                                log.warning(f"[inject] Base skin verification failed: {current_skin} != {base_skin_id}")
                                                            else:
                                                                log.info(f"[inject] ✓ Base skin verified: {current_skin}")
                                                            break
                                                else:
                                                    log.info(f"[inject] Skipping base skin verification wait in random mode")
                                            else:
                                                log.warning(f"[inject] Failed to force base skin - injection may fail")
                                                
                                        except Exception as e:
                                            log.error(f"[inject] ✗ Error forcing base skin: {e}")
                                            import traceback
                                            log.error(f"[inject] Traceback: {traceback.format_exc()}")
                                
                                log.debug(f"[inject] Base skin forcing block completed, continuing to injection")
                                # Track if we've been in InProgress phase
                                has_been_in_progress = False
                                
                                # Create callback to check if game ended
                                def game_ended_callback():
                                    nonlocal has_been_in_progress
                                    if self.state.phase == "InProgress":
                                        has_been_in_progress = True
                                    # Only stop after we've been in InProgress and then left it
                                    return has_been_in_progress and self.state.phase != "InProgress"
                                
                                # Inject skin in a separate thread to avoid blocking the ticker
                                log.info(f"[inject] Starting injection: {name}")
                                
                                def run_injection():
                                    try:
                                        # Check if LCU is still valid before starting injection
                                        if not self.lcu.ok:
                                            log.warning(f"[inject] LCU not available, skipping injection")
                                            return
                                        
                                        success = self.injection_manager.inject_skin_immediately(
                                            name, 
                                            stop_callback=game_ended_callback,
                                            champion_name=cname,
                                            champion_id=self.state.locked_champ_id
                                        )
                                        
                                        # Set flag to prevent UI detection from restarting (even if processes errored)
                                        self.state.injection_completed = True
                                        
                                        # Clear random state after injection
                                        if getattr(self.state, 'random_mode_active', False):
                                            self.state.random_skin_name = None
                                            self.state.random_skin_id = None
                                            self.state.random_mode_active = False
                                            log.info("[RANDOM] Random mode cleared after injection")
                                        
                                        if success:
                                            log.info("=" * LOG_SEPARATOR_WIDTH)
                                            log.info(f"✅ INJECTION COMPLETED >>> {name.upper()} <<<")
                                            log.info(f"   ⚠️  Verify in-game - timing determines if skin appears")
                                            log.info("=" * LOG_SEPARATOR_WIDTH)
                                        else:
                                            log.error("=" * LOG_SEPARATOR_WIDTH)
                                            log.error(f"❌ INJECTION FAILED >>> {name.upper()} <<<")
                                            log.error("=" * LOG_SEPARATOR_WIDTH)
                                            log.error(f"[inject] Skin will likely NOT appear in-game")
                                        
                                        # Request UI destruction after injection completes
                                        try:
                                            from ui.user_interface import get_user_interface
                                            user_interface = get_user_interface(self.state, self.skin_scraper)
                                            user_interface.request_ui_destruction()
                                            log_action(log, "UI destruction requested after injection completion", "🧹")
                                        except Exception as e:
                                            log.warning(f"[inject] Failed to request UI destruction after injection: {e}")
                                    except Exception as e:
                                        log.error(f"[inject] injection thread error: {e}")
                                        self.state.injection_completed = True  # Set flag even on error
                                
                                injection_thread = threading.Thread(target=run_injection, daemon=True, name="InjectionThread")
                                injection_thread.start()
                                
                                # Set a timeout to prevent hanging if injection takes too long
                                def timeout_injection():
                                    time.sleep(10)  # 10 second timeout
                                    if injection_thread.is_alive():
                                        log.warning(f"[inject] Injection thread timeout - forcing completion")
                                        self.state.injection_completed = True
                                
                                timeout_thread = threading.Thread(target=timeout_injection, daemon=True, name="InjectionTimeout")
                                timeout_thread.start()
                            except Exception as e:
                                log.error(f"[inject] injection error: {e}")
                        else:
                            log.warning(f"[inject] no injection manager available")
                    except Exception as e:
                        log.warning(f"[loadout #{self.ticker_id}] injection setup failed: {e}")
                else:
                    # No skin ID available - injection cannot proceed
                    log.error("=" * LOG_SEPARATOR_WIDTH)
                    log.error(f"❌ INJECTION FAILED - NO SKIN ID AVAILABLE")
                    log.error(f"   ⏱️  Loadout Timer: #{self.ticker_id}")
                    log.error("=" * LOG_SEPARATOR_WIDTH)
                    # Mark injection as completed to prevent retries
                    self.state.injection_completed = True

            if remain_ms <= 0:
                break
            time.sleep(1.0 / float(self.hz))
        
        # End of ticker: only release if we're still the current ticker
        if getattr(self.state, 'current_ticker', 0) == self.ticker_id:
            self.state.loadout_countdown_active = False
