#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Path utilities for Rose
Handles user data directories and permissions
"""

import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Tuple

# Cache for the resolved user data directory
_cached_user_data_dir: Optional[Path] = None


TOKEN_DUPLICATE = 0x0002
TOKEN_IMPERSONATE = 0x0004
TOKEN_QUERY = 0x0008
# The Desktop as Windows knows it (OneDrive's backup may have moved it)
FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"


def _explorer_process_token(access: int):
    """Open the token of explorer.exe for *access*: the caller closes it."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32
    PROCESS_QUERY_INFORMATION = 0x0400

    result = subprocess.run(
        ['tasklist', '/FI', 'IMAGENAME eq explorer.exe', '/FO', 'CSV', '/NH'],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    # Parse PID from CSV output: "explorer.exe","1234",...
    parts = result.stdout.strip().split('\n')[0].split(',')
    if len(parts) < 2:
        return None
    explorer_pid = int(parts[1].strip('"'))

    process_handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, explorer_pid)
    if not process_handle:
        return None
    try:
        token_handle = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(process_handle, access, ctypes.byref(token_handle)):
            return None
        return token_handle
    finally:
        kernel32.CloseHandle(process_handle)


@contextmanager
def _explorer_token(access: int) -> Iterator[Optional[object]]:
    """The token of explorer.exe, opened for *access* and closed after, or
    None. Explorer always runs as the user logged into the desktop, even when
    Rose runs elevated as a different admin account."""
    token = None
    if os.name == "nt":
        try:
            token = _explorer_process_token(access)
        except Exception:
            token = None
    try:
        yield token
    finally:
        if token is not None:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(token)


def _get_desktop_user_info() -> Tuple[Optional[str], Optional[str]]:
    """
    Get the actual desktop user's username and profile path.
    This finds the user who is logged into the desktop session,
    even if Rose is running elevated as a different admin account.

    Returns:
        Tuple of (username, profile_path) or (None, None) if detection fails
    """
    if os.name != "nt":
        return None, None

    try:
        import ctypes
        from ctypes import wintypes

        advapi32 = ctypes.windll.advapi32
        userenv = ctypes.windll.userenv
        TokenUser = 1

        with _explorer_token(TOKEN_QUERY) as token_handle:
            if token_handle is None:
                return None, None

            # Get token user info size
            token_info_size = wintypes.DWORD()
            advapi32.GetTokenInformation(token_handle, TokenUser, None, 0, ctypes.byref(token_info_size))

            # Allocate buffer and get token user
            token_user_buffer = ctypes.create_string_buffer(token_info_size.value)
            if not advapi32.GetTokenInformation(
                token_handle, TokenUser, token_user_buffer, token_info_size.value, ctypes.byref(token_info_size)
            ):
                return None, None

            # Extract SID from TOKEN_USER structure (SID is at offset 0)
            sid_ptr = ctypes.cast(token_user_buffer, ctypes.POINTER(ctypes.c_void_p))[0]

            # Lookup account name from SID
            name_size = wintypes.DWORD(256)
            domain_size = wintypes.DWORD(256)
            name = ctypes.create_unicode_buffer(256)
            domain = ctypes.create_unicode_buffer(256)
            sid_type = wintypes.DWORD()

            if not advapi32.LookupAccountSidW(
                None, sid_ptr, name, ctypes.byref(name_size),
                domain, ctypes.byref(domain_size), ctypes.byref(sid_type)
            ):
                return None, None

            username = name.value

            # Get user profile directory
            profile_dir = ctypes.create_unicode_buffer(260)
            profile_size = wintypes.DWORD(260)

            if userenv.GetUserProfileDirectoryW(token_handle, profile_dir, ctypes.byref(profile_size)):
                return username, profile_dir.value
            # Fallback: construct profile path
            return username, f"C:\\Users\\{username}"

    except Exception:
        return None, None


