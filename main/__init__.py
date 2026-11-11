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


LTK_MANAGER_DOWNLOAD_URL = "https://github.com/LeagueToolkit/ltk-manager/releases"


def _dll_dialog_text(reason: str, detail: str = ""):
    """Return (title, status_title, status_body, steps, action) for an injection
    runtime problem; *action* is the label of the button that fixes it."""
    if reason == "no_manager":
        return (
            "Rose - LTK Manager Missing",
            "Rose can't find LTK Manager",
            "Rose applies skins through LTK Manager. It only has to be installed: Rose "
            "opens it in the background during champ select and closes it after the game, "
            "so you never have to open it yourself.",
            f"1. Install LTK Manager ({LTK_MANAGER_DOWNLOAD_URL}), then restart Rose.\n"
            "2. Already installed in another folder? Click Set up path and select its "
            "ltk-manager.exe: Rose remembers it and starts right away.",
            "Set up path",
        )
    return (
        "Rose - Missing Component",
        "One Rose component is missing",
        f"Rose needs {detail or 'its bridge files'} in its tools folder before it can start.",
        "1. Reinstall Rose: these files are part of every install.\n"
        "2. If an antivirus removed them, restore the files or add Rose's folder to its exclusions.\n"
        "3. Restart Rose.",
        "Open tools folder",
    )


def _with_links(text: str) -> str:
    """The text with its web addresses as Task Dialog hyperlinks."""
    import re

    return re.sub(r"(https?://[^\s)]+)", r'<a href="\1">\1</a>', text)


def _show_native_dll_dialog(reason="missing", detail=""):
    """Show the DLL error with the native Windows Task Dialog API.

    Returns "fix" (the button that fixes it), "close", or None when the
    Task Dialog is not available.
    """
    if sys.platform != "win32":
        return None

    import ctypes
    from ctypes import wintypes
    import webbrowser

    title, status_title, status_body, steps, action = _dll_dialog_text(reason, detail)

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
        TaskDialogButton(button_open, action),
        TaskDialogButton(button_close, "Close Rose"),
    )
    content = _with_links(f"{status_body}\n\nHow to fix it:\n{steps}")
    footer = _with_links("Need help? Join the Rose Discord: https://discord.gg/roseskins")
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
    return "fix" if selected_button.value == button_open else "close"


def _show_fallback_dll_dialog(reason="missing", detail="") -> str:
    """The same choice as a MessageBox, when the Task Dialog is unavailable.

    Intentionally a Windows MessageBox rather than a Tk fallback.
    """
    import ctypes

    title, status_title, status_body, steps, action = _dll_dialog_text(reason, detail)
    message = (
        f"{status_title}\n\n{status_body}\n\nHow to fix it:\n{steps}\n\n"
        "Discord: https://discord.gg/roseskins\n\n"
        f"Press OK to {action.lower()}, or Cancel to close Rose."
    )
    response = ctypes.windll.user32.MessageBoxW(
        0, message, title, 0x00000001 | 0x00000030 | 0x00040000
    )
    return "fix" if response == 1 else "close"


def _pick_ltk_manager() -> Optional[Path]:
    """Ask for LTK Manager's executable with the Windows file picker (None if cancelled)."""
    import ctypes
    import os
    from ctypes import wintypes

    class OpenFileName(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    # Pairs of label and pattern, each ending in a NUL, the list in a second one
    file_filter = ctypes.create_unicode_buffer(
        "LTK Manager (ltk-manager.exe)\0ltk-manager.exe;LTK Manager.exe\0Programs (*.exe)\0*.exe\0\0"
    )
    file_buffer = ctypes.create_unicode_buffer(1024)
    initial_dir = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or ""
    dialog = OpenFileName(
        lStructSize=ctypes.sizeof(OpenFileName),
        lpstrFilter=ctypes.cast(file_filter, wintypes.LPCWSTR),
        nFilterIndex=1,
        lpstrFile=ctypes.cast(file_buffer, wintypes.LPWSTR),
        nMaxFile=len(file_buffer),
        lpstrInitialDir=initial_dir or None,
        lpstrTitle="Select LTK Manager (ltk-manager.exe)",
        # OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_EXPLORER | OFN_DONTADDTORECENT
        Flags=0x1000 | 0x0800 | 0x0008 | 0x00080000 | 0x02000000,
    )
    try:
        picked = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(dialog))
    except (AttributeError, OSError, ctypes.ArgumentError) as exc:
        log.warning(f"[DLL] Could not open the file picker: {exc}")
        return None
    return Path(file_buffer.value) if picked and file_buffer.value else None


