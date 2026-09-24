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


def _dll_dialog_text(reason: str, detail: str = ""):
    """Return (title, status_title, status_body, steps) for an LTK patcher problem."""
    source = "Get both files from LTK Manager."
    if reason == "expired":
        return (
            "Rose - Patcher Outdated",
            "The LTK patcher has reached its end of life",
            f"The ltk_patcher_dll.dll in Rose's tools folder stopped supporting new game builds on {detail}.",
            f"1. Update LTK Manager, then get both files from it.\n"
            "2. Open Rose's tools folder.\n"
            "3. Replace both files, then restart Rose.",
        )
    if reason == "invalid":
        return (
            "Rose - Broken Patcher",
            "One Rose component needs replacing",
            "The ltk_patcher_dll.dll in Rose's tools folder is not a recognized LTK patcher DLL.",
            f"1. {source}\n"
            "2. Open Rose's tools folder.\n"
            "3. Replace both files, then restart Rose.",
        )
    return (
        "Rose - Missing Patcher",
        "One Rose component is missing",
        f"Rose needs {detail or 'the LTK patcher'} in its tools folder before it can start.",
        f"1. {source}\n"
        "2. Open Rose's tools folder.\n"
        "3. Place both files there, then restart Rose.",
    )


def _show_native_dll_dialog(tools_dir, reason="missing", detail=""):
    """Show the DLL error with the native Windows Task Dialog API."""
    if sys.platform != "win32":
        return None

    import ctypes
    from ctypes import wintypes
    import subprocess
    import webbrowser

    title, status_title, status_body, steps = _dll_dialog_text(reason, detail)

    class TaskDialogButton(ctypes.Structure):
        _pack_ = 1
        _fields_ = [
            ("nButtonID", wintypes.INT),
            ("pszButtonText", wintypes.LPCWSTR),
        ]

    class TaskDialogConfig(ctypes.Structure):
        _pack_ = 1
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("hwndParent", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("dwFlags", wintypes.DWORD),
            ("dwCommonButtons", wintypes.DWORD),
            ("pszWindowTitle", wintypes.LPCWSTR),
            ("hMainIcon", ctypes.c_void_p),
            ("pszMainInstruction", wintypes.LPCWSTR),
            ("pszContent", wintypes.LPCWSTR),
            ("cButtons", wintypes.UINT),
            ("pButtons", ctypes.POINTER(TaskDialogButton)),
            ("nDefaultButton", wintypes.INT),
            ("cRadioButtons", wintypes.UINT),
            ("pRadioButtons", ctypes.c_void_p),
            ("nDefaultRadioButton", wintypes.INT),
            ("pszVerificationText", wintypes.LPCWSTR),
            ("pszExpandedInformation", wintypes.LPCWSTR),
            ("pszExpandedControlText", wintypes.LPCWSTR),
            ("pszCollapsedControlText", wintypes.LPCWSTR),
            ("hFooterIcon", ctypes.c_void_p),
            ("pszFooter", wintypes.LPCWSTR),
            ("pfCallback", ctypes.c_void_p),
            ("lpCallbackData", wintypes.LPARAM),
            ("cxWidth", wintypes.UINT),
        ]

    button_open = 1001
    button_close = 1002
    buttons = (TaskDialogButton * 2)(
        TaskDialogButton(button_open, "Open tools folder"),
        TaskDialogButton(button_close, "Close Rose"),
    )
    content = (
        f"{status_body}\n\nHow to fix it:\n{steps}"
    )
    footer = "Please do not request or share this file in Discord. Rose cannot distribute it because of licensing restrictions."
    assets_dirs = []
    if hasattr(sys, "_MEIPASS"):
        assets_dirs.append(Path(sys._MEIPASS) / "assets")
    if getattr(sys, "frozen", False):
        assets_dirs.extend([
            Path(sys.executable).parent / "assets",
            Path(sys.executable).parent / "_internal" / "assets",
        ])
    else:
        assets_dirs.append(Path(__file__).parent.parent / "assets")

    icon_handle = None
    user32 = ctypes.windll.user32
    try:
        user32.LoadImageW.restype = ctypes.c_void_p
        for assets_dir in assets_dirs:
            icon_path = assets_dir / "icon.ico"
            if icon_path.exists():
                icon_handle = user32.LoadImageW(
                    None,
                    str(icon_path),
                    1,  # IMAGE_ICON
                    0,
                    0,
                    0x00000010 | 0x00000040,  # LR_LOADFROMFILE | LR_DEFAULTSIZE
                )
                if icon_handle:
                    break
    except (AttributeError, OSError, ctypes.ArgumentError):
        icon_handle = None

    dialog_flags = 0x0001 | 0x0008  # TDF_ENABLE_HYPERLINKS | TDF_ALLOW_DIALOG_CANCELLATION
    if icon_handle:
        dialog_flags |= 0x0002  # TDF_USE_HICON_MAIN
    config = TaskDialogConfig(
        cbSize=ctypes.sizeof(TaskDialogConfig),
        dwFlags=dialog_flags,
        pszWindowTitle=title,
        hMainIcon=icon_handle,
        pszMainInstruction=status_title,
        pszContent=content,
        cButtons=2,
        pButtons=buttons,
        nDefaultButton=button_open,
        pszFooter=footer,
        pfCallback=None,
        cxWidth=240,
    )
    selected_button = wintypes.INT()

    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_long,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.LPARAM,
    )

    def on_task_dialog_event(hwnd, notification, wparam, lparam, ref_data):
        if notification == 3:  # TDN_HYPERLINK_CLICKED
            try:
                webbrowser.open(ctypes.wstring_at(lparam))
            except Exception:
                pass
        elif notification == 7:  # TDN_DIALOG_CONSTRUCTED
            try:
                rect = wintypes.RECT()
                user32 = ctypes.windll.user32
                current_x = 18
                for button_id in (button_open, button_close):
                    button_hwnd = user32.GetDlgItem(hwnd, button_id)
                    if not button_hwnd:
                        continue
                    user32.GetWindowRect(button_hwnd, ctypes.byref(rect))
                    top_left = wintypes.POINT(rect.left, rect.top)
                    bottom_right = wintypes.POINT(rect.right, rect.bottom)
                    user32.ScreenToClient(hwnd, ctypes.byref(top_left))
                    user32.ScreenToClient(hwnd, ctypes.byref(bottom_right))
                    user32.SetWindowPos(
                        button_hwnd,
                        0,
                        current_x,
                        top_left.y,
                        bottom_right.x - top_left.x,
                        bottom_right.y - top_left.y,
                        0x0004 | 0x0010,  # SWP_NOZORDER | SWP_NOACTIVATE
                    )
                    current_x += (bottom_right.x - top_left.x) + 8
            except Exception:
                pass
        return 0

    callback = callback_type(on_task_dialog_event)
    config.pfCallback = ctypes.cast(callback, ctypes.c_void_p)

    try:
        task_dialog = ctypes.windll.comctl32.TaskDialogIndirect
        task_dialog.restype = ctypes.c_long
        task_dialog.argtypes = [
            ctypes.POINTER(TaskDialogConfig),
            ctypes.POINTER(wintypes.INT),
            ctypes.POINTER(wintypes.INT),
            ctypes.POINTER(wintypes.BOOL),
        ]
        result = task_dialog(
            ctypes.byref(config),
            ctypes.byref(selected_button),
            None,
            None,
        )
    except (AttributeError, OSError, ctypes.ArgumentError):
        return None

    if result != 0:
        return None
    if selected_button.value == button_open:
        try:
            subprocess.run(["explorer", str(tools_dir)], check=False)
        except Exception:
            pass
    return False