def _get_localappdata_for_user(profile_path: str) -> Optional[Path]:
    """
    Get the LocalAppData path for a specific user profile.

    Args:
        profile_path: Path to the user's profile directory (e.g., C:\\Users\\username)

    Returns:
        Path to LocalAppData or None if it doesn't exist
    """
    localappdata = Path(profile_path) / "AppData" / "Local"
    if localappdata.exists():
        return localappdata
    return None


def get_user_data_dir() -> Path:
    """
    Get the user data directory where the application can write files.

    IMPORTANT: This function detects the actual desktop user, not the elevated
    admin account. This ensures that Rose's data directory matches what Pengu
    Loader (running in League's process) will use.

    This handles the case where:
    - User "daish" is logged into Windows
    - User runs Rose as "Admin" (different admin account)
    - Rose needs to use daish's AppData, not Admin's AppData
    """
    global _cached_user_data_dir

    if _cached_user_data_dir is not None:
        return _cached_user_data_dir

    if os.name == "nt":  # Windows
        # First, try to detect the actual desktop user
        # This handles the case where Rose runs as a different admin account
        desktop_username, desktop_profile = _get_desktop_user_info()

        current_username = os.environ.get("USERNAME", "").lower()

        # Check if there's a user mismatch
        if desktop_username and desktop_profile:
            if desktop_username.lower() != current_username:
                # User mismatch detected! Use the desktop user's AppData
                desktop_localappdata = _get_localappdata_for_user(desktop_profile)
                if desktop_localappdata:
                    _cached_user_data_dir = desktop_localappdata / "Rose"
                    # Ensure the directory exists with proper permissions
                    try:
                        _cached_user_data_dir.mkdir(parents=True, exist_ok=True)
                    except (OSError, PermissionError):
                        pass  # Will be created later when needed
                    return _cached_user_data_dir

        # No mismatch or detection failed - use current user's LOCALAPPDATA
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            _cached_user_data_dir = Path(localappdata) / "Rose"
            return _cached_user_data_dir

        # Fallback to user profile
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            _cached_user_data_dir = Path(userprofile) / "AppData" / "Local" / "Rose"
            return _cached_user_data_dir

        # Last resort: current directory
        _cached_user_data_dir = Path.cwd() / "skins"
        return _cached_user_data_dir

    else:  # Linux/macOS
        # Use XDG_DATA_HOME or fallback to ~/.local/share
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            _cached_user_data_dir = Path(xdg_data_home) / "Rose"
        else:
            _cached_user_data_dir = Path.home() / ".local" / "share" / "Rose"
        return _cached_user_data_dir


def get_appdata_dir() -> Path:
    """
    Get the Rose AppData directory.
    Alias for get_user_data_dir() for backwards compatibility.
    """
    return get_user_data_dir()


