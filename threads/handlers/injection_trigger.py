#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Injection Trigger
Handles triggering skin injection based on countdown timer
"""

import logging
import threading
import time
from typing import Optional

from config import BASE_SKIN_VERIFICATION_WAIT_S, LOG_SEPARATOR_WIDTH
from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger, log_action

log = get_logger()


class InjectionTrigger:
    """Handles triggering skin injection"""
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        injection_manager=None,
        skin_scraper=None,
    ):
        """Initialize injection trigger
        
        Args:
            lcu: LCU client instance
            state: Shared application state
            injection_manager: Injection manager instance
            skin_scraper: Skin scraper instance
        """
        self.lcu = lcu
        self.state = state
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
    
    def trigger_injection(self, name: str, ticker_id: int, cname: str = ""):
        """Trigger injection for a skin/chroma
        
        Args:
            name: Injection name (e.g., "skin_1234" or "chroma_5678")
            ticker_id: Ticker ID for logging
            cname: Champion name (optional)
        """
        if not name:
            log.error("=" * LOG_SEPARATOR_WIDTH)
            log.error(f"❌ INJECTION FAILED - NO SKIN ID AVAILABLE")
            log.error(f"   ⏱️  Loadout Timer: #{ticker_id}")
            log.error("=" * LOG_SEPARATOR_WIDTH)
            return
        
        # Mark that we've processed the last hovered skin
        self.state.last_hover_written = True
        log.info("=" * LOG_SEPARATOR_WIDTH)
        log.info(f"💉 PREPARING INJECTION >>> {name.upper()} <<<")
        log.info(f"   ⏱️  Loadout Timer: #{ticker_id}")
        log.info("=" * LOG_SEPARATOR_WIDTH)
        
        try:
            ui_skin_id = self.state.last_hovered_skin_id
            lcu_skin_id = self.state.selected_skin_id
            owned_skin_ids = self.state.owned_skin_ids
            
            # Check if custom mod is selected for this skin
            selected_custom_mod = getattr(self.state, 'selected_custom_mod', None)
            if selected_custom_mod and selected_custom_mod.get("skin_id") == ui_skin_id:
                # Inject custom mod instead of normal skin
                log.info(f"[INJECT] Custom mod selected for skin {ui_skin_id}, injecting custom mod instead")
                self._inject_custom_mod(selected_custom_mod)
                return
            
            # Skip injection for base skins
            if ui_skin_id == 0:
                log.info("[INJECT] skipping base skin injection (skinId=0) - no mods-only flow available")
                if self.injection_manager:
                    self.injection_manager.resume_if_suspended()
            
            # Force owned skins/chromas via LCU
            elif ui_skin_id in owned_skin_ids:
                self._force_owned_skin(ui_skin_id)
            
            # Inject if user doesn't own the hovered skin
            elif self.injection_manager:
                self._inject_unowned_skin(name, cname)
        
        except Exception as e:
            log.warning(f"[loadout #{ticker_id}] injection setup failed: {e}")
    
    def _force_owned_skin(self, skin_id: int):
        """Force owned skin/chroma selection via LCU"""
        log.info(f"[INJECT] User owns this skin/chroma (skinId={skin_id}), forcing selection via LCU")
        
        champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
        if champ_id and self.lcu:
            target_skin_id = skin_id
            log.info(f"[INJECT] Forcing owned skin/chroma (skinId={target_skin_id})")
            
            forced_successfully = False
            
            # Find the user's action ID to update
            try:
                sess = self.lcu.session or {}
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
                            
                            if not is_action_completed:
                                if action_id is not None:
                                    if self.lcu.set_selected_skin(action_id, target_skin_id):
                                        log.info(f"[INJECT] ✓ Owned skin/chroma forced via action")
                                        forced_successfully = True
                                    else:
                                        log.debug(f"[INJECT] Action-based approach failed")
                            break
                    if action_found:
                        break
                
                # Try my-selection endpoint if action-based failed
                if not forced_successfully:
                    if self.lcu.set_my_selection_skin(target_skin_id):
                        log.info(f"[INJECT] ✓ Owned skin/chroma forced via my-selection")
                        forced_successfully = True
                    else:
                        log.warning(f"[INJECT] ✗ Failed to force owned skin/chroma")
                
                # Verify the change
                if forced_successfully:
                    if not getattr(self.state, 'random_mode_active', False):
                        time.sleep(BASE_SKIN_VERIFICATION_WAIT_S)
                        verify_sess = self.lcu.session or {}
                        verify_team = verify_sess.get("myTeam") or []
                        for player in verify_team:
                            if player.get("cellId") == my_cell:
                                current_skin = player.get("selectedSkinId")
                                if current_skin == target_skin_id:
                                    log.info(f"[INJECT] ✓ Owned skin/chroma verified: {current_skin}")
                                else:
                                    log.warning(f"[INJECT] Verification failed: {current_skin} != {target_skin_id}")
                                break
                    else:
                        log.info(f"[INJECT] Skipping verification wait in random mode")
            
            except Exception as e:
                log.warning(f"[INJECT] Error forcing owned skin/chroma: {e}")
            
            # Resume game if suspended
            if self.injection_manager:
                try:
                    self.injection_manager.resume_if_suspended()
                except Exception as e:
                    log.warning(f"[INJECT] Failed to resume game after forcing owned skin: {e}")
    
    def _inject_unowned_skin(self, name: str, cname: str):
        """Inject unowned skin/chroma"""
        try:
            # Force base skin selection via LCU before injecting
            champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
            if champ_id:
                base_skin_id = champ_id * 1000
                
                # Read actual current selection from LCU session
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
                    log.debug(f"[INJECT] Failed to read actual LCU skin ID: {e}")
                
                # Only force base skin if current selection is not already base skin
                if actual_lcu_skin_id is None or actual_lcu_skin_id != base_skin_id:
                    self._force_base_skin(base_skin_id)
            
            # Create callback to check if game ended
            has_been_in_progress = False

            def game_ended_callback():
                nonlocal has_been_in_progress
                phase = self.state.phase
                if phase == "InProgress":
                    has_been_in_progress = True
                    return False
                if phase in ("Reconnect", "GameStart"):
                    return False
                return has_been_in_progress and phase not in ("InProgress", "Reconnect", "GameStart")
            
            # Inject skin in a separate thread
            log.info(f"[INJECT] Starting injection: {name}")
            
            champ_id_for_history = self.state.locked_champ_id

            def run_injection():
                try:
                    if not self.lcu.ok:
                        log.warning(f"[INJECT] LCU not available, skipping injection")
                        return
                    
                    success = self.injection_manager.inject_skin_immediately(
                        name,
                        stop_callback=game_ended_callback,
                        champion_name=cname,
                        champion_id=self.state.locked_champ_id
                    )
                    
                    # Clear random state after injection
                    if getattr(self.state, 'random_mode_active', False):
                        self.state.random_skin_name = None
                        self.state.random_skin_id = None
                        self.state.random_mode_active = False
                        log.info("[RANDOM] Random mode cleared after injection")
                    
                    if success:
                        # Persist historic entry
                        try:
                            injected_id = None
                            if isinstance(name, str) and '_' in name:
                                parts = name.split('_', 1)
                                if len(parts) == 2 and parts[1].isdigit():
                                    injected_id = int(parts[1])
                            champ_id = champ_id_for_history
                            if champ_id is not None and injected_id is not None:
                                from utils.core.historic import write_historic_entry
                                write_historic_entry(int(champ_id), int(injected_id))
                                log.info(f"[HISTORIC] Stored last injected ID {injected_id} for champion {champ_id}")
                        except Exception as e:
                            log.debug(f"[HISTORIC] Failed to store historic entry: {e}")
                        
                        log.info("=" * LOG_SEPARATOR_WIDTH)
                        log.info(f"✅ INJECTION COMPLETED >>> {name.upper()} <<<")
                        log.info(f"   ⚠️  Verify in-game - timing determines if skin appears")
                        log.info("=" * LOG_SEPARATOR_WIDTH)
                    else:
                        log.error("=" * LOG_SEPARATOR_WIDTH)
                        log.error(f"❌ INJECTION FAILED >>> {name.upper()} <<<")
                        log.error("=" * LOG_SEPARATOR_WIDTH)
                        log.error(f"[INJECT] Skin will likely NOT appear in-game")
                    
                    # Request UI destruction after injection
                    try:
                        from ui.core.user_interface import get_user_interface
                        user_interface = get_user_interface(self.state, self.skin_scraper)
                        user_interface.request_ui_destruction()
                        log_action(log, "UI destruction requested after injection completion", "🧹")
                    except Exception as e:
                        log.warning(f"[INJECT] Failed to request UI destruction after injection: {e}")
                except Exception as e:
                    log.error(f"[INJECT] injection thread error: {e}")
            
            injection_thread = threading.Thread(target=run_injection, daemon=True, name="InjectionThread")
            injection_thread.start()
        
        except Exception as e:
            log.error(f"[INJECT] injection error: {e}")
    
    def _force_base_skin(self, base_skin_id: int):
        """Force base skin selection via LCU"""
        log.info(f"[INJECT] Forcing base skin (skinId={base_skin_id})")
        
        # Hide chroma border/wheel immediately
        try:
            from ui.core.user_interface import get_user_interface
            user_interface = get_user_interface(self.state, self.skin_scraper)
            if user_interface.is_ui_initialized():
                user_interface._schedule_hide_all_on_main_thread()
                log.info("[INJECT] UI hiding scheduled - base skin forced for injection")
        except Exception as e:
            log.warning(f"[INJECT] Failed to schedule UI hide: {e}")
            import traceback
            log.warning(f"[INJECT] UI hide traceback: {traceback.format_exc()}")
        
        base_skin_set_successfully = False
        
        try:
            sess = self.lcu.session or {}
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
                        
                        if not is_action_completed:
                            if action_id is not None:
                                if self.lcu.set_selected_skin(action_id, base_skin_id):
                                    log.info(f"[INJECT] ✓ Base skin forced via action")
                                    base_skin_set_successfully = True
                                else:
                                    log.debug(f"[INJECT] Action-based approach failed")
                        break
                if action_found:
                    break
            
            # Try my-selection endpoint if action-based failed
            if not base_skin_set_successfully:
                if self.lcu.set_my_selection_skin(base_skin_id):
                    log.info(f"[INJECT] ✓ Base skin forced via my-selection")
                    base_skin_set_successfully = True
                else:
                    log.warning(f"[INJECT] ✗ Failed to force base skin")
            
            # Verify the change
            if base_skin_set_successfully:
                if not getattr(self.state, 'random_mode_active', False):
                    time.sleep(BASE_SKIN_VERIFICATION_WAIT_S)
                    verify_sess = self.lcu.session or {}
                    verify_team = verify_sess.get("myTeam") or []
                    for player in verify_team:
                        if player.get("cellId") == my_cell:
                            current_skin = player.get("selectedSkinId")
                            if current_skin != base_skin_id:
                                log.warning(f"[INJECT] Base skin verification failed: {current_skin} != {base_skin_id}")
                            else:
                                log.info(f"[INJECT] ✓ Base skin verified: {current_skin}")
                            break
                else:
                    log.info(f"[INJECT] Skipping base skin verification wait in random mode")
            else:
                log.warning(f"[INJECT] Failed to force base skin - injection may fail")
        
        except Exception as e:
            log.error(f"[INJECT] ✗ Error forcing base skin: {e}")
            import traceback
            log.error(f"[INJECT] Traceback: {traceback.format_exc()}")
    
    def _inject_custom_mod(self, custom_mod: dict):
        """Inject custom mod from mods storage (mod should already be extracted)"""
        try:
            from pathlib import Path
            
            if not self.injection_manager:
                log.error("[INJECT] Cannot inject custom mod - injection manager not available")
                return
            
            injector = self.injection_manager.injector
            if not injector:
                log.error("[INJECT] Cannot inject custom mod - injector not available")
                return
            
            mod_name = custom_mod.get("mod_name")
            mod_folder_name = custom_mod.get("mod_folder_name")
            skin_id = custom_mod.get("skin_id")
            
            if not mod_folder_name:
                log.error(f"[INJECT] Custom mod folder name not available")
                return
            
            # Verify mod folder exists (should already be extracted when selected)
            mod_folder = injector.mods_dir / mod_folder_name
            if not mod_folder.exists():
                log.error(f"[INJECT] Custom mod folder not found: {mod_folder}")
                log.error(f"[INJECT] Mod should have been extracted when selected")
                return
            
            log.info(f"[INJECT] Injecting custom mod: {mod_name} for skin {skin_id}")
            
            # Force base skin selection via LCU before injecting
            champion_id = self.state.locked_champ_id or self.state.hovered_champ_id
            if champion_id:
                base_skin_id = champion_id * 1000
                self._force_base_skin(base_skin_id)
            
            # Create callback to check if game ended
            has_been_in_progress = False

            def game_ended_callback():
                nonlocal has_been_in_progress
                phase = self.state.phase
                if phase == "InProgress":
                    has_been_in_progress = True
                    return False
                if phase in ("Reconnect", "GameStart"):
                    return False
                return has_been_in_progress and phase not in ("InProgress", "Reconnect", "GameStart")
            
            # Mod is already extracted, create and run overlay (same as normal injection)
            result = injector.overlay_manager.mk_run_overlay(
                [mod_folder_name],
                timeout=120,
                stop_callback=game_ended_callback,
                injection_manager=self.injection_manager
            )
            
            if result == 0:
                log.info("=" * LOG_SEPARATOR_WIDTH)
                log.info(f"✅ CUSTOM MOD INJECTION COMPLETED >>> {mod_name.upper()} <<<")
                log.info(f"   ⚠️  Verify in-game - timing determines if mod appears")
                log.info("=" * LOG_SEPARATOR_WIDTH)
                
                # Clear selected custom mod after successful injection
                self.state.selected_custom_mod = None
            else:
                log.error("=" * LOG_SEPARATOR_WIDTH)
                log.error(f"❌ CUSTOM MOD INJECTION FAILED >>> {mod_name.upper()} <<<")
                log.error("=" * LOG_SEPARATOR_WIDTH)
                log.error(f"[INJECT] Mod will likely NOT appear in-game")
        
        except Exception as e:
            log.error(f"[INJECT] ✗ Error injecting custom mod: {e}")
            import traceback
            log.error(f"[INJECT] Traceback: {traceback.format_exc()}")

