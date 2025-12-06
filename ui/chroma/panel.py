#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Chroma Panel Manager - Coordinates chroma panel and button widgets
"""

import threading
from typing import Callable, List, Dict
from utils.core.logging import get_logger, log_event, log_action, log_success
from utils.core.utilities import is_default_skin, is_owned, is_base_skin_owned

log = get_logger()


class ChromaPanelManager:
    """Headless chroma panel manager

    NOTE: The legacy PyQt6 visual chroma panel has been removed.
    This manager now only tracks chroma state for the JavaScript plugins
    (ROSE-ChromaWheel, ROSE-RandomSkin, ROSE-HistoricMode, etc.) and no longer
    creates or shows any Qt widgets.
    """
    
    def __init__(self, on_chroma_selected: Callable[[int, str], None] = None, state=None, lcu=None):
        self.on_chroma_selected = on_chroma_selected
        self.state = state  # SharedState for panel control
        self.lcu = lcu  # LCU client for game mode detection
        self.is_initialized = False  # Track initialization state
        self.pending_show = None  # (skin_name, chromas) kept for API compatibility
        self.pending_hide = False
        self.pending_create = False
        self.pending_destroy = False
        self.pending_rebuild = False
        self.current_skin_id = None  # Track current skin
        self.current_skin_name = None
        self.current_chromas = None
        self.current_champion_name = None  # Track champion for direct path
        self.current_champion_id = None  # Track champion ID for direct path
        self.current_selected_chroma_id = None  # Track currently applied chroma
        self.current_chroma_color = None  # Track current chroma color (for JavaScript plugin)
        self.current_chroma_colors = None  # Track both chroma colors for split-circle design (for JavaScript plugin)
        self.lock = threading.RLock()  # Use RLock for reentrant locking (prevents deadlock)
        self._rebuilding = False  # Flag to prevent infinite rebuild loops
    
    def request_create(self):
        """Request to create the panel (thread-safe, will be created in main thread)"""
        with self.lock:
            if not self.is_initialized:
                self.pending_create = True
                log.debug("[CHROMA] Create panel requested")
    
    def request_destroy(self):
        """Request to destroy the panel (thread-safe, will be destroyed in main thread)"""
        with self.lock:
            self.pending_destroy = True
            log.debug("[CHROMA] Destroy panel requested")
    
    def request_rebuild(self):
        """Request to rebuild the panel (thread-safe, for resolution changes)"""
        with self.lock:
            if not self._rebuilding:
                self.pending_rebuild = True
                log.info("[CHROMA] Rebuild requested (widgets will be destroyed and recreated)")
            else:
                log.debug("[CHROMA] Rebuild already in progress, ignoring duplicate request")
    
    def update_positions(self):
        """Legacy resolution/focus updater – now a no-op (no Qt widgets)."""
        return
    
    def _create_widgets(self):
        """Legacy widget creation – no longer creates any Qt UI.

        Kept only so existing calls don’t crash; logs once in debug.
        """
        if not self.is_initialized:
            self.is_initialized = True
            log.debug("[CHROMA] _create_widgets called in headless mode (no Qt widgets created)")
    
    def _on_click_catcher_clicked(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _destroy_widgets(self):
        """Reset state (no widgets to destroy)."""
        self.is_initialized = False
        self.last_skin_name = None
        self.last_chromas = None
    
    def _on_chroma_selected_wrapper(self, chroma_id: int, chroma_name: str):
        """Wrapper for chroma selection - tracks colors for JavaScript plugin"""
        # Call the original callback
        if self.on_chroma_selected:
            self.on_chroma_selected(chroma_id, chroma_name)
        
        # Track the selected chroma ID and colors (for JavaScript plugin)
        with self.lock:
            self.current_selected_chroma_id = chroma_id if chroma_id != 0 else None
            
            # Track chroma colors for JavaScript plugin
            chroma_colors = None
            chroma_color = None
            chroma_data = None
            
            # Try to get chroma data from current_chromas first
            if chroma_id != 0 and self.current_chromas:
                for chroma in self.current_chromas:
                    if chroma.get('id') == chroma_id:
                        chroma_data = chroma
                        break
            
            # Fallback: get chroma data from skin scraper cache if not in current_chromas
            if not chroma_data and chroma_id != 0:
                try:
                    from ui.chroma.selector import get_chroma_selector
                    chroma_selector = get_chroma_selector()
                    if chroma_selector and chroma_selector.skin_scraper and chroma_selector.skin_scraper.cache:
                        chroma_data = chroma_selector.skin_scraper.cache.chroma_id_map.get(chroma_id)
                        if chroma_data:
                            log.debug(f"[CHROMA] Found chroma data in skin scraper cache for chroma {chroma_id}")
                except Exception as e:
                    log.debug(f"[CHROMA] Failed to get chroma data from skin scraper: {e}")
            
            # Extract colors from chroma data
            if chroma_data:
                colors = chroma_data.get('colors', [])
                if colors:
                    if len(colors) >= 2:
                        # Check if both colors are identical
                        first_color = colors[0] if not colors[0].startswith('#') else colors[0][1:]
                        second_color = colors[1] if not colors[1].startswith('#') else colors[1][1:]
                        
                        if first_color == second_color:
                            # Both colors are the same - use solid circle
                            selected_color = colors[0]
                            chroma_color = selected_color if not selected_color.startswith('#') else selected_color[1:]
                            if not chroma_color.startswith('#'):
                                chroma_color = f"#{chroma_color}"
                        else:
                            # Colors are different - use split-circle design
                            chroma_colors = [colors[0], colors[1]]
                            # Ensure colors have # prefix
                            chroma_colors = [color if color.startswith('#') else f"#{color}" for color in chroma_colors]
                    elif len(colors) == 1:
                        # Use single color for solid circle
                        selected_color = colors[0]
                        chroma_color = selected_color if not selected_color.startswith('#') else selected_color[1:]
                        if not chroma_color.startswith('#'):
                            chroma_color = f"#{chroma_color}"
            
            # Store colors for JavaScript plugin access
            self.current_chroma_color = chroma_color  # None = rainbow for base skin
            self.current_chroma_colors = chroma_colors  # None = single color or rainbow
            log.debug(f"[CHROMA] Chroma colors tracked: {chroma_colors if chroma_colors else chroma_color if chroma_color else 'rainbow'}")
            
            log_event(log, f"Chroma selected: {chroma_name}" if chroma_id != 0 else "Base skin selected", "✨")
            
            # Broadcast chroma state to JavaScript
            try:
                if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                    self.state.ui_skin_thread._broadcast_chroma_state()
            except Exception as e:
                log.debug(f"[CHROMA] Failed to broadcast chroma state: {e}")
    
    def show_button_for_skin(self, skin_id: int, skin_name: str, chromas: List[Dict], champion_name: str = None, is_chroma_selection: bool = False, champion_id: int = None):
        """Show button for a skin (not the wheel itself)
        
        The button displays:
        - If chromas exist: clickable chroma wheel button
        - If no chromas: just the UnownedFrame overlay (golden border + lock for unowned skins)
        
        Note: chromas contains ALL chromas (both owned and unowned)
        Each chroma has an 'is_owned' flag set by ChromaSelector
        """
        with self.lock:
            # Clear pending_hide flag when showing button (allows panel to be shown after being hidden)
            if self.pending_hide:
                self.pending_hide = False
                log.debug("[CHROMA] Clearing pending_hide flag - showing button for skin")
            
            # If switching to a different skin, hide the wheel and reset selection
            # But don't reset if it's just a chroma selection for the same base skin
            is_different_skin = (self.current_skin_id is not None and 
                               self.current_skin_id != skin_id)
            
            if is_different_skin and not is_chroma_selection:
                log.debug(f"[CHROMA] Switching skins - hiding wheel and resetting selection")
                self.pending_hide = True
                # Only reset if the selected chroma is not for this skin
                # Check if current_selected_chroma_id belongs to this skin's chromas
                if self.current_selected_chroma_id and chromas:
                    chroma_belongs_to_skin = any(c.get('id') == self.current_selected_chroma_id for c in chromas)
                    if not chroma_belongs_to_skin:
                        self.current_selected_chroma_id = None  # Reset selection for new skin
                        self.current_chroma_color = None  # Reset chroma color (for JavaScript plugin)
                        self.current_chroma_colors = None  # Reset chroma colors (for JavaScript plugin)
                    else:
                        log.debug(f"[CHROMA] Preserving selected chroma {self.current_selected_chroma_id} for same base skin")
                else:
                    self.current_selected_chroma_id = None  # Reset selection for new skin
                    self.current_chroma_color = None  # Reset chroma color (for JavaScript plugin)
                    self.current_chroma_colors = None  # Reset chroma colors (for JavaScript plugin)
            elif is_chroma_selection:
                log.debug(f"[CHROMA] Chroma selection for same base skin - preserving selection")
            
            # Update current skin data for button (store champion name and ID for later)
            self.current_skin_id = skin_id
            self.current_skin_name = skin_name
            self.current_chromas = chromas
            self.current_champion_name = champion_name  # Store for image loading
            self.current_champion_id = champion_id  # Store champion ID for direct path
            
            # Calculate base skin ID for preview loading (important for chromas)
            self.current_base_skin_id = skin_id  # Default to original skin_id
            if chromas and len(chromas) > 0:
                # If we have chromas, the first chroma should have the base skin ID
                first_chroma = chromas[0]
                if 'skinId' in first_chroma:
                    self.current_base_skin_id = first_chroma['skinId']
                    log.debug(f"[CHROMA] Using base skin ID {self.current_base_skin_id} for previews (original skin_id: {skin_id})")
                else:
                    log.warning(f"[CHROMA] First chroma missing skinId field: {first_chroma}")
            else:
                log.debug(f"[CHROMA] No chromas found, using original skin_id {skin_id} as base skin ID")
            
            # Ensure widgets are created if needed (JavaScript plugin handles button display)
            if not self.is_initialized:
                # Request widget creation
                self.request_create()
                log.debug(f"[CHROMA] Widgets not initialized yet - will be created for {skin_name}")
            
            # Broadcast chroma state to JavaScript when panel is shown/updated
            try:
                if self.state and hasattr(self.state, 'ui_skin_thread') and self.state.ui_skin_thread:
                    self.state.ui_skin_thread._broadcast_chroma_state()
            except Exception as e:
                log.debug(f"[CHROMA] Failed to broadcast chroma state on show: {e}")
            
    
    def show_wheel_directly(self):
        """Request to show the chroma panel for current skin (called by JavaScript plugin)"""
        with self.lock:
            if self.current_skin_name and self.current_chromas:
                log.info(f"[CHROMA] Request to show panel for {self.current_skin_name}")
                self.pending_show = (self.current_skin_name, self.current_chromas)
    
    def process_pending(self):
        """Process pending show/hide requests (must be called from main thread) - NON-BLOCKING"""
        # Try to acquire lock with timeout to avoid blocking
        if not self.lock.acquire(blocking=False):
            return  # Skip this iteration if lock is held by another thread
        
        try:
            # Process create request (headless – only marks manager initialized)
            if self.pending_create:
                self.pending_create = False
                self._create_widgets()
            
            # Process rebuild request – no-op in headless mode (no widgets to rebuild)
            if self.pending_rebuild:
                self.pending_rebuild = False
            
            # Process destroy request
            if self.pending_destroy:
                self.pending_destroy = False
                try:
                    self._destroy_widgets()
                except Exception as e:
                    log.error(f"[CHROMA] Error destroying widgets: {e}")
                return  # Don't process other requests after destroying
            
            # Process show request – no visual panel anymore, only update state flags if needed
            if self.pending_show:
                skin_name, chromas = self.pending_show
                self.pending_show = None

                # Pause UI detection flag as if a panel were open, so existing logic keeps working
                if self.state:
                    self.state.chroma_panel_open = True
                    self.state.chroma_panel_skin_name = skin_name
                    log.debug(f"[CHROMA] (headless) UI detection paused - virtual panel open (skin: {skin_name})")
            
            # Process hide request
            if self.pending_hide:
                self.pending_hide = False
                
                # Resume UI detection when the (virtual) panel closes
                if self.state:
                    self.state.chroma_panel_open = False
                    log.debug("[CHROMA] (headless) UI detection resumed - virtual panel closed")
        finally:
            self.lock.release()
    
    def hide(self):
        """Request to hide the chroma panel (thread-safe)"""
        with self.lock:
            self.pending_hide = True
    
    def cleanup(self):
        """Clean up resources (called on app exit or UI destruction)"""
        try:
            # Try to acquire lock with timeout to avoid deadlock
            import time
            lock_acquired = False
            try:
                lock_acquired = self.lock.acquire(timeout=0.05)  # 50ms timeout
                if not lock_acquired:
                    log.debug("[CHROMA] Could not acquire lock for cleanup - forcing destruction")
            except Exception as e:
                log.debug(f"[CHROMA] Lock acquisition failed: {e} - forcing destruction")
            
            try:
                # Force immediate destruction of widgets
                if self.is_initialized:
                    self._destroy_widgets()
                else:
                    log.debug("[CHROMA] Not initialized, requesting destruction")
                    # Just request destruction if not initialized
                    self.request_destroy()
            finally:
                if lock_acquired:
                    self.lock.release()
                    
        except Exception as e:
            log.error(f"[CHROMA] Error during cleanup: {e}")
            import traceback
            log.error(f"[CHROMA] Cleanup traceback: {traceback.format_exc()}")
    
    


# Global panel manager instance
_chroma_panel_manager = None


def clear_global_panel_manager():
    """Clear the global panel manager instance"""
    global _chroma_panel_manager
    _chroma_panel_manager = None


def get_chroma_panel(state=None, lcu=None) -> ChromaPanelManager:
    """Get or create global chroma panel manager"""
    global _chroma_panel_manager
    if _chroma_panel_manager is None:
        _chroma_panel_manager = ChromaPanelManager(state=state, lcu=lcu)
    return _chroma_panel_manager
