#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Resolution Utilities - Handles resolution-based positioning and sizing for UI components
Supports 3 resolutions: 1600x900, 1280x720, 1024x576
"""

from typing import Dict, Tuple, Optional
from utils.logging import get_logger

log = get_logger()

# Resolution configurations
RESOLUTIONS = {
    (1600, 900): "1600x900",
    (1280, 720): "1280x720", 
    (1024, 576): "1024x576"
}

# Click catcher positions and sizes for each resolution (Summoner's Rift)
CLICK_CATCHER_CONFIGS = {
    "1600x900": {
        "EDIT_RUNES": {"x": 552, "y": 834, "width": 41, "height": 41},
        "REC_RUNES": {"x": 499, "y": 834, "width": 41, "height": 41},
        "SETTINGS": {"x": 1518, "y": 2, "width": 33, "height": 33},
        "SUM_L": {"x": 859, "y": 831, "width": 46, "height": 47},
        "SUM_R": {"x": 918, "y": 831, "width": 46, "height": 47},
        "WARD": {"x": 989, "y": 831, "width": 46, "height": 47},
        "EMOTES": {"x": 1048, "y": 832, "width": 46, "height": 46},
        "MESSAGE": {"x": 1431, "y": 834, "width": 48, "height": 40},
        "ABILITIES": {"x": 663, "y": 769, "width": 277, "height": 40},
        "QUESTS": {"x": 1479, "y": 834, "width": 47, "height": 40},
        "CLOSE_SETTINGS": {"x": 738, "y": 776, "width": 125, "height": 40},
        "CLOSE_EMOTES": {"x": 1467, "y": 73, "width": 40, "height": 40},
        "CLOSE_WARD": {"x": 0, "y": 0, "width": 1600, "height": 900},
        "CLOSE_MESSAGE_R": {"x": 1367, "y": 428, "width": 33, "height": 33},
        "CLOSE_MESSAGE_L": {"x": 961, "y": 440, "width": 33, "height": 33},
        "CLOSE_MESSAGE_M": {"x": 1431, "y": 834, "width": 48, "height": 40},
        "CLOSE_RUNES_X": {"x": 1443, "y": 80, "width": 40, "height": 40},
        "CLOSE_RUNES_L": {"x": 0, "y": 0, "width": 138, "height": 900},
        "CLOSE_RUNES_R": {"x": 1462, "y": 0, "width": 138, "height": 900},
        "CLOSE_RUNES_TOP": {"x": 0, "y": 0, "width": 1600, "height": 100},
        "CLOSE_SUM": {"x": 0, "y": 0, "width": 1600, "height": 900},
        "CLOSE_ABILITIES": {"x": 738, "y": 769, "width": 127, "height": 40},
        "CLOSE_QUESTS": {"x": 1362, "y": 111, "width": 30, "height": 30}
    },
    "1280x720": {
        "EDIT_RUNES": {"x": 441, "y": 667, "width": 34, "height": 34},
        "REC_RUNES": {"x": 399, "y": 667, "width": 34, "height": 34},
        "SETTINGS": {"x": 1214, "y": 2, "width": 27, "height": 27},
        "SUM_L": {"x": 687, "y": 664, "width": 37, "height": 38},
        "SUM_R": {"x": 734, "y": 664, "width": 37, "height": 38},
        "WARD": {"x": 791, "y": 664, "width": 37, "height": 38},
        "EMOTES": {"x": 838, "y": 665, "width": 37, "height": 37},
        "MESSAGE": {"x": 1144, "y": 667, "width": 39, "height": 32},
        "ABILITIES": {"x": 530, "y": 615, "width": 222, "height": 32},
        "QUESTS": {"x": 1183, "y": 667, "width": 38, "height": 32},
        "CLOSE_SETTINGS": {"x": 590, "y": 620, "width": 101, "height": 33},
        "CLOSE_EMOTES": {"x": 1173, "y": 58, "width": 33, "height": 33},
        "CLOSE_WARD": {"x": 0, "y": 0, "width": 1280, "height": 720},
        "CLOSE_MESSAGE_R": {"x": 1093, "y": 342, "width": 27, "height": 27},
        "CLOSE_MESSAGE_L": {"x": 768, "y": 352, "width": 27, "height": 27},
        "CLOSE_MESSAGE_M": {"x": 1144, "y": 667, "width": 39, "height": 32},
        "CLOSE_RUNES_X": {"x": 1154, "y": 64, "width": 33, "height": 33},
        "CLOSE_RUNES_L": {"x": 0, "y": 0, "width": 111, "height": 720},
        "CLOSE_RUNES_R": {"x": 1169, "y": 0, "width": 111, "height": 720},
        "CLOSE_RUNES_TOP": {"x": 0, "y": 0, "width": 1280, "height": 80},
        "CLOSE_SUM": {"x": 0, "y": 0, "width": 1280, "height": 720},
        "CLOSE_ABILITIES": {"x": 590, "y": 615, "width": 102, "height": 32},
        "CLOSE_QUESTS": {"x": 1089, "y": 88, "width": 25, "height": 25}
    },
    "1024x576": {
        "EDIT_RUNES": {"x": 353, "y": 533, "width": 27, "height": 27},
        "REC_RUNES": {"x": 319, "y": 533, "width": 27, "height": 27},
        "SETTINGS": {"x": 971, "y": 1, "width": 22, "height": 22},
        "SUM_L": {"x": 549, "y": 531, "width": 30, "height": 31},
        "SUM_R": {"x": 587, "y": 531, "width": 30, "height": 31},
        "WARD": {"x": 633, "y": 531, "width": 30, "height": 31},
        "EMOTES": {"x": 670, "y": 532, "width": 30, "height": 30},
        "MESSAGE": {"x": 915, "y": 533, "width": 31, "height": 26},
        "ABILITIES": {"x": 424, "y": 492, "width": 178, "height": 26},
        "QUESTS": {"x": 946, "y": 533, "width": 30, "height": 26},
        "CLOSE_SETTINGS": {"x": 472, "y": 496, "width": 81, "height": 26},
        "CLOSE_EMOTES": {"x": 939, "y": 46, "width": 26, "height": 26},
        "CLOSE_WARD": {"x": 0, "y": 0, "width": 1024, "height": 576},
        "CLOSE_MESSAGE_R": {"x": 874, "y": 273, "width": 22, "height": 22},
        "CLOSE_MESSAGE_L": {"x": 615, "y": 281, "width": 22, "height": 22},
        "CLOSE_MESSAGE_M": {"x": 915, "y": 533, "width": 31, "height": 26},
        "CLOSE_RUNES_X": {"x": 923, "y": 51, "width": 26, "height": 26},
        "CLOSE_RUNES_L": {"x": 0, "y": 0, "width": 88, "height": 576},
        "CLOSE_RUNES_R": {"x": 935, "y": 0, "width": 88, "height": 576},
        "CLOSE_RUNES_TOP": {"x": 0, "y": 0, "width": 1024, "height": 64},
        "CLOSE_SUM": {"x": 0, "y": 0, "width": 1024, "height": 576},
        "CLOSE_ABILITIES": {"x": 472, "y": 492, "width": 82, "height": 26},
        "CLOSE_QUESTS": {"x": 871, "y": 71, "width": 20, "height": 20}
    }
}

# Click catcher positions for Howling Abyss (ARAM) - only x values differ
CLICK_CATCHER_CONFIGS_ARAM = {
    "1600x900": {
        "EDIT_RUNES": {"x": 560, "y": 834, "width": 41, "height": 41},
        "REC_RUNES": {"x": 507, "y": 834, "width": 41, "height": 41},
        "SUM_R": {"x": 924, "y": 831, "width": 46, "height": 47},
        "SUM_L": {"x": 865, "y": 831, "width": 46, "height": 47},
        "EMOTES": {"x": 1045, "y": 832, "width": 46, "height": 46}
    },
    "1280x720": {
        "EDIT_RUNES": {"x": 448, "y": 667, "width": 34, "height": 34},
        "REC_RUNES": {"x": 406, "y": 667, "width": 34, "height": 34},
        "SUM_R": {"x": 739, "y": 664, "width": 37, "height": 38},
        "SUM_L": {"x": 692, "y": 664, "width": 37, "height": 38},
        "EMOTES": {"x": 836, "y": 665, "width": 37, "height": 37}
    },
    "1024x576": {
        "EDIT_RUNES": {"x": 358, "y": 533, "width": 27, "height": 27},
        "REC_RUNES": {"x": 324, "y": 533, "width": 27, "height": 27},
        "SUM_R": {"x": 591, "y": 531, "width": 30, "height": 31},
        "SUM_L": {"x": 553, "y": 531, "width": 30, "height": 31},
        "EMOTES": {"x": 669, "y": 532, "width": 30, "height": 30}
    }
}

# Click catcher positions for Arena (Map ID 22) - no REC_RUNES, EDIT_RUNES, or WARD
CLICK_CATCHER_CONFIGS_ARENA = {
    "1600x900": {
        "SUM_L": {"x": 715, "y": 831, "width": 46, "height": 47},
        "SUM_R": {"x": 774, "y": 831, "width": 46, "height": 47},
        "EMOTES": {"x": 849, "y": 832, "width": 46, "height": 46}
    },
    "1280x720": {
        "SUM_L": {"x": 572, "y": 664, "width": 37, "height": 38},
        "SUM_R": {"x": 619, "y": 664, "width": 37, "height": 38},
        "EMOTES": {"x": 679, "y": 665, "width": 37, "height": 37}
    },
    "1024x576": {
        "SUM_L": {"x": 457, "y": 531, "width": 30, "height": 31},
        "SUM_R": {"x": 495, "y": 531, "width": 30, "height": 31},
        "EMOTES": {"x": 543, "y": 532, "width": 30, "height": 30}
    }
}


def get_resolution_key(resolution: Tuple[int, int]) -> Optional[str]:
    """
    Get the resolution key for a given resolution tuple
    
    Args:
        resolution: (width, height) tuple
        
    Returns:
        Resolution key string or None if not supported
    """
    if resolution in RESOLUTIONS:
        return RESOLUTIONS[resolution]
    return None


def get_click_catcher_config(resolution: Tuple[int, int], catcher_name: str, map_id: Optional[int] = None) -> Optional[Dict[str, int]]:
    """
    Get click catcher configuration for a specific resolution and catcher name
    
    Args:
        resolution: (width, height) tuple
        catcher_name: Name of the click catcher (e.g., 'EDIT_RUNES', 'SETTINGS')
        map_id: Optional map ID (12 = ARAM/Howling Abyss, 11 = SR, 22 = Arena, None = use default)
        
    Returns:
        Dictionary with x, y, width, height or None if not found
    """
    resolution_key = get_resolution_key(resolution)
    if not resolution_key:
        log.warning(f"[ResolutionUtils] Unsupported resolution: {resolution}")
        return None
    
    # Check if this catcher has gamemode-specific config
    is_aram = map_id == 12
    is_arena = map_id == 22
    
    # Check Arena config first
    if is_arena and resolution_key in CLICK_CATCHER_CONFIGS_ARENA:
        if catcher_name in CLICK_CATCHER_CONFIGS_ARENA[resolution_key]:
            log.debug(f"[ResolutionUtils] Using Arena config for {catcher_name} at {resolution_key}")
            return CLICK_CATCHER_CONFIGS_ARENA[resolution_key][catcher_name].copy()
    
    # Check ARAM config
    if is_aram and resolution_key in CLICK_CATCHER_CONFIGS_ARAM:
        if catcher_name in CLICK_CATCHER_CONFIGS_ARAM[resolution_key]:
            log.debug(f"[ResolutionUtils] Using ARAM config for {catcher_name} at {resolution_key}")
            return CLICK_CATCHER_CONFIGS_ARAM[resolution_key][catcher_name].copy()
    
    # Fall back to default (Summoner's Rift) config
    if resolution_key not in CLICK_CATCHER_CONFIGS:
        log.warning(f"[ResolutionUtils] No config found for resolution: {resolution_key}")
        return None
    
    if catcher_name not in CLICK_CATCHER_CONFIGS[resolution_key]:
        log.warning(f"[ResolutionUtils] No config found for catcher '{catcher_name}' in resolution {resolution_key}")
        return None
    
    return CLICK_CATCHER_CONFIGS[resolution_key][catcher_name].copy()


def get_all_click_catcher_configs(resolution: Tuple[int, int], map_id: Optional[int] = None) -> Optional[Dict[str, Dict[str, int]]]:
    """
    Get all click catcher configurations for a specific resolution
    
    Args:
        resolution: (width, height) tuple
        map_id: Optional map ID (12 = ARAM/Howling Abyss, 11 = SR, 22 = Arena, None = use default)
        
    Returns:
        Dictionary of all catcher configs or None if resolution not supported
    """
    resolution_key = get_resolution_key(resolution)
    if not resolution_key:
        log.warning(f"[ResolutionUtils] Unsupported resolution: {resolution}")
        return None
    
    # Check if we should use gamemode-specific config
    is_aram = map_id == 12
    is_arena = map_id == 22
    
    # Check Arena config
    if is_arena and resolution_key in CLICK_CATCHER_CONFIGS_ARENA:
        # Start with default config and overlay Arena-specific values
        result = {name: config.copy() for name, config in CLICK_CATCHER_CONFIGS[resolution_key].items()}
        
        # Override with Arena-specific configs where they exist
        for name, config in CLICK_CATCHER_CONFIGS_ARENA[resolution_key].items():
            result[name] = config.copy()
        
        return result
    
    # Check ARAM config
    if is_aram and resolution_key in CLICK_CATCHER_CONFIGS_ARAM:
        # Start with default config and overlay ARAM-specific values
        result = {name: config.copy() for name, config in CLICK_CATCHER_CONFIGS[resolution_key].items()}
        
        # Override with ARAM-specific configs where they exist
        for name, config in CLICK_CATCHER_CONFIGS_ARAM[resolution_key].items():
            result[name] = config.copy()
        
        return result
    
    if resolution_key not in CLICK_CATCHER_CONFIGS:
        log.warning(f"[ResolutionUtils] No config found for resolution: {resolution_key}")
        return None
    
    # Return a deep copy of all configs
    return {name: config.copy() for name, config in CLICK_CATCHER_CONFIGS[resolution_key].items()}


def is_supported_resolution(resolution: Tuple[int, int]) -> bool:
    """
    Check if a resolution is supported
    
    Args:
        resolution: (width, height) tuple
        
    Returns:
        True if supported, False otherwise
    """
    return resolution in RESOLUTIONS


def get_current_resolution() -> Optional[Tuple[int, int]]:
    """
    Get the current League window resolution
    
    Returns:
        (width, height) tuple or None if League window not found
    """
    try:
        from utils.window_utils import find_league_window_rect
        window_rect = find_league_window_rect()
        
        if not window_rect:
            return None
        
        window_left, window_top, window_right, window_bottom = window_rect
        width = window_right - window_left
        height = window_bottom - window_top
        
        return (width, height)
    except Exception as e:
        log.error(f"[ResolutionUtils] Error getting current resolution: {e}")
        return None


def log_resolution_info(resolution: Tuple[int, int], map_id: Optional[int] = None):
    """
    Log information about the current resolution and available click catchers
    
    Args:
        resolution: (width, height) tuple
        map_id: Optional map ID (12 = ARAM/Howling Abyss, 11 = SR, 22 = Arena, None = use default)
    """
    resolution_key = get_resolution_key(resolution)
    if resolution_key:
        log.info(f"[ResolutionUtils] Current resolution: {resolution_key}")
        configs = get_all_click_catcher_configs(resolution, map_id=map_id)
        if configs:
            log.info(f"[ResolutionUtils] Available click catchers for {resolution_key}:")
            for name, config in configs.items():
                log.info(f"[ResolutionUtils]   {name}: ({config['x']}, {config['y']}) {config['width']}x{config['height']}")
    else:
        log.warning(f"[ResolutionUtils] Unsupported resolution: {resolution}")
