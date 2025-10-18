#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Chroma Panel Manager - Coordinates chroma panel and button widgets
"""

import threading
from typing import Callable, List, Dict
from utils.logging import get_logger, log_event, log_success, log_action
from utils.chroma_button import OpeningButton
from utils.chroma_panel_widget import ChromaPanelWidget
from utils.chroma_click_catcher import ClickCatcherOverlay

log = get_logger()


class ChromaPanelManager:
    """Manages PyQt6 chroma panel - uses polling instead of QTimer"""
    
    def __init__(self, on_chroma_selected: Callable[[int, str], None] = None, state=None):
        self.on_chroma_selected = on_chroma_selected
        self.state = state  # SharedState for OCR pause control
        self.widget = None
        self.reopen_button = None
        self.click_catcher = None  # Invisible overlay to catch clicks outside UI
        self.is_initialized = False
        self.pending_show = None  # (skin_name, chromas) to show from other threads
        self.pending_hide = False
        self.pending_show_button = False
        self.pending_hide_button = False
        self.pending_create = False  # Request to create widgets
        self.pending_destroy = False  # Request to destroy widgets
        self.pending_rebuild = False  # Request to rebuild widgets (for resolution changes)
        self.pending_update_button_state = None  # True/False to update button panel_is_open state
        self.current_skin_id = None  # Track current skin for button
        self.current_skin_name = None
        self.current_chromas = None
        self.current_champion_name = None  # Track champion for direct path
        self.current_selected_chroma_id = None  # Track currently applied chroma
        self.current_chroma_color = None  # Track current chroma color for button display
        self.lock = threading.RLock()  # Use RLock for reentrant locking (prevents deadlock)
        self._rebuilding = False  # Flag to prevent infinite rebuild loops
        self.pending_initial_unowned_fade = False  # Flag to trigger initial UnownedFrame fade after creation
    
    def request_create(self):
        """Request to create the panel (thread-safe, will be created in main thread)"""
        with self.lock:
            if not self.is_initialized:
                self.pending_create = True
                log.debug("[CHROMA] Create panel requested")
    
    def request_initial_unowned_fade(self):
        """Request initial UnownedFrame fade-in for first unowned skin (thread-safe)"""
        with self.lock:
            self.pending_initial_unowned_fade = True
            log.debug("[CHROMA] Initial UnownedFrame fade requested")
    
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
        """Check for resolution changes and focus changes periodically - NON-BLOCKING
        
        Note: When widgets are parented to League window (embedded mode), Windows
        automatically handles ALL positioning. We only need to check for resolution changes
        and detect when League window gains focus to close the panel.
        """
        try:
            # Try to acquire lock with timeout to avoid blocking
            if not self.lock.acquire(blocking=False):
                return  # Skip this iteration if lock is held by another thread
            
            try:
                # Don't check while rebuilding
                if self._rebuilding:
                    return
                
                # Only check resolution changes when widgets are visible
                # Check at most once per second to avoid excessive polling
                import time
                current_time = time.time()
                if not hasattr(self, '_last_resolution_check'):
                    self._last_resolution_check = 0
                
                # Check resolution only once per second AND only if widgets are visible
                widgets_visible = (self.widget and self.widget.isVisible()) or (self.reopen_button and self.reopen_button.isVisible())
                if widgets_visible and (current_time - self._last_resolution_check >= 1.0):
                    self._last_resolution_check = current_time
                    
                # Check for resolution changes and trigger rebuild if needed
                if self.widget:
                    self.widget.check_resolution_and_update()
                if self.reopen_button:
                    self.reopen_button.check_resolution_and_update()
            finally:
                self.lock.release()
        except RuntimeError:
            # Widget may have been deleted
            pass
    
    def _create_widgets(self):
        """Create widgets (must be called from main thread)"""
        if not self.is_initialized:
            # Force reload of scaled values to ensure we use current resolution
            from utils.chroma_scaling import get_scaled_chroma_values
            from utils.window_utils import get_league_window_client_size, get_league_window_handle
            
            # Get current resolution and force cache refresh
            current_res = get_league_window_client_size()
            if current_res:
                log.debug(f"[CHROMA] Creating widgets for resolution: {current_res}")
                # Force reload to get fresh values for current resolution
                get_scaled_chroma_values(resolution=current_res, force_reload=True)
            
            # Get League window handle for click catcher
            league_hwnd = get_league_window_handle()
            
            self.widget = ChromaPanelWidget(on_chroma_selected=self._on_chroma_selected_wrapper, manager=self)
            self.reopen_button = OpeningButton(on_click=self._on_reopen_clicked, manager=self)
            # Set button reference on wheel so it can detect button clicks
            self.widget.set_button_reference(self.reopen_button)
            
            # Create click catcher overlay (invisible, catches clicks on League to close panel)
            if league_hwnd:
                self.click_catcher = ClickCatcherOverlay(
                    on_click_callback=self._on_click_catcher_clicked,
                    parent_hwnd=league_hwnd
                )
            
            self.is_initialized = True
            log.info("[CHROMA] Panel widgets created")
    
    def _on_click_catcher_clicked(self):
        """Called when click catcher overlay is clicked - close panel"""
        log.debug("[CHROMA] Click catcher clicked, closing panel")
        self.hide()
    
    def _destroy_widgets(self):
        """Destroy widgets (must be called from main thread)"""
        if self.is_initialized:
            # Destroy click catcher first
            if self.click_catcher:
                try:
                    self.click_catcher.hide()
                    self.click_catcher.deleteLater()
                    self.click_catcher = None
                except Exception as e:
                    log.warning(f"[CHROMA] Error destroying click catcher: {e}")
            
            if self.widget:
                try:
                    # Un-parent from League window before destroying
                    if hasattr(self.widget, '_league_window_hwnd') and self.widget._league_window_hwnd:
                        import ctypes
                        widget_hwnd = int(self.widget.winId())
                        ctypes.windll.user32.SetParent(widget_hwnd, 0)  # Un-parent (set to desktop)
                        self.widget._league_window_hwnd = None
                        log.debug("[CHROMA] Panel un-parented from League window")
                    
                    # Clear button reference before destroying
                    self.widget.set_button_reference(None)
                    # Use hide() + deleteLater() instead of close() to avoid blocking
                    self.widget.hide()
                    self.widget.deleteLater()
                    self.widget = None
                except Exception as e:
                    log.warning(f"[CHROMA] Error destroying panel widget: {e}")
            if self.reopen_button:
                try:
                    # Un-parent UnownedFrame from League window first
                    import ctypes
                    if hasattr(self.reopen_button, 'unowned_frame') and self.reopen_button.unowned_frame:
                        if hasattr(self.reopen_button, '_unowned_frame_parented') and self.reopen_button._unowned_frame_parented:
                            try:
                                frame_hwnd = int(self.reopen_button.unowned_frame.winId())
                                ctypes.windll.user32.SetParent(frame_hwnd, 0)  # Un-parent
                                log.debug("[CHROMA] UnownedFrame un-parented from League window")
                            except:
                                pass
                        # Lock and OutlineGold are children of UnownedFrame, will be deleted automatically
                        self.reopen_button.unowned_frame.hide()
                        self.reopen_button.unowned_frame.deleteLater()
                    
                    # Un-parent button from League window before destroying
                    if hasattr(self.reopen_button, '_league_window_hwnd') and self.reopen_button._league_window_hwnd:
                        button_hwnd = int(self.reopen_button.winId())
                        ctypes.windll.user32.SetParent(button_hwnd, 0)  # Un-parent (set to desktop)
                        self.reopen_button._league_window_hwnd = None
                        log.debug("[CHROMA] Button un-parented from League window")
                    
                    # Use hide() + deleteLater() instead of close() to avoid blocking
                    self.reopen_button.hide()
                    self.reopen_button.deleteLater()
                    self.reopen_button = None
                except Exception as e:
                    log.warning(f"[CHROMA] Error destroying reopen button: {e}")
            self.is_initialized = False
            self.last_skin_name = None
            self.last_chromas = None
            log.info("[CHROMA] Panel widgets destroyed (un-parented from League)")
    
    def _on_chroma_selected_wrapper(self, chroma_id: int, chroma_name: str):
        """Wrapper for chroma selection - button stays visible (no need to show again)"""
        # Call the original callback
        if self.on_chroma_selected:
            self.on_chroma_selected(chroma_id, chroma_name)
        
        # Track the selected chroma ID and update button color
        with self.lock:
            self.current_selected_chroma_id = chroma_id if chroma_id != 0 else None
            
            # Update button color to match selected chroma
            if self.reopen_button:
                # Find the selected chroma's color from current_chromas
                chroma_color = None
                if chroma_id != 0 and self.current_chromas:
                    for chroma in self.current_chromas:
                        if chroma.get('id') == chroma_id:
                            colors = chroma.get('colors', [])
                            if colors:
                                chroma_color = colors[0] if not colors[0].startswith('#') else colors[0][1:]
                                if not chroma_color.startswith('#'):
                                    chroma_color = f"#{chroma_color}"
                            break
                
                # Set button color (None = rainbow for base skin)
                self.current_chroma_color = chroma_color  # Save for rebuilds
                self.reopen_button.set_chroma_color(chroma_color)
                log.debug(f"[CHROMA] Button color updated to: {chroma_color if chroma_color else 'rainbow'}")
            
            self.pending_update_button_state = False  # Wheel will be hidden, so button should be unhovered
            log_event(log, f"Chroma selected: {chroma_name}" if chroma_id != 0 else "Base skin selected", "✨")
    
    def _on_reopen_clicked(self):
        """Handle button click - toggle the panel for current skin"""
        with self.lock:
            if self.current_skin_name and self.current_chromas:
                # Check if wheel is currently visible
                is_wheel_visible = self.widget and self.widget.isVisible()
                
                if is_wheel_visible:
                    # Wheel is open, close it
                    log_action(log, f"Closing panel for {self.current_skin_name}", "🎨")
                    self.pending_hide = True
                    self.pending_update_button_state = False  # Button should unhover
                else:
                    # Wheel is closed, open it
                    separator = "=" * 80
                    log.info(separator)
                    log.info(f"🎨 OPENING CHROMA WHEEL")
                    log.info(f"   📋 Skin: {self.current_skin_name}")
                    log.info(f"   📋 Chromas: {len(self.current_chromas)}")
                    log.info(separator)
                    self.pending_show = (self.current_skin_name, self.current_chromas)
                    self.pending_update_button_state = True  # Button should hover
                # Don't hide button - it should stay visible while skin has chromas
                # self.pending_hide_button = True  # REMOVED - button stays visible
                # self.pending_show_button = False  # REMOVED - no need to cancel show
    
    def show_button_for_skin(self, skin_id: int, skin_name: str, chromas: List[Dict], champion_name: str = None):
        """Show button for a skin (not the wheel itself)
        
        The button displays:
        - If chromas exist: clickable chroma wheel button
        - If no chromas: just the UnownedFrame overlay (golden border + lock for unowned skins)
        
        Note: chromas contains ALL chromas (both owned and unowned)
        Each chroma has an 'is_owned' flag set by ChromaSelector
        """
        with self.lock:
            # If switching to a different skin, hide the wheel and reset selection
            if self.current_skin_id is not None and self.current_skin_id != skin_id:
                log.debug(f"[CHROMA] Switching skins - hiding wheel and resetting selection")
                self.pending_hide = True
                self.current_selected_chroma_id = None  # Reset selection for new skin
                self.current_chroma_color = None  # Reset chroma color
                self.pending_update_button_state = False  # Reset button state when switching skins
                
                # Reset button to rainbow (only if button exists)
                if self.reopen_button:
                    self.reopen_button.set_chroma_color(None)
            
            # Update current skin data for button (store champion name for later)
            self.current_skin_id = skin_id
            self.current_skin_name = skin_name
            self.current_chromas = chromas
            self.current_champion_name = champion_name  # Store for image loading
            
            # Queue the show/hide request regardless of initialization state
            # Strategy for skins without chromas:
            # - Show the button first to position the UnownedFrame
            # - Then hide the button (UnownedFrame stays visible independently)
            has_chromas = chromas and len(chromas) > 0
            
            if not self.is_initialized:
                if has_chromas:
                    log.debug(f"[CHROMA] Widgets not initialized yet - queueing button show for {skin_name} ({len(chromas)} chromas)")
                else:
                    log.debug(f"[CHROMA] Widgets not initialized yet - will show UnownedFrame only for {skin_name}")
            else:
                if has_chromas:
                    log.debug(f"[CHROMA] Showing button for {skin_name} ({len(chromas)} chromas)")
                else:
                    log.debug(f"[CHROMA] Showing UnownedFrame only for {skin_name} (no chromas)")
            
            # Always show first to ensure UnownedFrame is positioned
            self.pending_show_button = True
            
            # For skins without chromas, immediately hide the button after showing
            # (UnownedFrame will remain visible as it has independent visibility)
            if not has_chromas:
                self.pending_hide_button = True
            else:
                # Skin has chromas - ensure button stays visible (cancel any pending hide)
                self.pending_hide_button = False
            
            # Reset button state to unhovered when showing for new skin (wheel will be closed)
            if self.pending_update_button_state is None:
                self.pending_update_button_state = False
    
    def show_wheel_directly(self):
        """Request to show the chroma panel for current skin (called by button click)"""
        with self.lock:
            if self.current_skin_name and self.current_chromas:
                log.info(f"[CHROMA] Request to show panel for {self.current_skin_name}")
                self.pending_show = (self.current_skin_name, self.current_chromas)
                self.pending_hide_button = True
    
    def process_pending(self):
        """Process pending show/hide requests (must be called from main thread) - NON-BLOCKING"""
        # Try to acquire lock with timeout to avoid blocking
        if not self.lock.acquire(blocking=False):
            return  # Skip this iteration if lock is held by another thread
        
        try:
            # Process create request
            if self.pending_create:
                self.pending_create = False
                try:
                    self._create_widgets()
                    
                    # Process initial UnownedFrame fade if requested (for first unowned skin)
                    if self.pending_initial_unowned_fade and self.reopen_button:
                        log.info("[CHROMA] Applying initial UnownedFrame fade after widget creation")
                        self.reopen_button.unowned_frame_fade_owned_to_not_owned_first()
                        self.pending_initial_unowned_fade = False
                except Exception as e:
                    log.error(f"[CHROMA] Error creating widgets: {e}")
            
            # Process rebuild request (resolution change) - ONLY if already initialized
            if self.pending_rebuild:
                if not self.is_initialized:
                    log.warning("[CHROMA] Rebuild requested but widgets not initialized yet")
                    self.pending_rebuild = False
                elif self._rebuilding:
                    log.debug("[CHROMA] Rebuild already in progress, skipping duplicate")
                else:
                    self.pending_rebuild = False
                    self._rebuilding = True
                    log.info("="*80)
                    log.info("[CHROMA] 🔄 STARTING WIDGET REBUILD (RESOLUTION CHANGE)")
                    log.info("="*80)
                    
                try:
                    # Save current state
                    was_panel_visible = self.widget and self.widget.isVisible()
                    was_button_visible = self.reopen_button and self.reopen_button.isVisible()
                    
                    # Save UnownedFrame opacity before rebuild
                    unowned_frame_opacity = 0.0
                    if self.reopen_button and hasattr(self.reopen_button, 'unowned_frame') and self.reopen_button.unowned_frame:
                        if hasattr(self.reopen_button, 'unowned_frame_opacity_effect'):
                            unowned_frame_opacity = self.reopen_button.unowned_frame_opacity_effect.opacity()
                    
                    log.info(f"[CHROMA] Rebuild state: panel_visible={was_panel_visible}, button_visible={was_button_visible}, unowned_frame_opacity={unowned_frame_opacity:.2f}")
                    
                    # Destroy old widgets
                    log.info("[CHROMA] Destroying old widgets...")
                    self._destroy_widgets()
                    
                    # Small delay to allow cleanup
                    from PyQt6.QtWidgets import QApplication
                    QApplication.processEvents()
                    
                    # Recreate widgets with fresh resolution values
                    log.info("[CHROMA] Creating new widgets with updated resolution...")
                    self._create_widgets()
                    
                    # Restore chroma color on button after rebuild
                    if self.reopen_button and self.current_chroma_color:
                        self.reopen_button.set_chroma_color(self.current_chroma_color)
                        log.debug(f"[CHROMA] Button color restored after rebuild: {self.current_chroma_color}")
                    
                    # Restore UnownedFrame opacity after rebuild
                    if self.reopen_button and hasattr(self.reopen_button, 'unowned_frame_opacity_effect'):
                        self.reopen_button.unowned_frame_opacity_effect.setOpacity(unowned_frame_opacity)
                        log.info(f"[CHROMA] UnownedFrame opacity restored after rebuild: {unowned_frame_opacity:.2f}")
                    
                    # Restore visibility state
                    if was_button_visible and self.current_skin_name and self.current_chromas:
                        log.info("[CHROMA] Restoring button visibility after rebuild")
                        self.pending_show_button = True
                    
                    if was_panel_visible and self.current_skin_name and self.current_chromas:
                        log.info("[CHROMA] Restoring panel visibility after rebuild")
                        self.pending_show = (self.current_skin_name, self.current_chromas)
                    
                    log.info("="*80)
                    log.info("[CHROMA] ✅ WIDGET REBUILD COMPLETED SUCCESSFULLY")
                    log.info("="*80)
                except Exception as e:
                    log.error(f"[CHROMA] ❌ Error rebuilding widgets: {e}")
                    import traceback
                    log.error(traceback.format_exc())
                finally:
                    self._rebuilding = False
                    # Continue processing other requests in the same frame
                    # (removed early return)
            
            # Process destroy request
            if self.pending_destroy:
                self.pending_destroy = False
                try:
                    log.debug("[CHROMA] Starting widget destruction...")
                    self._destroy_widgets()
                    log.debug("[CHROMA] Widget destruction completed")
                except Exception as e:
                    log.error(f"[CHROMA] Error destroying widgets: {e}")
                return  # Don't process other requests after destroying
            
            # Process show request
            if self.pending_show:
                skin_name, chromas = self.pending_show
                self.pending_show = None
                
                if self.widget:
                    # Create click catcher if it doesn't exist (was destroyed on last hide)
                    if not self.click_catcher:
                        from utils.window_utils import get_league_window_handle
                        league_hwnd = get_league_window_handle()
                        if league_hwnd:
                            self.click_catcher = ClickCatcherOverlay(
                                on_click_callback=self._on_click_catcher_clicked,
                                parent_hwnd=league_hwnd
                            )
                            log.debug("[CHROMA] Click catcher overlay created")
                    
                    # Show click catcher FIRST (at bottom of z-order)
                    if self.click_catcher:
                        self.click_catcher.show()
                        self.click_catcher.raise_()  # Make it visible
                        self.click_catcher.update()  # Force repaint
                        log.debug("[CHROMA] Click catcher overlay shown")
                    
                    # Pass the currently selected chroma ID so wheel opens at that index
                    self.widget.set_chromas(skin_name, chromas, self.current_champion_name, self.current_selected_chroma_id, self.current_skin_id)
                    # Position wheel above button
                    button_pos = self.reopen_button.pos() if self.reopen_button else None
                    self.widget.show_wheel(button_pos=button_pos)
                    self.widget.setVisible(True)
                    self.widget.raise_()  # Panel on top
                    
                    # CRITICAL: Re-apply position AFTER show() to prevent Qt from resetting it
                    if hasattr(self.widget, '_update_position'):
                        self.widget._update_position()
                    
                    # Ensure button is also on top
                    if self.reopen_button:
                        self.reopen_button.raise_()
                    
                    log_success(log, f"Chroma panel displayed for {skin_name}", "🎨")
                    
                    # Pause OCR while panel is open (panel covers the text area)
                    if self.state:
                        self.state.chroma_panel_open = True
                        # Store the base skin NAME to avoid re-detecting the same skin on resume
                        # Chromas are named like "Base Skin Name" + " Ruby", so we store the base
                        self.state.chroma_panel_skin_name = skin_name
                        log.debug(f"[CHROMA] OCR paused - panel open (skin: {skin_name})")
            
            # Process hide request
            if self.pending_hide:
                self.pending_hide = False
                
                # Destroy click catcher when panel closes
                if self.click_catcher:
                    try:
                        self.click_catcher.hide()
                        self.click_catcher.deleteLater()
                        self.click_catcher = None
                        log.debug("[CHROMA] Click catcher overlay destroyed")
                    except Exception as e:
                        log.warning(f"[CHROMA] Error destroying click catcher: {e}")
                
                if self.widget:
                    self.widget.hide()
                    
                    # Resume OCR when panel closes
                    if self.state:
                        self.state.chroma_panel_open = False
                        log.debug(f"[CHROMA] OCR resumed - panel closed")
            
            # Process button state update (after show/hide to ensure correct final state)
            if self.pending_update_button_state is not None:
                new_state = self.pending_update_button_state
                self.pending_update_button_state = None
                if self.reopen_button and self.is_initialized:
                    try:
                        # Check if widget is still valid before updating
                        if not self.reopen_button.isHidden() or new_state is False:
                            self.reopen_button.set_wheel_open(new_state)
                    except (RuntimeError, AttributeError) as e:
                        log.debug(f"[CHROMA] Button no longer valid for state update: {e}")
            
            # Process reopen button show request
            if self.pending_show_button:
                self.pending_show_button = False
                if self.reopen_button:
                    self.reopen_button.show()
                    self.reopen_button.raise_()
                    
                    # CRITICAL: Re-apply position AFTER show() to prevent Qt from resetting it
                    if hasattr(self.reopen_button, '_update_position'):
                        self.reopen_button._update_position()
                        log.debug("[CHROMA] Button shown and position re-applied")
                    else:
                        log.debug("[CHROMA] Reopen button shown")
            
            # Process reopen button hide request
            if self.pending_hide_button:
                self.pending_hide_button = False
                if self.reopen_button:
                    self.reopen_button.hide()
        finally:
            self.lock.release()
    
    def hide(self):
        """Request to hide the chroma panel (thread-safe)"""
        with self.lock:
            self.pending_hide = True
    
    def hide_reopen_button(self):
        """Request to hide the reopen button (thread-safe)"""
        with self.lock:
            self.pending_hide_button = True
            self.pending_update_button_state = False  # Reset button state when hiding
            self.current_chroma_color = None  # Reset color when hiding
            
            # Reset button to rainbow
            if self.reopen_button:
                self.reopen_button.set_chroma_color(None)
    
    def cleanup(self):
        """Clean up resources (called on app exit)"""
        self.request_destroy()


# Global panel manager instance
_chroma_panel_manager = None


def get_chroma_panel(state=None) -> ChromaPanelManager:
    """Get or create global chroma panel manager"""
    global _chroma_panel_manager
    if _chroma_panel_manager is None:
        _chroma_panel_manager = ChromaPanelManager(state=state)
    return _chroma_panel_manager


# Backward compatibility alias
def get_chroma_wheel() -> ChromaPanelManager:
    """Backward compatibility alias - use get_chroma_panel() instead"""
    return get_chroma_panel()


# Legacy class name alias
ChromaWheelManager = ChromaPanelManager