def _set_up_ltk_manager_path(tools_dir) -> Optional[bool]:
    """Let the user point Rose at LTK Manager and save it as ltkManagerPath.

    True once Rose finds LTK Manager there, None when the user cancelled or
    picked something else (the dialog shows again).
    """
    import ctypes

    from config import set_config_option
    from injection.tools.tools_manager import LTK_MANAGER_EXECUTABLES, ToolsManager

    picked = _pick_ltk_manager()
    if picked is None:
        return None
    message_flags = 0x00000030 | 0x00040000  # MB_ICONWARNING | MB_TOPMOST
    if picked.name.lower() not in {name.lower() for name in LTK_MANAGER_EXECUTABLES}:
        ctypes.windll.user32.MessageBoxW(
            0,
            f"{picked.name} is not LTK Manager.\n\nSelect ltk-manager.exe in the folder LTK Manager "
            "is installed in.",
            "Rose - LTK Manager Missing",
            message_flags,
        )
        return None
    set_config_option("General", "ltkManagerPath", str(picked))
    if ToolsManager(tools_dir).detect_ltk_manager() is None:
        ctypes.windll.user32.MessageBoxW(
            0,
            "Rose could not save the path in its config.ini.\n\nCheck that Rose can write to "
            "%LOCALAPPDATA%\\Rose, then try again.",
            "Rose - LTK Manager Missing",
            message_flags,
        )
        return None
    log.info(f"[DLL] LTK Manager set up at {picked}")
    return True


def _show_dll_dialog(tools_dir, reason="missing", detail="") -> bool:
    """Show a native recovery dialog before the main app starts.

    Returns whether Rose can start (LTK Manager was set up from the dialog).
    """
    import subprocess

    while True:
        choice = _show_native_dll_dialog(reason, detail)
        if choice is None:
            choice = _show_fallback_dll_dialog(reason, detail)
        if choice != "fix":
            return False
        if reason == "no_manager":
            if _set_up_ltk_manager_path(tools_dir):
                return True
            continue  # cancelled or not LTK Manager: back to the dialog
        try:
            tools_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["explorer", str(tools_dir)], check=False)
        except Exception as exc:
            log.warning(f"[DLL] Could not open the tools folder: {exc}")
        return False


def _check_dll_present() -> bool:
    """Check that Rose's LTF bridge is present and LTK Manager is installed."""
    import sys
    if sys.platform != "win32":
        return True  # Only relevant on Windows

    from injection.tools.tools_manager import LTF_BRIDGE_DLL, LTF_LAUNCHER, ToolsManager
    from utils.core.paths import get_tools_dir

    tools_dir = get_tools_dir()
    missing = [name for name in (LTF_LAUNCHER, LTF_BRIDGE_DLL) if not (tools_dir / name).exists()]
    if missing:
        return _show_dll_dialog(tools_dir, reason="missing", detail=" and ".join(missing))
    if ToolsManager(tools_dir).detect_ltk_manager() is None:
        return _show_dll_dialog(tools_dir, reason="no_manager")
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
from .setup.initialization import convert_stored_mods, setup_logging_and_cleanup, initialize_tray_manager
from .core.lockfile import check_single_instance
from .core.initialization import initialize_core_components
from .core.threads import initialize_threads
from .core.lcu_handler import create_lcu_disconnection_handler
from .core.cleanup import perform_cleanup
from .runtime.loop import run_main_loop

import utils.integration.pengu_loader as pengu_loader
from state import AppStatus
from utils.core.logging import get_logger, log_success
from utils.core.issue_reporter import report_issue
from utils.threading.thread_manager import create_daemon_thread
from config import APP_VERSION, MAIN_LOOP_FORCE_QUIT_TIMEOUT_S, get_config_option, set_config_option
from injection.config.config_manager import ConfigManager
from injection.game.game_detector import GameDetector
from injection.mods.ltk_sync import start_saved_mods_sync
from injection.mods.mod_facts import remove_unpacked_leftovers
import time

log = get_logger()


def _warn_pengu_activation_failed() -> None:
    """Tell the user Rose will not show in the client because Pengu Loader is not active.

    Rose's own Troubleshooting panel lives in the client plugins, the part that
    failed, so this has to be a Windows dialog. It runs on its own thread so
    startup goes on while it is open.
    """
    log = get_logger()
    log.error("[Pengu] Activation failed - Rose will not appear in the League client")
    report_issue(
        "PENGU_ACTIVATION_FAILED",
        "error",
        "Pengu Loader could not be activated, so Rose did not appear in the League client.",
        hint="Close the League client, then restart Rose. If it happens again, make sure your antivirus is not blocking Pengu Loader.",
    )
    if sys.platform != "win32":
        return

    def show():
        import ctypes
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                "Rose could not activate Pengu Loader, so it will not appear in the League client.\n\n"
                "Close the League client, then restart Rose.\n"
                "If it happens again, make sure your antivirus is not blocking Pengu Loader.\n\n"
                "Details are in %LOCALAPPDATA%\\Rose\\logs\\",
                "Rose - Pengu Loader",
                0x50030,  # MB_OK | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
            )
        except Exception as e:
            log.warning(f"[Pengu] Could not show the activation warning: {e}")

    create_daemon_thread(show, "PenguActivationWarning").start()


