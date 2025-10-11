#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Click Catcher Overlay - Invisible layer to detect clicks outside chroma UI
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor
from utils.logging import get_logger

log = get_logger()


class ClickCatcherOverlay(QWidget):
    """
    Invisible overlay that fills the entire League window
    Positioned UNDER the chroma UI (lower z-order)
    Catches clicks to close the panel
    """
    
    def __init__(self, on_click_callback=None, parent_hwnd=None):
        super().__init__()
        self.on_click_callback = on_click_callback
        self._league_window_hwnd = parent_hwnd
        
        # Setup as transparent overlay
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Enable mouse tracking
        self.setMouseTracking(True)
        
        # Parent to League window if provided
        if parent_hwnd:
            self._parent_and_position()
    
    def _parent_and_position(self):
        """Parent to League and fill entire client area"""
        if not self._league_window_hwnd:
            return
        
        try:
            import ctypes
            from ctypes import wintypes
            
            widget_hwnd = int(self.winId())
            
            # Move to (0,0) before parenting
            self.move(0, 0)
            
            # Change to WS_CHILD style
            GWL_STYLE = -16
            WS_POPUP = 0x80000000
            WS_CHILD = 0x40000000
            
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
            else:  # 32-bit
                SetWindowLong = ctypes.windll.user32.SetWindowLongW
                SetWindowLong.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
                SetWindowLong.restype = ctypes.c_long
                GetWindowLong = ctypes.windll.user32.GetWindowLongW
                GetWindowLong.argtypes = [ctypes.c_void_p, ctypes.c_int]
                GetWindowLong.restype = ctypes.c_long
                
                current_style = GetWindowLong(widget_hwnd, GWL_STYLE)
                new_style = (current_style & ~WS_POPUP) | WS_CHILD
                SetWindowLong(widget_hwnd, GWL_STYLE, ctypes.c_long(new_style).value)
            
            # Parent to League
            result = ctypes.windll.user32.SetParent(widget_hwnd, self._league_window_hwnd)
            
            if result:
                # Get League client size
                client_rect = wintypes.RECT()
                ctypes.windll.user32.GetClientRect(self._league_window_hwnd, ctypes.byref(client_rect))
                
                league_width = client_rect.right
                league_height = client_rect.bottom
                
                # Fill entire League client area
                self.setGeometry(0, 0, league_width, league_height)
                
                # Position at (0, 0) and set to BOTTOM of z-order (under everything)
                HWND_BOTTOM = 1
                SWP_SHOWWINDOW = 0x0040
                ctypes.windll.user32.SetWindowPos(
                    widget_hwnd,
                    HWND_BOTTOM,  # Put at bottom of z-order (under panel/button)
                    0, 0,
                    league_width, league_height,
                    SWP_SHOWWINDOW
                )
                
                log.debug(f"[CHROMA] Click catcher overlay created ({league_width}x{league_height})")
            else:
                log.error("[CHROMA] Failed to parent click catcher to League window")
        except Exception as e:
            log.error(f"[CHROMA] Error creating click catcher: {e}")
    
    def paintEvent(self, event):
        """Paint the overlay - nearly transparent"""
        painter = QPainter(self)
        # Fill with nearly transparent black (alpha=1 so Qt detects mouse events)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
    
    def mousePressEvent(self, event):
        """Handle click on overlay - close panel"""
        if event.button() == Qt.MouseButton.LeftButton:
            log.debug("[CHROMA] Click caught on overlay, closing panel")
            if self.on_click_callback:
                self.on_click_callback()
        event.accept()

