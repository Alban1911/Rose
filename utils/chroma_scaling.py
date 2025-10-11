#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma UI Resolution Scaling Utilities
Provides dynamic scaling based on League window resolution
"""

from typing import Tuple, Optional
from utils.window_utils import get_league_window_client_size
from config import (
    CHROMA_UI_REFERENCE_WIDTH, CHROMA_UI_REFERENCE_HEIGHT,
    # Dimension ratios
    CHROMA_PANEL_PREVIEW_WIDTH_RATIO, CHROMA_PANEL_PREVIEW_HEIGHT_RATIO,
    CHROMA_PANEL_CIRCLE_RADIUS_RATIO, CHROMA_PANEL_WINDOW_WIDTH_RATIO,
    CHROMA_PANEL_WINDOW_HEIGHT_RATIO, CHROMA_PANEL_CIRCLE_SPACING_RATIO,
    CHROMA_PANEL_BUTTON_SIZE_RATIO,
    # Positioning ratios
    CHROMA_PANEL_SCREEN_EDGE_MARGIN_RATIO, CHROMA_PANEL_PREVIEW_X_RATIO,
    CHROMA_PANEL_PREVIEW_Y_RATIO, CHROMA_PANEL_ROW_Y_OFFSET_RATIO,
    # Button visual ratios
    CHROMA_PANEL_GOLD_BORDER_PX_RATIO, CHROMA_PANEL_DARK_BORDER_PX_RATIO,
    CHROMA_PANEL_GRADIENT_RING_PX_RATIO, CHROMA_PANEL_INNER_DISK_RADIUS_PX_RATIO,
    # UI positioning ratios
    CHROMA_UI_ANCHOR_OFFSET_X_RATIO, CHROMA_UI_ANCHOR_OFFSET_Y_RATIO,
    CHROMA_UI_BUTTON_OFFSET_X_RATIO, CHROMA_UI_BUTTON_OFFSET_Y_RATIO,
    CHROMA_UI_PANEL_OFFSET_X_RATIO, CHROMA_UI_PANEL_OFFSET_Y_BASE_RATIO,
    CHROMA_UI_SCREEN_MARGIN_RATIO
)


# Cache for scaling values to avoid recalculating every frame
_scale_cache = {
    'resolution': None,
    'scale_factor': 1.0,
    'values': {}
}


def get_league_resolution() -> Tuple[int, int]:
    """
    Get current League window resolution
    
    Returns:
        Tuple of (width, height), defaults to reference resolution if not detected
    """
    client_size = get_league_window_client_size()
    if client_size:
        return client_size
    # Fallback to reference resolution
    return (CHROMA_UI_REFERENCE_WIDTH, CHROMA_UI_REFERENCE_HEIGHT)


def get_scale_factor(resolution: Optional[Tuple[int, int]] = None) -> float:
    """
    Calculate scale factor based on League window resolution
    
    Args:
        resolution: (width, height) tuple, or None to auto-detect
        
    Returns:
        Scale factor (1.0 = reference resolution 1600x900)
    """
    if resolution is None:
        resolution = get_league_resolution()
    
    width, height = resolution
    
    # Scale based on height (more consistent for 16:9 aspect ratios)
    scale = height / CHROMA_UI_REFERENCE_HEIGHT
    
    return scale


def get_scaled_value(ratio: float, resolution: Optional[Tuple[int, int]] = None) -> int:
    """
    Get scaled pixel value from ratio
    
    Args:
        ratio: The ratio value (e.g., 0.036667 for button size)
        resolution: Optional resolution tuple, will auto-detect if None
        
    Returns:
        Scaled integer pixel value
    """
    if resolution is None:
        resolution = get_league_resolution()
    
    _, height = resolution
    return int(ratio * height)


class ScaledChromaValues:
    """
    Container for all scaled chroma UI values
    Auto-detects League resolution and scales all values accordingly
    """
    
    def __init__(self, resolution: Optional[Tuple[int, int]] = None):
        """
        Initialize with detected or specified resolution
        
        Args:
            resolution: (width, height) or None to auto-detect
        """
        if resolution is None:
            resolution = get_league_resolution()
        
        self.resolution = resolution
        self.width, self.height = resolution
        self.scale_factor = get_scale_factor(resolution)
        
        # Calculate all scaled values
        self._calculate_values()
    
    def _calculate_values(self):
        """Calculate all scaled values from ratios"""
        h = self.height
        
        # Panel dimensions
        self.preview_width = int(CHROMA_PANEL_PREVIEW_WIDTH_RATIO * h)
        self.preview_height = int(CHROMA_PANEL_PREVIEW_HEIGHT_RATIO * h)
        self.circle_radius = int(CHROMA_PANEL_CIRCLE_RADIUS_RATIO * h)
        self.window_width = int(CHROMA_PANEL_WINDOW_WIDTH_RATIO * h)
        self.window_height = int(CHROMA_PANEL_WINDOW_HEIGHT_RATIO * h)
        self.circle_spacing = int(CHROMA_PANEL_CIRCLE_SPACING_RATIO * h)
        self.button_size = int(CHROMA_PANEL_BUTTON_SIZE_RATIO * h)
        
        # Ensure button size is odd (for true center pixel)
        if self.button_size % 2 == 0:
            self.button_size += 1
        
        # Panel positioning
        self.screen_edge_margin = int(CHROMA_PANEL_SCREEN_EDGE_MARGIN_RATIO * h)
        self.preview_x = int(CHROMA_PANEL_PREVIEW_X_RATIO * h)
        self.preview_y = int(CHROMA_PANEL_PREVIEW_Y_RATIO * h)
        self.row_y_offset = int(CHROMA_PANEL_ROW_Y_OFFSET_RATIO * h)
        
        # Button visual dimensions
        self.gold_border_px = CHROMA_PANEL_GOLD_BORDER_PX_RATIO * h
        self.dark_border_px = CHROMA_PANEL_DARK_BORDER_PX_RATIO * h
        self.gradient_ring_px = CHROMA_PANEL_GRADIENT_RING_PX_RATIO * h
        self.inner_disk_radius_px = CHROMA_PANEL_INNER_DISK_RADIUS_PX_RATIO * h
        
        # UI positioning
        self.anchor_offset_x = int(CHROMA_UI_ANCHOR_OFFSET_X_RATIO * h)
        self.anchor_offset_y = int(CHROMA_UI_ANCHOR_OFFSET_Y_RATIO * h)
        self.button_offset_x = int(CHROMA_UI_BUTTON_OFFSET_X_RATIO * h)
        self.button_offset_y = int(CHROMA_UI_BUTTON_OFFSET_Y_RATIO * h)
        self.panel_offset_x = int(CHROMA_UI_PANEL_OFFSET_X_RATIO * h)
        self.panel_offset_y_base = int(CHROMA_UI_PANEL_OFFSET_Y_BASE_RATIO * h)
        self.screen_margin = int(CHROMA_UI_SCREEN_MARGIN_RATIO * h)
        
        # Calculate final panel offset (with button size adjustment)
        self.panel_offset_y = self.panel_offset_y_base - (self.button_size // 2)
    
    def __repr__(self):
        return f"ScaledChromaValues({self.width}x{self.height}, scale={self.scale_factor:.2f})"


def get_scaled_chroma_values(resolution: Optional[Tuple[int, int]] = None) -> ScaledChromaValues:
    """
    Get scaled chroma values with caching
    
    Args:
        resolution: (width, height) or None to auto-detect
        
    Returns:
        ScaledChromaValues instance with all scaled values
    """
    global _scale_cache
    
    if resolution is None:
        resolution = get_league_resolution()
    
    # Return cached values if resolution hasn't changed
    if _scale_cache['resolution'] == resolution:
        return _scale_cache['values']
    
    # Calculate new values
    scaled = ScaledChromaValues(resolution)
    
    # Update cache
    _scale_cache['resolution'] = resolution
    _scale_cache['scale_factor'] = scaled.scale_factor
    _scale_cache['values'] = scaled
    
    return scaled


# Convenience function for getting just the scale factor
def get_ui_scale() -> float:
    """
    Get current UI scale factor (1.0 = reference resolution)
    
    Returns:
        Scale factor based on League window height
    """
    return get_scale_factor()

