#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for Rose
"""

import argparse
import sys
from typing import Optional
from pathlib import Path

# Python version check
MIN_PYTHON = (3, 11)
if sys.version_info < MIN_PYTHON:
    raise RuntimeError(
        f"Rose requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer. "
        "Please upgrade your interpreter and rebuild the application."
    )


def _get_tools_dir() -> Path:
    """Get the tools directory path (works in both frozen and development environments)"""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable (PyInstaller)
        if hasattr(sys, '_MEIPASS'):
            # One-file mode: tools are in _MEIPASS
            base_path = Path(sys._MEIPASS)
            return base_path / "injection" / "tools"
        else:
            # One-dir mode: tools are alongside executable
            base_dir = Path(sys.executable).parent
            possible_dirs = [
                base_dir / "injection" / "tools",
                base_dir / "_internal" / "injection" / "tools",
            ]
            for dir_path in possible_dirs:
                if dir_path.exists():
                    return dir_path
            return possible_dirs[0]
    else:
        # Running as Python script
        return Path(__file__).parent.parent / "injection" / "tools"


_VALID_DLL_HASHES = {
    "4a009619c6dea691780b2f20cf17e08de478a78b3f11cd72759dd71c00ad1c90",
}


def _check_dll_hash(dll_path) -> bool:
    """Verify cslol-dll.dll matches a known-good SHA-256 hash."""
    import hashlib
    try:
        sha = hashlib.sha256()
        with open(dll_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest() in _VALID_DLL_HASHES
    except Exception:
        return False


def _show_dll_invalid_dialog(tools_dir) -> bool:
    """Show a warning that the DLL file is invalid/untrusted."""
    import ctypes
    import subprocess

    ctypes.windll.user32.MessageBoxW(
        0,
        "The cslol-dll.dll file you provided is not recognized.\n\n"
        "It may be corrupted, outdated, or from an untrusted source.\n"
        "Using an unverified DLL can compromise your system.\n\n"
        "Please replace it with the correct file.\n\n"
        "This file is NOT available on our Discord. Do not ask for it there.\n"
        "Asking for or sharing this file will result in a permanent ban.",
        "Rose - Invalid DLL",
        0x40010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND
    )
    try:
        subprocess.run(["explorer", str(tools_dir)], check=False)
    except Exception:
        pass
    return False


def _check_dll_present() -> bool:
    """
    Check if cslol-dll.dll is present and valid. If not, show a warning dialog and exit.
    Returns True if DLL is present and hash-verified, False otherwise.
    """
    if sys.platform != "win32":
        return True  # Only relevant on Windows

    tools_dir = _get_tools_dir()
    dll_path = tools_dir / "cslol-dll.dll"

    if dll_path.exists():
        if _check_dll_hash(dll_path):
            return True
        # DLL exists but wrong hash — show specific warning
        return _show_dll_invalid_dialog(tools_dir)

    # DLL missing

    # DLL is missing - show native Windows TaskDialog with clickable link
    import ctypes
    from ctypes import wintypes
    import subprocess
    import webbrowser

    # Ensure tools directory exists for the user to place the DLL
    tools_dir.mkdir(parents=True, exist_ok=True)

    # Initialize common controls (required for TaskDialog)
    class INITCOMMONCONTROLSEX(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint),
            ("dwICC", ctypes.c_uint),
        ]

    ICC_WIN95_CLASSES = 0x000000FF
    icc = INITCOMMONCONTROLSEX()
    icc.dwSize = ctypes.sizeof(INITCOMMONCONTROLSEX)
    icc.dwICC = ICC_WIN95_CLASSES
    ctypes.windll.comctl32.InitCommonControlsEx(ctypes.byref(icc))

    # TaskDialog button IDs
    IDCANCEL = 2
    ID_OPEN_FOLDER = 1000

    # TaskDialog flags
    TDF_ENABLE_HYPERLINKS = 0x0001
    TDF_ALLOW_DIALOG_CANCELLATION = 0x0008

    # TaskDialog icons - use TD_WARNING_ICON properly
    TD_WARNING_ICON = 0xFFFF  # -1 as unsigned

    # Callback for hyperlink clicks
    TDN_HYPERLINK_CLICKED = 3

    # Store callback reference to prevent garbage collection
    callback_ref = None

    def make_callback():
        @ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM, ctypes.c_long)
        def task_dialog_callback(hwnd, msg, wparam, lparam, refdata):
            if msg == TDN_HYPERLINK_CLICKED:
                try:
                    url = ctypes.wstring_at(lparam)
                    webbrowser.open(url)
                except Exception:
                    pass
            return 0
        return task_dialog_callback

    callback_ref = make_callback()

    # TASKDIALOG_BUTTON structure
    class TASKDIALOG_BUTTON(ctypes.Structure):
        _fields_ = [
            ("nButtonID", ctypes.c_int),
            ("pszButtonText", wintypes.LPCWSTR),
        ]

    # TASKDIALOGCONFIG structure
    class TASKDIALOGCONFIG(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("hwndParent", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("dwFlags", ctypes.c_uint),
            ("dwCommonButtons", ctypes.c_uint),
            ("pszWindowTitle", wintypes.LPCWSTR),
            ("pszMainIcon", wintypes.LPCWSTR),
            ("pszMainInstruction", wintypes.LPCWSTR),
            ("pszContent", wintypes.LPCWSTR),
            ("cButtons", ctypes.c_uint),
            ("pButtons", ctypes.POINTER(TASKDIALOG_BUTTON)),
            ("nDefaultButton", ctypes.c_int),
            ("cRadioButtons", ctypes.c_uint),
            ("pRadioButtons", ctypes.c_void_p),
            ("nDefaultRadioButton", ctypes.c_int),
            ("pszVerificationText", wintypes.LPCWSTR),
            ("pszExpandedInformation", wintypes.LPCWSTR),
            ("pszExpandedControlText", wintypes.LPCWSTR),
            ("pszCollapsedControlText", wintypes.LPCWSTR),
            ("pszFooterIcon", wintypes.LPCWSTR),
            ("pszFooter", wintypes.LPCWSTR),
            ("pfCallback", ctypes.c_void_p),
            ("lpCallbackData", ctypes.c_void_p),
            ("cxWidth", ctypes.c_uint),
        ]

    # Create buttons array
    buttons = (TASKDIALOG_BUTTON * 2)()
    buttons[0].nButtonID = ID_OPEN_FOLDER
    buttons[0].pszButtonText = "Open Folder"
    buttons[1].nButtonID = IDCANCEL
    buttons[1].pszButtonText = "Cancel"

    content_text = (
        "Due to DMCA restrictions, Rose cannot distribute the cslol-dll.dll file.\n\n"
        "You must provide your own signed cslol-dll.dll file.\n\n"
        "This file is NOT available on our Discord. Do not ask for it there.\n"
        "Asking for or sharing this file on the Discord will result in a permanent ban.\n\n"
        "<a href=\"https://discord.gg/roseapp\">https://discord.gg/roseapp</a>"
    )

    # Configure dialog
    config = TASKDIALOGCONFIG()
    config.cbSize = ctypes.sizeof(TASKDIALOGCONFIG)
    config.hwndParent = None
    config.hInstance = None
    config.dwFlags = TDF_ENABLE_HYPERLINKS | TDF_ALLOW_DIALOG_CANCELLATION
    config.dwCommonButtons = 0
    config.pszWindowTitle = "Rose - DLL Required"
    config.pszMainIcon = ctypes.cast(TD_WARNING_ICON, wintypes.LPCWSTR)
    config.pszMainInstruction = "DLL file required"
    config.pszContent = content_text
    config.cButtons = 2
    config.pButtons = ctypes.cast(buttons, ctypes.POINTER(TASKDIALOG_BUTTON))
    config.nDefaultButton = ID_OPEN_FOLDER
    config.pfCallback = ctypes.cast(callback_ref, ctypes.c_void_p)
    config.lpCallbackData = 0
    config.cxWidth = 0

    # Show dialog
    button_pressed = ctypes.c_int(0)
    hr = ctypes.windll.comctl32.TaskDialogIndirect(
        ctypes.byref(config),
        ctypes.byref(button_pressed),
        None,
        None
    )

    # Check if TaskDialog failed
    if hr != 0:
        # Fallback to simple MessageBox
        result = ctypes.windll.user32.MessageBoxW(
            0,
            "Due to DMCA restrictions, Rose cannot distribute the cslol-dll.dll file.\n\n"
            "You must provide your own signed cslol-dll.dll file.\n\n"
            "This file is NOT available on our Discord. Do not ask for it there.\n"
            "Asking for or sharing this file will result in a permanent ban.\n\n"
            "Click OK to open the folder where you should place the DLL.",
            "Rose - DLL Required",
            0x40031  # MB_OKCANCEL | MB_ICONWARNING | MB_SETFOREGROUND
        )
        if result == 1:  # IDOK
            try:
                subprocess.run(["explorer", str(tools_dir)], check=False)
            except Exception:
                pass
        return False

    # Handle button press
    if button_pressed.value == ID_OPEN_FOLDER:
        try:
            subprocess.run(["explorer", str(tools_dir)], check=False)
        except Exception:
            pass

    return False

# Setup console first (before any imports that might use it)
from .setup.console import setup_console, redirect_none_streams, start_console_buffer_manager
setup_console()
redirect_none_streams()
start_console_buffer_manager()

# Setup signal handlers
from .core.signals import setup_signal_handlers
setup_signal_handlers()

# Now import everything else
from .setup.arguments import setup_arguments
from .setup.initialization import setup_logging_and_cleanup, initialize_tray_manager
from .core.lockfile import check_single_instance
from .core.initialization import initialize_core_components
from .core.threads import initialize_threads
from .core.lcu_handler import create_lcu_disconnection_handler
from .core.cleanup import perform_cleanup
from .runtime.loop import run_main_loop

import utils.integration.pengu_loader as pengu_loader
from state import AppStatus
from utils.core.logging import get_logger, log_success
from utils.threading.thread_manager import create_daemon_thread
from config import APP_VERSION, MAIN_LOOP_FORCE_QUIT_TIMEOUT_S, set_config_option
from injection.config.config_manager import ConfigManager
from injection.game.game_detector import GameDetector
import time

log = get_logger()


def _setup_pengu_and_injection(lcu, injection_manager) -> None:
    """
    Detect and save leaguepath/clientpath, then setup both Pengu Loader and injection system.
    
    This function:
    1. Detects leaguepath/clientpath from lockfile
    2. Saves paths to config.ini
    3. Verifies paths are written
    4. Sets league path in Pengu Loader and activates it
    5. Initializes injection system with detected paths
    
    Note: LCU is already connected when this is called (WebSocket is active)
    """
    log.info("Detecting League paths...")
    
    # Detect paths using GameDetector (only once)
    config_manager = ConfigManager()
    game_detector = GameDetector(config_manager)
    league_path, client_path = game_detector.detect_paths()
    
    if not league_path or not client_path:
        log.warning("Could not detect League paths, skipping setup")
        return
    
    # Save paths to config.ini
    log.info("Saving League paths to config.ini: league=%s, client=%s", league_path, client_path)
    config_manager.save_paths(str(league_path), str(client_path))
    
    # Verify paths are written to config.ini (with retries)
    max_verify_attempts = 5
    verify_interval = 0.2
    paths_verified = False
    
    for attempt in range(max_verify_attempts):
        saved_league_path = config_manager.load_league_path()
        saved_client_path = config_manager.load_client_path()
        
        if saved_league_path and saved_client_path:
            # Normalize paths for comparison
            saved_league_normalized = str(Path(saved_league_path).resolve())
            saved_client_normalized = str(Path(saved_client_path).resolve())
            league_normalized = str(league_path.resolve())
            client_normalized = str(client_path.resolve())
            
            if saved_league_normalized == league_normalized and saved_client_normalized == client_normalized:
                paths_verified = True
                log.info("Paths verified in config.ini")
                break
        
        if attempt < max_verify_attempts - 1:
            time.sleep(verify_interval)
    
    if not paths_verified:
        log.warning("Could not verify paths in config.ini, continuing anyway")
    
    # Set client path in Pengu Loader and activate
    log.info("Setting client path in Pengu Loader and activating...")
    pengu_loader.activate_on_start(str(client_path))
    
    # Initialize injection system now (with detected paths already in config.ini)
    log.info("Initializing injection system...")
    injection_manager.initialize_when_ready()


def _update_registry_version() -> None:
    """Update the DisplayVersion in Windows registry to match the current app version.

    After an auto-update the Inno Setup registry entry still shows the version
    that was originally installed.  Writing the current ``APP_VERSION`` on every
    startup keeps "Apps & features" in sync.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import winreg
        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Rose"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
    except Exception:
        pass


