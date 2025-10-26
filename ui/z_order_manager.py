#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Centralized Z-Order Management System
Replaces creation order dependency with explicit z-level management
"""

# Standard library imports
import ctypes
import threading
from typing import Dict, Optional

# Local imports
from utils.logging import get_logger

log = get_logger()


class ZOrderManager:
    """
    Centralized z-order management for all UI components
    Replaces fragile creation order dependency with explicit z-levels
    """
    
    # Explicit z-order levels (higher numbers = on top)
    Z_LEVELS = {
        'LEAGUE_WINDOW': 0,        # Base League window
        'UNOWNED_FRAME': 100,      # Golden border + lock icon (behind interactive elements)
        'DICE_BUTTON': 150,        # Dice button for random skin selection
        'CHROMA_BUTTON': 200,      # Circular chroma button (above unowned frame)
        'RANDOM_FLAG': 250,        # Random flag indicator (above chroma button)
        'CHROMA_PANEL': 300,       # Chroma selection panel (above flag)
        'CLICK_CATCHER': 400,      # Invisible overlay for click detection (topmost)
    }
    
    def __init__(self):
        self._widgets: Dict[str, object] = {}  # widget_name -> widget_instance
        self._z_levels: Dict[str, int] = {}    # widget_name -> z_level
        self._lock = threading.RLock()
        self._dirty = False  # Flag to track if z-order needs refresh
        self._last_refresh_time = 0.0
        self._refresh_interval = 0.1  # Refresh at most every 100ms
    
    def register_widget(self, widget, widget_name: str, z_level: int):
        """
        Register a widget with its z-level
        
        Args:
            widget: The widget instance
            widget_name: Unique name for the widget
            z_level: Z-level from Z_LEVELS constants
        """
        with self._lock:
            self._widgets[widget_name] = widget
            self._z_levels[widget_name] = z_level
            self._dirty = True
            # Only log registration for important widgets to reduce spam
            if widget_name in ['chroma_panel', 'unowned_frame']:
                log.debug(f"[Z-ORDER] Registered {widget_name} at z-level {z_level}")
    
    def unregister_widget(self, widget_name: str):
        """Unregister a widget"""
        with self._lock:
            if widget_name in self._widgets:
                del self._widgets[widget_name]
                del self._z_levels[widget_name]
                self._dirty = True
                # Only log unregistration for important widgets to reduce spam
                if widget_name in ['chroma_panel', 'unowned_frame']:
                    log.debug(f"[Z-ORDER] Unregistered {widget_name}")
    
    def set_z_level(self, widget_name: str, z_level: int):
        """Change a widget's z-level"""
        with self._lock:
            if widget_name in self._z_levels:
                self._z_levels[widget_name] = z_level
                self._dirty = True
                # Only log z-level changes for important widgets to reduce spam
                if widget_name in ['chroma_panel', 'unowned_frame']:
                    log.debug(f"[Z-ORDER] {widget_name} z-level changed to {z_level}")
    
    def refresh_z_order(self, force: bool = False):
        """
        Refresh z-order for all registered widgets
        Only refreshes if dirty or forced, and respects refresh interval
        
        Args:
            force: Force refresh even if not dirty
        """
        import time
        current_time = time.time()
        
        with self._lock:
            # Check if refresh is needed
            if not force and not self._dirty:
                return
            
            # Respect refresh interval
            if not force and (current_time - self._last_refresh_time) < self._refresh_interval:
                return
            
            # Sort widgets by z-level (ascending order)
            sorted_widgets = sorted(
                self._widgets.items(),
                key=lambda item: self._z_levels[item[0]]
            )
            
            # Apply z-order using Windows API
            self._apply_z_order(sorted_widgets)
            
            self._dirty = False
            self._last_refresh_time = current_time
    
    def _apply_z_order(self, sorted_widgets):
        """Apply z-order to widgets using Windows SetWindowPos"""
        try:
            # Windows API constants
            HWND_BOTTOM = 1
            HWND_TOP = 0
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            
            # Apply z-order: process widgets in ORDER (lowest z-level first)
            # Build a chain by placing each widget AFTER the previous one using the previous widget's HWND
            # This ensures: unowned_frame(100) < chroma_button(200) < random_flag(250) < chroma_panel(300) < click_catcher(400)
            
            # Debug: Log the processing order
            for widget_name, widget in sorted_widgets:
                log.debug(f"[Z-ORDER] Will process {widget_name} (level {self._z_levels[widget_name]})")
            
            # CORRECT APPROACH: Process in FORWARD order (lowest first), place each at HWND_TOP
            # Why: When you place at HWND_TOP, each new widget goes ABOVE the previous ones
            # So processing frame(100) → button(200) → panel(300) results in:
            # - frame placed first at top (then gets pushed down)
            # - button placed at top (above frame)
            # - panel placed at top (above button)
            # Final visual: frame < button < panel ✓
            
            for widget_name, widget in sorted_widgets:  # Process LOWEST to HIGHEST z-level
                try:
                    if not hasattr(widget, 'winId') or not widget.isVisible():
                        continue
                    
                    widget_hwnd = int(widget.winId())
                    z_level = self._z_levels[widget_name]
                    
                    # Place each widget at HWND_TOP in order from lowest to highest z-level
                    # This ensures lowest z-level is first (gets pushed to bottom)
                    # and highest z-level is last (stays on top)
                    result = ctypes.windll.user32.SetWindowPos(
                        widget_hwnd,
                        HWND_TOP,  # Place at top
                        0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                    )
                    
                    # Debug logging for z-order application
                    if widget_name in ['unowned_frame', 'chroma_button', 'chroma_panel']:
                        log.debug(f"[Z-ORDER] Applied z-order to {widget_name} (level {z_level}) - result: {bool(result)}")
                    
                    if not result:
                        # Only log failures, not successes to reduce spam
                        log.warning(f"[Z-ORDER] Failed to set z-order for {widget_name}")
                    
                except Exception as e:
                    log.debug(f"[Z-ORDER] Error setting z-order for {widget_name}: {e}")
            
            # No need for special "force" operations - the main loop already applies proper z-order
            # The sorted_widgets are processed in ascending z-level order, which naturally creates
            # the correct stacking: unowned_frame(100) < chroma_button(200) < random_flag(250) < chroma_panel(300)
            
            # Log the final widget order for debugging
            import time
            current_time = time.time()
            if not hasattr(self, '_last_apply_log_time'):
                self._last_apply_log_time = 0
            
            if current_time - self._last_apply_log_time >= 1.0:  # Log at most once per second
                self._last_apply_log_time = current_time
                widget_order = [f"{name}({self._z_levels[name]})" for name, _ in sorted_widgets]
                log.debug(f"[Z-ORDER] Applied z-order to {len(sorted_widgets)} widgets: {widget_order}")
                
                # Log which widgets are visible
                visible_widgets = []
                for name, widget in sorted_widgets:
                    if hasattr(widget, 'winId') and widget.isVisible():
                        visible_widgets.append(f"{name}({self._z_levels[name]})")
                log.debug(f"[Z-ORDER] Visible widgets: {visible_widgets}")
            
        except Exception as e:
            log.error(f"[Z-ORDER] Error applying z-order: {e}")
    
    def bring_to_front(self, widget_name: str):
        """Bring a specific widget to the front of its z-level"""
        with self._lock:
            if widget_name not in self._widgets:
                return
            
            try:
                widget = self._widgets[widget_name]
                if not hasattr(widget, 'winId') or not widget.isVisible():
                    return
                
                widget_hwnd = int(widget.winId())
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOACTIVATE = 0x0010
                
                # Bring to front
                result = ctypes.windll.user32.SetWindowPos(
                    widget_hwnd,
                    0,  # HWND_TOP
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                )
                
                if not result:
                    # Only log failures to reduce spam
                    log.warning(f"[Z-ORDER] Failed to bring {widget_name} to front")
                    
            except Exception as e:
                log.debug(f"[Z-ORDER] Error bringing {widget_name} to front: {e}")
    
    def get_widget_z_level(self, widget_name: str) -> Optional[int]:
        """Get the z-level of a widget"""
        with self._lock:
            return self._z_levels.get(widget_name)
    
    def get_all_widgets(self) -> Dict[str, object]:
        """Get all registered widgets"""
        with self._lock:
            return self._widgets.copy()
    
    def cleanup(self):
        """Clean up all registered widgets"""
        with self._lock:
            self._widgets.clear()
            self._z_levels.clear()
            self._dirty = False
            log.debug("[Z-ORDER] Manager cleaned up")


# Global z-order manager instance
_z_order_manager: Optional[ZOrderManager] = None


def get_z_order_manager() -> ZOrderManager:
    """Get or create the global z-order manager"""
    global _z_order_manager
    if _z_order_manager is None:
        _z_order_manager = ZOrderManager()
        log.debug("[Z-ORDER] Global z-order manager created")
    return _z_order_manager


def cleanup_z_order_manager():
    """Clean up the global z-order manager"""
    global _z_order_manager
    if _z_order_manager:
        _z_order_manager.cleanup()
        _z_order_manager = None
        log.debug("[Z-ORDER] Global z-order manager cleaned up")
