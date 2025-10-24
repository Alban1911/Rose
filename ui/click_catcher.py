#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ClickCatcher - Base UI component for detecting clicks on specific UI elements
Invisible overlay that detects clicks and triggers customizable actions

Usage:
    # Create instance (abstract base class)
    click_catcher = ClickCatcherHide(state=state, x=100, y=100, width=50, height=50)
    
    # Connect click detection signal
    click_catcher.click_detected.connect(on_click_handler)
    
    # Show at specific position (e.g., over settings button)
    click_catcher.show_catcher()
    
    # Hide when no longer needed
    click_catcher.hide_catcher()

Features:
    - Inherits from ChromaWidgetBase like all other UI elements
    - Child of League window with proper parenting system
    - Invisible overlay that doesn't block clicks to League window
    - Positioned using absolute coordinates in League window
    - Automatically handles resolution changes and League window parenting
    - Integrates with z-order management system
    - Abstract base class for ClickCatcherHide and ClickCatcherShow
"""

import ctypes
from PyQt6.QtCore import pyqtSignal, QTimer
from ui.chroma_base import ChromaWidgetBase
from ui.z_order_manager import ZOrderManager
from utils.logging import get_logger
from utils.resolution_utils import get_click_catcher_config, get_current_resolution, is_supported_resolution

log = get_logger()

# Global registry of all click catchers for mouse monitoring
_click_catchers = {}
_mouse_timer = None
_last_mouse_pos = (0, 0)
_last_mouse_state = False


def _get_mouse_state():
    """Get current mouse position and left button state"""
    try:
        # Get mouse position
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        
        point = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        
        # Get mouse button state
        mouse_state = ctypes.windll.user32.GetAsyncKeyState(0x01)  # VK_LBUTTON
        button_pressed = bool(mouse_state & 0x8000)
        
        return (point.x, point.y), button_pressed
    except Exception as e:
        log.error(f"[ClickCatcher] Error getting mouse state: {e}")
        return (0, 0), False


def _check_mouse_clicks():
    """Check for mouse clicks in click catcher areas"""
    global _last_mouse_pos, _last_mouse_state
    
    try:
        current_pos, current_state = _get_mouse_state()
        
        # Check for button press (transition from not pressed to pressed)
        if current_state and not _last_mouse_state:
            log.debug(f"[ClickCatcher] Mouse click detected at screen coordinates {current_pos}")
            
            # Check if click is in any click catcher area
            for catcher_id, catcher_info in _click_catchers.items():
                catcher_x, catcher_y, catcher_width, catcher_height, league_hwnd, signal_obj = catcher_info
                
                # Convert screen coordinates to League window coordinates
                from utils.window_utils import get_league_window_handle, find_league_window_rect
                league_hwnd_actual = get_league_window_handle()
                if league_hwnd_actual == league_hwnd:
                    window_rect = find_league_window_rect()
                    if window_rect:
                        window_left, window_top, window_right, window_bottom = window_rect
                        league_x = current_pos[0] - window_left
                        league_y = current_pos[1] - window_top
                        
                        log.debug(f"[ClickCatcher] Click at League coordinates ({league_x}, {league_y}), checking against {catcher_id} at ({catcher_x}, {catcher_y}) size {catcher_width}x{catcher_height}")
                        
                        # Check if click is within click catcher bounds
                        if (catcher_x <= league_x <= catcher_x + catcher_width and 
                            catcher_y <= league_y <= catcher_y + catcher_height):
                            log.info(f"[ClickCatcher] ✓ Click detected in {catcher_id} at ({league_x}, {league_y})")
                            # Emit signal in a thread-safe way
                            signal_obj.emit()
                            break
                        else:
                            log.debug(f"[ClickCatcher] Click outside {catcher_id} bounds")
        
        _last_mouse_pos = current_pos
        _last_mouse_state = current_state
    except Exception as e:
        log.error(f"[ClickCatcher] Error checking mouse clicks: {e}")


def _start_mouse_monitoring():
    """Start mouse monitoring using a timer"""
    global _mouse_timer
    
    if _mouse_timer is not None:
        log.debug("[ClickCatcher] Mouse monitoring already running")
        return  # Already running
    
    try:
        # Create a QTimer for mouse monitoring
        _mouse_timer = QTimer()
        _mouse_timer.timeout.connect(_check_mouse_clicks)
        _mouse_timer.start(16)  # ~60 FPS monitoring
        log.info("[ClickCatcher] ✓ Mouse monitoring started")
    except Exception as e:
        log.error(f"[ClickCatcher] Exception starting mouse monitoring: {e}")


def _stop_mouse_monitoring():
    """Stop mouse monitoring"""
    global _mouse_timer
    
    if _mouse_timer:
        _mouse_timer.stop()
        _mouse_timer = None
        log.debug("[ClickCatcher] Mouse monitoring stopped")


class ClickCatcher(ChromaWidgetBase):
    """
    Abstract base class for invisible click catchers that detect clicks on specific UI elements
    Used to trigger customizable actions when specific areas are clicked
    """
    
    # Signal emitted when click is detected
    click_detected = pyqtSignal()
    
    def __init__(self, state=None, x=0, y=0, width=50, height=50, shape='circle', catcher_name=None, widget_name='click_catcher'):
        # Initialize with explicit z-level for click catchers
        super().__init__(
            z_level=ZOrderManager.Z_LEVELS['CLICK_CATCHER'],
            widget_name=widget_name
        )
        
        # Store reference to shared state
        self.state = state
        
        # Store catcher name for resolution-based positioning
        self.catcher_name = catcher_name
        
        # Position and size for the click catcher (will be set by resolution config)
        self.catcher_x = x
        self.catcher_y = y
        self.catcher_width = width
        self.catcher_height = height
        self.shape = shape  # 'circle' or 'rectangle'
        
        # No visual elements needed - purely virtual click catcher
        # All click detection is handled by the global mouse hook
        
        # Track resolution for change detection
        self._current_resolution = None
        
        # Create the click catcher component
        self._create_components()
        
        # Register this click catcher globally
        self._register_click_catcher()
        
        log.debug(f"[ClickCatcher] Virtual click catcher created at ({self.catcher_x}, {self.catcher_y}) size {self.catcher_width}x{self.catcher_height}")
    
    def _create_components(self):
        """Create the click catcher component - now purely virtual for mouse hook detection"""
        # Get League window for positioning reference
        from utils.window_utils import get_league_window_handle, find_league_window_rect
        
        # Get League window handle and size
        league_hwnd = get_league_window_handle()
        window_rect = find_league_window_rect()
        if not league_hwnd or not window_rect:
            log.debug("[ClickCatcher] Could not get League window for positioning")
            return
        
        window_left, window_top, window_right, window_bottom = window_rect
        window_width = window_right - window_left
        window_height = window_bottom - window_top
        
        # Store resolution for change detection
        self._current_resolution = (window_width, window_height)
        
        # Update position and size based on current resolution if catcher_name is provided
        if self.catcher_name:
            current_resolution = get_current_resolution()
            if current_resolution and is_supported_resolution(current_resolution):
                config = get_click_catcher_config(current_resolution, self.catcher_name)
                if config:
                    self.catcher_x = config['x']
                    self.catcher_y = config['y']
                    self.catcher_width = config['width']
                    self.catcher_height = config['height']
                    log.debug(f"[ClickCatcher] Updated {self.catcher_name} position for resolution {current_resolution}: ({self.catcher_x}, {self.catcher_y}) size {self.catcher_width}x{self.catcher_height}")
                else:
                    log.warning(f"[ClickCatcher] No config found for {self.catcher_name} at resolution {current_resolution}")
            else:
                log.warning(f"[ClickCatcher] Unsupported resolution: {current_resolution}")
        
        # No actual widget creation - this is now purely virtual
        # The mouse hook will handle all click detection
        log.debug(f"[ClickCatcher] Virtual click catcher registered at ({self.catcher_x}, {self.catcher_y}) size {self.catcher_width}x{self.catcher_height}")
    
    def _register_click_catcher(self):
        """Register this click catcher in the global registry"""
        global _click_catchers
        
        # Get League window handle
        from utils.window_utils import get_league_window_handle
        league_hwnd = get_league_window_handle()
        
        if league_hwnd:
            # Store click catcher info: (x, y, width, height, league_hwnd, signal_object)
            _click_catchers[id(self)] = (
                self.catcher_x, self.catcher_y, self.catcher_width, self.catcher_height,
                league_hwnd, self.click_detected
            )
            
            log.info(f"[ClickCatcher] ✓ Registered click catcher {id(self)} at ({self.catcher_x}, {self.catcher_y}) size {self.catcher_width}x{self.catcher_height}")
            log.info(f"[ClickCatcher] Total click catchers registered: {len(_click_catchers)}")
            
            # Start mouse monitoring if not already running
            _start_mouse_monitoring()
        else:
            log.error("[ClickCatcher] ✗ Failed to get League window handle for registration")
    
    def _unregister_click_catcher(self):
        """Unregister this click catcher from the global registry"""
        global _click_catchers
        
        if id(self) in _click_catchers:
            del _click_catchers[id(self)]
            log.debug(f"[ClickCatcher] Unregistered click catcher {id(self)}")
            
            # Stop mouse monitoring if no more click catchers
            if not _click_catchers:
                _stop_mouse_monitoring()
    
    # No paintEvent needed - purely virtual click catcher
    # Click detection is handled by the global mouse monitoring timer
    
    def show_catcher(self):
        """Show the click catcher - re-register for detection"""
        # Re-register the click catcher to enable detection
        self._register_click_catcher()
        log.debug("[ClickCatcher] Click catcher detection enabled")
    
    def hide_catcher(self):
        """Hide the click catcher - now just disables detection"""
        # Unregister to disable detection
        self._unregister_click_catcher()
        log.debug("[ClickCatcher] Click catcher detection disabled")
    
    def set_position(self, x, y, width=None, height=None):
        """Update the position and optionally size of the click catcher"""
        self.catcher_x = x
        self.catcher_y = y
        
        if width is not None:
            self.catcher_width = width
        if height is not None:
            self.catcher_height = height
        
        # Recreate components with new position
        self._create_components()
        
        log.debug(f"[ClickCatcher] Position updated to ({x}, {y}) size {self.catcher_width}x{self.catcher_height}")
    
    def check_resolution_and_update(self):
        """Check for resolution changes and update positioning"""
        try:
            from utils.window_utils import find_league_window_rect
            window_rect = find_league_window_rect()
            
            if not window_rect:
                return
            
            window_left, window_top, window_right, window_bottom = window_rect
            current_resolution = (window_right - window_left, window_bottom - window_top)
            
            if self._current_resolution != current_resolution:
                log.info(f"[ClickCatcher] Resolution changed from {self._current_resolution} to {current_resolution}, recreating components")
                
                # Update position and size based on new resolution if catcher_name is provided
                if self.catcher_name:
                    if is_supported_resolution(current_resolution):
                        config = get_click_catcher_config(current_resolution, self.catcher_name)
                        if config:
                            self.catcher_x = config['x']
                            self.catcher_y = config['y']
                            self.catcher_width = config['width']
                            self.catcher_height = config['height']
                            log.info(f"[ClickCatcher] Updated {self.catcher_name} position for new resolution {current_resolution}: ({self.catcher_x}, {self.catcher_y}) size {self.catcher_width}x{self.catcher_height}")
                        else:
                            log.warning(f"[ClickCatcher] No config found for {self.catcher_name} at resolution {current_resolution}")
                    else:
                        log.warning(f"[ClickCatcher] Unsupported resolution: {current_resolution}")
                
                # Update stored resolution
                self._current_resolution = current_resolution
                
                # Recreate components with new resolution
                self._create_components()
                
        except Exception as e:
            log.error(f"[ClickCatcher] Error checking resolution: {e}")
    
    def cleanup(self):
        """Clean up the click catcher"""
        try:
            # Unregister from global registry
            self._unregister_click_catcher()
            
            # Properly destroy the PyQt6 widget
            self.deleteLater()
            log.debug("[ClickCatcher] Cleaned up and scheduled for deletion")
        except Exception as e:
            log.debug(f"[ClickCatcher] Error during cleanup: {e}")
    
    def on_click_detected(self):
        """
        Method to be implemented by subclasses
        Called when a click is detected in the click catcher area
        """
        raise NotImplementedError("Subclasses must implement on_click_detected method")


def test_mouse_monitoring():
    """Test function to verify mouse monitoring is working"""
    log.info("[ClickCatcher] Testing mouse monitoring functionality...")
    
    # Create a test click catcher (using ClickCatcherHide as default implementation)
    from ui.click_catcher_hide import ClickCatcherHide
    test_catcher = ClickCatcherHide(x=100, y=100, width=50, height=50, shape='rectangle')
    
    def test_click_handler():
        log.info("[ClickCatcher] ✓ Test click detected!")
    
    test_catcher.click_detected.connect(test_click_handler)
    
    log.info("[ClickCatcher] Test click catcher created at (100, 100). Click in that area to test.")
    log.info("[ClickCatcher] Click catchers registered: " + str(list(_click_catchers.keys())))
    
    return test_catcher
