#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
User Interface Manager - Parent class for all UI components
Manages ChromaUI and UnownedFrame as separate components
"""

# Standard library imports
import threading
from typing import Optional

# Local imports
from ui.chroma_ui import ChromaUI
from utils.logging import get_logger
from utils.utilities import (
    is_owned, is_chroma_id, get_base_skin_id_for_chroma, 
    is_base_skin_owned, is_base_skin
)

log = get_logger()


class UserInterface:
    """Parent class managing all UI components"""
    
    def __init__(self, state, skin_scraper):
        self.state = state
        self.skin_scraper = skin_scraper
        self.lock = threading.Lock()
        
        # UI Components (will be initialized when entering ChampSelect)
        self.chroma_ui = None
        
        # Current skin tracking
        self.current_skin_id = None
        self.current_skin_name = None
        self.current_champion_name = None
        self.current_champion_id = None
        
        # Track UI element visibility state before hiding
        self._ui_visibility_state = {
            'chroma_ui_visible': False,
        }
        
        # Randomization state
        self._randomization_in_progress = False
        self._randomization_started = False  # Prevent multiple simultaneous randomizations
        
        # Pending initialization/destruction flags
        self._pending_ui_initialization = False
        self._pending_ui_destruction = False
        self._ui_destruction_in_progress = False
        self._last_destruction_time = 0.0
        self._force_reinitialize = False  # Flag to force UI recreation
        # Track last base skin shown (owned or unowned) to detect chroma swaps within same base
        self._last_base_skin_id = None
    
    def _check_and_activate_historic_mode(self, skin_id: int) -> None:
        """Check and activate historic mode if conditions are met"""
        if self.state.historic_first_detection_done or self.state.locked_champ_id is None:
            return
        
        # Check if current skin is the default skin (champion_id * 1000)
        base_skin_id = self.state.locked_champ_id * 1000
        if skin_id == base_skin_id:
            # Check if there's a historic entry for this champion
            try:
                from utils.historic import get_historic_skin_for_champion
                historic_skin_id = get_historic_skin_for_champion(self.state.locked_champ_id)
                
                if historic_skin_id is not None:
                    # Activate historic mode
                    self.state.historic_mode_active = True
                    self.state.historic_skin_id = historic_skin_id
                    log.info(f"[HISTORIC] Historic mode ACTIVATED for champion {self.state.locked_champ_id} (historic skin ID: {historic_skin_id})")
                    
                    # Broadcast state to JavaScript (will show JS plugin flag)
                    try:
                        if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                            self.state.ui_skin_thread._broadcast_historic_state()
                            log.debug("[HISTORIC] Broadcasted state to JavaScript")
                    except Exception as e:
                        log.debug(f"[UI] Failed to broadcast historic state on activation: {e}")
                else:
                    log.debug(f"[HISTORIC] No historic entry found for champion {self.state.locked_champ_id}")
            except Exception as e:
                log.debug(f"[HISTORIC] Failed to check historic entry: {e}")
        else:
            log.debug(f"[HISTORIC] First detected skin is not default (skin_id={skin_id}, base={base_skin_id}) - historic mode not activated")
        
        # Mark first detection as done AFTER processing (only activate on first detection)
        self.state.historic_first_detection_done = True
    
    def _initialize_components(self):
        """Initialize all UI components (must be called from main thread)"""
        try:
            log.info("[UI] Creating ChromaUI components...")
            # Initialize ChromaUI (chroma selector + panel)
            self.chroma_ui = ChromaUI(
                skin_scraper=self.skin_scraper,
                state=self.state
            )
            log.info("[UI] ChromaUI created successfully")

            # DiceButton is now handled by JavaScript (Rose-RandomSkin plugin)

        except Exception as e:
            log.error(f"[UI] Failed to initialize UI components: {e}")
            import traceback
            log.error(f"[UI] Traceback: {traceback.format_exc()}")
            # Clean up any partially created components
            if self.chroma_ui:
                try:
                    self.chroma_ui.cleanup()
                except Exception as e:
                    log.debug(f"[UI] Error cleaning up ChromaUI: {e}")
                self.chroma_ui = None
            raise
    
    def create_click_catchers(self):
        """Legacy method - no-op for compatibility."""
        pass
    def _try_show_click_blocker(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _show_click_blocker_on_main_thread(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _hide_click_blocker_with_delay(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def create_click_catchers_for_finalization(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def show_skin(self, skin_id: int, skin_name: str, champion_name: str = None, champion_id: int = None):
        """Show UI for a specific skin - manages both ChromaUI and UnownedFrame"""
        if not self.is_ui_initialized():
            log.debug("[UI] Cannot show skin - UI not initialized")
            return
        with self.lock:
            # Prevent duplicate processing of the same skin
            if (self.current_skin_id == skin_id and 
                self.current_skin_name == skin_name and 
                self.current_champion_name == champion_name):
                log.debug(f"[UI] Skipping duplicate skin: {skin_name} (ID: {skin_id})")
                return
            
            log.info(f"[UI] Showing skin: {skin_name} (ID: {skin_id})")
            
            # Capture previous base skin before updating current
            prev_skin_id = self.current_skin_id
            prev_base_skin_id = None
            if prev_skin_id is not None:
                prev_chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
                prev_base_skin_id = prev_skin_id if is_base_skin(prev_skin_id, prev_chroma_id_map) else get_base_skin_id_for_chroma(prev_skin_id, prev_chroma_id_map)

            # Update current skin tracking
            self.current_skin_id = skin_id
            self.current_skin_name = skin_name
            self.current_champion_name = champion_name
            self.current_champion_id = champion_id
            
            # Check if this is a chroma selection for the same base skin
            is_chroma_selection = self._is_chroma_selection_for_same_base_skin(skin_id, skin_name)
            
            # Check if skin has chromas
            has_chromas = self._skin_has_chromas(skin_id)
            
            # Check ownership
            is_owned_var = is_owned(skin_id, self.state.owned_skin_ids)
            chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
            is_base_skin_var = is_base_skin(skin_id, chroma_id_map)
            # Determine new base skin id for current selection
            new_base_skin_id = skin_id if is_base_skin_var else get_base_skin_id_for_chroma(skin_id, chroma_id_map)
            
            # Check if base skin is owned
            base_skin_owned = is_base_skin_owned(skin_id, self.state.owned_skin_ids, chroma_id_map)
            
            # Special case: Elementalist Lux forms (fake IDs 99991-99999) should always show UnownedFrame
            is_elementalist_form = 99991 <= skin_id <= 99999
            
            # Same-base chroma swap occurs when switching from base skin (or its chroma) to another chroma of same base
            is_same_base_chroma = (not is_base_skin_var) and (prev_base_skin_id is not None) and (new_base_skin_id == prev_base_skin_id)
            
            # Determine what to show
            should_show_chroma_ui = has_chromas
            # Show UnownedFrame for:
            # 1. Elementalist Lux forms (fake IDs 99991-99999) - always show
            # 2. When the base skin is not owned
            should_show_unowned_frame = is_elementalist_form or (not base_skin_owned)
            
            log.debug(f"[UI] Skin analysis: has_chromas={has_chromas}, is_owned={is_owned_var}, is_base_skin={is_base_skin_var}, base_skin_owned={base_skin_owned}, is_elementalist_form={is_elementalist_form}, is_chroma_selection={is_chroma_selection}")
            log.debug(f"[UI] Will show: chroma_ui={should_show_chroma_ui}")
            
            # Show/hide ChromaUI based on chromas
            if should_show_chroma_ui:
                self._show_chroma_ui(skin_id, skin_name, champion_name, champion_id)
            else:
                self._hide_chroma_ui()
            
            # Cancel randomization if skin changed and random mode is active (but not during randomization sequence)
            if self.state.random_mode_active and not self._randomization_in_progress:
                self._cancel_randomization()
            
            # Always reset randomization flags if skin changed (user manually changed skin)
            # This ensures dice button can be clicked again even if previous randomization was in progress
            if self._randomization_started:
                log.debug("[UI] Resetting randomization flag due to skin change")
                self._randomization_started = False
                # Also reset in-progress flag if it was set (e.g., during base skin forcing)
                if self._randomization_in_progress:
                    log.debug("[UI] Cancelling randomization in progress due to skin change")
                    self._randomization_in_progress = False
                    # Cancel the state but don't call full _cancel_randomization to avoid double broadcast
                    if self.state.random_mode_active:
                        self.state.random_skin_name = None
                        self.state.random_skin_id = None
                        self.state.random_mode_active = False
                        try:
                            if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                                self.state.ui_skin_thread._broadcast_random_mode_state()
                        except Exception as e:
                            log.debug(f"[UI] Failed to broadcast random mode state on skin change: {e}")
            
            # Broadcast dice button state to JavaScript (dice button is now handled by JS)
            self._update_dice_button()

            # Update last base skin id after handling
            self._last_base_skin_id = new_base_skin_id if new_base_skin_id is not None else (skin_id if is_base_skin_var else None)
            
            # Historic mode activation: check on first skin detection if champion is locked with default skin
            self._check_and_activate_historic_mode(skin_id)
            
            # Historic mode deactivation: if skin changes from default to non-default, deactivate historic mode
            if self.state.historic_mode_active and self.state.locked_champ_id is not None:
                base_skin_id = self.state.locked_champ_id * 1000
                # Check if current skin is not the default skin (and not a chroma of the default skin)
                # Use the already computed new_base_skin_id to check if this is still the base skin or its chroma
                if new_base_skin_id != base_skin_id:
                    # Skin changed to a different base skin - deactivate historic mode
                    self.state.historic_mode_active = False
                    self.state.historic_skin_id = None
                    log.info(f"[HISTORIC] Historic mode DEACTIVATED - skin changed from default to {skin_id} (base: {new_base_skin_id})")
                    
                    # Broadcast state to JavaScript (will hide JS plugin flag)
                    try:
                        if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                            self.state.ui_skin_thread._broadcast_historic_state()
                    except Exception as e:
                        log.debug(f"[UI] Failed to broadcast historic state on deactivation: {e}")
    
    def hide_all(self):
        """Hide all UI components"""
        with self.lock:
            if not self.is_ui_initialized():
                log.debug("[UI] Cannot hide - UI not initialized")
                return
            log.info("[UI] Hiding all UI components")
            self._hide_chroma_ui()
    
    def _schedule_hide_all_on_main_thread(self):
        """Schedule hide_all() to run on the main thread"""
        try:
            # Use threading.Timer to schedule on main thread
            timer = threading.Timer(0.0, self.hide_all)
            timer.daemon = True
            timer.start()
            log.debug("[UI] hide_all() scheduled on main thread")
        except Exception as e:
            log.warning(f"[UI] Failed to schedule hide_all on main thread: {e}")
            # No fallback - avoid direct call that could cause thread issues
    
    def _skin_has_chromas(self, skin_id: int) -> bool:
        """Check if skin has chromas"""
        try:
            # Special case: Elementalist Lux (skin ID 99007) has Forms instead of chromas
            if skin_id == 99007:
                log.debug(f"[UI] Elementalist Lux detected - has Forms instead of chromas")
                return True
            
            # Special case: Elementalist Lux forms (fake IDs 99991-99999) are considered chromas
            if 99991 <= skin_id <= 99999:
                log.debug(f"[UI] Elementalist Lux form detected - considered as chroma")
                return True
            
            # Special case: Risen Legend Kai'Sa (skin ID 145070) has HOL chroma instead of regular chromas
            if skin_id == 145070:
                log.debug(f"[UI] Risen Legend Kai'Sa detected - has HOL chroma instead of regular chromas")
                return True
            
            # Special case: Immortalized Legend Kai'Sa (skin ID 145071) is treated as a chroma of Risen Legend
            if skin_id == 145071:
                log.debug(f"[UI] Immortalized Legend Kai'Sa detected - treated as chroma of Risen Legend")
                return True
            
            # Special case: Risen Legend Kai'Sa HOL chroma (fake ID 100001) is considered a chroma
            if skin_id == 100001:
                log.debug(f"[UI] Risen Legend Kai'Sa HOL chroma detected - considered as chroma")
                return True
            
            # Special case: Risen Legend Ahri (skin ID 103085) has HOL chroma instead of regular chromas
            if skin_id == 103085:
                log.debug(f"[UI] Risen Legend Ahri detected - has HOL chroma instead of regular chromas")
                return True
            
            # Special case: Immortalized Legend Ahri (skin ID 103086) is treated as a chroma of Risen Legend Ahri
            if skin_id == 103086:
                log.debug(f"[UI] Immortalized Legend Ahri detected - treated as chroma of Risen Legend Ahri")
                return True
            
            # Special case: Risen Legend Ahri HOL chroma (fake ID 88888) is considered a chroma
            if skin_id == 88888:
                log.debug(f"[UI] Risen Legend Ahri HOL chroma detected - considered as chroma")
                return True
            
            # First, check if this skin_id is a chroma by looking it up in the chroma cache
            if self.skin_scraper and self.skin_scraper.cache:
                if skin_id in self.skin_scraper.cache.chroma_id_map:
                    # This is a chroma - it's always considered to have chromas
                    # because it's part of the base skin's chroma set
                    return True
            
            # For base skins, check if they actually have chromas
            chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
            return bool(chromas)
        except Exception as e:
            log.debug(f"[UI] Error checking chromas for skin {skin_id}: {e}")
            return False
    
    def _is_chroma_selection_for_same_base_skin(self, skin_id: int, skin_name: str) -> bool:
        """Check if this is a chroma selection for the same base skin we were already showing"""
        try:
            # Check if we have a current skin ID that's a base skin
            if not hasattr(self, 'current_skin_id') or self.current_skin_id is None:
                return False
            
            # Check if the current skin is a base skin
            current_base_skin_id = self.current_skin_id
            chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
            if is_chroma_id(current_base_skin_id, chroma_id_map):
                # Current skin is already a chroma, get its base skin
                current_base_skin_id = get_base_skin_id_for_chroma(current_base_skin_id, chroma_id_map)
                if current_base_skin_id is None:
                    return False
            
            # Check if the new skin_id is a chroma of the same base skin
            if is_base_skin(skin_id, chroma_id_map):
                # New skin is a base skin, not a chroma selection
                return False
            
            # Get the base skin ID for the new chroma
            new_base_skin_id = get_base_skin_id_for_chroma(skin_id, chroma_id_map)
            if new_base_skin_id is None:
                return False
            
            # Check if both chromas belong to the same base skin
            is_same_base = current_base_skin_id == new_base_skin_id
            
            if is_same_base:
                log.debug(f"[UI] Detected chroma selection for same base skin: {current_base_skin_id} -> {skin_id}")
            
            return is_same_base
            
        except Exception as e:
            log.debug(f"[UI] Error checking chroma selection: {e}")
            return False
    
    
    def _show_chroma_ui(self, skin_id: int, skin_name: str, champion_name: str = None, champion_id: int = None):
        """Show ChromaUI for skin with chromas"""
        if self.chroma_ui:
            try:
                self.chroma_ui.show_for_skin(skin_id, skin_name, champion_name, champion_id)
                log.debug(f"[UI] ChromaUI shown for {skin_name}")
            except Exception as e:
                log.error(f"[UI] Error showing ChromaUI: {e}")
    
    def _hide_chroma_ui(self):
        """Hide ChromaUI"""
        if self.chroma_ui:
            try:
                self.chroma_ui.hide()
                log.debug("[UI] ChromaUI hidden")
            except Exception as e:
                log.debug(f"[UI] Error hiding ChromaUI: {e}")
    
    def _show_unowned_frame(self, skin_id: int, skin_name: str, champion_name: str = None, is_same_base_chroma: bool = False):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _hide_unowned_frame(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def check_resolution_and_update(self):
        """Check for resolution changes and update UI components accordingly"""
        try:
            # Check ChromaUI for resolution changes (it handles its own resolution checking)
            if self.chroma_ui:
                # ChromaUI components handle their own resolution checking
                pass
                
        except Exception as e:
            log.error(f"[UI] Error checking resolution changes: {e}")
            import traceback
            log.error(traceback.format_exc())
    
    
    def is_ui_initialized(self):
        """Check if UI components are initialized"""
        # In Swiftplay mode, click_catchers are not created, so skip those checks
        if self.state and self.state.is_swiftplay_mode:
            return (
                self.chroma_ui is not None
            )
        return (
            self.chroma_ui is not None
        )
    
    def request_ui_initialization(self):
        """Request UI initialization (called from any thread)"""
        with self.lock:
            if self._ui_destruction_in_progress:
                log.warning("[UI] UI initialization requested but destruction is in progress - skipping")
                return
            
            # Check if we're in cooldown period after destruction
            import time
            current_time = time.time()
            if self._last_destruction_time > 0 and (current_time - self._last_destruction_time) < 0.5:  # 500ms cooldown
                remaining_time = 0.5 - (current_time - self._last_destruction_time)
                log.warning(f"[UI] UI initialization requested but in cooldown period - {remaining_time:.2f}s remaining")
                return
            
            # Check for force reinitialize FIRST (before other checks)
            if self._force_reinitialize:
                log.info("[UI] Force reinitializing UI for new ChampSelect")
                # Force destruction and recreation
                self._pending_ui_destruction = True
                self._pending_ui_initialization = True
                self._force_reinitialize = False
            elif not self.is_ui_initialized() and not self._pending_ui_initialization:
                log.info("[UI] UI initialization requested for ChampSelect")
                # Defer widget creation to main thread to avoid PyQt6 thread issues
                self._pending_ui_initialization = True
                self._pending_ui_destruction = False  # Cancel any pending destruction
            else:
                log.debug("[UI] UI initialization requested but already initialized or pending")
    
    def process_pending_operations(self):
        """Process pending UI operations (must be called from main thread)"""
        with self.lock:
            # Handle pending destruction first (takes priority)
            if self._pending_ui_destruction:
                log.info("[UI] Processing pending UI destruction in main thread")
                self._pending_ui_destruction = False
                self._ui_destruction_in_progress = True
                try:
                    self.destroy_ui()
                    
                    # Record destruction time for cooldown
                    import time
                    self._last_destruction_time = time.time()
                except Exception as e:
                    log.error(f"[UI] Failed to process pending UI destruction: {e}")
                    import traceback
                    log.error(f"[UI] Destruction failure traceback: {traceback.format_exc()}")
                finally:
                    self._ui_destruction_in_progress = False
            
            # Handle pending initialization (either new or after destruction)
            if self._pending_ui_initialization:
                ui_initialized = self.is_ui_initialized()
                log.debug(f"[UI] Checking initialization: pending={self._pending_ui_initialization}, initialized={ui_initialized}")
                if not ui_initialized:
                    log.info("[UI] Processing pending UI initialization in main thread")
                    self._pending_ui_initialization = False
                    try:
                        self._initialize_components()
                    except Exception as e:
                        log.error(f"[UI] Failed to process pending UI initialization: {e}")
                        # Reset the flag so we can try again later
                        self._pending_ui_initialization = True
            

    def request_ui_destruction(self):
        """Request UI destruction (called from any thread)"""
        with self.lock:
            if self.is_ui_initialized():
                log.info("[UI] UI destruction requested")
                self._pending_ui_destruction = True
                self._pending_ui_initialization = False  # Cancel any pending initialization
            else:
                log.debug("[UI] UI destruction requested but UI not initialized")
    
    def has_pending_operations(self):
        """Check if there are pending UI operations"""
        with self.lock:
            return (self._pending_ui_destruction or 
                    self._pending_ui_initialization)
    
    def destroy_ui(self):
        """Destroy UI components (must be called from main thread)"""
        log.info("[UI] Starting UI component destruction")
        
        # Try to acquire lock with timeout to avoid deadlock
        import time
        lock_acquired = False
        try:
            lock_acquired = self.lock.acquire(timeout=0.001)  # 1ms timeout
            if not lock_acquired:
                log.debug("[UI] Could not acquire lock for destruction - proceeding without lock")
        except Exception as e:
            log.debug(f"[UI] Lock acquisition failed: {e} - proceeding without lock")
        
        try:
            # Store references to cleanup outside the lock to avoid deadlock
            chroma_ui_to_cleanup = None
            
            if lock_acquired:
                try:
                    log.debug("[UI] Lock acquired, storing references")
                    chroma_ui_to_cleanup = self.chroma_ui
                    self.chroma_ui = None
                    
                    # Also clear global instances
                    try:
                        from ui.chroma_panel import clear_global_panel_manager
                        clear_global_panel_manager()
                        log.debug("[UI] Global instances cleared")
                    except Exception as e:
                        log.debug(f"[UI] Could not clear global instances: {e}")
                    
                    log.debug("[UI] References stored and cleared")
                finally:
                    self.lock.release()
                    lock_acquired = False
            else:
                # If we couldn't acquire lock, try to get references without lock (risky but necessary)
                log.warning("[UI] Attempting to get UI references without lock for cleanup")
                try:
                    chroma_ui_to_cleanup = self.chroma_ui
                    
                    # CRITICAL: Set components to None even without lock
                    self.chroma_ui = None
                    
                    log.debug("[UI] Got references without lock and cleared instance variables")
                except Exception as e:
                    log.warning(f"[UI] Could not get references without lock: {e}")
                    # Still try to clear the instance variables
                    try:
                        self.chroma_ui = None
                        log.debug("[UI] Cleared instance variables despite error")
                    except Exception as e2:
                        log.error(f"[UI] Could not clear instance variables: {e2}")
            
            # Cleanup components outside the lock to avoid deadlock
            if chroma_ui_to_cleanup:
                try:
                    chroma_ui_to_cleanup.cleanup()
                except Exception as e:
                    log.error(f"[UI] Error cleaning up ChromaUI: {e}")
                    import traceback
                    log.error(f"[UI] ChromaUI cleanup traceback: {traceback.format_exc()}")
            
            # If we couldn't get references, try to force cleanup through global instances
            if not chroma_ui_to_cleanup:
                log.warning("[UI] No references obtained, attempting global cleanup")
                try:
                    # Try to cleanup global chroma panel manager
                    from ui.chroma_panel import _chroma_panel_manager
                    if _chroma_panel_manager:
                        log.debug("[UI] Cleaning up global chroma panel manager")
                        _chroma_panel_manager.cleanup()
                        log.debug("[UI] Global chroma panel manager cleaned up")
                except Exception as e:
                    log.warning(f"[UI] Error cleaning up global chroma panel manager: {e}")
            
            # PyQt6 removed - no Qt events to process
            log.info("[UI] UI components destroyed successfully")
            
        except Exception as e:
            log.error(f"[UI] Critical error during UI destruction: {e}")
            import traceback
            log.error(f"[UI] UI destruction traceback: {traceback.format_exc()}")
            raise
        finally:
            if lock_acquired:
                self.lock.release()
    
    def _handle_dice_click_disabled(self):
        """Handle dice button click in disabled state - start randomization"""
        # Prevent multiple simultaneous randomization attempts
        if self._randomization_started:
            log.debug("[UI] Randomization already in progress, ignoring click")
            return
            
        log.info("[UI] Starting random skin selection")
        self._randomization_started = True
        
        # Force champion's base skin first
        champion_id = self.skin_scraper.cache.champion_id if self.skin_scraper and self.skin_scraper.cache else None
        base_champion_skin_id = champion_id * 1000 if champion_id else None
        
        if self.current_skin_id == base_champion_skin_id:
            # Already champion's base skin, proceed with randomization
            self._start_randomization()
        else:
            # Need to force champion's base skin first
            self._force_base_skin_and_randomize()
    
    def _handle_dice_click_enabled(self):
        """Handle dice button click in enabled state - cancel randomization"""
        log.info("[UI] Cancelling random skin selection")
        self._cancel_randomization()

    def _force_base_skin_and_randomize(self):
        """Force champion's base skin via LCU API then start randomization"""
        if not self.state.locked_champ_id:
            log.warning("[UI] Cannot force base skin - no locked champion")
            return
        
        # Set flag to prevent cancellation during randomization
        self._randomization_in_progress = True
        
        # Get champion's base skin ID (champion_id * 1000)
        champion_id = self.state.locked_champ_id
        base_skin_id = champion_id * 1000
        log.info(f"[UI] Forcing champion base skin: {base_skin_id} (champion {champion_id})")
        
        # Force base skin via LCU (reuse existing LCU instance)
        try:
            # Get the existing LCU instance from the skin scraper
            if not self.skin_scraper or not hasattr(self.skin_scraper, 'lcu'):
                log.warning("[UI] No LCU instance available")
                self._randomization_in_progress = False
                return
            
            lcu = self.skin_scraper.lcu
            
            # Try to set base skin
            if lcu.set_my_selection_skin(base_skin_id):
                log.info(f"[UI] Forced champion base skin: {base_skin_id}")
                # Start randomization immediately
                self._start_randomization()
            else:
                log.warning("[UI] Failed to force champion base skin")
                self._randomization_in_progress = False
                self._randomization_started = False
        except Exception as e:
            log.error(f"[UI] Error forcing champion base skin: {e}")
            self._randomization_in_progress = False
            self._randomization_started = False
    
    def _start_randomization(self):
        """Start the randomization sequence"""
        # Check if randomization was cancelled (e.g., user changed skin during base skin forcing)
        if not self._randomization_started:
            log.debug("[UI] Randomization was cancelled, aborting start")
            self._randomization_in_progress = False
            return
        
        # Disable HistoricMode if active
        try:
            if getattr(self.state, 'historic_mode_active', False):
                self.state.historic_mode_active = False
                self.state.historic_skin_id = None
                log.info("[HISTORIC] Historic mode DISABLED due to RandomMode activation")
                # Broadcast state to JavaScript (will hide JS plugin flag)
                try:
                    if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                        self.state.ui_skin_thread._broadcast_historic_state()
                except Exception as e:
                    log.debug(f"[UI] Failed to broadcast historic state on RandomMode activation: {e}")
        except Exception:
            pass
        
        # Select random skin
        random_selection = self._select_random_skin()
        if random_selection:
            random_skin_name, random_skin_id = random_selection
            self.state.random_skin_name = random_skin_name
            self.state.random_skin_id = random_skin_id
            self.state.random_mode_active = True
            log.info(f"[UI] Random skin selected: {random_skin_name} (ID: {random_skin_id})")
            
            # Broadcast random mode state to JavaScript
            try:
                if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                    self.state.ui_skin_thread._broadcast_random_mode_state()
            except Exception as e:
                log.debug(f"[UI] Failed to broadcast random mode state: {e}")
        else:
            log.warning("[UI] No random skin available")
            self._cancel_randomization()
        
        # Clear the randomization flags AFTER everything is set up
        self._randomization_in_progress = False
        self._randomization_started = False
    
    def _cancel_randomization(self):
        """Cancel randomization and reset state"""
        # Reset state
        self.state.random_skin_name = None
        self.state.random_skin_id = None
        self.state.random_mode_active = False
        
        # Broadcast random mode state to JavaScript
        try:
            if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                self.state.ui_skin_thread._broadcast_random_mode_state()
        except Exception as e:
            log.debug(f"[UI] Failed to broadcast random mode state on cancel: {e}")
        
        # Clear randomization flags
        self._randomization_in_progress = False
        self._randomization_started = False
    
    def reset_skin_state(self):
        """Reset all skin-related state for new ChampSelect"""
        with self.lock:
            # Reset current skin tracking
            self.current_skin_id = None
            self.current_skin_name = None
            self.current_champion_name = None
            self.current_champion_id = None
            
            # Reset UI detection state
            self.last_skin_name = None
            self.last_skin_id = None
            
            # Reset randomization state
            self._randomization_started = False
            
            # Force UI recreation for new ChampSelect
            self._force_reinitialize = True
            
            log.debug("[UI] Skin state reset for new ChampSelect")
        
        log.info("[UI] Randomization cancelled")
    
    def _on_click_catcher_hide_clicked(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _on_click_catcher_clicked(self, instance_name: str):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _create_show_instances_for_panel(self, panel_name: str):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _destroy_all_show_instances(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _hide_all_ui_elements(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _show_all_ui_elements(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def show_click_catcher_hide(self, x, y, width=50, height=50):
        """Legacy method - no-op for compatibility."""
        pass
    
    def hide_click_catcher_hide(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def show_click_catcher(self, instance_name: str):
        """Legacy method - no-op for compatibility."""
        pass
    
    def hide_click_catcher(self, instance_name: str):
        """Legacy method - no-op for compatibility."""
        pass
    
    def show_all_click_catchers(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def hide_all_click_catchers(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _show_click_catchers(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _select_random_skin(self) -> Optional[tuple]:
        """Select a random skin from available skins (excluding base skin)
        
        Returns:
            Tuple of (skin_name, skin_id) or None if no skin available
        """
        if not self.skin_scraper or not self.skin_scraper.cache.skins:
            log.warning("[UI] No skins available for random selection")
            return None
        
        # Filter out the champion's base skin (champion_id * 1000) and actual chromas
        champion_id = self.skin_scraper.cache.champion_id
        base_champion_skin_id = champion_id * 1000 if champion_id else None
        
        chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else None
        available_skins = [
            skin for skin in self.skin_scraper.cache.skins 
            if skin.get('skinId') != base_champion_skin_id and is_base_skin(skin.get('skinId'), chroma_id_map)
        ]
        
        # Debug logging
        log.debug(f"[UI] Champion ID: {champion_id}, Base skin ID: {base_champion_skin_id}")
        log.debug(f"[UI] Total skins in cache: {len(self.skin_scraper.cache.skins)}")
        log.debug(f"[UI] Available skins for random selection: {len(available_skins)}")
        for skin in available_skins[:5]:  # Show first 5 for debugging
            log.debug(f"[UI] Available skin: {skin.get('skinName')} (ID: {skin.get('skinId')})")
        
        if not available_skins:
            log.warning("[UI] No non-base skins available for random selection")
            return None
        
        # Select random skin
        import random
        selected_skin = random.choice(available_skins)
        skin_id = selected_skin.get('skinId')
        localized_skin_name = selected_skin.get('skinName', '')
        
        if not localized_skin_name or not skin_id:
            log.warning("[UI] Selected skin has no name or ID")
            return None
        
        # Use localized skin name directly from LCU (no database conversion needed)
        english_skin_name = localized_skin_name
        
        # Check if this skin has chromas
        chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
        if chromas:
            log.info(f"[UI] Skin '{english_skin_name}' has {len(chromas)} chromas, selecting random chroma")
            
            # Create list of all options: base skin + all chromas
            all_options = []
            
            # Add base skin (the original skin without chromas)
            all_options.append({
                'id': skin_id,
                'name': english_skin_name,
                'type': 'base'
            })
            
            # Add all chromas
            for chroma in chromas:
                localized_chroma_name = chroma.get('name', f'{english_skin_name} Chroma')
                # Use localized chroma name directly from LCU
                english_chroma_name = localized_chroma_name
                all_options.append({
                    'id': chroma.get('id'),
                    'name': english_chroma_name,
                    'type': 'chroma'
                })
            
            # Select random option from base + chromas
            selected_option = random.choice(all_options)
            selected_name = selected_option['name']
            selected_id = selected_option['id']
            selected_type = selected_option['type']
            
            log.info(f"[UI] Random selection: {selected_type} '{selected_name}' (ID: {selected_id})")
            return (selected_name, selected_id)
        else:
            # No chromas, return the base skin name and ID
            log.info(f"[UI] Skin '{english_skin_name}' has no chromas, using base skin")
            return (english_skin_name, skin_id)
    
    
    
    
    def _update_dice_button(self):
        """Broadcast dice button state to JavaScript (dice button is now handled by JS)"""
        # Skip dice button in Swiftplay mode
        if self.state.is_swiftplay_mode:
            return
        
        # Broadcast random mode state to JavaScript (dice button is handled by Rose-RandomSkin plugin)
        if self.current_skin_id:
            try:
                if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                    self.state.ui_skin_thread._broadcast_random_mode_state()
            except Exception as e:
                log.debug(f"[UI] Failed to broadcast random mode state on dice button update: {e}")

    def cleanup(self):
        """Clean up all UI components"""
        with self.lock:
            if self.chroma_ui:
                self.chroma_ui.cleanup()
            log.info("[UI] All UI components cleaned up")


# Global UI instance
_user_interface = None


def get_user_interface(state=None, skin_scraper=None) -> UserInterface:
    """Get or create global user interface instance"""
    global _user_interface
    if _user_interface is None:
        _user_interface = UserInterface(state, skin_scraper)
    else:
        # Update the existing instance with new parameters if they were provided
        if state is not None and _user_interface.state != state:
            _user_interface.state = state
        if skin_scraper is not None and _user_interface.skin_scraper != skin_scraper:
            _user_interface.skin_scraper = skin_scraper
    return _user_interface
