#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Base classes and configuration for Chroma UI components
"""

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt
from utils.window_utils import get_league_window_handle, get_league_window_rect_fast


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
    
    def _setup_common_window_flags(self):
        """Setup common window flags and attributes for chroma UI"""
        # Frameless, always-on-top window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
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
        
        # Calculate and apply position
        self._update_position()
    
    def _update_position(self):
        """Update widget position based on current League window position"""
        screen = QApplication.primaryScreen().geometry()
        anchor_x, anchor_y = ChromaUIConfig.get_anchor_point(screen)
        
        # Calculate position: center the widget's CENTER on the anchor point + offset
        # This ensures both button and panel have their centers aligned at the anchor point
        # (since both have offset_x = 0)
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
        Update position if League window has moved
        Call this periodically from the main loop
        """
        if self.isVisible() and self._widget_width > 0:
            self._update_position()
    
    def get_screen_center(self):
        """Get screen center coordinates (for backward compatibility)"""
        screen = QApplication.primaryScreen().geometry()
        return (screen.width() // 2, screen.height() // 2)