def run_league_unlock(args: Optional[argparse.Namespace] = None,
                      injection_threshold: Optional[float] = None) -> None:
    """Run the core Rose application startup and main loop."""
    # Check for single instance before doing anything else
    check_single_instance()

    # Keep the Windows "Apps & features" version in sync after auto-updates
    _update_registry_version()

    # Safety net: if a previous session didn't shut down cleanly, deactivate
    # Pengu Loader before we re-activate it later in the startup sequence.
    pengu_loader.cleanup_if_dirty()

    # Parse arguments if they were not provided
    if args is None:
        args = setup_arguments()
    
    # Setup logging and cleanup
    setup_logging_and_cleanup(args)

    # Clean up old Pengu Loader IFEO registry entry that can cause client crashes
    # This runs on every startup to handle both fresh installs and updates
    pengu_loader.cleanup_old_pengu_ifeo()

    # Initialize system tray manager immediately to hide console
    tray_manager = initialize_tray_manager(args)
    
    # Initialize app status manager
    app_status = AppStatus(tray_manager)
    log_success(log, "App status manager initialized", "")
    
    # Check initial status (will show locked until all components are ready)
    app_status.update_status(force=True)
    
    # Initialize core components
    lcu, skin_scraper, state, injection_manager = initialize_core_components(args, injection_threshold)
    
    # Configure skin writing based on the final injection threshold (seconds → ms)
    state.skin_write_ms = max(0, int(injection_manager.injection_threshold * 1000))
    state.inject_batch = getattr(args, 'inject_batch', state.inject_batch) or state.inject_batch
    
    # Create LCU disconnection handler
    on_lcu_disconnected = create_lcu_disconnection_handler(state, skin_scraper, app_status)
    
    # Update tray manager quit callback now that state is available
    if tray_manager:
        def updated_tray_quit_callback():
            """Callback for tray quit - set the shared state stop flag"""
            log.info("Setting stop flag from tray quit")
            log.debug(f"[DEBUG] State before setting stop: {state.stop}")
            state.stop = True
            log.debug(f"[DEBUG] State after setting stop: {state.stop}")
            log.info("Stop flag set - main loop should exit")
            
            # Immediately try to trigger any pending console operations that might be blocking
            if sys.platform == "win32":
                try:
                    # Force a console input check to unblock any stuck operations
                    import msvcrt  # Windows-only module
                    if msvcrt.kbhit():
                        msvcrt.getch()  # Consume any pending input
                except (ImportError, OSError) as e:
                    log.debug(f"Console input check failed: {e}")
            
            # Add a timeout to force quit if main loop doesn't exit
            def force_quit_timeout():
                import time
                from .core.signals import force_quit_handler
                time.sleep(MAIN_LOOP_FORCE_QUIT_TIMEOUT_S)
                from .core.state import get_app_state
                app_state = get_app_state()
                if not app_state.shutting_down:
                    log.warning(f"Main loop did not exit within {MAIN_LOOP_FORCE_QUIT_TIMEOUT_S}s - forcing quit")
                    force_quit_handler()
            
            timeout_thread = create_daemon_thread(target=force_quit_timeout, 
                                                 name="ForceQuitTimeout")
            timeout_thread.start()
        
        tray_manager.quit_callback = updated_tray_quit_callback
    
    # Initialize threads (this starts the WebSocket server)
    thread_manager, t_phase, t_ui, t_ws, t_lcu_monitor = initialize_threads(
        lcu, state, args, injection_manager, skin_scraper, app_status, on_lcu_disconnected
    )
    
    # Wait for WebSocket status to be active before activating Pengu Loader
    log.info("Waiting for WebSocket status to be active before activating Pengu Loader...")
    while not t_ws.connection.is_connected:
        time.sleep(0.1)
    
    log.info("WebSocket status is active, proceeding with Pengu Loader and injection system setup")
    
    # Setup Pengu Loader and injection system (LCU is already connected when WebSocket is active)
    _setup_pengu_and_injection(lcu, injection_manager)
    
    # Run main loop
    try:
        run_main_loop(state, skin_scraper)
    finally:
        # Perform cleanup
        perform_cleanup(state, thread_manager, tray_manager, injection_manager)


