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

# Language-specific ABILITIES and CLOSE_ABILITIES configurations for all resolutions
LANGUAGE_CONFIGS = {
    "fr": {
        "1600x900": {"ABILITIES": {"x": 663, "width": 277}, "CLOSE_ABILITIES": {"x": 738, "width": 127}},
        "1280x720": {"ABILITIES": {"x": 530, "width": 221}, "CLOSE_ABILITIES": {"x": 590, "width": 101}},
        "1024x576": {"ABILITIES": {"x": 424, "width": 177}, "CLOSE_ABILITIES": {"x": 472, "width": 81}}
    },
    "ar": {
        "1600x900": {"ABILITIES": {"x": 720, "width": 163}, "CLOSE_ABILITIES": {"x": 753, "width": 96}},
        "1280x720": {"ABILITIES": {"x": 576, "width": 130}, "CLOSE_ABILITIES": {"x": 602, "width": 76}},
        "1024x576": {"ABILITIES": {"x": 460, "width": 104}, "CLOSE_ABILITIES": {"x": 481, "width": 61}}
    },
    "id": {
        "1600x900": {"ABILITIES": {"x": 707, "width": 188}, "CLOSE_ABILITIES": {"x": 733, "width": 136}},
        "1280x720": {"ABILITIES": {"x": 565, "width": 150}, "CLOSE_ABILITIES": {"x": 586, "width": 108}},
        "1024x576": {"ABILITIES": {"x": 452, "width": 120}, "CLOSE_ABILITIES": {"x": 468, "width": 86}}
    },
    "cs": {
        "1600x900": {"ABILITIES": {"x": 665, "width": 273}, "CLOSE_ABILITIES": {"x": 753, "width": 97}},
        "1280x720": {"ABILITIES": {"x": 532, "width": 218}, "CLOSE_ABILITIES": {"x": 602, "width": 77}},
        "1024x576": {"ABILITIES": {"x": 425, "width": 174}, "CLOSE_ABILITIES": {"x": 481, "width": 62}}
    },
    "de": {
        "1600x900": {"ABILITIES": {"x": 666, "width": 270}, "CLOSE_ABILITIES": {"x": 737, "width": 128}},
        "1280x720": {"ABILITIES": {"x": 532, "width": 216}, "CLOSE_ABILITIES": {"x": 589, "width": 102}},
        "1024x576": {"ABILITIES": {"x": 426, "width": 172}, "CLOSE_ABILITIES": {"x": 471, "width": 81}}
    },
    "el": {
        "1600x900": {"ABILITIES": {"x": 682, "width": 239}, "CLOSE_ABILITIES": {"x": 727, "width": 148}},
        "1280x720": {"ABILITIES": {"x": 545, "width": 191}, "CLOSE_ABILITIES": {"x": 581, "width": 118}},
        "1024x576": {"ABILITIES": {"x": 436, "width": 152}, "CLOSE_ABILITIES": {"x": 464, "width": 94}}
    },
    "en": {
        "1600x900": {"ABILITIES": {"x": 702, "width": 198}, "CLOSE_ABILITIES": {"x": 738, "width": 126}},
        "1280x720": {"ABILITIES": {"x": 561, "width": 158}, "CLOSE_ABILITIES": {"x": 590, "width": 100}},
        "1024x576": {"ABILITIES": {"x": 449, "width": 126}, "CLOSE_ABILITIES": {"x": 472, "width": 80}}
    },
    "es": {
        "1600x900": {"ABILITIES": {"x": 691, "width": 221}, "CLOSE_ABILITIES": {"x": 739, "width": 124}},
        "1280x720": {"ABILITIES": {"x": 552, "width": 176}, "CLOSE_ABILITIES": {"x": 591, "width": 99}},
        "1024x576": {"ABILITIES": {"x": 441, "width": 141}, "CLOSE_ABILITIES": {"x": 472, "width": 79}}
    },
    "hu": {
        "1600x900": {"ABILITIES": {"x": 644, "width": 315}, "CLOSE_ABILITIES": {"x": 739, "width": 124}},
        "1280x720": {"ABILITIES": {"x": 515, "width": 252}, "CLOSE_ABILITIES": {"x": 591, "width": 99}},
        "1024x576": {"ABILITIES": {"x": 412, "width": 201}, "CLOSE_ABILITIES": {"x": 472, "width": 79}}
    },
    "it": {
        "1600x900": {"ABILITIES": {"x": 679, "width": 245}, "CLOSE_ABILITIES": {"x": 730, "width": 142}},
        "1280x720": {"ABILITIES": {"x": 543, "width": 196}, "CLOSE_ABILITIES": {"x": 584, "width": 113}},
        "1024x576": {"ABILITIES": {"x": 434, "width": 156}, "CLOSE_ABILITIES": {"x": 467, "width": 90}}
    },
    "ja": {
        "1600x900": {"ABILITIES": {"x": 720, "width": 162}, "CLOSE_ABILITIES": {"x": 758, "width": 87}},
        "1280x720": {"ABILITIES": {"x": 576, "width": 129}, "CLOSE_ABILITIES": {"x": 606, "width": 69}},
        "1024x576": {"ABILITIES": {"x": 460, "width": 103}, "CLOSE_ABILITIES": {"x": 485, "width": 55}}
    },
    "ko": {
        "1600x900": {"ABILITIES": {"x": 739, "width": 124}, "CLOSE_ABILITIES": {"x": 742, "width": 119}},
        "1280x720": {"ABILITIES": {"x": 591, "width": 99}, "CLOSE_ABILITIES": {"x": 593, "width": 95}},
        "1024x576": {"ABILITIES": {"x": 472, "width": 79}, "CLOSE_ABILITIES": {"x": 474, "width": 76}}
    },
    "pl": {
        "1600x900": {"ABILITIES": {"x": 654, "width": 294}, "CLOSE_ABILITIES": {"x": 734, "width": 134}},
        "1280x720": {"ABILITIES": {"x": 523, "width": 235}, "CLOSE_ABILITIES": {"x": 587, "width": 107}},
        "1024x576": {"ABILITIES": {"x": 418, "width": 188}, "CLOSE_ABILITIES": {"x": 469, "width": 85}}
    },
    "pt": {
        "1600x900": {"ABILITIES": {"x": 678, "width": 246}, "CLOSE_ABILITIES": {"x": 739, "width": 124}},
        "1280x720": {"ABILITIES": {"x": 542, "width": 196}, "CLOSE_ABILITIES": {"x": 591, "width": 99}},
        "1024x576": {"ABILITIES": {"x": 433, "width": 157}, "CLOSE_ABILITIES": {"x": 472, "width": 79}}
    },
    "ro": {
        "1600x900": {"ABILITIES": {"x": 695, "width": 213}, "CLOSE_ABILITIES": {"x": 730, "width": 143}},
        "1280x720": {"ABILITIES": {"x": 556, "width": 170}, "CLOSE_ABILITIES": {"x": 584, "width": 114}},
        "1024x576": {"ABILITIES": {"x": 444, "width": 136}, "CLOSE_ABILITIES": {"x": 467, "width": 91}}
    },
    "ru": {
        "1600x900": {"ABILITIES": {"x": 667, "width": 268}, "CLOSE_ABILITIES": {"x": 742, "width": 119}},
        "1280x720": {"ABILITIES": {"x": 533, "width": 214}, "CLOSE_ABILITIES": {"x": 593, "width": 95}},
        "1024x576": {"ABILITIES": {"x": 426, "width": 171}, "CLOSE_ABILITIES": {"x": 474, "width": 76}}
    },
    "th": {
        "1600x900": {"ABILITIES": {"x": 753, "width": 96}, "CLOSE_ABILITIES": {"x": 741, "width": 121}},
        "1280x720": {"ABILITIES": {"x": 602, "width": 76}, "CLOSE_ABILITIES": {"x": 592, "width": 96}},
        "1024x576": {"ABILITIES": {"x": 481, "width": 61}, "CLOSE_ABILITIES": {"x": 473, "width": 77}}
    },
    "tr": {
        "1600x900": {"ABILITIES": {"x": 679, "width": 244}, "CLOSE_ABILITIES": {"x": 758, "width": 87}},
        "1280x720": {"ABILITIES": {"x": 543, "width": 195}, "CLOSE_ABILITIES": {"x": 606, "width": 69}},
        "1024x576": {"ABILITIES": {"x": 434, "width": 156}, "CLOSE_ABILITIES": {"x": 485, "width": 55}}
    },
    "vi": {
        "1600x900": {"ABILITIES": {"x": 710, "width": 183}, "CLOSE_ABILITIES": {"x": 732, "width": 139}},
        "1280x720": {"ABILITIES": {"x": 568, "width": 146}, "CLOSE_ABILITIES": {"x": 585, "width": 111}},
        "1024x576": {"ABILITIES": {"x": 454, "width": 117}, "CLOSE_ABILITIES": {"x": 468, "width": 88}}
    },
    "zh": {
        "1600x900": {"ABILITIES": {"x": 739, "width": 125}, "CLOSE_ABILITIES": {"x": 757, "width": 88}},
        "1280x720": {"ABILITIES": {"x": 591, "width": 100}, "CLOSE_ABILITIES": {"x": 605, "width": 70}},
        "1024x576": {"ABILITIES": {"x": 472, "width": 80}, "CLOSE_ABILITIES": {"x": 484, "width": 56}}
    }
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


def get_click_catcher_config(resolution: Tuple[int, int], catcher_name: str, map_id: Optional[int] = None, language: Optional[str] = None, queue_id: Optional[int] = None) -> Optional[Dict[str, int]]:
    """
    Get click catcher configuration for a specific resolution and catcher name
    
    Args:
        resolution: (width, height) tuple
        catcher_name: Name of the click catcher (e.g., 'EDIT_RUNES', 'SETTINGS')
        map_id: Optional map ID (12 = ARAM/Howling Abyss, 11 = SR, 22 = Arena, None = use default)
        language: Optional language code for language-specific coordinates (e.g., 'en', 'fr', 'de')
        queue_id: Optional queue ID (2400 = ARAM, etc.)
        
    Returns:
        Dictionary with x, y, width, height or None if not found
    """
    resolution_key = get_resolution_key(resolution)
    if not resolution_key:
        log.warning(f"[ResolutionUtils] Unsupported resolution: {resolution}")
        return None
    
    # Check for language-specific coordinates for ABILITIES and CLOSE_ABILITIES
    if language and catcher_name in ['ABILITIES', 'CLOSE_ABILITIES']:
        language_coords = get_language_specific_coordinates(language, resolution, catcher_name)
        if language_coords:
            log.debug(f"[ResolutionUtils] Using language-specific config for {catcher_name} at {resolution_key} with language {language}")
            return language_coords
        else:
            log.debug(f"[ResolutionUtils] No language-specific config found for {catcher_name} with language {language}, falling back to default")
    
    # Check if this catcher has gamemode-specific config
    # Check by queue_id first (2400 = ARAM), then by map_id
    is_aram = (queue_id == 2400) or (map_id == 12)
    is_arena = map_id == 22
    
    # Check Arena config first
    if is_arena and resolution_key in CLICK_CATCHER_CONFIGS_ARENA:
        if catcher_name in CLICK_CATCHER_CONFIGS_ARENA[resolution_key]:
            log.debug(f"[ResolutionUtils] Using Arena config for {catcher_name} at {resolution_key}")
            return CLICK_CATCHER_CONFIGS_ARENA[resolution_key][catcher_name].copy()
    
    # Check ARAM config
    if is_aram and resolution_key in CLICK_CATCHER_CONFIGS_ARAM:
        if catcher_name in CLICK_CATCHER_CONFIGS_ARAM[resolution_key]:
            log.debug(f"[ResolutionUtils] Using ARAM config for {catcher_name} at {resolution_key} (queue_id={queue_id}, map_id={map_id})")
            return CLICK_CATCHER_CONFIGS_ARAM[resolution_key][catcher_name].copy()
    
    # Fall back to default (Summoner's Rift) config
    if resolution_key not in CLICK_CATCHER_CONFIGS:
        log.warning(f"[ResolutionUtils] No config found for resolution: {resolution_key}")
        return None
    
    if catcher_name not in CLICK_CATCHER_CONFIGS[resolution_key]:
        log.warning(f"[ResolutionUtils] No config found for catcher '{catcher_name}' in resolution {resolution_key}")
        return None
    
    return CLICK_CATCHER_CONFIGS[resolution_key][catcher_name].copy()


def get_all_click_catcher_configs(resolution: Tuple[int, int], map_id: Optional[int] = None, queue_id: Optional[int] = None) -> Optional[Dict[str, Dict[str, int]]]:
    """
    Get all click catcher configurations for a specific resolution
    
    Args:
        resolution: (width, height) tuple
        map_id: Optional map ID (12 = ARAM/Howling Abyss, 11 = SR, 22 = Arena, None = use default)
        queue_id: Optional queue ID (2400 = ARAM, etc.)
        
    Returns:
        Dictionary of all catcher configs or None if resolution not supported
    """
    resolution_key = get_resolution_key(resolution)
    if not resolution_key:
        log.warning(f"[ResolutionUtils] Unsupported resolution: {resolution}")
        return None
    
    # Check if we should use gamemode-specific config
    # Check by queue_id first (2400 = ARAM), then by map_id
    is_aram = (queue_id == 2400) or (map_id == 12)
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


def get_language_specific_coordinates(language: str, resolution: Tuple[int, int], element: str) -> Optional[Dict[str, int]]:
    """
    Get language-specific coordinates for ABILITIES or CLOSE_ABILITIES elements
    
    Args:
        language: Language code (e.g., 'en', 'fr', 'de')
        resolution: Resolution tuple (width, height)
        element: Element name ('ABILITIES' or 'CLOSE_ABILITIES')
    
    Returns:
        Dictionary with x, y, width, height or None if not found
    """
    if language not in LANGUAGE_CONFIGS:
        log.debug(f"[ResolutionUtils] Language {language} not found in configs, using default")
        return None
    
    # Get resolution string
    resolution_str = RESOLUTIONS.get(resolution)
    if not resolution_str:
        log.warning(f"[ResolutionUtils] Unsupported resolution for language coordinates: {resolution}")
        return None
    
    if resolution_str not in LANGUAGE_CONFIGS[language]:
        log.debug(f"[ResolutionUtils] Resolution {resolution_str} not found for language {language}")
        return None
    
    if element not in LANGUAGE_CONFIGS[language][resolution_str]:
        log.debug(f"[ResolutionUtils] Element {element} not found for language {language} at resolution {resolution_str}")
        return None
    
    # Get language-specific coordinates for this resolution
    lang_config = LANGUAGE_CONFIGS[language][resolution_str][element]
    lang_x = lang_config["x"]
    lang_width = lang_config["width"]
    
    # Y coordinates and height are the same for all languages (only x and width vary)
    # Get these from the base resolution config
    if resolution_str not in CLICK_CATCHER_CONFIGS:
        log.warning(f"[ResolutionUtils] No base config found for resolution {resolution_str}")
        return None
    
    base_element_config = CLICK_CATCHER_CONFIGS[resolution_str].get(element)
    if not base_element_config:
        log.warning(f"[ResolutionUtils] No base config found for element {element} at resolution {resolution_str}")
        return None
    
    return {
        "x": lang_x,
        "y": base_element_config["y"],
        "width": lang_width,
        "height": base_element_config["height"]
    }


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
