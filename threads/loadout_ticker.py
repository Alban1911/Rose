#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Loadout countdown ticker thread
"""

import time
import threading
from typing import Optional
from lcu.client import LCU
from state.shared_state import SharedState
from database.name_db import NameDB
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
                 ticker_id: int, mode: str = "auto", db: Optional[NameDB] = None, 
                 injection_manager=None, skin_scraper=None):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.state = state
        self.hz = max(TIMER_HZ_MIN, min(TIMER_HZ_MAX, int(hz)))
        self.fallback_ms = max(0, int(fallback_ms))
        self.ticker_id = int(ticker_id)
        self.mode = mode
        self.db = db
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
        
        while (not self.state.stop) and (self.state.phase == "ChampSelect") and self.state.loadout_countdown_active and (self.state.current_ticker == self.ticker_id):
            now = time.monotonic()
            
            # Periodic LCU resync
            if (now - last_poll) >= poll_period_s:
                last_poll = now
                sess = self.lcu.session or {}
                t = (sess.get("timer") or {})
                phase = str((t.get("phase") or "")).upper()
                left_ms = int(t.get("adjustedTimeLeftInPhase") or 0)
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
                    cname = self.db.champ_name_by_id.get(champ_id or -1, "").strip() if self.db else ""

                    # 1) Base: prefer skin ID (Data Dragon) → ex: "Blood Lord"
                    if self.state.last_hovered_skin_id and self.db and self.state.last_hovered_skin_id in self.db.skin_name_by_id:
                        base = self.db.skin_name_by_id[self.state.last_hovered_skin_id].strip()
                    else:
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
                    name = random_skin_name
                    random_skin_id = getattr(self.state, 'random_skin_id', None)
                    log.info(f"[RANDOM] Injecting random skin: {name} (ID: {random_skin_id})")
                else:
                    # For injection, we need the English name from the database
                    # Use the English skin name that was already processed by UI detection thread
                    injection_name = getattr(self.state, 'last_hovered_skin_key', None)
                    name = final_label if final_label else None
                    if injection_name:
                        name = injection_name
                        log.debug(f"[inject] Using English name from database: '{name}'")
                    else:
                        # Fallback to UI detected text if no English name available
                        name = getattr(self.state, 'ui_last_text', None) or name
                        log.warning(f"[inject] No English name found, using localized: '{name}'")
                    if name:
                        # If UI detected text is like "Champion X Champion", normalize to "X Champion"
                        try:
                            champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                            cname = (self.db.champ_name_by_id.get(champ_id or -1, "") or "").strip() if self.db else ""
                            if cname:
                                low = name.strip()
                                if low.lower().startswith(cname.lower() + " ") and low.lower().endswith(" " + cname.lower()):
                                    core = low[len(cname) + 1:-(len(cname) + 1)].strip()
                                    if core:
                                        name = f"{core} {cname}".strip()
                        except Exception:
                            pass
                
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
                                # Get selected chroma ID from state (already selected via wheel shown by UI detection)
                                # For random mode, use the random skin ID instead
                                if getattr(self.state, 'random_mode_active', False) and getattr(self.state, 'random_skin_id', None):
                                    random_skin_id = self.state.random_skin_id
                                    # Check if the random skin ID is actually a chroma
                                    if self.skin_scraper and self.skin_scraper.cache and random_skin_id in self.skin_scraper.cache.chroma_id_map:
                                        selected_chroma_id = random_skin_id
                                        log.info(f"[RANDOM] Using random chroma ID: {selected_chroma_id}")
                                    else:
                                        selected_chroma_id = None
                                        log.info(f"[RANDOM] Using random base skin ID: {random_skin_id}")
                                else:
                                    selected_chroma_id = self.state.selected_chroma_id
                                    if selected_chroma_id:
                                        log.info(f"[inject] Using selected chroma ID: {selected_chroma_id}")
                                    else:
                                        log.debug(f"[inject] No chroma selected, using base skin")
                                
                                # Force base skin selection via LCU before injecting
                                # This ensures LCU has the correct state for injection to work properly
                                champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                                if champ_id:
                                    base_skin_id = champ_id * 1000
                                    
                                    # Only force base skin if current selection is not already base skin
                                    if lcu_skin_id is None or lcu_skin_id != base_skin_id:
                                        log.info(f"[inject] Forcing base skin (skinId={base_skin_id}, was {lcu_skin_id})")
                                        
                                        # Hide chroma border/wheel immediately when forcing base skin
                                        try:
                                            from ui.user_interface import get_user_interface
                                            user_interface = get_user_interface(self.state, self.skin_scraper, self.db)
                                            if user_interface.is_ui_initialized():
                                                # Hide all UI components
                                                user_interface.hide_all()
                                                
                                                log.info("[inject] UI hidden - base skin forced for injection")
                                        except Exception as e:
                                            log.debug(f"[inject] Failed to hide chroma UI: {e}")
                                        
                                        base_skin_set_successfully = False
                                        
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
                                        success = self.injection_manager.inject_skin_immediately(
                                            name, 
                                            stop_callback=game_ended_callback,
                                            chroma_id=selected_chroma_id,
                                            champion_name=cname
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
                                            user_interface = get_user_interface(self.state, self.skin_scraper, self.db)
                                            user_interface.request_ui_destruction()
                                            log_action(log, "UI destruction requested after injection completion", "🧹")
                                        except Exception as e:
                                            log.warning(f"[inject] Failed to request UI destruction after injection: {e}")
                                    except Exception as e:
                                        log.error(f"[inject] injection thread error: {e}")
                                        self.state.injection_completed = True  # Set flag even on error
                                
                                injection_thread = threading.Thread(target=run_injection, daemon=True, name="InjectionThread")
                                injection_thread.start()
                            except Exception as e:
                                log.error(f"[inject] injection error: {e}")
                        else:
                            log.warning(f"[inject] no injection manager available")
                    except Exception as e:
                        log.warning(f"[loadout #{self.ticker_id}] injection setup failed: {e}")

            if remain_ms <= 0:
                break
            time.sleep(1.0 / float(self.hz))
        
        # End of ticker: only release if we're still the current ticker
        if getattr(self.state, 'current_ticker', 0) == self.ticker_id:
            self.state.loadout_countdown_active = False
