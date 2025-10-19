#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma UI Resolution Scaling Utilities
Provides dynamic scaling based on League window resolution
"""

from typing import Tuple, Optional
from utils.window_utils import get_league_window_client_size
import config


# DEPRECATED - Scaling cache removed, now using hard-coded values


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
    return (config.CHROMA_UI_REFERENCE_WIDTH, config.CHROMA_UI_REFERENCE_HEIGHT)


# DEPRECATED - All scaling functions removed
# Use hard-coded values from CHROMA_PANEL_CONFIGS instead


class ScaledChromaValues:
    """
    Container for all hard-coded chroma UI values
    Uses fixed pixel values for three supported resolutions
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
        
        # Load hard-coded values for this resolution
        self._load_hardcoded_values()
    
    def _load_hardcoded_values(self):
        """Load hard-coded values for the current resolution"""
        resolution_key = (self.width, self.height)
        
        if resolution_key in config.CHROMA_PANEL_CONFIGS:
            # Use hard-coded values for supported resolution
            config_values = config.CHROMA_PANEL_CONFIGS[resolution_key]
            self.preview_width = config_values['preview_width']
            self.preview_height = config_values['preview_height']
            self.circle_radius = config_values['circle_radius']
            self.window_width = config_values['window_width']
            self.window_height = config_values['window_height']
            self.circle_spacing = config_values['circle_spacing']
            self.button_size = config_values['button_size']
            self.button_width = config_values['button_width']
            self.button_height = config_values['button_height']
            self.screen_edge_margin = config_values['screen_edge_margin']
            self.preview_x = config_values['preview_x']
            self.preview_y = config_values['preview_y']
            self.row_y_offset = config_values['row_y_offset']
            self.panel_x = config_values['panel_x']
            self.panel_y = config_values['panel_y']
        else:
            # Fallback to 1600x900 values for unsupported resolutions
            fallback_config = config.CHROMA_PANEL_CONFIGS[(1600, 900)]
            self.preview_width = fallback_config['preview_width']
            self.preview_height = fallback_config['preview_height']
            self.circle_radius = fallback_config['circle_radius']
            self.window_width = fallback_config['window_width']
            self.window_height = fallback_config['window_height']
            self.circle_spacing = fallback_config['circle_spacing']
            self.button_size = fallback_config['button_size']
            self.button_width = fallback_config['button_width']
            self.button_height = fallback_config['button_height']
            self.screen_edge_margin = fallback_config['screen_edge_margin']
            self.preview_x = fallback_config['preview_x']
            self.preview_y = fallback_config['preview_y']
            self.row_y_offset = fallback_config['row_y_offset']
            self.panel_x = fallback_config['panel_x']
            self.panel_y = fallback_config['panel_y']
        
        # Button visual dimensions (fixed values)
        # Increase gold border by 1px for maximum resolution (1600x900)
        if resolution_key == (1600, 900):
            self.gold_border_px = 3  # Increased from 2 to 3px for 1600x900
        else:
            self.gold_border_px = 2  # Keep 2px for other resolutions
        self.dark_border_px = 3
        self.gradient_ring_px = 4
        self.inner_disk_radius_px = 2.5
        
        # Note: UI positioning offsets removed - now calculated directly from config ratios
        # in real-time to support hot-reload and prevent caching issues
    
    def __repr__(self):
        return f"ScaledChromaValues({self.width}x{self.height}, hardcoded=True)"


def get_scaled_chroma_values(resolution: Optional[Tuple[int, int]] = None, force_reload: bool = False) -> ScaledChromaValues:
    """
    Get hard-coded chroma values for the specified resolution
    
    Args:
        resolution: (width, height) or None to auto-detect
        force_reload: Ignored (kept for compatibility)
        
    Returns:
        ScaledChromaValues instance with hard-coded values for the resolution
    """
    # Always return a new instance with hard-coded values
    # No caching needed since values are now hard-coded
    return ScaledChromaValues(resolution)


# DEPRECATED - Scale factor no longer used with hard-coded values
def get_ui_scale() -> float:
    """
    DEPRECATED - Always returns 1.0 since we now use hard-coded values
    
    Returns:
        Always 1.0 (kept for compatibility)
    """
    return 1.0

