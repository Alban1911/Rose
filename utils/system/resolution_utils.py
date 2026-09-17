#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Resolution Utilities - Handles resolution-based positioning and sizing for UI components
Supports 3 resolutions: 1600x900, 1280x720, 1024x576
"""

from typing import Dict, Tuple, Optional
from utils.core.logging import get_logger

log = get_logger()

# Resolution configurations
RESOLUTIONS = {
    (1600, 900): "1600x900",
    (1280, 720): "1280x720", 
    (1024, 576): "1024x576"
}

BASE_RESOLUTION: Tuple[int, int] = (1600, 900)
BASE_RESOLUTION_KEY: str = RESOLUTIONS[BASE_RESOLUTION]


def _get_scaling_factors(resolution: Tuple[int, int]) -> Tuple[float, float]:
    """Calculate scaling factors relative to the 1600x900 baseline."""
    base_width, base_height = BASE_RESOLUTION
    width, height = resolution
    if base_width == 0 or base_height == 0:
        raise ValueError("Base resolution dimensions must be non-zero")
    return width / base_width, height / base_height


def _scale_position(value: int, scale: float) -> int:
    """Scale a positional coordinate using the provided factor."""
    if value == 0:
        return 0
    return int(round(value * scale))


def _scale_dimension(value: int, scale: float) -> int:
    """Scale a size dimension ensuring minimum size of 1 when original > 0."""
    if value == 0:
        return 0
    scaled = int(round(value * scale))
    return max(1, scaled)


def _scale_rect_config(config: Dict[str, int], scale_x: float, scale_y: float) -> Dict[str, int]:
    """Scale a rectangle-style configuration dictionary."""
    return {
        "x": _scale_position(config.get("x", 0), scale_x),
        "y": _scale_position(config.get("y", 0), scale_y),
        "width": _scale_dimension(config.get("width", 0), scale_x),
        "height": _scale_dimension(config.get("height", 0), scale_y),
    }


def get_scaling_factors(resolution: Tuple[int, int]) -> Tuple[float, float]:
    """Public helper to obtain scaling factors relative to the base resolution."""
    return _get_scaling_factors(resolution)


def scale_position_from_base(value: int, resolution: Tuple[int, int], axis: str = "x") -> int:
    """Scale a positional value from the base resolution along the specified axis."""
    scale_x, scale_y = _get_scaling_factors(resolution)
    scale = scale_x if axis.lower() == "x" else scale_y
    return _scale_position(value, scale)


def scale_dimension_from_base(value: int, resolution: Tuple[int, int], axis: str = "x") -> int:
    """Scale a dimension (width/height) from the base resolution along the specified axis."""
    scale_x, scale_y = _get_scaling_factors(resolution)
    scale = scale_x if axis.lower() == "x" else scale_y
    return _scale_dimension(value, scale)

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
CLICK_CATCHER_CONFIGS = {}

# Click catcher positions for Howling Abyss (ARAM) - only x values differ
CLICK_CATCHER_CONFIGS_ARAM = {}

# Click catcher positions for Arena (Map ID 22) - no REC_RUNES, EDIT_RUNES, or WARD
CLICK_CATCHER_CONFIGS_ARENA = {}

# Click catcher positions for ARAM: Mayhem (Queue ID 2400) - no REC_RUNES, no EDIT_RUNES
CLICK_CATCHER_CONFIGS_MAYHEM = {}


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
        from utils.system.window_utils import find_league_window_rect
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
    
    # Get resolution string if supported
    resolution_str = RESOLUTIONS.get(resolution)
    if resolution_str and resolution_str in LANGUAGE_CONFIGS[language] and element in LANGUAGE_CONFIGS[language][resolution_str]:
        lang_config = LANGUAGE_CONFIGS[language][resolution_str][element]
        base_element_config = CLICK_CATCHER_CONFIGS.get(resolution_str, {}).get(element)
        if base_element_config:
            return base_element_config
        else:
            log.warning(f"[ResolutionUtils] No base config found for element {element} at resolution {resolution_str}")
            return None

    # Fallback: scale from base 1600x900 values
    base_language_configs = LANGUAGE_CONFIGS[language].get(BASE_RESOLUTION_KEY)
    if not base_language_configs or element not in base_language_configs:
        log.debug(f"[ResolutionUtils] No base language config for element {element} in language {language}")
        return None

    base_element_config = CLICK_CATCHER_CONFIGS.get(BASE_RESOLUTION_KEY, {}).get(element)
    if base_element_config:
        return base_element_config
    return None
