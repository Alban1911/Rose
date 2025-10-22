#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Utilities - Shared utility functions used throughout the application
Contains common functions that are used across multiple modules
"""

from typing import Optional
from utils.logging import get_logger

log = get_logger()


def is_default_skin(skin_id: int) -> bool:
    """Check if a skin ID is the champion's default skin
    
    Args:
        skin_id: The skin ID to check
        
    Returns:
        True if the skin ID is the champion's default skin (skin_id % 1000 == 0), False otherwise
    """
    return skin_id % 1000 == 0


def is_owned(skin_id: int, owned_skin_ids: set) -> bool:
    """Check if a skin is owned (either default skin or in owned_skin_ids)
    
    Args:
        skin_id: The skin ID to check
        owned_skin_ids: Set of owned skin IDs from LCU
        
    Returns:
        True if the skin is owned (default skin or in owned_skin_ids), False otherwise
    """
    return is_default_skin(skin_id) or (skin_id in owned_skin_ids)


def is_chroma_id(skin_id: int, chroma_id_map: Optional[dict]) -> bool:
    """Check if a skin ID is a chroma using the chroma_id_map
    
    Args:
        skin_id: The skin ID to check
        chroma_id_map: Dictionary mapping chroma IDs to chroma data (can be None)
        
    Returns:
        True if the skin ID is a chroma, False otherwise
    """
    # Check hardcoded special chroma IDs first (always check these)
    if skin_id in (145071, 103086, 99991, 99992, 99993, 99994, 99995, 99996, 99997, 99998, 99999):
        return True
    
    # Check chroma_id_map if it's not None and not empty
    if chroma_id_map is not None:
        return skin_id in chroma_id_map
    
    return False


def get_base_skin_id_for_chroma(chroma_id: int, chroma_id_map: Optional[dict]) -> Optional[int]:
    """Get the base skin ID for a given chroma ID
    
    Args:
        chroma_id: The chroma ID
        chroma_id_map: Dictionary mapping chroma IDs to chroma data
        
    Returns:
        Base skin ID if found, None otherwise
    """
    try:
        # Check if this is an Elementalist Lux form (fake ID)
        if 99991 <= chroma_id <= 99999:
            return 99007  # Elementalist Lux base skin ID
        
        # Special case: Elementalist Lux base skin (99007)
        if chroma_id == 99007:
            return 99007  # Elementalist Lux base skin ID

        # Special case: Risen Legend Kai'Sa (145070)
        if chroma_id == 145070:
            return 145070  # Risen Legend Kai'Sa base skin ID
        
        # Special case: Immortalized Legend Kai'Sa (145071)
        if chroma_id == 145071:
            return 145070  # Immortalized Legend Kai'Sa base skin ID
        
        # Special case: Risen Legend Ahri (103085)
        if chroma_id == 103085:
            return 103085  # Risen Legend Ahri base skin ID
        
        # Special case: Immortalized Legend Ahri (103086)
        if chroma_id == 103086:
            return 103085  # Immortalized Legend Ahri base skin ID
        
        # Check if this chroma ID exists in the cache
        if chroma_id_map is not None:
            chroma_data = chroma_id_map.get(chroma_id)
            if chroma_data:
                return chroma_data.get('skinId')
        
        return None
        
    except Exception as e:
        log.debug(f"[UTILITIES] Error getting base skin ID for chroma {chroma_id}: {e}")
        return None


def is_base_skin_of_chroma_set(skin_id: int, chroma_id_map: Optional[dict]) -> bool:
    """Check if a skin ID is the base skin of a chroma set
    
    Args:
        skin_id: The skin ID to check
        chroma_id_map: Dictionary mapping chroma IDs to chroma data
        
    Returns:
        True if the skin is a base skin of a chroma set, False otherwise
    """
    # Check if this skin ID appears as a base skin for any chromas in the map
    if chroma_id_map is not None:
        for chroma_id, chroma_data in chroma_id_map.items():
            if chroma_data and chroma_data.get('skinId') == skin_id:
                return True
    
    # Special cases that are base skins but might not be in chroma_id_map
    special_base_skins = [99007, 145070, 103085]
    if skin_id in special_base_skins:
        return True
    
    return False


def is_base_skin(skin_id: int, chroma_id_map: Optional[dict]) -> bool:
    """Check if a skin ID is a base skin (not a chroma)
    
    Args:
        skin_id: The skin ID to check
        chroma_id_map: Dictionary mapping chroma IDs to chroma data
        
    Returns:
        True if the skin is a base skin, False if it's a chroma
    """
    return not is_chroma_id(skin_id, chroma_id_map)


def is_base_skin_owned(skin_id: int, owned_skin_ids: set, chroma_id_map: Optional[dict]) -> bool:
    """Check if the base skin of a given skin is owned
    
    Args:
        skin_id: The skin ID (can be base skin or chroma)
        owned_skin_ids: Set of owned skin IDs from LCU
        chroma_id_map: Dictionary mapping chroma IDs to chroma data
        
    Returns:
        True if the base skin is owned, False otherwise
    """
    # Check if this is a base skin or a chroma
    if is_base_skin(skin_id, chroma_id_map):
        # This is a base skin, check if it's owned
        return is_owned(skin_id, owned_skin_ids)
    else:
        # This is a chroma, get its base skin and check if that's owned
        base_skin_id = get_base_skin_id_for_chroma(skin_id, chroma_id_map)
        return is_owned(base_skin_id, owned_skin_ids) if base_skin_id is not None else False


def convert_to_english_skin_name(skin_id: int, localized_name: str, db=None, champion_name: str = None, chroma_id_map: Optional[dict] = None) -> str:
    """Convert localized skin name to English using database
    
    Args:
        skin_id: The skin ID (must be a base skin ID, not a chroma ID)
        localized_name: The localized skin name from LCU
        db: NameDB instance for lookups (optional)
        champion_name: Champion name for special handling (optional)
        chroma_id_map: Dictionary mapping chroma IDs to chroma data (optional, for assertion)
        
    Returns:
        English skin name if found, otherwise returns localized name
    """
    # Assert that this is a base skin ID, not a chroma ID
    # Use is_base_skin instead of is_base_skin_of_chroma_set since a skin can be a base skin
    # without being in the chroma_id_map (if not owned or not loaded)
    assert is_base_skin(skin_id, chroma_id_map), \
        f"convert_to_english_skin_name called with chroma ID {skin_id}. Use convert_to_english_chroma_name for chromas."
    # Special handling for Kai'Sa skins - always use "Risen Legend Kai'Sa" for preview paths
    if champion_name and champion_name.lower().replace("'", "") == "kaisa" and skin_id in [145070, 145071]:
        log.debug(f"[UTILITIES] Special handling for Kai'Sa skin ID {skin_id} - using 'Risen Legend Kai'Sa'")
        return "Risen Legend Kai'Sa"
    
    # Special handling for Ahri skins - always use "Risen Legend Ahri" for preview paths
    if champion_name and champion_name.lower() == "ahri" and skin_id in [103085, 103086]:
        log.debug(f"[UTILITIES] Special handling for Ahri skin ID {skin_id} - using 'Risen Legend Ahri'")
        return "Risen Legend Ahri"
    
    if not db:
        log.debug(f"[UTILITIES] No database available for skin name conversion, using localized: '{localized_name}'")
        return localized_name
    
    try:
        english_name = db.get_english_skin_name_by_id(skin_id)
        if english_name:
            # Override database result for special cases
            if champion_name and champion_name.lower().replace("'", "") == "kaisa" and skin_id in [145070, 145071]:
                log.debug(f"[UTILITIES] Overriding database result for Kai'Sa skin ID {skin_id} - using 'Risen Legend Kai'Sa'")
                return "Risen Legend Kai'Sa"
            if champion_name and champion_name.lower() == "ahri" and skin_id in [103085, 103086]:
                log.debug(f"[UTILITIES] Overriding database result for Ahri skin ID {skin_id} - using 'Risen Legend Ahri'")
                return "Risen Legend Ahri"
            
            log.debug(f"[UTILITIES] Converted skin name: '{localized_name}' -> '{english_name}' (ID: {skin_id})")
            return english_name
        else:
            log.debug(f"[UTILITIES] No English name found for skin ID {skin_id}, using localized: '{localized_name}'")
            return localized_name
    except Exception as e:
        log.debug(f"[UTILITIES] Error converting skin name for ID {skin_id}: {e}, using localized: '{localized_name}'")
        return localized_name


def convert_to_english_chroma_name(chroma_id: int, localized_name: str, base_skin_name: str, skin_scraper=None) -> str:
    """Convert localized chroma name to English
    
    Args:
        chroma_id: The chroma ID
        localized_name: The localized chroma name from LCU
        base_skin_name: The English base skin name
        skin_scraper: LCUSkinScraper instance for chroma data (optional)
        
    Returns:
        English chroma name if possible, otherwise returns formatted name
    """
    # Try to get English chroma name from skin scraper's chroma cache
    if skin_scraper and skin_scraper.cache:
        chroma_data = skin_scraper.cache.chroma_id_map.get(chroma_id)
        if chroma_data and 'name' in chroma_data:
            english_chroma_name = chroma_data['name']
            log.debug(f"[UTILITIES] Using English chroma name from skin scraper: '{localized_name}' -> '{english_chroma_name}' (ID: {chroma_id})")
            return english_chroma_name
    
    # Fallback: use base skin name + "Chroma" or localized name
    if not localized_name or localized_name == f'{base_skin_name} Chroma':
        return f'{base_skin_name} Chroma'
    
    # If the localized name looks like a simple color description, keep it
    # Otherwise, use the base skin name + "Chroma"
    return localized_name if len(localized_name.split()) <= 2 else f'{base_skin_name} Chroma'
