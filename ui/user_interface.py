#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
User Interface Manager - Parent class for all UI components
Manages ChromaUI and UnownedFrame as separate components
"""

import threading
from typing import Optional, Callable
from utils.logging import get_logger
from utils.utilities import is_default_skin, is_owned, is_chroma_id, get_base_skin_id_for_chroma, convert_to_english_skin_name, convert_to_english_chroma_name, is_base_skin_owned, is_base_skin
from ui.chroma_ui import ChromaUI
from ui.z_order_manager import get_z_order_manager

log = get_logger()


class UserInterface:
    """Parent class managing all UI components"""
    
    def __init__(self, state, skin_scraper, db=None):
        self.state = state
        self.skin_scraper = skin_scraper
        self.db = db
        self.lock = threading.Lock()
        
        # Z-order management
        self._z_manager = get_z_order_manager()
        
        # UI Components (will be initialized when entering ChampSelect)
        self.chroma_ui = None
        self.unowned_frame = None
        self.dice_button = None
        self.random_flag = None
        
        # Current skin tracking
        self.current_skin_id = None
        self.current_skin_name = None
        self.current_champion_name = None
        
        # Randomization state
        self._randomization_in_progress = False
        self._randomization_started = False  # Prevent multiple simultaneous randomizations
        
        # Pending initialization/destruction flags
        self._pending_ui_initialization = False
        self._pending_ui_destruction = False
        self._ui_destruction_in_progress = False
        self._last_destruction_time = 0.0
        # Track last base skin shown (owned or unowned) to detect chroma swaps within same base
        self._last_base_skin_id = None
    
    def _initialize_components(self):
        """Initialize all UI components (must be called from main thread)"""
        try:
            log.info("[UI] Creating ChromaUI components...")
            # Initialize ChromaUI (chroma selector + panel)
            self.chroma_ui = ChromaUI(
                skin_scraper=self.skin_scraper,
                state=self.state,
                db=self.db
            )
            log.info("[UI] ChromaUI created successfully")
            
            log.info("[UI] Creating UnownedFrame components...")
            # Create UnownedFrame instance directly
            from ui.unowned_frame import UnownedFrame
            self.unowned_frame = UnownedFrame(state=self.state)
            
            # Ensure the initial UnownedFrame is properly positioned
            self.unowned_frame._create_components()
            self.unowned_frame.show()
            log.info("[UI] UnownedFrame created successfully")
            
            log.info("[UI] Creating DiceButton components...")
            # Create DiceButton instance
            from ui.dice_button import DiceButton
            self.dice_button = DiceButton(state=self.state)
            
            # Connect dice button signals
            self.dice_button.dice_clicked.connect(self._on_dice_clicked)
            log.info("[UI] DiceButton created successfully")
            
            log.info("[UI] Creating RandomFlag components...")
            # Create RandomFlag instance
            from ui.random_flag import RandomFlag
            self.random_flag = RandomFlag(state=self.state)
            log.info("[UI] RandomFlag created successfully")
            
            self._last_unowned_skin_id = None
            # Track last base skin that showed UnownedFrame to control fade behavior
            self._last_unowned_base_skin_id = None
            log.info("[UI] All UI components initialized successfully")
            
        except Exception as e:
            log.error(f"[UI] Failed to initialize UI components: {e}")
            import traceback
            log.error(f"[UI] Traceback: {traceback.format_exc()}")
            # Clean up any partially created components
            if self.chroma_ui:
                try:
                    self.chroma_ui.cleanup()
                except:
                    pass
                self.chroma_ui = None
            if self.unowned_frame:
                try:
                    self.unowned_frame.cleanup()
                except:
                    pass
                self.unowned_frame = None
            raise
    
    def show_skin(self, skin_id: int, skin_name: str, champion_name: str = None):
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
                prev_base_skin_id = prev_skin_id if not is_chroma_id(prev_skin_id, self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else {}) else get_base_skin_id_for_chroma(prev_skin_id, self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else {})

            # Update current skin tracking
            self.current_skin_id = skin_id
            self.current_skin_name = skin_name
            self.current_champion_name = champion_name
            
            # Check if this is a chroma selection for the same base skin
            is_chroma_selection = self._is_chroma_selection_for_same_base_skin(skin_id, skin_name)
            
            # Check if skin has chromas
            has_chromas = self._skin_has_chromas(skin_id)
            
            # Check ownership
            is_owned_var = is_owned(skin_id, self.state.owned_skin_ids)
            chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else {}
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
            log.debug(f"[UI] Will show: chroma_ui={should_show_chroma_ui}, unowned_frame={should_show_unowned_frame}")
            
            # Show/hide ChromaUI based on chromas
            if should_show_chroma_ui:
                self._show_chroma_ui(skin_id, skin_name, champion_name)
            else:
                self._hide_chroma_ui()
            
            # Show/hide UnownedFrame based on ownership
            if should_show_unowned_frame:
                self._show_unowned_frame(skin_id, skin_name, champion_name, is_same_base_chroma=is_same_base_chroma)
            else:
                self._hide_unowned_frame()

            # Cancel randomization if skin changed and random mode is active (but not during randomization sequence)
            if self.state.random_mode_active and not self._randomization_in_progress:
                self._cancel_randomization()
            
            # Update dice button visibility
            self._update_dice_button()

            # Update last base skin id after handling
            self._last_base_skin_id = new_base_skin_id if new_base_skin_id is not None else (skin_id if is_base_skin_var else None)
    
    def hide_all(self):
        """Hide all UI components"""
        with self.lock:
            if not self.is_ui_initialized():
                log.debug("[UI] Cannot hide - UI not initialized")
                return
            log.info("[UI] Hiding all UI components")
            self._hide_chroma_ui()
            self._hide_unowned_frame()
            if self.dice_button:
                self.dice_button.hide_button()
            if self.random_flag:
                self.random_flag.hide_flag()
    
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
            return chromas and len(chromas) > 0
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
            chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else {}
            if is_chroma_id(current_base_skin_id, chroma_id_map):
                # Current skin is already a chroma, get its base skin
                current_base_skin_id = get_base_skin_id_for_chroma(current_base_skin_id, chroma_id_map)
                if current_base_skin_id is None:
                    return False
            
            # Check if the new skin_id is a chroma of the same base skin
            if not is_chroma_id(skin_id, chroma_id_map):
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
    
    
    def _show_chroma_ui(self, skin_id: int, skin_name: str, champion_name: str = None):
        """Show ChromaUI for skin with chromas"""
        if self.chroma_ui:
            try:
                self.chroma_ui.show_for_skin(skin_id, skin_name, champion_name)
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
        """Show UnownedFrame for unowned skin"""
        if self.unowned_frame:
            try:
                # Determine base skin ID for the current skin
                current_base_skin_id = skin_id
                chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else {}
                if is_chroma_id(skin_id, chroma_id_map):
                    base_id = get_base_skin_id_for_chroma(skin_id, chroma_id_map)
                    if base_id is not None:
                        current_base_skin_id = base_id
                # No-op on chroma swaps within the same base skin (decide after computing base id)
                if is_same_base_chroma:
                    log.debug(f"[UI] UnownedFrame no-op for same base chroma swap: {skin_name}")
                    # Track last ids and exit without triggering fades
                    self._last_unowned_skin_id = skin_id
                    self._last_unowned_base_skin_id = current_base_skin_id
                    return
                
                # Decide fade behavior based on base skin changes only
                if getattr(self, '_last_unowned_base_skin_id', None) is None:
                    # First time showing - fade in
                    self.unowned_frame.fade_in()
                    log.debug(f"[UI] UnownedFrame first shown for {skin_name}")
                elif self._last_unowned_base_skin_id == current_base_skin_id:
                    # Same base skin (e.g., chroma swap) - do nothing (avoid triggering any fade)
                    log.debug(f"[UI] UnownedFrame unchanged for same base skin (no-op) for {skin_name}")
                    # Track IDs and exit early without any visual changes
                    self._last_unowned_skin_id = skin_id
                    self._last_unowned_base_skin_id = current_base_skin_id
                    return
                else:
                    # Different base skin - perform fade transition
                    self.unowned_frame.fade_out()
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(200, lambda: self.unowned_frame.fade_in())
                    log.debug(f"[UI] UnownedFrame transition (different base skin) shown for {skin_name}")
                
                # Track last shown IDs
                self._last_unowned_skin_id = skin_id
                self._last_unowned_base_skin_id = current_base_skin_id
            except Exception as e:
                log.error(f"[UI] Error showing UnownedFrame: {e}")
    
    def _hide_unowned_frame(self):
        """Hide UnownedFrame"""
        if self.unowned_frame:
            try:
                # Fade out UnownedFrame
                self.unowned_frame.fade_out()
                # Reset tracking when hiding
                self._last_unowned_skin_id = None
                self._last_unowned_base_skin_id = None
                log.debug("[UI] UnownedFrame hidden")
            except Exception as e:
                log.debug(f"[UI] Error hiding UnownedFrame: {e}")
    
    def check_resolution_and_update(self):
        """Check for resolution changes and update UI components accordingly"""
        try:
            # Check if UnownedFrame needs resolution update by destroying and recreating it
            if self.unowned_frame:
                # Get current resolution
                from utils.window_utils import get_league_window_client_size
                current_resolution = get_league_window_client_size()
                
                if current_resolution and hasattr(self.unowned_frame, '_current_resolution'):
                    # Only recreate if resolution actually changed AND it's not None
                    if (self.unowned_frame._current_resolution is not None and 
                        current_resolution != self.unowned_frame._current_resolution):
                        log.info(f"[UI] UnownedFrame resolution changed from {self.unowned_frame._current_resolution} to {current_resolution}, destroying and recreating")
                        
                        # Save current state
                        current_opacity = 0.0
                        if hasattr(self.unowned_frame, 'opacity_effect') and self.unowned_frame.opacity_effect:
                            current_opacity = self.unowned_frame.opacity_effect.opacity()
                        
                        # Completely destroy the old UnownedFrame
                        self.unowned_frame.hide()
                        self.unowned_frame.deleteLater()
                        self.unowned_frame = None
                        
                        # Small delay to ensure cleanup
                        from PyQt6.QtWidgets import QApplication
                        QApplication.processEvents()
                        
                        # Create completely new UnownedFrame with fresh resolution values
                        from ui.unowned_frame import UnownedFrame
                        self.unowned_frame = UnownedFrame(state=self.state)
                        
                        # Ensure the initial UnownedFrame is properly positioned (same as initialization)
                        self.unowned_frame._create_components()
                        self.unowned_frame.show()
                        
                        # Use the same logic as skin swaps to show the UnownedFrame
                        if self.unowned_frame.opacity_effect:
                            # Check if current skin should show UnownedFrame
                            should_show = self.unowned_frame._should_show_for_current_skin()
                            if should_show:
                                # Use the same method that works during skin swaps
                                log.info("[UI] UnownedFrame recreated with new resolution, using skin swap logic to show unowned skin")
                                self._show_unowned_frame(self.current_skin_id, self.current_skin_name, self.current_champion_name)
                            else:
                                # If current skin is owned or base, keep it hidden
                                self.unowned_frame.opacity_effect.setOpacity(0.0)
                                log.info("[UI] UnownedFrame recreated with new resolution, set opacity to 0.0 for owned/base skin")
                        
                        # Ensure proper z-order
                        self.unowned_frame.refresh_z_order()
                    elif self.unowned_frame._current_resolution is None:
                        # Just update the resolution without recreating
                        self.unowned_frame._current_resolution = current_resolution
                        log.debug(f"[UI] UnownedFrame resolution initialized to {current_resolution}")
            
            # Check ChromaUI for resolution changes (it handles its own resolution checking)
            if self.chroma_ui:
                # ChromaUI components handle their own resolution checking
                pass
            
            # Check DiceButton for resolution changes
            if self.dice_button:
                self.dice_button.check_resolution_and_update()
            
            # Check RandomFlag for resolution changes
            if self.random_flag:
                self.random_flag.check_resolution_and_update()
                
        except Exception as e:
            log.error(f"[UI] Error checking resolution changes: {e}")
            import traceback
            log.error(traceback.format_exc())
    
    def refresh_z_order(self):
        """Refresh z-order for all UI components"""
        try:
            self._z_manager.refresh_z_order()
            # Only log occasionally to avoid spam - log at most once per 10 seconds
            import time
            current_time = time.time()
            if not hasattr(self, '_last_zorder_log_time'):
                self._last_zorder_log_time = 0
            
            if current_time - self._last_zorder_log_time >= 10.0:
                self._last_zorder_log_time = current_time
                log.debug("[UI] Z-order refreshed for all components")
        except Exception as e:
            log.error(f"[UI] Error refreshing z-order: {e}")
    
    def is_ui_initialized(self):
        """Check if UI components are initialized"""
        return (self.chroma_ui is not None and 
                self.unowned_frame is not None and 
                self.dice_button is not None and 
                self.random_flag is not None)
    
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
            
            if not self.is_ui_initialized() and not self._pending_ui_initialization:
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
                    log.debug("[UI] About to call destroy_ui()")
                    self.destroy_ui()
                    log.debug("[UI] destroy_ui() completed successfully")
                    
                    # Record destruction time for cooldown
                    import time
                    self._last_destruction_time = time.time()
                    log.debug("[UI] Destruction completed and timestamp recorded")
                except Exception as e:
                    log.error(f"[UI] Failed to process pending UI destruction: {e}")
                    import traceback
                    log.error(f"[UI] Destruction failure traceback: {traceback.format_exc()}")
                finally:
                    self._ui_destruction_in_progress = False
                    log.debug("[UI] Destruction flag cleared")
            
            # Handle pending initialization only if not destroyed
            elif self._pending_ui_initialization and not self.is_ui_initialized():
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
        return self._pending_ui_initialization or self._pending_ui_destruction
    
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
            unowned_frame_to_cleanup = None
            dice_button_to_cleanup = None
            random_flag_to_cleanup = None
            
            if lock_acquired:
                try:
                    log.debug("[UI] Lock acquired, storing references")
                    chroma_ui_to_cleanup = self.chroma_ui
                    unowned_frame_to_cleanup = self.unowned_frame
                    dice_button_to_cleanup = self.dice_button
                    random_flag_to_cleanup = self.random_flag
                    self.chroma_ui = None
                    self.unowned_frame = None
                    self.dice_button = None
                    self.random_flag = None
                    
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
                    unowned_frame_to_cleanup = self.unowned_frame
                    dice_button_to_cleanup = self.dice_button
                    random_flag_to_cleanup = self.random_flag
                    log.debug("[UI] Got references without lock")
                except Exception as e:
                    log.warning(f"[UI] Could not get references without lock: {e}")
            
            # Cleanup components outside the lock to avoid deadlock
            if chroma_ui_to_cleanup:
                log.debug("[UI] Cleaning up ChromaUI...")
                try:
                    chroma_ui_to_cleanup.cleanup()
                    log.debug("[UI] ChromaUI cleaned up successfully")
                except Exception as e:
                    log.error(f"[UI] Error cleaning up ChromaUI: {e}")
                    import traceback
                    log.error(f"[UI] ChromaUI cleanup traceback: {traceback.format_exc()}")
            
            if unowned_frame_to_cleanup:
                log.debug("[UI] Cleaning up UnownedFrame...")
                try:
                    unowned_frame_to_cleanup.cleanup()
                    log.debug("[UI] UnownedFrame cleaned up successfully")
                except Exception as e:
                    log.error(f"[UI] Error cleaning up UnownedFrame: {e}")
                    import traceback
                    log.error(f"[UI] UnownedFrame cleanup traceback: {traceback.format_exc()}")
            
            if dice_button_to_cleanup:
                log.debug("[UI] Cleaning up DiceButton...")
                try:
                    dice_button_to_cleanup.cleanup()
                    log.debug("[UI] DiceButton cleaned up successfully")
                except Exception as e:
                    log.error(f"[UI] Error cleaning up DiceButton: {e}")
                    import traceback
                    log.error(f"[UI] DiceButton cleanup traceback: {traceback.format_exc()}")
            
            if random_flag_to_cleanup:
                log.debug("[UI] Cleaning up RandomFlag...")
                try:
                    random_flag_to_cleanup.cleanup()
                    log.debug("[UI] RandomFlag cleaned up successfully")
                except Exception as e:
                    log.error(f"[UI] Error cleaning up RandomFlag: {e}")
                    import traceback
                    log.error(f"[UI] RandomFlag cleanup traceback: {traceback.format_exc()}")
            
            # If we couldn't get references, try to force cleanup through global instances
            if not chroma_ui_to_cleanup and not unowned_frame_to_cleanup:
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
            
            # Force Qt to process events to ensure widgets are actually destroyed
            log.debug("[UI] Processing Qt events for widget destruction...")
            try:
                from PyQt6.QtWidgets import QApplication
                QApplication.processEvents()
                log.debug("[UI] Qt events processed successfully")
            except Exception as e:
                log.error(f"[UI] Error processing Qt events: {e}")
                import traceback
                log.error(f"[UI] Qt events traceback: {traceback.format_exc()}")
            
            log.info("[UI] UI components destroyed successfully")
            
        except Exception as e:
            log.error(f"[UI] Critical error during UI destruction: {e}")
            import traceback
            log.error(f"[UI] UI destruction traceback: {traceback.format_exc()}")
            raise
        finally:
            if lock_acquired:
                self.lock.release()
    
    def _on_dice_clicked(self, state: str):
        """Handle dice button click events"""
        log.info(f"[UI] Dice button clicked in {state} state")
        if state == 'disabled':
            self._handle_dice_click_disabled()
        elif state == 'enabled':
            self._handle_dice_click_enabled()
        else:
            log.warning(f"[UI] Unknown dice button state: {state}")
    
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
                # Add a delay to let UI detection process the base skin change
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(1000, self._start_randomization)
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
        # Switch dice to disabled state (non-interactive)
        if self.dice_button:
            self.dice_button.set_state('disabled')
        
        # Fade in random flag
        if self.random_flag:
            self.random_flag.show_flag()
        
        # Switch dice to enabled state
        if self.dice_button:
            self.dice_button.set_state('enabled')
        
        # Select random skin
        random_selection = self._select_random_skin()
        if random_selection:
            random_skin_name, random_skin_id = random_selection
            self.state.random_skin_name = random_skin_name
            self.state.random_skin_id = random_skin_id
            self.state.random_mode_active = True
            log.info(f"[UI] Random skin selected: {random_skin_name} (ID: {random_skin_id})")
        else:
            log.warning("[UI] No random skin available")
            self._cancel_randomization()
        
        # Clear the randomization flags AFTER everything is set up
        self._randomization_in_progress = False
        self._randomization_started = False
    
    def _cancel_randomization(self):
        """Cancel randomization and reset state"""
        # Fade out random flag
        if self.random_flag:
            self.random_flag.hide_flag()
        
        # Reset state
        self.state.random_skin_name = None
        self.state.random_skin_id = None
        self.state.random_mode_active = False
        
        # Clear randomization flags
        self._randomization_in_progress = False
        self._randomization_started = False
        
        # Switch dice to disabled state
        if self.dice_button:
            self.dice_button.set_state('disabled')
        
        log.info("[UI] Randomization cancelled")
    
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
        
        chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else {}
        available_skins = [
            skin for skin in self.skin_scraper.cache.skins 
            if skin.get('skinId') != base_champion_skin_id and not is_chroma_id(skin.get('skinId'), chroma_id_map)
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
        
        # Convert localized skin name to English using database
        chroma_id_map = self.skin_scraper.cache.chroma_id_map if self.skin_scraper and self.skin_scraper.cache else {}
        english_skin_name = convert_to_english_skin_name(skin_id, localized_skin_name, self.db, chroma_id_map=chroma_id_map)
        
        # Check if this skin has chromas
        chromas = self.skin_scraper.get_chromas_for_skin(skin_id)
        if chromas and len(chromas) > 0:
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
                # Convert chroma name to English if possible
                english_chroma_name = convert_to_english_chroma_name(chroma.get('id'), localized_chroma_name, english_skin_name, self.skin_scraper)
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
        """Update dice button visibility based on current context"""
        if not self.dice_button:
            log.debug("[UI] Dice button not initialized")
            return
        
        # Show dice button if we have a skin (champion name is optional)
        if self.current_skin_id:
            log.debug(f"[UI] Showing dice button for skin ID: {self.current_skin_id}")
            self.dice_button.show_button()
        else:
            log.debug("[UI] Hiding dice button - no current skin")
            self.dice_button.hide_button()

    def cleanup(self):
        """Clean up all UI components"""
        with self.lock:
            if self.chroma_ui:
                self.chroma_ui.cleanup()
            if self.unowned_frame:
                self.unowned_frame.cleanup()
            if self.dice_button:
                self.dice_button.cleanup()
            if self.random_flag:
                self.random_flag.cleanup()
            log.info("[UI] All UI components cleaned up")


# Global UI instance
_user_interface = None


def get_user_interface(state=None, skin_scraper=None, db=None) -> UserInterface:
    """Get or create global user interface instance"""
    global _user_interface
    if _user_interface is None:
        _user_interface = UserInterface(state, skin_scraper, db)
    else:
        # Update the existing instance with new parameters if they were provided
        if state is not None and _user_interface.state != state:
            _user_interface.state = state
        if skin_scraper is not None and _user_interface.skin_scraper != skin_scraper:
            _user_interface.skin_scraper = skin_scraper
        if db is not None and _user_interface.db != db:
            _user_interface.db = db
    return _user_interface
