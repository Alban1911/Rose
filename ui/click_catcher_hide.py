#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ClickCatcherHide - UI component for detecting clicks on specific UI elements
Invisible overlay that detects clicks and triggers UI opacity changes

Usage:
    # Create instance
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
    - White circle at 65% opacity for debugging (can be made fully invisible)
    - Positioned using absolute coordinates in League window
    - Automatically handles resolution changes and League window parenting
    - Integrates with z-order management system
"""

from PyQt6.QtWidgets import QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QColor
from ui.chroma_base import ChromaWidgetBase
from ui.z_order_manager import ZOrderManager
from utils.logging import get_logger

log = get_logger()


class ClickCatcherHide(ChromaWidgetBase):
    """
    Invisible click catcher that detects clicks on specific UI elements
    Used to trigger UI opacity changes when settings button is pressed
    """
    
    # Signal emitted when click is detected
    click_detected = pyqtSignal()
    
    def __init__(self, state=None, x=0, y=0, width=50, height=50, shape='circle'):
        # Initialize with explicit z-level for click catchers
        super().__init__(
            z_level=ZOrderManager.Z_LEVELS['CLICK_CATCHER'],
            widget_name='click_catcher_hide'
        )
        
        # Store reference to shared state
        self.state = state
        
        # Position and size for the click catcher
        self.catcher_x = x
        self.catcher_y = y
        self.catcher_width = width
        self.catcher_height = height
        self.shape = shape  # 'circle' or 'rectangle'
        
        # Create opacity effect for visual debugging (65% opacity white circle)
        self.opacity_effect = QGraphicsOpacityEffect()
        self.opacity_effect.setOpacity(0.65)  # 65% opacity for debugging
        self.setGraphicsEffect(self.opacity_effect)
        
        # Track resolution for change detection
        self._current_resolution = None
        
        # Create the click catcher component
        self._create_components()
        
        # Start hidden
        self.hide()
        
        log.debug(f"[ClickCatcherHide] Created at ({x}, {y}) size {width}x{height}")
    
    def _create_components(self):
        """Create the click catcher component with precise positioning"""
        # Get League window for positioning
        from utils.window_utils import get_league_window_handle, find_league_window_rect
        import ctypes
        
        # Get League window handle and size
        league_hwnd = get_league_window_handle()
        window_rect = find_league_window_rect()
        if not league_hwnd or not window_rect:
            log.debug("[ClickCatcherHide] Could not get League window for positioning")
            return
        
        window_left, window_top, window_right, window_bottom = window_rect
        window_width = window_right - window_left
        window_height = window_bottom - window_top
        
        # Set exact size
        self.setFixedSize(self.catcher_width, self.catcher_height)
        
        # Get widget handle and parent to League window
        widget_hwnd = int(self.winId())
        ctypes.windll.user32.SetParent(widget_hwnd, league_hwnd)
        
        # Set window style to WS_CHILD (64-bit compatible)
        GWL_STYLE = -16
        WS_CHILD = 0x40000000
        WS_POPUP = 0x80000000
        
        if ctypes.sizeof(ctypes.c_void_p) == 8:  # 64-bit
            SetWindowLongPtr = ctypes.windll.user32.SetWindowLongPtrW
            SetWindowLongPtr.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
            SetWindowLongPtr.restype = ctypes.c_longlong
            GetWindowLongPtr = ctypes.windll.user32.GetWindowLongPtrW
            GetWindowLongPtr.argtypes = [ctypes.c_void_p, ctypes.c_int]
            GetWindowLongPtr.restype = ctypes.c_longlong
            
            current_style = GetWindowLongPtr(widget_hwnd, GWL_STYLE)
            new_style = (current_style & ~WS_POPUP) | WS_CHILD
            SetWindowLongPtr(widget_hwnd, GWL_STYLE, new_style)
        else:
            current_style = ctypes.windll.user32.GetWindowLongW(widget_hwnd, GWL_STYLE)
            new_style = (current_style & ~WS_POPUP) | WS_CHILD
            ctypes.windll.user32.SetWindowLongW(widget_hwnd, GWL_STYLE, new_style)
        
        # Position precisely in League window client coordinates
        # Since we're a child window, coordinates are relative to the parent's client area
        HWND_TOP = 0
        ctypes.windll.user32.SetWindowPos(
            widget_hwnd, HWND_TOP, self.catcher_x, self.catcher_y, 0, 0,
            0x0001 | 0x0004  # SWP_NOSIZE | SWP_NOZORDER
        )
        
        # Store resolution for change detection
        self._current_resolution = (window_width, window_height)
        
        log.debug(f"[ClickCatcherHide] Positioned at ({self.catcher_x}, {self.catcher_y}) size {self.catcher_width}x{self.catcher_height}")
    
    def paintEvent(self, event):
        """Paint the click catcher - white shape at 65% opacity for debugging"""
        painter = QPainter(self)
        
        # Fill with white shape at 65% opacity for debugging
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(255, 255, 255, 166))  # White with ~65% opacity (166/255)
        painter.setPen(Qt.PenStyle.NoPen)
        
        # Draw shape based on type
        if self.shape == 'rectangle':
            painter.drawRect(self.rect())
        else:  # circle
            painter.drawEllipse(self.rect())
    
    def mousePressEvent(self, event):
        """Handle mouse press events - emit signal when clicked"""
        if event.button() == Qt.MouseButton.LeftButton:
            log.debug("[ClickCatcherHide] Click detected")
            self.click_detected.emit()
        event.accept()
    
    def show_catcher(self):
        """Show the click catcher"""
        self.show()
        log.debug("[ClickCatcherHide] Click catcher shown")
    
    def hide_catcher(self):
        """Hide the click catcher"""
        self.hide()
        log.debug("[ClickCatcherHide] Click catcher hidden")
    
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
        
        log.debug(f"[ClickCatcherHide] Position updated to ({x}, {y}) size {self.catcher_width}x{self.catcher_height}")
    
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
                log.info(f"[ClickCatcherHide] Resolution changed from {self._current_resolution} to {current_resolution}, recreating components")
                # Recreate components with new resolution
                self._create_components()
                
        except Exception as e:
            log.error(f"[ClickCatcherHide] Error checking resolution: {e}")
    
    def cleanup(self):
        """Clean up the click catcher"""
        try:
            # Properly destroy the PyQt6 widget
            self.hide()
            self.deleteLater()
            log.debug("[ClickCatcherHide] Cleaned up and scheduled for deletion")
        except Exception as e:
            log.debug(f"[ClickCatcherHide] Error during cleanup: {e}")
