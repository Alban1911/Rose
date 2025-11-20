#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Utilities - Shared utility functions used throughout the application
Contains common functions that are used across multiple modules
"""

# Standard library imports
import socket
from typing import Optional

# Local imports
from utils.logging import get_logger

log = get_logger()


def get_champion_id_from_skin_id(skin_id: int) -> int:
    """Get champion ID from a skin ID
    
    Args:
        skin_id: The skin ID
        
    Returns:
        The champion ID (skin_id // 1000)
    """
    return skin_id // 1000


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


# No longer converting to English - using LCU localized names directly


def find_free_port(start_port: int = 3000, max_attempts: int = 100) -> Optional[int]:
    """
    Find a free port starting from start_port.
    
    Args:
        start_port: The starting port number to check (default: 3000)
        max_attempts: Maximum number of ports to try (default: 100)
        
    Returns:
        A free port number, or None if no free port found
    """
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                # Port is free, return it
                log.debug(f"[UTILITIES] Found free port: {port}")
                return port
        except OSError:
            # Port is in use, try next one
            continue
    
    log.warning(f"[UTILITIES] No free port found in range {start_port}-{start_port + max_attempts - 1}")
    return None