def _show_dll_dialog(tools_dir, reason="missing", detail="") -> bool:
    """Show a native recovery dialog before the main app starts."""
    import subprocess
    import webbrowser

    native_result = _show_native_dll_dialog(tools_dir, reason, detail)
    if native_result is not None:
        return native_result

    # Keep the recovery UI native-only if TaskDialogIndirect is unavailable.
    # This is intentionally a Windows MessageBox rather than a Tk fallback.
    import ctypes
    tools_dir.mkdir(parents=True, exist_ok=True)
    title, status_title, status_body, steps = _dll_dialog_text(reason, detail)
    message = (
        f"{status_title}\n\n{status_body}\n\nHow to fix it:\n{steps}\n\n"
        "Please do not request or share this file in Discord.\n"
        "Discord: https://discord.gg/roseskins\n\n"
        "Press OK to open the tools folder, or Cancel to close Rose."
    )
    response = ctypes.windll.user32.MessageBoxW(
        0, message, title, 0x00000001 | 0x00000030 | 0x00040000
    )
    if response == 1:
        try:
            subprocess.run(["explorer", str(tools_dir)], check=False)
        except Exception:
            pass
    return False


def _sync_cslol_stub(tools_dir: Path) -> None:
    """Replace cslol-dll.dll with Rose's stand-in when they differ.

    Updaters before this change skip cslol-dll.dll, so an update leaves the
    user's own copy in place. The stand-in ships again as cslol-dll.stub,
    which they do copy.
    """
    stub = tools_dir / "cslol-dll.stub"
    target = tools_dir / "cslol-dll.dll"
    try:
        if not stub.is_file():
            return
        if target.is_file() and target.read_bytes() == stub.read_bytes():
            return
        import shutil
        shutil.copyfile(stub, target)
    except OSError:
        pass  # The tools check reports a missing DLL when injection needs it


