#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Path utilities for LeagueUnlocked
Handles user data directories and permissions
"""

import os
import sys
from pathlib import Path


def get_user_data_dir() -> Path:
    """
    Get the user data directory where the application can write files.
    This ensures proper permissions regardless of where the app is installed.
    """
    if os.name == "nt":  # Windows
        # Use %LOCALAPPDATA% for user-specific data (logs, cache, etc.)
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            return Path(localappdata) / "LeagueUnlocked"
        else:
            # Fallback to user profile
            userprofile = os.environ.get("USERPROFILE")
            if userprofile:
                return Path(userprofile) / "AppData" / "Local" / "LeagueUnlocked"
            else:
                # Last resort: current directory
                return Path.cwd() / "skins"
    else:  # Linux/macOS
        # Use XDG_DATA_HOME or fallback to ~/.local/share
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            return Path(xdg_data_home) / "LeagueUnlocked"
        else:
            # Use pathlib for home directory
            return Path.home() / ".local" / "share" / "LeagueUnlocked"


def get_appdata_dir() -> Path:
    """
    Get the LeagueUnlocked AppData directory.
    Alias for get_user_data_dir() for backwards compatibility.
    """
    return get_user_data_dir()


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


def get_asset_path(asset_name: str) -> Path:
    """
    Get the path to an asset file (icons, images, etc.)
    Works in both development and frozen (PyInstaller) environments.
    
    Args:
        asset_name: Name of the asset file (e.g., "champ-select-flyout-background.jpg")
        
    Returns:
        Path to the asset file
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        # PyInstaller extracts data files to _MEIPASS (onefile) or _internal (onedir)
        if hasattr(sys, '_MEIPASS'):
            # One-file mode: use _MEIPASS
            base_path = Path(sys._MEIPASS)
        else:
            # One-dir mode: use _internal folder
            base_path = Path(sys.executable).parent / "_internal"
        return base_path / "assets" / asset_name
    else:
        # Running as script
        app_dir = get_app_dir()
        return app_dir / "assets" / asset_name


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