def _known_folder(folder_id: str, token) -> Optional[Path]:
    """Where Windows keeps the known folder *folder_id* of the user *token*
    is (None: this account's), or None when it cannot tell."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        shell32 = ctypes.WinDLL("shell32")
        ole32 = ctypes.WinDLL("ole32")
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.c_char_p, wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        pointer = ctypes.c_void_p()
        result = shell32.SHGetKnownFolderPath(uuid.UUID(folder_id).bytes_le, 0, token, ctypes.byref(pointer))
        try:
            if result != 0 or not pointer.value:
                return None
            return Path(ctypes.wstring_at(pointer.value))
        finally:
            ole32.CoTaskMemFree(pointer)
    except Exception:
        return None


def get_desktop_user_desktop_dir() -> Path:
    """
    The Desktop of the user logged into the desktop, where Windows keeps it.

    OneDrive's backup moves the Desktop into the OneDrive folder, so it is
    asked from Windows, not assumed under the profile. Rose may run elevated
    as another admin account, whose Desktop the user never sees: Windows is
    then asked with the desktop user's token, as get_user_data_dir finds
    that user. Falls back on <profile>\\Desktop.
    """
    desktop_username, desktop_profile = _get_desktop_user_info()
    other_user = bool(desktop_username) and desktop_username.lower() != os.environ.get("USERNAME", "").lower()
    if other_user:
        with _explorer_token(TOKEN_QUERY | TOKEN_IMPERSONATE | TOKEN_DUPLICATE) as token:
            desktop = _known_folder(FOLDERID_DESKTOP, token) if token is not None else None
    else:
        desktop = _known_folder(FOLDERID_DESKTOP, None)
    if desktop is not None:
        return desktop
    profile = desktop_profile if other_user else os.environ.get("USERPROFILE")
    return (Path(profile) if profile else Path.home()) / "Desktop"


def get_skins_dir() -> Path:
    """
    Get the skins directory path.
    Creates the directory if it doesn't exist.
    """
    skins_dir = get_user_data_dir() / "skins"
    skins_dir.mkdir(parents=True, exist_ok=True)
    return skins_dir


def get_classic_skins_dir() -> Path:
    """
    Get the Rift Classic skins directory path (LeagueSkins' classic/ folder).
    Creates the directory if it doesn't exist.
    """
    classic_dir = get_user_data_dir() / "classic"
    classic_dir.mkdir(parents=True, exist_ok=True)
    return classic_dir


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


def open_folder_in_explorer(folder: Path) -> None:
    """
    Create `folder` if missing and reveal it in the OS file explorer.
    Raises on failure — callers handle logging/error reporting.
    """
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(folder))
    else:
        subprocess.Popen(["xdg-open", str(folder)])


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
        # __file__ is utils/core/paths.py, so we need to go up 3 levels to get to root
        return Path(__file__).parent.parent.parent


def get_tools_dir() -> Path:
    """Where Rose's injection tools are (ltk_launcher.exe, LeagueToolFlop.dll):
    inside the bundle of a built Rose, beside the sources otherwise."""
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            # One-file mode: tools are in _MEIPASS
            return Path(sys._MEIPASS) / "injection" / "tools"
        # One-dir mode: tools are alongside executable
        possible_dirs = [
            get_app_dir() / "injection" / "tools",
            get_app_dir() / "_internal" / "injection" / "tools",
        ]
        return next((dir_path for dir_path in possible_dirs if dir_path.exists()), possible_dirs[0])
    return get_app_dir() / "injection" / "tools"


def get_assets_dir() -> Path:
    """
    Get the base assets directory.
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
        return base_path / "assets"
    else:
        # Running as script
        app_dir = get_app_dir()
        return app_dir / "assets"


def get_asset_path(asset_name: str) -> Path:
    """
    Get the path to an asset file (icons, images, etc.)
    Works in both development and frozen (PyInstaller) environments.

    Args:
        asset_name: Name of the asset file (e.g., "champ-select-flyout-background-sr.jpg")

    Returns:
        Path to the asset file, or to a guaranteed-missing asset for invalid input.
    """
    assets_dir = get_assets_dir()
    invalid_asset = assets_dir / "__invalid_asset_path__"

    if not isinstance(asset_name, str):
        return invalid_asset

    cleaned_name = asset_name.replace("\\", "/").lstrip("/")
    candidate = Path(cleaned_name)

    if (
        not cleaned_name
        or candidate.is_absolute()
        or candidate.drive
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or ":" in cleaned_name
    ):
        return invalid_asset

    asset_path = assets_dir / candidate
    try:
        asset_path.resolve(strict=False).relative_to(assets_dir.resolve(strict=False))
    except (OSError, ValueError):
        return invalid_asset

    return asset_path


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


def get_detected_user_info() -> Tuple[str, str, bool]:
    """
    Get information about user detection for logging/debugging.

    Returns:
        Tuple of (current_username, target_username, is_mismatch)
    """
    current_username = os.environ.get("USERNAME", "unknown")
    desktop_username, _ = _get_desktop_user_info()

    if desktop_username:
        is_mismatch = desktop_username.lower() != current_username.lower()
        return current_username, desktop_username, is_mismatch

    return current_username, current_username, False
