#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI Lifecycle Manager
Manages UI component initialization, destruction, and pending operations
"""

import threading
import time
from state.shared_state import SharedState
from ui.chroma.ui import ChromaUI
from utils.logging import get_logger

log = get_logger()


class UILifecycleManager:
    """Manages UI component lifecycle"""
    
    def __init__(self, state: SharedState, skin_scraper=None):
        """Initialize UI lifecycle manager
        
        Args:
            state: Shared application state
            skin_scraper: Skin scraper instance
        """
        self.state = state
        self.skin_scraper = skin_scraper
        self.lock = threading.Lock()
        
        # UI Components
        self.chroma_ui: ChromaUI = None
        
        # Pending initialization/destruction flags
        self._pending_ui_initialization = False
        self._pending_ui_destruction = False
        self._ui_destruction_in_progress = False
        self._last_destruction_time = 0.0
        self._force_reinitialize = False
    
    def initialize_components(self, skin_scraper=None):
        """Initialize all UI components (must be called from main thread)
        
        Args:
            skin_scraper: Optional skin scraper instance (if None, uses self.skin_scraper)
        """
        # Use provided skin_scraper or fall back to stored one
        scraper = skin_scraper if skin_scraper is not None else self.skin_scraper
        
        if scraper is None:
            log.error("[UI] Cannot initialize UI components - skin_scraper is None")
            raise ValueError("skin_scraper must be provided to initialize UI components")
        
        try:
            log.info("[UI] Creating ChromaUI components...")
            # Initialize ChromaUI (chroma selector + panel)
            self.chroma_ui = ChromaUI(
                skin_scraper=scraper,
                state=self.state
            )
            log.info("[UI] ChromaUI created successfully")
        except Exception as e:
            log.error(f"[UI] Failed to initialize UI components: {e}")
            import traceback
            log.error(f"[UI] Traceback: {traceback.format_exc()}")
            # Clean up any partially created components
            if self.chroma_ui:
                try:
                    self.chroma_ui.cleanup()
                except Exception as e2:
                    log.debug(f"[UI] Error cleaning up ChromaUI: {e2}")
                self.chroma_ui = None
            raise
    
    def is_ui_initialized(self) -> bool:
        """Check if UI components are initialized"""
        # In Swiftplay mode, click_catchers are not created, so skip those checks
        if self.state and self.state.is_swiftplay_mode:
            return self.chroma_ui is not None
        return self.chroma_ui is not None
    
    def request_ui_initialization(self):
        """Request UI initialization (called from any thread)"""
        with self.lock:
            if self._ui_destruction_in_progress:
                log.warning("[UI] UI initialization requested but destruction is in progress - skipping")
                return
            
            # Check if we're in cooldown period after destruction
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
    
    def request_ui_destruction(self):
        """Request UI destruction (called from any thread)"""
        with self.lock:
            if self.is_ui_initialized():
                log.info("[UI] UI destruction requested")
                self._pending_ui_destruction = True
                self._pending_ui_initialization = False  # Cancel any pending initialization
            else:
                log.debug("[UI] UI destruction requested but UI not initialized")
    
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
                        # Pass skin_scraper explicitly to ensure it's available
                        self.initialize_components(self.skin_scraper)
                    except Exception as e:
                        log.error(f"[UI] Failed to process pending UI initialization: {e}")
                        # Reset the flag so we can try again later
                        self._pending_ui_initialization = True
                    else:
                        # Return True to indicate initialization succeeded
                        return True
        return False
    
    def has_pending_operations(self) -> bool:
        """Check if there are pending UI operations"""
        with self.lock:
            return (self._pending_ui_destruction or 
                    self._pending_ui_initialization)
    
    def destroy_ui(self):
        """Destroy UI components (must be called from main thread)"""
        log.info("[UI] Starting UI component destruction")
        
        # Try to acquire lock with timeout to avoid deadlock
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
                        from ui.chroma.panel import clear_global_panel_manager
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
                    from ui.chroma.panel import _chroma_panel_manager
                    if _chroma_panel_manager:
                        log.debug("[UI] Cleaning up global chroma panel manager")
                        _chroma_panel_manager.cleanup()
                        log.debug("[UI] Global chroma panel manager cleaned up")
                except Exception as e:
                    log.warning(f"[UI] Error cleaning up global chroma panel manager: {e}")
            
            log.info("[UI] UI components destroyed successfully")
            
        except Exception as e:
            log.error(f"[UI] Critical error during UI destruction: {e}")
            import traceback
            log.error(f"[UI] UI destruction traceback: {traceback.format_exc()}")
            raise
        finally:
            if lock_acquired:
                self.lock.release()
    
    def reset_skin_state(self):
        """Reset all skin-related state for new ChampSelect"""
        with self.lock:
            # Force UI recreation for new ChampSelect
            self._force_reinitialize = True
            log.debug("[UI] Skin state reset for new ChampSelect")
    
    @property
    def force_reinitialize(self) -> bool:
        """Get force reinitialize flag"""
        return self._force_reinitialize
    
    @force_reinitialize.setter
    def force_reinitialize(self, value: bool):
        """Set force reinitialize flag"""
        self._force_reinitialize = value

