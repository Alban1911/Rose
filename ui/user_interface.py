#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
User Interface Manager - Parent class for all UI components
Manages ChromaUI and UnownedFrame as separate components
"""

import threading
from typing import Optional, Callable
from utils.logging import get_logger
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
        
        # Current skin tracking
        self.current_skin_id = None
        self.current_skin_name = None
        self.current_champion_name = None
        
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
                prev_base_skin_id = prev_skin_id if (prev_skin_id % 1000 == 0) else self._get_base_skin_id_for_chroma(prev_skin_id)

            # Update current skin tracking
            self.current_skin_id = skin_id
            self.current_skin_name = skin_name
            self.current_champion_name = champion_name
            
            # Check if this is a chroma selection for the same base skin
            is_chroma_selection = self._is_chroma_selection_for_same_base_skin(skin_id, skin_name)
            
            # Check if skin has chromas
            has_chromas = self._skin_has_chromas(skin_id)
            
            # Check ownership
            is_owned = skin_id in self.state.owned_skin_ids
            is_base_skin = skin_id % 1000 == 0
            # Determine new base skin id for current selection
            new_base_skin_id = skin_id if is_base_skin else self._get_base_skin_id_for_chroma(skin_id)
            # Same-base chroma swap occurs when switching from base skin (or its chroma) to another chroma of same base
            is_same_base_chroma = (not is_base_skin) and (prev_base_skin_id is not None) and (new_base_skin_id == prev_base_skin_id)
            
            # Determine what to show
            should_show_chroma_ui = has_chromas
            # Always show UnownedFrame for unowned, non-base skins (do not hide on chroma selection)
            should_show_unowned_frame = (not is_owned) and (not is_base_skin)
            
            log.debug(f"[UI] Skin analysis: has_chromas={has_chromas}, is_owned={is_owned}, is_base_skin={is_base_skin}, is_chroma_selection={is_chroma_selection}")
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

            # Update last base skin id after handling
            self._last_base_skin_id = new_base_skin_id if new_base_skin_id is not None else (skin_id if is_base_skin else None)
    
    def hide_all(self):
        """Hide all UI components"""
        with self.lock:
            if not self.is_ui_initialized():
                log.debug("[UI] Cannot hide - UI not initialized")
                return
            log.info("[UI] Hiding all UI components")
            self._hide_chroma_ui()
            self._hide_unowned_frame()
    
    def _skin_has_chromas(self, skin_id: int) -> bool:
        """Check if skin has chromas"""
        try:
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
            
            # Check if the current skin is a base skin (ID % 1000 == 0)
            current_base_skin_id = self.current_skin_id
            if current_base_skin_id % 1000 != 0:
                # Current skin is already a chroma, get its base skin
                current_base_skin_id = self._get_base_skin_id_for_chroma(current_base_skin_id)
                if current_base_skin_id is None:
                    return False
            
            # Check if the new skin_id is a chroma of the same base skin
            if skin_id % 1000 == 0:
                # New skin is a base skin, not a chroma selection
                return False
            
            # Get the base skin ID for the new chroma
            new_base_skin_id = self._get_base_skin_id_for_chroma(skin_id)
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
    
    def _get_base_skin_id_for_chroma(self, chroma_id: int) -> Optional[int]:
        """Get the base skin ID for a given chroma ID"""
        try:
            if not self.skin_scraper or not self.skin_scraper.cache:
                return None
            
            # Check if this chroma ID exists in the cache
            chroma_data = self.skin_scraper.cache.chroma_id_map.get(chroma_id)
            if chroma_data:
                return chroma_data.get('skinId')
            
            return None
            
        except Exception as e:
            log.debug(f"[UI] Error getting base skin ID for chroma {chroma_id}: {e}")
            return None
    
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
                if skin_id % 1000 != 0:
                    base_id = self._get_base_skin_id_for_chroma(skin_id)
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
        return self.chroma_ui is not None and self.unowned_frame is not None
    
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
            
            if lock_acquired:
                try:
                    log.debug("[UI] Lock acquired, storing references")
                    chroma_ui_to_cleanup = self.chroma_ui
                    unowned_frame_to_cleanup = self.unowned_frame
                    self.chroma_ui = None
                    self.unowned_frame = None
                    
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
    
    def cleanup(self):
        """Clean up all UI components"""
        with self.lock:
            if self.chroma_ui:
                self.chroma_ui.cleanup()
            if self.unowned_frame:
                self.unowned_frame.cleanup()
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
