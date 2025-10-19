#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Base classes and configuration for Chroma UI components
"""

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt
from utils.window_utils import get_league_window_handle
from ui.z_order_manager import get_z_order_manager, ZOrderManager
import ctypes


# ChromaUIConfig class removed - no longer needed
# All positioning is now done directly in ChromaWidgetBase using config ratios


class ChromaWidgetBase(QWidget):
    """
    Base class for chroma UI widgets (panel and button)
    Provides common functionality and synchronized positioning
    Uses Windows parent-child relationship to embed in League window
    Now uses centralized z-order management instead of creation order dependency
    """
    
    def __init__(self, parent=None, z_level: int = None, widget_name: str = None):
        super().__init__(parent)
        self._setup_common_window_flags()
        self._anchor_offset_x = 0  # Override in child classes
        self._anchor_offset_y = 0  # Override in child classes
        self._widget_width = 0  # Store widget dimensions for repositioning
        self._widget_height = 0
        self._position_offset_x = 0  # Store position offsets
        self._position_offset_y = 0
        self._league_window_hwnd = None  # Store League window handle for parenting
        
        # Z-order management
        self._z_level = z_level
        self._widget_name = widget_name
        self._z_manager = get_z_order_manager()
        
        # Register with z-order manager if both z_level and widget_name are provided
        if z_level is not None and widget_name is not None:
            self._z_manager.register_widget(self, widget_name, z_level)
    
    def _setup_common_window_flags(self):
        """Setup common window flags and attributes for chroma UI"""
        # Frameless window - NO WindowStaysOnTopHint since we'll parent to League
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Enable mouse tracking for hover effects
        self.setMouseTracking(True)
    
    def position_relative_to_anchor(self, width: int, height: int, offset_x: int = 0, offset_y: int = 0):
        """
        Position this widget relative to the global anchor point
        
        Args:
            width: Widget width
            height: Widget height
            offset_x: Additional X offset from anchor (positive = right)
            offset_y: Additional Y offset from anchor (positive = down)
        """
        # Store dimensions and offsets for later updates
        self._widget_width = width
        self._widget_height = height
        self._position_offset_x = offset_x
        self._position_offset_y = offset_y
        
        # Parent to League window (child window - Windows handles positioning automatically)
        self._parent_to_league_window()
        
        # Calculate and apply position in client coordinates
        self._update_position()
    
    def _update_position(self):
        """Update widget position relative to League window (in client coordinates if parented)"""
        # If we're parented to League, use client coordinates; otherwise use screen coordinates
        if self._league_window_hwnd:
            # Get this widget's window handle for positioning
            widget_hwnd = int(self.winId())
            
            # Get League window client area size ONLY (no screen coordinates needed!)
            # Windows automatically handles the screen position since we're a child window
            try:
                from ctypes import wintypes
                client_rect = wintypes.RECT()
                ctypes.windll.user32.GetClientRect(self._league_window_hwnd, ctypes.byref(client_rect))
                
                window_width = client_rect.right - client_rect.left
                window_height = client_rect.bottom - client_rect.top
            except Exception:
                return  # Failed to get client rect
            
            # Hardcoded positions for each resolution (no scaling)
            if window_width == 1600 and window_height == 900:
                # 1600x900 resolution
                widget_x = 778
                widget_y = 700
            elif window_width == 1280 and window_height == 720:
                # 1280x720 resolution
                widget_x = 622
                widget_y = 560
            elif window_width == 1024 and window_height == 576:
                # 1024x576 resolution
                widget_x = 496
                widget_y = 446
            else:
                # Unsupported resolution - use default 1600x900 values
                from utils.logging import get_logger
                log = get_logger()
                log.warning(f"[CHROMA] Unsupported resolution {window_width}x{window_height}, using 1600x900 defaults")
                widget_x = 777
                widget_y = 700
            
            # Debug logging for position calculation
            from utils.logging import get_logger
            log = get_logger()
            log.debug(f"[CHROMA] {self.__class__.__name__} positioned at client coords ({widget_x}, {widget_y})")
            
            # Use Windows API to position child window in client coordinates
            # These coordinates are RELATIVE TO PARENT WINDOW, not screen!
            SWP_NOACTIVATE = 0x0010
            SWP_NOSIZE = 0x0001
            HWND_TOP = 0  # Place at top of z-order (above UnownedFrame)
            result = ctypes.windll.user32.SetWindowPos(
                widget_hwnd,
                HWND_TOP,  # hWndInsertAfter - place at top of z-order
                int(widget_x), int(widget_y),
                0, 0,  # width, height (ignored with NOSIZE)
                SWP_NOACTIVATE | SWP_NOSIZE  # Removed SWP_NOZORDER to allow positioning
            )
            
            if not result:
                from utils.logging import get_logger
                log = get_logger()
                log.error(f"[CHROMA] SetWindowPos FAILED for {self.__class__.__name__} (error: {ctypes.get_last_error()})")
            
            # Note: Z-order will be handled by the refresh mechanism
            
            # Verify position was actually set
            from ctypes import wintypes
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(widget_hwnd, ctypes.byref(rect))
            log.debug(f"[CHROMA] {self.__class__.__name__} positioned at ({rect.left}, {rect.top}) with size ({rect.right - rect.left}, {rect.bottom - rect.top})")
            
            # Convert to client coordinates relative to parent
            point = wintypes.POINT()
            point.x = rect.left
            point.y = rect.top
            ctypes.windll.user32.ScreenToClient(self._league_window_hwnd, ctypes.byref(point))
            
            from utils.logging import get_logger
            log = get_logger()
            log.info(f"  - VERIFIED actual position: ({point.x}, {point.y})")
        else:
            # Not parented to League - should not happen in normal operation
            from utils.logging import get_logger
            log = get_logger()
            log.error(f"[CHROMA] {self.__class__.__name__} not parented - cannot position widget!")
            self.hide()
    
    def update_position_if_needed(self):
        """
        Update position if League window has moved or resolution changed
        Call this periodically from the main loop
        
        Note: When parented to League window, Windows automatically moves child windows,
        but we still need to handle resolution changes and repositioning
        """
        if self.isVisible() and self._widget_width > 0:
            # Check if we need to re-parent (League window might have changed)
            # Only check once per second to avoid overhead
            import time
            current_time = time.time()
            if not hasattr(self, '_last_parent_check'):
                self._last_parent_check = 0
            
            # Check parenting status at most once per second
            if current_time - self._last_parent_check >= 1.0:
                self._last_parent_check = current_time
                
                if not self._league_window_hwnd or not self._is_parented_correctly():
                    self._parent_to_league_window()
            
            # Z-order is now managed centrally - no need for individual widget z-order refresh
            # The z-order manager handles all z-order updates efficiently
    
    def refresh_z_order(self):
        """Refresh z-order using centralized manager"""
        if self._widget_name:
            self._z_manager.refresh_z_order()
    
    def bring_to_front(self):
        """Bring this widget to the front of its z-level"""
        if self._widget_name:
            self._z_manager.bring_to_front(self._widget_name)
    
    def set_z_level(self, z_level: int):
        """Change this widget's z-level"""
        if self._widget_name:
            self._z_manager.set_z_level(self._widget_name, z_level)
            self._z_level = z_level
    
    def _parent_to_league_window(self):
        """
        Make this widget a child window of the League client window
        This makes Windows automatically handle positioning and occlusion
        """
        try:
            # Get League window handle
            league_hwnd = get_league_window_handle()
            if not league_hwnd:
                from utils.logging import get_logger
                log = get_logger()
                log.warning(f"[CHROMA] Cannot parent {self.__class__.__name__} - League window not found")
                return
            
            # Get this widget's window handle
            widget_hwnd = int(self.winId())
            
            # IMPORTANT: Clear any existing parent first (handles rebuilds)
            current_parent = ctypes.windll.user32.GetParent(widget_hwnd)
            if current_parent and current_parent != league_hwnd:
                ctypes.windll.user32.SetParent(widget_hwnd, 0)  # Un-parent first
                QApplication.processEvents()
            
            # Move widget to (0, 0) in screen coordinates BEFORE parenting
            # This prevents Qt from caching a screen position that might interfere
            self.move(0, 0)
            QApplication.processEvents()  # Ensure Qt processes the move
            
            # First, change the window style to WS_CHILD to make it a proper child window
            # This prevents Qt from fighting with Windows over positioning
            GWL_STYLE = -16
            WS_POPUP = 0x80000000
            WS_CHILD = 0x40000000
            
            # Define SetWindowLongW with proper types for 64-bit compatibility
            if ctypes.sizeof(ctypes.c_void_p) == 8:  # 64-bit
                # Use SetWindowLongPtrW for 64-bit
                SetWindowLongPtr = ctypes.windll.user32.SetWindowLongPtrW
                SetWindowLongPtr.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
                SetWindowLongPtr.restype = ctypes.c_longlong
                GetWindowLongPtr = ctypes.windll.user32.GetWindowLongPtrW
                GetWindowLongPtr.argtypes = [ctypes.c_void_p, ctypes.c_int]
                GetWindowLongPtr.restype = ctypes.c_longlong
                
                # Get current style
                current_style = GetWindowLongPtr(widget_hwnd, GWL_STYLE)
                
                # Remove WS_POPUP and add WS_CHILD
                new_style = (current_style & ~WS_POPUP) | WS_CHILD
                SetWindowLongPtr(widget_hwnd, GWL_STYLE, new_style)
            else:  # 32-bit
                # Use SetWindowLongW for 32-bit
                SetWindowLong = ctypes.windll.user32.SetWindowLongW
                SetWindowLong.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
                SetWindowLong.restype = ctypes.c_long
                GetWindowLong = ctypes.windll.user32.GetWindowLongW
                GetWindowLong.argtypes = [ctypes.c_void_p, ctypes.c_int]
                GetWindowLong.restype = ctypes.c_long
                
                # Get current style
                current_style = GetWindowLong(widget_hwnd, GWL_STYLE)
                
                # Remove WS_POPUP and add WS_CHILD
                new_style = (current_style & ~WS_POPUP) | WS_CHILD
                SetWindowLong(widget_hwnd, GWL_STYLE, ctypes.c_long(new_style).value)
            
            # Now set the parent
            result = ctypes.windll.user32.SetParent(widget_hwnd, league_hwnd)
            
            if result:
                self._league_window_hwnd = league_hwnd
                
                # Set window to always be on top WITHIN the parent window's child hierarchy
                HWND_TOPMOST = -1
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_SHOWWINDOW = 0x0040
                SWP_FRAMECHANGED = 0x0020  # Reapply frame after style change
                
                ctypes.windll.user32.SetWindowPos(
                    widget_hwnd,
                    HWND_TOPMOST,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_FRAMECHANGED
                )
                
                # Update position in client coordinates
                self._update_position()
                
                # Log success (show every time for rebuild debugging)
                from utils.logging import get_logger
                log = get_logger()
                
                # Get client rect for debugging
                from ctypes import wintypes
                client_rect = wintypes.RECT()
                ctypes.windll.user32.GetClientRect(league_hwnd, ctypes.byref(client_rect))
                log.info(f"[CHROMA] ✅ {self.__class__.__name__} parented to League window ({client_rect.right}x{client_rect.bottom})")
            else:
                from utils.logging import get_logger
                log = get_logger()
                log.error(f"[CHROMA] SetParent failed for {self.__class__.__name__} (result=0)")
        except Exception as e:
            # Parenting failed, will use fallback tracking mode
            self._league_window_hwnd = None
            from utils.logging import get_logger
            log = get_logger()
            log.debug(f"[CHROMA] Failed to parent widget to League window: {e}, using fallback tracking")
    
    def _is_parented_correctly(self):
        """Check if this widget is still correctly parented to League window"""
        try:
            if not self._league_window_hwnd:
                return False
            
            # Get current parent
            widget_hwnd = int(self.winId())
            current_parent = ctypes.windll.user32.GetParent(widget_hwnd)
            
            return current_parent == self._league_window_hwnd
        except Exception:
            return False
    
    def get_screen_center(self):
        """Get screen center coordinates (for backward compatibility)"""
        screen = QApplication.primaryScreen().geometry()
        return (screen.width() // 2, screen.height() // 2)
    
    def cleanup(self):
        """Clean up widget and unregister from z-order manager"""
        if self._widget_name:
            self._z_manager.unregister_widget(self._widget_name)
            self._widget_name = None
            self._z_level = None