def _warn_pengu_injection_failed(client_pid: int) -> None:
    """Pengu Loader was activated, but the client checked once the LCU was up
    has no Pengu module and Rose's plugin never reached the bridge
    (utils.integration.startup_verifier). Called on the verifier's thread."""
    log = get_logger()
    report_issue(
        "PENGU_INJECTION_FAILED",
        "error",
        "Pengu Loader was not loaded into the League client, so Rose did not appear in it.",
        details={"client_pid": client_pid},
        hint="Right-click Rose in the system tray and choose Diagnose Rose startup.",
    )
    if sys.platform != "win32":
        return

    import ctypes
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            "Rose did not load into this League client: Pengu Loader's DLL is missing from it.\n\n"
            "Right-click Rose's system tray icon and choose Diagnose Rose startup. "
            "Keep League open while collecting the report.\n\n"
            "Then send report.txt and report.json on the Rose Discord (https://discord.gg/roseskins) "
            "or in a GitHub issue (https://github.com/Alban1911/Rose/issues), so we can find out why. "
            "You can also paste them into an AI assistant for a first look.",
            "Rose - Client injection failed",
            0x50030,  # MB_OK | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
        )
    except Exception as e:
        log.warning(f"[Pengu] Could not show the injection warning: {e}")


def _setup_pengu_and_injection(lcu, injection_manager, activate_pengu: bool = True) -> None:
    """
    Detect and save leaguepath/clientpath, then setup Pengu Loader and injection system.

    Args:
        activate_pengu: If True, activate Pengu Loader (startup couldn't).
                        If False, skip Pengu activation (done at startup, or a
                        reconnection after account swap).
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
        if not pengu_loader.activate_on_start(str(client_path)):
            _warn_pengu_activation_failed()

    # Initialize injection system now (with detected paths already in config.ini)
    log.info("Initializing injection system...")
    injection_manager.initialize_when_ready()


def _update_registry_version() -> None:
    """Update the DisplayVersion in Windows registry to match the current app version.

    After an auto-update the Inno Setup registry entry still shows the version
    that was originally installed.  Writing the current ``APP_VERSION`` on every
    startup keeps "Apps & features" in sync.

    Inno names its entry after the AppId (``AppId={{...}}`` keeps the closing
    ``}}``). Older installers also wrote ``Uninstall\\Rose``, which stays until
    a newer installer runs, so that one is kept in sync too while it exists.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import winreg
    except ImportError:
        return
    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for name in ("{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}}_is1", "Rose"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{uninstall}\{name}", 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        except Exception:
            pass

def _schedule_restart() -> bool:
    """Spawn a detached helper that relaunches Rose after this process exits.

    The new instance cannot start while the current one is still alive because
    of the single-instance mutex, so a small batch file waits for this PID to
    exit and then starts Rose again.
    """
    import os
    import subprocess
    import tempfile

    try:
        pid = os.getpid()
        if getattr(sys, 'frozen', False):
            exe_path = Path(sys.executable).resolve()
            workdir = exe_path.parent
            launch_cmd = f'start "" /D "{workdir}" "{exe_path}"'
        else:
            # Development mode: relaunch `python main.py` from the project root
            exe_path = Path(sys.executable).resolve()
            workdir = Path(__file__).parent.parent
            launch_cmd = f'start "" /D "{workdir}" "{exe_path}" "main.py"'

        batch_path = Path(tempfile.gettempdir()) / f"rose_restart_{pid}.bat"

        batch_content = (
            "@echo off\n"
            "setlocal enableextensions\n"
            f'set "TARGET_PID={pid}"\n'
            ":wait\n"
            'tasklist /FI "PID eq %TARGET_PID%" /NH 2>NUL | find /I "%TARGET_PID%" >NUL\n'
            'if not errorlevel 1 (\n'
            '    ping 127.0.0.1 -n 2 >NUL\n'
            '    goto wait\n'
            ')\n'
            f"{launch_cmd}\n"
            'del "%~f0" >NUL 2>&1\n'
            "exit\n"
        )
        batch_path.write_text(batch_content, encoding="utf-8")

        subprocess.Popen(
            ["cmd", "/c", str(batch_path)],
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log.info(f"Restart scheduled via {batch_path}")
        return True
    except Exception as e:
        log.error(f"Failed to schedule restart: {e}")
        return False

def _remove_unpacked_mods_while_alone() -> None:
    """Remove the .modpkg copies earlier reads left unpacked: Rose runs alone
    now and nothing has read a mod yet, so none is being unpacked."""
    remove_unpacked_leftovers()


def _sync_mods_changed_while_closed() -> None:
    """Sync the saved mods with LTK Manager's library, which may have lost or
    changed one while Rose was closed."""
    start_saved_mods_sync(only_if_changed=False)


def run_league_unlock(args: Optional[argparse.Namespace] = None,
                      injection_threshold: Optional[float] = None) -> None:
    """Run the core Rose application startup and main loop."""
    # Check for single instance before doing anything else
    check_single_instance()
    _remove_unpacked_mods_while_alone()

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

    # Mods an earlier Rose stored as folders become the archives LTK Manager
    # installs as they are. Before anything else starts: no injection, import
    # or mod list may touch a folder while it is converted
    convert_stored_mods(tray_manager)

    _sync_mods_changed_while_closed()

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

        def updated_tray_restart_callback():
            """Callback for tray restart - relaunch Rose after this process exits"""
            log.info("Restart requested from tray - scheduling relaunch")
            if not _schedule_restart():
                log.warning("Restart scheduling failed; Rose will quit without relaunching")
            state.stop = True
            log.info("Stop flag set - main loop should exit before relaunch")

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

        tray_manager.restart_callback = updated_tray_restart_callback

        # A Quit or Restart clicked while Rose was starting runs now
        tray_manager.run_pending_request()
    
    # Initialize threads (this starts the WebSocket server)
    thread_manager, t_phase, t_ui, t_ws, t_lcu_monitor = initialize_threads(
        lcu, state, args, injection_manager, skin_scraper, app_status, on_lcu_disconnected, on_lcu_reconnected
    )

    # Activate Pengu now rather than once a client runs: a client started after
    # Rose then loads the plugins itself instead of starting without them and
    # waiting for a restart. A running client is restarted (the bridge is up).
    log.info("Activating Pengu Loader...")
    pengu_active = pengu_loader.activate_on_start(get_config_option("General", "clientPath"))
    if not pengu_active:
        log.warning("Pengu Loader could not be activated yet; retrying once the client is up")

    # Wait for WebSocket status to be active before setting up the injection system
    log.info("Waiting for WebSocket status to be active...")
    while not t_ws.connection.is_connected:
        time.sleep(0.1)

    log.info("WebSocket status is active, proceeding with Pengu Loader and injection system setup")

    # A restart the client refused while it was still starting goes through now
    pengu_loader.retry_deferred_restart()

    # Setup Pengu Loader and injection system (LCU is already connected when WebSocket is active)
    _setup_pengu_and_injection(lcu, injection_manager, activate_pengu=not pengu_active)

    from utils.integration.startup_verifier import StartupInjectionVerifier
    verifier = StartupInjectionVerifier(lcu, state, t_ui.websocket_server, _warn_pengu_injection_failed)
    thread_manager.register("Startup injection verifier", verifier, stop_method=verifier.stop)
    verifier.start()
    
    # Run main loop
    try:
        run_main_loop(state, skin_scraper)
    finally:
        # Perform cleanup
        perform_cleanup(state, thread_manager, tray_manager, injection_manager)


def _remove_ltk_mods() -> int:
    """Remove from LTK Manager's library the mods Rose added there
    (ltk_library.remove_rose_mods): Rose's uninstaller runs Rose with
    --remove-ltk-mods when the user does not keep Rose's data. It checked
    that Rose is closed and waits for this, hidden: no single-instance check,
    no launcher, no dialog, and a watchdog ends it should LTK Manager hang."""
    import os
    import threading

    from config import UNINSTALL_CLEANUP_DEADLINE_S
    from injection.overlay.ltf_session import LtfHost
    from injection.overlay.ltk_library import remove_rose_mods
    from utils.core.logging import setup_logging
    from utils.core.paths import get_injection_dir, get_tools_dir

    setup_logging('customer')
    watchdog = threading.Timer(UNINSTALL_CLEANUP_DEADLINE_S, os._exit, args=(1,))
    watchdog.daemon = True
    watchdog.start()
    try:
        return remove_rose_mods(LtfHost(get_tools_dir(), get_injection_dir()))
    except Exception as e:
        log.error(f"[MODS] Could not remove Rose's mods from LTK Manager's library: {e}", exc_info=True)
        return 1


def main() -> None:
    """Program entry point that prepares and launches Rose."""
    args = setup_arguments()
    if args.uninstaller_removes_ltk_mods:
        sys.exit(_remove_ltk_mods())
    # Update before checking the DLL: a Rose that refuses to start still
    # receives the version that fixes its check
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

    if not _check_dll_present():
        sys.exit(1)

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
