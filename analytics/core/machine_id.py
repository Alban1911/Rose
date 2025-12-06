#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Machine ID retrieval using Windows Machine GUID
"""

import sys
import uuid
from pathlib import Path
from typing import Optional

from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir

log = get_logger()

# Cache machine ID in memory
_machine_id_cache: Optional[str] = None


def _get_windows_machine_guid() -> Optional[str]:
    """
    Retrieve Windows Machine GUID from registry.
    
    Returns:
        Machine GUID string or None if retrieval fails
    """
    if sys.platform != "win32":
        return None
    
    try:
        import winreg
        
        # Open the registry key
        key_path = r"SOFTWARE\Microsoft\Cryptography"
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            key_path,
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        )
        
        try:
            # Read the MachineGuid value
            machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(machine_guid)
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        log.debug(f"Failed to read Windows Machine GUID from registry: {e}")
        return None


def _generate_fallback_machine_id() -> str:
    """
    Generate a fallback machine ID and store it in user data directory.
    
    Returns:
        Generated UUID string
    """
    user_data_dir = get_user_data_dir()
    machine_id_file = user_data_dir / "machine_id.txt"
    
    # Try to read existing fallback ID
    if machine_id_file.exists():
        try:
            with open(machine_id_file, "r", encoding="utf-8") as f:
                existing_id = f.read().strip()
                if existing_id:
                    return existing_id
        except Exception as e:
            log.debug(f"Failed to read existing machine ID file: {e}")
    
    # Generate new UUID
    new_id = str(uuid.uuid4())
    
    # Save to file
    try:
        user_data_dir.mkdir(parents=True, exist_ok=True)
        with open(machine_id_file, "w", encoding="utf-8") as f:
            f.write(new_id)
        log.debug(f"Generated and saved fallback machine ID: {new_id}")
    except Exception as e:
        log.warning(f"Failed to save fallback machine ID to file: {e}")
    
    return new_id


def get_machine_id() -> str:
    """
    Get a persistent machine identifier.
    
    First tries to retrieve Windows Machine GUID from registry.
    Falls back to a generated UUID stored in user data directory.
    
    Returns:
        Machine ID string (persistent across app restarts)
    """
    global _machine_id_cache
    
    # Return cached value if available
    if _machine_id_cache is not None:
        return _machine_id_cache
    
    # Try Windows Machine GUID first
    machine_id = _get_windows_machine_guid()
    
    if machine_id:
        _machine_id_cache = machine_id
        log.debug(f"Retrieved Windows Machine GUID: {machine_id}")
        return machine_id
    
    # Fallback to generated UUID
    log.debug("Windows Machine GUID not available, using fallback UUID")
    machine_id = _generate_fallback_machine_id()
    _machine_id_cache = machine_id
    
    return machine_id

