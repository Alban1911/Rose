#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Path utilities for LoL Skin Changer
Handles user data directories and permissions
"""

import os
from pathlib import Path
from typing import Optional


def get_user_data_dir() -> Path:
    """
    Get the user data directory where the application can write files.
    This ensures proper permissions regardless of where the app is installed.
    """
    if os.name == "nt":  # Windows
        # Use %APPDATA% for user-specific data
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "LoLSkinChanger"
        else:
            # Fallback to user profile
            userprofile = os.environ.get("USERPROFILE")
            if userprofile:
                return Path(userprofile) / "AppData" / "Roaming" / "LoLSkinChanger"
            else:
                # Last resort: current directory
                return Path.cwd() / "skins"
    else:  # Linux/macOS
        # Use XDG_DATA_HOME or fallback to ~/.local/share
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            return Path(xdg_data_home) / "LoLSkinChanger"
        else:
            home = os.path.expanduser("~")
            return Path(home) / ".local" / "share" / "LoLSkinChanger"


def get_skins_dir() -> Path:
    """
    Get the skins directory path.
    Creates the directory if it doesn't exist.
    """
    skins_dir = get_user_data_dir() / "skins"
    skins_dir.mkdir(parents=True, exist_ok=True)
    return skins_dir


def get_state_dir() -> Path:
    """
    Get the state directory path for application state files.
    Creates the directory if it doesn't exist.
    """
    state_dir = get_user_data_dir() / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def get_injection_dir() -> Path:
    """
    Get the injection directory path for mods and overlays.
    Creates the directory if it doesn't exist.
    """
    injection_dir = get_user_data_dir() / "injection"
    injection_dir.mkdir(parents=True, exist_ok=True)
    return injection_dir


def get_app_dir() -> Path:
    """
    Get the main application directory (where the exe is located).
    This is read-only for installed applications.
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return Path(sys.executable).parent
    else:
        # Running as script
        return Path(__file__).parent.parent


def ensure_write_permissions(path: Path) -> bool:
    """
    Ensure that the given path is writable.
    Returns True if writable, False otherwise.
    """
    try:
        # Try to create a test file
        test_file = path / ".write_test"
        test_file.touch()
        test_file.unlink()
        return True
    except (OSError, PermissionError):
        return False


# Import sys for get_app_dir function
import sys