def _check_dll_present() -> bool:
    """Check that the user-provided LTK patcher is present and not past its end of life."""
    import sys
    if sys.platform != "win32":
        return True  # Only relevant on Windows

    from datetime import datetime
    from injection.tools.patcher import check_ltk_patcher

    tools_dir = _get_tools_dir()
    _sync_cslol_stub(tools_dir)
    status = check_ltk_patcher(tools_dir)
    if status.missing:
        return _show_dll_dialog(tools_dir, reason="missing", detail=" and ".join(status.missing))
    if status.eol is None:
        return _show_dll_dialog(tools_dir, reason="invalid")
    if status.expired:
        eol = datetime.fromtimestamp(status.eol).strftime("%Y-%m-%d %H:%M")
        return _show_dll_dialog(tools_dir, reason="expired", detail=eol)
    return True


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


def _setup_pengu_and_injection(lcu, injection_manager, activate_pengu: bool = True) -> None:
    """
    Detect and save leaguepath/clientpath, then setup Pengu Loader and injection system.

    Args:
        activate_pengu: If True, activate Pengu Loader (first startup).
                        If False, skip Pengu activation (reconnection after account swap).
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

    # Set client path in Pengu Loader and activate (skip on reconnection)
    if activate_pengu:
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

    # Safety net: recover a previous session before startup. If League still owns
    # the loaded module, cleanup_if_dirty adopts the active session instead.
    pengu_loader.cleanup_if_dirty()

    # Parse arguments if they were not provided
    if args is None:
        args = setup_arguments()
    
    # Setup logging and cleanup
    setup_logging_and_cleanup(args)

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

    # Create LCU reconnection handler. Pengu remains active across account swaps;
    # the newly created League client process is covered by the existing IFEO
    # registration, so no loader or client restart is necessary here.
    def on_lcu_reconnected():
        log.info("[Main] LCU reconnected after account swap - keeping Pengu Loader active...")
        try:
            _setup_pengu_and_injection(lcu, injection_manager, activate_pengu=False)
        except Exception as e:
            log.warning(f"[Main] Failed to re-initialize after reconnection: {e}")

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
        lcu, state, args, injection_manager, skin_scraper, app_status, on_lcu_disconnected, on_lcu_reconnected
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
