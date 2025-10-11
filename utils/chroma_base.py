#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Base classes and configuration for Chroma UI components
"""

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt
from utils.window_utils import get_league_window_handle, get_league_window_rect_fast
import ctypes


class ChromaUIConfig:
    """
    Centralized configuration for chroma UI positioning
    Now uses dynamic scaling based on League window resolution
    """
    
    @classmethod
    def _get_scaled_values(cls):
        """Get scaled values for current resolution"""
        from utils.chroma_scaling import get_scaled_chroma_values
        return get_scaled_chroma_values()
    
    @classmethod
    @property
    def ANCHOR_OFFSET_X(cls):
        return cls._get_scaled_values().anchor_offset_x
    
    @classmethod
    @property
    def ANCHOR_OFFSET_Y(cls):
        return cls._get_scaled_values().anchor_offset_y
    
    @classmethod
    @property
    def BUTTON_OFFSET_X(cls):
        return cls._get_scaled_values().button_offset_x
    
    @classmethod
    @property
    def BUTTON_OFFSET_Y(cls):
        return cls._get_scaled_values().button_offset_y
    
    @classmethod
    @property
    def PANEL_OFFSET_X(cls):
        return cls._get_scaled_values().panel_offset_x
    
    @classmethod
    @property
    def PANEL_OFFSET_Y(cls):
        return cls._get_scaled_values().panel_offset_y
    
    @classmethod
    def get_anchor_point(cls, screen_geometry=None):
        """
        Get the anchor point - relative to League window center
        FAST version using cached window handle
        
        Args:
            screen_geometry: Screen geometry (for fallback if League window not found)
            
        Returns:
            Tuple of (x, y) coordinates for the anchor point
        """
        # Try fast path: get cached window handle and position
        try:
            hwnd = get_league_window_handle()
            if hwnd:
                window_rect = get_league_window_rect_fast(hwnd)
                if window_rect:
                    # League window found - calculate center quickly
                    left, top, right, bottom = window_rect
                    window_width = right - left
                    window_height = bottom - top
                    
                    # Calculate center of the League window CLIENT AREA
                    window_center_x = left + (window_width // 2)
                    window_center_y = top + (window_height // 2)
                    
                    # Apply offsets from scaled config
                    scaled = cls._get_scaled_values()
                    anchor_x = window_center_x + scaled.anchor_offset_x
                    anchor_y = window_center_y + scaled.anchor_offset_y
                    
                    return (anchor_x, anchor_y)
        except Exception:
            pass
        
        # Fallback: Use screen center if League window not found
        if screen_geometry:
            center_x = screen_geometry.width() // 2
            center_y = screen_geometry.height() // 2
        else:
            # Get screen geometry if not provided
            from PyQt6.QtWidgets import QApplication
            screen = QApplication.primaryScreen().geometry()
            center_x = screen.width() // 2
            center_y = screen.height() // 2
        
        scaled = cls._get_scaled_values()
        return (center_x + scaled.anchor_offset_x, center_y + scaled.anchor_offset_y)


class ChromaWidgetBase(QWidget):
    """
    Base class for chroma UI widgets (panel and button)
    Provides common functionality and synchronized positioning
    Uses Windows parent-child relationship to embed in League window
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_common_window_flags()
        self._anchor_offset_x = 0  # Override in child classes
        self._anchor_offset_y = 0  # Override in child classes
        self._widget_width = 0  # Store widget dimensions for repositioning
        self._widget_height = 0
        self._position_offset_x = 0  # Store position offsets
        self._position_offset_y = 0
        self._league_window_hwnd = None  # Store League window handle for parenting
    
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
        
        # Parent FIRST to the League window (changes coordinate system to client coords)
        self._parent_to_league_window()
        
        # THEN calculate and apply position (now in correct coordinate system)
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
                
                window_width = client_rect.right
                window_height = client_rect.bottom
            except Exception:
                return  # Failed to get client rect
            
            # Get scaled values based on ACTUAL League window resolution
            from utils.chroma_scaling import get_scaled_chroma_values
            scaled = get_scaled_chroma_values(resolution=(window_width, window_height), force_reload=False)
            
            # Calculate center of League client area (in client coordinates)
            center_x = window_width // 2
            center_y = window_height // 2
            
            # Apply offsets from scaled config (these are already scaled based on current resolution)
            anchor_x = center_x + scaled.anchor_offset_x
            anchor_y = center_y + scaled.anchor_offset_y
            
            # Calculate widget position (client coordinates - relative to parent's 0,0)
            # Widget's center should be at (anchor + offset)
            widget_x = anchor_x + self._position_offset_x - (self._widget_width // 2)
            widget_y = anchor_y + self._position_offset_y - (self._widget_height // 2)
            
            # Ensure widget stays within League window client area
            margin = scaled.screen_margin
            widget_x = max(margin, min(widget_x, window_width - self._widget_width - margin))
            widget_y = max(margin, min(widget_y, window_height - self._widget_height - margin))
            
            # Use Windows API to position child window (Qt's move() doesn't work well with WS_CHILD)
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_NOSIZE = 0x0001
            ctypes.windll.user32.SetWindowPos(
                widget_hwnd,
                0,  # hWndInsertAfter (ignored with NOZORDER)
                int(widget_x), int(widget_y),
                0, 0,  # width, height (ignored with NOSIZE)
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOSIZE
            )
        else:
            # Fallback to screen coordinates (original behavior)
            screen = QApplication.primaryScreen().geometry()
            anchor_x, anchor_y = ChromaUIConfig.get_anchor_point(screen)
            
            # Calculate position: center the widget's CENTER on the anchor point + offset
            widget_x = anchor_x + self._position_offset_x - (self._widget_width // 2)
            widget_y = anchor_y + self._position_offset_y - (self._widget_height // 2)
            
            # Ensure widget stays on screen
            from utils.chroma_scaling import get_scaled_chroma_values
            margin = get_scaled_chroma_values().screen_margin
            widget_x = max(margin, min(widget_x, screen.width() - self._widget_width - margin))
            widget_y = max(margin, min(widget_y, screen.height() - self._widget_height - margin))
            
            self.move(widget_x, widget_y)
    
    def update_position_if_needed(self):
        """
        Update position if League window has moved or resolution changed
        Call this periodically from the main loop
        
        Note: When parented to League window, Windows automatically moves child windows,
        but we still need to handle resolution changes and repositioning
        """
        if self.isVisible() and self._widget_width > 0:
            # Check if we need to re-parent (League window might have changed)
            if not self._league_window_hwnd or not self._is_parented_correctly():
                self._parent_to_league_window()
            elif self._league_window_hwnd:
                # Refresh z-order to stay on top within parent (prevents League from covering us)
                self._refresh_z_order()
                
                # ALWAYS update position when parented (handles resolution changes)
                # This is cheap since it just uses SetWindowPos
                self._update_position()
            else:
                # Not parented - update position for tracking mode
                self._update_position()
    
    def _refresh_z_order(self):
        """Keep widget on top within parent window hierarchy"""
        try:
            widget_hwnd = int(self.winId())
            HWND_TOP = 0
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            
            # Move to top of z-order without activating
            ctypes.windll.user32.SetWindowPos(
                widget_hwnd,
                HWND_TOP,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            )
        except Exception:
            pass  # Silently fail if z-order refresh fails
    
    def _parent_to_league_window(self):
        """
        Make this widget a child window of the League client window
        This makes Windows automatically handle positioning and occlusion
        """
        try:
            # Get League window handle
            league_hwnd = get_league_window_handle()
            if not league_hwnd:
                return
            
            # Get this widget's window handle
            widget_hwnd = int(self.winId())
            
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
                
                # Log success (only once per widget)
                if not hasattr(self, '_parent_log_shown'):
                    from utils.logging import get_logger
                    log = get_logger()
                    log.info(f"[CHROMA] Widget {self.__class__.__name__} parented to League window (child window style)")
                    self._parent_log_shown = True
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