def main() -> None:
    """Program entry point that prepares and launches Rose."""
    # Check for required DLL before anything else
    if not _check_dll_present():
        sys.exit(1)

    args = setup_arguments()
    if sys.platform == "win32":
        if not args.dev:
            try:
                from launcher import run_launcher
                run_launcher(
                    dev_mode=args.dev,
                    test_download_fail=getattr(args, 'test_download_fail', False),
                )
            except ModuleNotFoundError as err:
                print(f"[Launcher] Unable to import launcher module: {err}")
            except Exception as err:  # noqa: BLE001
                print(f"[Launcher] Launcher encountered an error: {err}")

    run_league_unlock(args=args)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Top-level exception handler to catch any unhandled crashes
        import traceback
        import ctypes
        try:
            from utils.core.issue_reporter import report_issue
            report_issue(
                "FATAL_CRASH",
                "error",
                "Rose crashed unexpectedly.",
                details={"type": type(e).__name__, "error": str(e)},
                hint="Check %LOCALAPPDATA%\\Rose\\logs\\ for details.",
            )
        except Exception:
            pass
        
        error_msg = f"""
================================================================================
FATAL ERROR - Rose Crashed
================================================================================
Error: {e}
Type: {type(e).__name__}

Traceback:
{traceback.format_exc()}
================================================================================

This error has been logged. Please report this issue with the log file.
Log location: Check %LOCALAPPDATA%\\Rose\\logs\\
================================================================================
"""
        
        # Try to log the error
        try:
            log = get_logger()
            log.error(error_msg)
        except (AttributeError, RuntimeError, OSError) as e:
            # If logging fails, print to stderr
            print(error_msg, file=sys.stderr)
            print(f"Logging system error: {e}", file=sys.stderr)
        
        # Show error dialog on Windows
        if sys.platform == "win32":
            try:
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"Rose crashed with an unhandled error:\n\n{str(e)}\n\nError type: {type(e).__name__}\n\nPlease check the log file in:\n%LOCALAPPDATA%\\Rose\\logs\\",
                    "Rose - Fatal Error",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except Exception:
                pass
        
        sys.exit(1)

