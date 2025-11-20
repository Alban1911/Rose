#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for the modularized Rose
"""

# Standard library imports
import argparse
import atexit
import contextlib
import ctypes
import io
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple


MIN_PYTHON = (3, 11)
if sys.version_info < MIN_PYTHON:
    raise RuntimeError(
        f"Rose requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer. "
        "Please upgrade your interpreter and rebuild the application."
    )

# Local imports - constants first (needed for Windows setup)
from config import WINDOWS_DPI_AWARENESS_SYSTEM, CONSOLE_BUFFER_CLEAR_INTERVAL_S, APP_VERSION

if TYPE_CHECKING:
    from lcu.client import LCU
    from lcu.skin_scraper import LCUSkinScraper
    from state.shared_state import SharedState
    from state.app_status import AppStatus
    from threads.phase_thread import PhaseThread
    from threads.champ_thread import ChampThread
    from pengu.skin_monitor import PenguSkinMonitorThread
    from threads.websocket_thread import WSEventThread
    from threads.lcu_monitor_thread import LCUMonitorThread
    from utils.tray_manager import TrayManager
    from ui.user_interface import UserInterface
    from injection.manager import InjectionManager


# Fix for windowed mode - allocate console to prevent blocking operations
if sys.platform == "win32":
    try:
        # Set DPI awareness to SYSTEM_AWARE before any GUI operations
        # This prevents Qt from trying to change it later (which causes "Access denied")
        # PROCESS_SYSTEM_DPI_AWARE
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(WINDOWS_DPI_AWARENESS_SYSTEM)
        except (OSError, AttributeError) as e:
            try:
                # Fallback for older Windows versions
                ctypes.windll.user32.SetProcessDPIAware()
            except (OSError, AttributeError) as e2:
                # If both fail, continue anyway - not critical
                pass
        
        # Check if we're in windowed mode (no console attached)
        console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not console_hwnd:
            # Allocate a console for the process to prevent blocking operations
            ctypes.windll.kernel32.AllocConsole()
            # Hide the console window immediately
            console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if console_hwnd:
                ctypes.windll.user32.ShowWindow(console_hwnd, 0)  # SW_HIDE = 0
        
        # Increase console buffer size to prevent blocking (Windows-specific fix)
        # This prevents the console output buffer from filling up and causing writes to block
        try:
            # Get stdout handle
            STD_OUTPUT_HANDLE = -11
            STD_ERROR_HANDLE = -12
            stdout_handle = ctypes.windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            stderr_handle = ctypes.windll.kernel32.GetStdHandle(STD_ERROR_HANDLE)
            
            # Define COORD structure for buffer size
            class COORD(ctypes.Structure):
                _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]
            
            # Set large screen buffer (10000 lines x 200 columns = 2MB buffer)
            # This gives plenty of room for logs without blocking
            new_size = COORD(200, 10000)
            
            # Set buffer size for both stdout and stderr
            ctypes.windll.kernel32.SetConsoleScreenBufferSize(stdout_handle, new_size)
            ctypes.windll.kernel32.SetConsoleScreenBufferSize(stderr_handle, new_size)
        except (OSError, AttributeError):
            # Failed to increase buffer size - not critical, will rely on queue-based logging
            pass
    except (OSError, AttributeError):
        # If console allocation fails, continue with original approach
        pass

# Fix for windowed mode - redirect None streams to devnull to prevent blocking
if sys.stdin is None:
    sys.stdin = open(os.devnull, 'r', encoding='utf-8')
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')

# Start a background thread to periodically clear console buffer (prevents blocking)
if sys.platform == "win32":
    def _console_buffer_manager():
        """
        Background thread to prevent console buffer from blocking
        
        Windows hidden console buffers can fill up and cause writes to block.
        This thread periodically:
        1. Clears the input buffer to prevent buildup
        2. Flushes stdout/stderr to prevent output buffer blocking
        3. Reads from console output buffer to keep it empty
        4. Handles any pending console events
        """
        try:
            import msvcrt
            
            # Get console output handle for buffer manipulation
            try:
                STD_OUTPUT_HANDLE = -11
                stdout_handle = ctypes.windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
                has_console_handle = stdout_handle and stdout_handle != -1
            except (OSError, AttributeError):
                has_console_handle = False
            
            while True:
                time.sleep(CONSOLE_BUFFER_CLEAR_INTERVAL_S)
                
                # Clear any pending console input
                try:
                    while msvcrt.kbhit():
                        msvcrt.getch()
                except (OSError, IOError):
                    pass
                
                # Flush output streams to prevent buffer blocking
                try:
                    if sys.stdout and hasattr(sys.stdout, 'flush'):
                        sys.stdout.flush()
                except (OSError, ValueError, IOError):
                    pass  # Stream is closed or invalid
                
                try:
                    if sys.stderr and hasattr(sys.stderr, 'flush'):
                        sys.stderr.flush()
                except (OSError, ValueError, IOError):
                    pass  # Stream is closed or invalid
                
                # Try to read console buffer info to keep it from filling
                # This is a Windows API call that can help prevent buffer overflow
                if has_console_handle:
                    try:
                        # Define CONSOLE_SCREEN_BUFFER_INFO structure
                        class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
                            _fields_ = [
                                ("dwSize", ctypes.c_uint),
                                ("dwCursorPosition", ctypes.c_uint),
                                ("wAttributes", ctypes.c_ushort),
                                ("srWindow", ctypes.c_uint * 4),
                                ("dwMaximumWindowSize", ctypes.c_uint),
                            ]
                        
                        csbi = CONSOLE_SCREEN_BUFFER_INFO()
                        # Just reading the buffer info can help prevent some blocking scenarios
                        ctypes.windll.kernel32.GetConsoleScreenBufferInfo(stdout_handle, ctypes.byref(csbi))
                    except (OSError, AttributeError):
                        pass  # API call failed, not critical
                    
        except (ImportError, OSError):
            pass  # Thread will exit silently if it fails
    
    _console_thread = threading.Thread(target=_console_buffer_manager, daemon=True, name="ConsoleBufferManager")
    _console_thread.start()
# Local imports - core modules
from lcu.client import LCU
from lcu.skin_scraper import LCUSkinScraper
from state.shared_state import SharedState
from state.app_status import AppStatus
from threads.phase_thread import PhaseThread
from threads.champ_thread import ChampThread
from pengu import PenguSkinMonitorThread
from threads.websocket_thread import WSEventThread
from threads.lcu_monitor_thread import LCUMonitorThread

# Local imports - utilities
from utils.logging import setup_logging, get_logger, log_section, log_success, log_status, get_log_mode
from utils.tray_manager import TrayManager
from utils.thread_manager import ThreadManager, create_daemon_thread
from utils import pengu_loader

# Local imports - UI and injection
from ui.user_interface import get_user_interface
from injection.manager import InjectionManager

# Local imports - configuration
from config import (
    APP_VERSION,
    DEFAULT_VERBOSE,
    PHASE_HZ_DEFAULT,
    WS_PING_INTERVAL_DEFAULT,
    TIMER_HZ_DEFAULT,
    FALLBACK_LOADOUT_MS_DEFAULT,
    SKIN_THRESHOLD_MS_DEFAULT,
    DEFAULT_DOWNLOAD_SKINS,
    DEFAULT_FORCE_UPDATE_SKINS,
    TRAY_INIT_SLEEP_S,
    MAIN_LOOP_FORCE_QUIT_TIMEOUT_S,
    PHASE_POLL_INTERVAL_DEFAULT,
    WS_PING_TIMEOUT_DEFAULT,
    CHROMA_PANEL_PROCESSING_THRESHOLD_S,
    MAIN_LOOP_SLEEP,
    THREAD_JOIN_TIMEOUT_S,
    THREAD_FORCE_EXIT_TIMEOUT_S,
    MAIN_LOOP_STALL_THRESHOLD_S,
    set_config_option,
)

class AppState:
    """Application state to replace global variables"""
    def __init__(self):
        self.shutting_down = False
        self.lock_file = None
        self.lock_file_path = None

# Create app state instance
_app_state = AppState()

def signal_handler(signum, frame):
    """Handle system signals for graceful shutdown"""
    if _app_state.shutting_down:
        return  # Prevent multiple shutdown attempts
    _app_state.shutting_down = True
    
    print(f"\nReceived signal {signum}, initiating graceful shutdown...")
    try:
        pengu_loader.deactivate_on_exit()
    except Exception:
        pass
    # Force exit if we're stuck
    os._exit(0)

def force_quit_handler():
    """Force quit handler that can be called from anywhere"""
    if _app_state.shutting_down:
        return
    _app_state.shutting_down = True
    
    print("\nForce quit initiated...")
    try:
        pengu_loader.deactivate_on_exit()
    except Exception:
        pass
    os._exit(0)

# Set up signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# PyQt6 removed - chroma UI is now handled by JavaScript plugins

log = get_logger()


class LockFile:
    """Context manager for application lock file"""
    
    def __init__(self, lock_path: Path):
        self.path = lock_path
        self.file_handle = None
        self._acquired = False
        
    def __enter__(self):
        """Acquire lock file"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Try to create lock file exclusively
            self.file_handle = open(self.path, 'x')
            self.file_handle.write(f"{os.getpid()}\n")
            self.file_handle.write(f"{time.time()}\n")
            self.file_handle.flush()
            self._acquired = True
            _app_state.lock_file = self.file_handle
            _app_state.lock_file_path = self.path
            return self
        except FileExistsError:
            # Check if stale lock
            if self._is_stale_lock():
                self.path.unlink()
                return self.__enter__()  # Retry
            raise RuntimeError("Another instance is already running")
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release lock file"""
        try:
            if self.file_handle:
                self.file_handle.close()
            if self.path.exists():
                self.path.unlink()
        except (IOError, OSError, PermissionError) as e:
            log.debug(f"Lock file cleanup error (non-critical): {e}")
        return False
    
    def _is_stale_lock(self) -> bool:
        """Check if lock file is from a dead process"""
        try:
            with open(self.path, 'r') as f:
                lines = f.readlines()
                if len(lines) >= 1:
                    old_pid = int(lines[0].strip())
                    # Check if process is still running
                    try:
                        import psutil
                        return not psutil.pid_exists(old_pid)
                    except ImportError:
                        # Fallback for Windows
                        try:
                            ctypes.windll.kernel32.OpenProcess(0x1000, False, old_pid)
                            return False  # Process exists
                        except OSError:
                            return True  # Process doesn't exist
        except (IOError, ValueError):
            return True  # Assume stale if can't read
        return False


def create_lock_file():
    """Create a lock file to prevent multiple instances"""
    try:
        # Create a lock file in the state directory
        from utils.paths import get_state_dir
        state_dir = get_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        
        lock_file_path = state_dir / "rose.lock"
        _app_state.lock_file_path = lock_file_path
        
        # Windows-only approach using file creation
        try:
            # Try to create the lock file exclusively
            _app_state.lock_file = open(lock_file_path, 'x')
            _app_state.lock_file.write(f"{os.getpid()}\n")
            _app_state.lock_file.write(f"{time.time()}\n")
            _app_state.lock_file.flush()
            
            # Register cleanup function
            atexit.register(cleanup_lock_file)
            
            return True
        except FileExistsError:
            # Lock file exists, check if process is still running
            try:
                with open(lock_file_path, 'r') as f:
                    lines = f.readlines()
                    if len(lines) >= 1:
                        old_pid = int(lines[0].strip())
                        # Check if process is still running (Windows)
                        try:
                            import psutil
                            if psutil.pid_exists(old_pid):
                                return False  # Another instance is running
                        except ImportError:
                            # Fallback: try to check if process exists
                            try:
                                ctypes.windll.kernel32.OpenProcess(0x1000, False, old_pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                                return False  # Process exists
                            except OSError:
                                # Process doesn't exist, we can proceed
                                log.debug(f"Old process {old_pid} no longer exists")
                    
                    # Old lock file is stale, remove it
                    os.remove(lock_file_path)
                    
                    # Try again
                    _app_state.lock_file = open(lock_file_path, 'x')
                    _app_state.lock_file.write(f"{os.getpid()}\n")
                    _app_state.lock_file.write(f"{time.time()}\n")
                    _app_state.lock_file.flush()
                    atexit.register(cleanup_lock_file)
                    return True
                    
            except (IOError, ValueError) as e:
                # If we can't read the lock file, assume it's stale
                log.debug(f"Lock file read error: {e}, assuming stale")
                try:
                    os.remove(lock_file_path)
                    _app_state.lock_file = open(lock_file_path, 'x')
                    _app_state.lock_file.write(f"{os.getpid()}\n")
                    _app_state.lock_file.write(f"{time.time()}\n")
                    _app_state.lock_file.flush()
                    atexit.register(cleanup_lock_file)
                    return True
                except (IOError, OSError) as cleanup_error:
                    log.error(f"Failed to create lock file after cleanup: {cleanup_error}")
                    return False
                
    except (IOError, OSError, PermissionError) as e:
        log.error(f"Failed to create lock file: {e}")
        return False

def cleanup_lock_file():
    """Clean up the lock file"""
    try:
        if _app_state.lock_file:
            _app_state.lock_file.close()
            _app_state.lock_file = None
            
        # Remove the lock file
        if _app_state.lock_file_path and _app_state.lock_file_path.exists():
            _app_state.lock_file_path.unlink()
    except (IOError, OSError, PermissionError) as e:
        log.debug(f"Lock file cleanup error (non-critical): {e}")

def check_single_instance():
    """Check if another instance is already running"""
    if not create_lock_file():
        # Show error message using Windows MessageBox since console might not be visible
        if sys.platform == "win32":
            try:
                # MB_OK (0x0) + MB_ICONERROR (0x10) + MB_SETFOREGROUND (0x10000) + MB_TOPMOST (0x40000)
                # = 0x50010 - Ensures dialog appears on top and gets focus
                ctypes.windll.user32.MessageBoxW(
                    0, 
                    "Another instance of Rose is already running!\n\nPlease close the existing instance before starting a new one.",
                    "Rose - Instance Already Running",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except (OSError, AttributeError) as e:
                # Fallback to logging if MessageBox fails
                log.error(f"Failed to show message box: {e}")
                log.error("Another instance of Rose is already running!")
                log.error("Please close the existing instance before starting a new one.")
        else:
            log.error("Another instance of Rose is already running!")
            log.error("Please close the existing instance before starting a new one.")
        sys.exit(1)






def setup_arguments() -> argparse.Namespace:
    """Parse and return command line arguments"""
    ap = argparse.ArgumentParser(
        description="Rose - Windows UI API skin detection"
    )
    
    # General arguments
    ap.add_argument("--verbose", action="store_true", default=DEFAULT_VERBOSE,
                   help="Enable verbose logging (developer mode - shows all technical details)")
    ap.add_argument("--debug", action="store_true", default=False,
                   help="Enable ultra-detailed debug logging (includes function traces and variable dumps)")
    ap.add_argument("--lockfile", type=str, default=None)
    
    
    # Threading arguments
    ap.add_argument("--phase-hz", type=float, default=PHASE_HZ_DEFAULT)
    ap.add_argument("--ws-ping", type=int, default=WS_PING_INTERVAL_DEFAULT)
    
    # Timer arguments
    ap.add_argument("--timer-hz", type=int, default=TIMER_HZ_DEFAULT, 
                   help="Loadout countdown display frequency (Hz)")
    ap.add_argument("--fallback-loadout-ms", type=int, default=FALLBACK_LOADOUT_MS_DEFAULT, 
                   help="(deprecated) Old fallback ms if LCU doesn't provide timer — ignored")
    ap.add_argument("--skin-threshold-ms", type=int, default=SKIN_THRESHOLD_MS_DEFAULT, 
                   help="Write last skin at T<=threshold (ms)")
    ap.add_argument("--inject-batch", type=str, default="", 
                   help="Batch to execute right after skin write (leave empty to disable)")
    
    
    # Skin download arguments
    ap.add_argument("--download-skins", action="store_true", default=DEFAULT_DOWNLOAD_SKINS, 
                   help="Automatically download skins at startup")
    ap.add_argument("--no-download-skins", action="store_false", dest="download_skins", 
                   help="Disable automatic skin downloading")
    ap.add_argument("--force-update-skins", action="store_true", default=DEFAULT_FORCE_UPDATE_SKINS, 
                   help="Force update all skins (re-download existing ones)")
    ap.add_argument("--max-champions", type=int, default=None, 
                   help="Limit number of champions to download skins for (for testing)")
    
    # Log management arguments (none - retention managed by age in utils.logging)
    
    return ap.parse_args()


def setup_logging_and_cleanup(args: argparse.Namespace) -> None:
    """Setup logging and clean up old logs and debug folders"""
    # Clean up old log files on startup
    from utils.logging import cleanup_logs
    cleanup_logs()
    
    # Determine log mode based on flags
    if args.debug:
        log_mode = 'debug'
    elif args.verbose:
        log_mode = 'verbose'
    else:
        log_mode = 'customer'
    
    # Setup logging
    setup_logging(log_mode)
    
    # Suppress PIL/Pillow debug messages for optional image plugins
    logging.getLogger("PIL").setLevel(logging.INFO)
    
    # Show startup banner (mode-aware via log_section)
    if log_mode == 'customer':
        # Simple startup for customer mode
        pass  # Already shown in setup_logging()
    else:
        # Detailed startup for verbose/debug
        log_section(log, "Rose Starting", "🚀", {
            "Verbose Mode": "Enabled" if args.verbose else "Disabled",
            "Download Skins": "Enabled" if args.download_skins else "Disabled"
        })
    


def initialize_tray_manager(args: argparse.Namespace) -> Optional[TrayManager]:
    """Initialize the system tray manager"""
    try:
        def tray_quit_callback():
            """Callback for tray quit - will be updated with state reference later"""
            log.info("Setting stop flag from tray quit")
            # Callback will be updated later when state is initialized
        
        tray_manager = TrayManager(quit_callback=tray_quit_callback)
        tray_manager.start()
        log_success(log, "System tray icon initialized - console hidden", "📍")
        
        # Give tray icon a moment to fully initialize
        time.sleep(TRAY_INIT_SLEEP_S)
        
        # Note: Status will be managed by AppStatus class
        
        return tray_manager
    except Exception as e:
        log.warning(f"Failed to initialize system tray: {e}")
        log.info("Application will continue without system tray icon")
        return None


def run_league_unlock(injection_threshold: Optional[float] = None):
    """Run the core Rose application startup and main loop."""
    set_config_option("General", "installed_version", APP_VERSION)
    # Check for admin rights FIRST (required for injection to work)
    from utils.admin_utils import ensure_admin_rights
    ensure_admin_rights()
    
    # Check for single instance before doing anything else
    check_single_instance()
    
    # Parse arguments
    args = setup_arguments()
    
    # Setup logging and cleanup
    setup_logging_and_cleanup(args)
    pengu_loader.activate_on_start()
    
    # Initialize system tray manager immediately to hide console
    tray_manager = initialize_tray_manager(args)
    
    # Initialize app status manager
    app_status = AppStatus(tray_manager)
    log_success(log, "App status manager initialized", "📊")
    
    # Check initial status (will show locked until all components are ready)
    app_status.update_status(force=True)
    
    # Initialize core components with error handling
    try:
        log.info("Initializing LCU client...")
        lcu = LCU(args.lockfile)
        log.info("✓ LCU client initialized")

        log.info("Initializing skin scraper...")
        skin_scraper = LCUSkinScraper(lcu)
        log.info("✓ Skin scraper initialized")
        
        log.info("Initializing shared state...")
        state = SharedState()
        log.info("✓ Shared state initialized")
    except Exception as e:
        log.error("=" * 80)
        log.error("FATAL ERROR DURING INITIALIZATION")
        log.error("=" * 80)
        log.error(f"Failed to initialize core components: {e}")
        log.error(f"Error type: {type(e).__name__}")
        import traceback
        log.error(f"Traceback:\n{traceback.format_exc()}")
        log.error("=" * 80)
        
        # Show error message to user
        if sys.platform == "win32":
            try:
                # ctypes already imported at top of file
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"Rose failed to initialize:\n\n{str(e)}\n\nCheck the log file for details:\n{log.handlers[0].baseFilename if log.handlers else 'N/A'}",
                    "Rose - Initialization Error",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except Exception:
                pass
        sys.exit(1)
    
    # Database initialization no longer needed - LCU provides all skin and champion data
    db = None

    # PyQt6 removed - chroma UI is now handled by JavaScript plugins
    qt_app = None
    chroma_selector = None

    # Initialize injection manager with database (lazy initialization)
    try:
        log.info("Initializing injection manager...")
        injection_manager = InjectionManager(shared_state=state)
        if injection_threshold is not None:
            log.info(f"Launcher override: setting injection threshold to {injection_threshold:.2f}s")
            injection_manager.injection_threshold = max(0.0, injection_threshold)
        log.info("✓ Injection manager initialized")
        injection_manager.initialize_when_ready()
        
        # Ensure hashes.game.txt exists and is up to date
        try:
            from utils.hashes_downloader import ensure_hashes_file
            # Get the tools directory path
            injection_dir = injection_manager._get_injection_dir()
            tools_dir = injection_dir / "tools"
            log.info("Checking hashes.game.txt...")
            if ensure_hashes_file(tools_dir):
                log_success(log, "hashes.game.txt is ready", "✅")
            else:
                log.warning("Failed to ensure hashes.game.txt (non-critical, continuing)")
        except Exception as e:
            log.warning(f"Failed to check/update hashes.game.txt: {e} (non-critical, continuing)")
    except Exception as e:
        log.error("=" * 80)
        log.error("FATAL ERROR DURING INJECTION MANAGER INITIALIZATION")
        log.error("=" * 80)
        log.error(f"Failed to initialize injection manager: {e}")
        log.error(f"Error type: {type(e).__name__}")
        import traceback
        log.error(f"Traceback:\n{traceback.format_exc()}")
        log.error("=" * 80)
        
        # Show error message to user
        if sys.platform == "win32":
            try:
                # ctypes already imported at top of file
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"Rose failed to initialize injection system:\n\n{str(e)}\n\nCheck the log file for details:\n{log.handlers[0].baseFilename if log.handlers else 'N/A'}",
                    "Rose - Injection Error",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except Exception:
                pass
        sys.exit(1)
    
    # Launcher now handles skin downloads; mark complete will be called after all initialization
    # app_status.mark_download_process_complete()  # Moved to after "System ready"
    
    # Multi-language support is no longer needed - we use LCU scraper + English DB
    # Skin names are matched using: Windows UI API (client lang) → LCU scraper → skinId → English DB
    
    
    # Configure skin writing based on the final injection threshold (seconds → ms)
    state.skin_write_ms = max(0, int(injection_manager.injection_threshold * 1000))
    state.inject_batch = getattr(args, 'inject_batch', state.inject_batch) or state.inject_batch
    
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
                time.sleep(MAIN_LOOP_FORCE_QUIT_TIMEOUT_S)
                if not _app_state.shutting_down:
                    log.warning(f"Main loop did not exit within {MAIN_LOOP_FORCE_QUIT_TIMEOUT_S}s - forcing quit")
                    force_quit_handler()
            
            timeout_thread = create_daemon_thread(target=force_quit_timeout, 
                                                 name="ForceQuitTimeout")
            timeout_thread.start()
        
        tray_manager.quit_callback = updated_tray_quit_callback

    # Function to handle LCU disconnection
    def on_lcu_disconnected():
        """Handle LCU disconnection - reset UI detection status"""
        log.info("[Main] LCU disconnected - resetting UI state")

        # Reset shared state fields that influence UI detection
        state.phase = None
        state.hovered_champ_id = None
        state.locked_champ_id = None
        state.locked_champ_timestamp = 0.0
        state.own_champion_locked = False
        state.players_visible = 0
        state.all_locked_announced = False
        state.loadout_countdown_active = False
        state.loadout_t0 = 0.0
        state.loadout_left0_ms = 0
        state.last_remain_ms = 0
        state.last_hover_written = False
        state.selected_skin_id = None
        state.selected_chroma_id = None
        state.selected_form_path = None
        state.pending_chroma_selection = False
        state.chroma_panel_open = False
        state.reset_skin_notification = True
        state.current_game_mode = None
        state.current_map_id = None
        state.current_queue_id = None
        state.chroma_panel_skin_name = None
        state.is_swiftplay_mode = False
        state.random_mode_active = False
        state.random_skin_name = None
        state.random_skin_id = None
        state.historic_mode_active = False
        state.historic_skin_id = None
        state.historic_first_detection_done = False
        state.ui_skin_id = None
        state.ui_last_text = None
        state.last_hovered_skin_key = None
        state.last_hovered_skin_id = None
        state.last_hovered_skin_slug = None
        state.champion_exchange_triggered = False
        state.injection_completed = False

        # Clear collection state safely
        try:
            state.locks_by_cell.clear()
        except Exception:
            state.locks_by_cell = {}
        try:
            state.processed_action_ids.clear()
        except Exception:
            state.processed_action_ids = set()
        try:
            state.owned_skin_ids.clear()
        except Exception:
            state.owned_skin_ids = set()
        try:
            state.swiftplay_skin_tracking.clear()
        except Exception:
            state.swiftplay_skin_tracking = {}
        try:
            state.swiftplay_extracted_mods.clear()
        except Exception:
            state.swiftplay_extracted_mods = []

        # Reset UI detection thread cache/connection
        if getattr(state, "ui_skin_thread", None) is not None:
            try:
                state.ui_skin_thread.clear_cache()
                if hasattr(state.ui_skin_thread, "connection"):
                    state.ui_skin_thread.connection.disconnect()
                state.ui_skin_thread.detection_available = False
                state.ui_skin_thread.detection_attempts = 0
            except Exception as e:
                log.debug(f"[Main] Failed to reset skin monitor thread after disconnection: {e}")

        # Tear down any existing UI overlay so it can be recreated cleanly
        try:
            from ui import user_interface as ui_module

            ui_instance = getattr(ui_module, "_user_interface", None)
            if ui_instance is not None:
                if ui_instance.state is not state:
                    ui_instance.state = state
                if skin_scraper and ui_instance.skin_scraper is not skin_scraper:
                    ui_instance.skin_scraper = skin_scraper

                try:
                    ui_instance.reset_skin_state()
                except Exception as e:
                    log.debug(f"[Main] Failed to reset UI skin state on disconnection: {e}")

                try:
                    ui_instance.request_ui_destruction()
                except Exception as e:
                    log.debug(f"[Main] Failed to request UI destruction on disconnection: {e}")
        except Exception as e:
            log.debug(f"[Main] Unable to access UI instance during disconnection: {e}")

        # Update tray status (forces icon refresh if needed)
        if app_status:
            try:
                app_status.update_status(force=True)
            except Exception as e:
                log.debug(f"[Main] Failed to update app status after disconnection: {e}")

                
    # Initialize thread manager for organized thread lifecycle
    thread_manager = ThreadManager()
    
    # Create and register threads
    t_phase = PhaseThread(lcu, state, interval=1.0/max(PHASE_POLL_INTERVAL_DEFAULT, args.phase_hz), 
                         log_transitions=False, injection_manager=injection_manager, skin_scraper=skin_scraper, db=db)
    thread_manager.register("Phase", t_phase)
    
    t_ui = PenguSkinMonitorThread(state, lcu, skin_scraper=skin_scraper, injection_manager=injection_manager)
    state.ui_skin_thread = t_ui  # Store reference for access during champion exchange
    thread_manager.register("Pengu Skin Monitor", t_ui, stop_method=t_ui.stop)
    
    t_ws = WSEventThread(lcu, state, ping_interval=args.ws_ping, 
                        ping_timeout=WS_PING_TIMEOUT_DEFAULT, timer_hz=args.timer_hz, 
                        fallback_ms=args.fallback_loadout_ms, injection_manager=injection_manager, 
                        skin_scraper=skin_scraper, app_status=app_status)
    thread_manager.register("WebSocket", t_ws, stop_method=t_ws.stop)
    
    # Language callback to update shared state
    def on_language_detected(language: str):
        """Callback when language is detected from LCU"""
        if language:
            # Extract language code from locale (e.g., 'en_US' -> 'en')
            language_code = language.split('_')[0] if '_' in language else language
            state.current_language = language_code
            log.info(f"[Main] Language detected and set: {language_code} (from {language})")
        else:
            log.warning("[Main] Language detection returned None")
    
    t_lcu_monitor = LCUMonitorThread(lcu, state, on_language_detected, t_ws, 
                                      db=None, skin_scraper=skin_scraper, injection_manager=injection_manager,
                                      disconnect_callback=on_lcu_disconnected)
    thread_manager.register("LCU Monitor", t_lcu_monitor)
    
    # Start all threads
    thread_manager.start_all()

    log.info("System ready")
    
    # Wait for PenguSkinMonitor thread to be ready (servers started)
    if t_ui and hasattr(t_ui, 'ready_event'):
        t_ui.ready_event.wait(timeout=5.0)  # Wait up to 5 seconds for servers to start
    
    # Mark app as fully ready after all threads and servers are initialized
    app_status.mark_download_process_complete()

    last_phase = None
    last_loop_time = time.time()
    try:
        while not state.stop:
            loop_start = time.time()
            
            # Watchdog: detect if previous loop took too long
            time_since_last_loop = loop_start - last_loop_time
            if time_since_last_loop > MAIN_LOOP_STALL_THRESHOLD_S:
                log.warning(f"Main loop stall detected: {time_since_last_loop:.1f}s since last iteration")
            last_loop_time = loop_start
            
            # Check if we should stop (extra check with logging)
            if state.stop:
                log.debug("[DEBUG] Main loop detected stop flag - exiting")
                break
            
            ph = state.phase
            if ph != last_phase:
                last_phase = ph
            
            
            # Check for skin changes and notify UI (modular architecture)
            try:
                # For Swiftplay mode, use ui_skin_id and calculate champion_id from skin_id
                # For regular mode, use last_hovered_skin_id and locked_champ_id
                if state.is_swiftplay_mode and state.ui_skin_id:
                    current_skin_id = state.ui_skin_id
                    current_skin_name = state.ui_last_text or f"Skin {current_skin_id}"
                    # Calculate champion ID from skin ID for Swiftplay
                    from utils.utilities import get_champion_id_from_skin_id
                    champion_id = get_champion_id_from_skin_id(current_skin_id)
                    champion_name = None
                    # Load champion data if not already loaded
                    if skin_scraper:
                        if not skin_scraper.cache.is_loaded_for_champion(champion_id):
                            skin_scraper.scrape_champion_skins(champion_id)
                        if skin_scraper.cache.is_loaded_for_champion(champion_id):
                            champion_name = skin_scraper.cache.champion_name
                elif state.last_hovered_skin_id and state.locked_champ_id:
                    current_skin_id = state.last_hovered_skin_id
                    current_skin_name = state.last_hovered_skin_key
                    
                    # Get champion name from LCU skin scraper cache
                    champion_name = None
                    if skin_scraper and skin_scraper.cache.is_loaded_for_champion(state.locked_champ_id):
                        champion_name = skin_scraper.cache.champion_name
                else:
                    current_skin_id = None
                    champion_id = None
                    champion_name = None
                    current_skin_name = None
                
                # Check if UI should be hidden in Swiftplay mode when detection is lost
                if state.is_swiftplay_mode and state.ui_skin_id is None:
                    # Use a flag to avoid spamming hide() calls
                    if not hasattr(run_league_unlock, '_swiftplay_ui_hidden'):
                        try:
                            from ui.user_interface import get_user_interface
                            user_interface = get_user_interface()
                            if user_interface.is_ui_initialized():
                                if user_interface.chroma_ui:
                                    user_interface.chroma_ui.hide()
                                run_league_unlock._swiftplay_ui_hidden = True
                                log.debug("[MAIN] Hiding UI - no skin detected in Swiftplay mode")
                        except Exception as e:
                            log.debug(f"[MAIN] Error hiding UI: {e}")
                
                if current_skin_id:
                    # Check if we need to reset skin notification debouncing
                    if state.reset_skin_notification:
                        if hasattr(run_league_unlock, '_last_notified_skin_id'):
                            delattr(run_league_unlock, '_last_notified_skin_id')
                        state.reset_skin_notification = False
                        log.debug("[MAIN] Reset skin notification debouncing for new ChampSelect")
                    
                    # Check if this is a new skin (debouncing at main loop level)
                    last_notified = getattr(run_league_unlock, '_last_notified_skin_id', None)
                    should_notify = (last_notified is None or last_notified != current_skin_id)
                    
                    if should_notify:
                        # Notify UserInterface of the skin change
                        try:
                            # Get the user interface that was already initialized
                            from ui.user_interface import get_user_interface
                            user_interface = get_user_interface()
                            if user_interface.is_ui_initialized():
                                # Use the correct champion_id (either from Swiftplay or regular mode)
                                champ_id_for_ui = champion_id if state.is_swiftplay_mode else state.locked_champ_id
                                user_interface.show_skin(current_skin_id, current_skin_name or f"Skin {current_skin_id}", champion_name, champ_id_for_ui)
                                log.info(f"[MAIN] Notified UI of skin change: {current_skin_id} - '{current_skin_name}'")
                                # Track the last notified skin
                                run_league_unlock._last_notified_skin_id = current_skin_id
                                # Reset hide flag since we're showing a skin
                                if hasattr(run_league_unlock, '_swiftplay_ui_hidden'):
                                    delattr(run_league_unlock, '_swiftplay_ui_hidden')
                                    log.debug("[MAIN] Reset UI hide flag - skin detected")
                            else:
                                # Only log once per skin to avoid spam
                                if not hasattr(run_league_unlock, '_ui_not_initialized_logged') or run_league_unlock._ui_not_initialized_logged != current_skin_id:
                                    log.debug(f"[MAIN] UI not initialized yet - skipping skin notification for {current_skin_id}")
                                    run_league_unlock._ui_not_initialized_logged = current_skin_id
                        except Exception as e:
                            log.error(f"[MAIN] Failed to notify UI: {e}")
                
                # Process pending UI initialization and requests
                from ui.user_interface import get_user_interface
                user_interface = get_user_interface()
                
                # Process pending UI operations first (must be done in main thread)
                if user_interface.has_pending_operations():
                    log.debug("[MAIN] Processing pending UI operations")
                user_interface.process_pending_operations()
                
                # Handle champion exchange - hide UI elements (must be done in main thread)
                if state.champion_exchange_triggered:
                    try:
                        state.champion_exchange_triggered = False  # Reset flag
                        if user_interface.is_ui_initialized():
                            log.info("[MAIN] Champion exchange detected - hiding UI elements")
                            
                            # Chroma button is handled by JavaScript plugin - no need to hide Python button
                    except Exception as e:
                        log.error(f"[MAIN] Failed to hide UI during champion exchange: {e}")
                
                if user_interface.is_ui_initialized() and user_interface.chroma_ui and user_interface.chroma_ui.chroma_selector and user_interface.chroma_ui.chroma_selector.panel:
                    chroma_start = time.time()
                    user_interface.chroma_ui.chroma_selector.panel.process_pending()
                    # Update positions to follow League window
                    user_interface.chroma_ui.chroma_selector.panel.update_positions()
                    chroma_elapsed = time.time() - chroma_start
                    if chroma_elapsed > CHROMA_PANEL_PROCESSING_THRESHOLD_S:
                        log.warning(f"[WATCHDOG] Chroma panel processing took {chroma_elapsed:.2f}s")
                
                # Check for resolution changes and update UI components
                if user_interface.is_ui_initialized():
                    user_interface.check_resolution_and_update()
            except Exception as e:
                log.debug(f"UI processing error: {e}")
            
            time.sleep(MAIN_LOOP_SLEEP)
    except KeyboardInterrupt:
        log_section(log, "Shutting Down (Keyboard Interrupt)", "⚠️")
        log.debug(f"[DEBUG] Keyboard interrupt - setting state.stop = True")
        state.stop = True
    finally:
        log.debug(f"[DEBUG] Finally block - setting state.stop = True")
        state.stop = True
        
        log_section(log, "Cleanup", "🧹")
        pengu_loader.deactivate_on_exit()
        
        # Stop system tray
        if tray_manager:
            try:
                log.info("Stopping system tray...")
                tray_manager.stop()
                log_success(log, "System tray stopped", "✓")
            except Exception as e:
                log.warning(f"Error stopping system tray: {e}")
        
        # Stop all managed threads using ThreadManager
        still_alive, elapsed = thread_manager.stop_all(timeout=THREAD_JOIN_TIMEOUT_S)
        
        # Check if any threads are still alive
        if still_alive:
            log.warning(f"Some threads did not stop: {', '.join(still_alive)}")
            log.warning(f"Cleanup took {elapsed:.1f}s - forcing exit")
            
            # Clean up lock file before forced exit
            cleanup_lock_file()
            
            # Force exit after timeout
            if elapsed > THREAD_FORCE_EXIT_TIMEOUT_S:
                log.error(f"Forced exit after {elapsed:.1f}s - threads still running")
                os._exit(0)  # Force immediate exit without waiting for threads
        else:
            log_success(log, f"All threads stopped cleanly in {elapsed:.1f}s", "✓")
        
        # Clean up lock file on exit
        cleanup_lock_file()
        
        
        # Clean up console if we allocated one
        if sys.platform == "win32":
            try:
                console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if console_hwnd:
                    # Free the console
                    ctypes.windll.kernel32.FreeConsole()
            except (OSError, AttributeError) as e:
                log.debug(f"Console cleanup error (non-critical): {e}")


def main():
    """Program entry point that prepares and launches Rose."""
    if sys.platform == "win32":
        try:
            from launcher.launcher import run_launcher

            run_launcher()
        except ModuleNotFoundError as err:
            print(f"[Launcher] Unable to import launcher module: {err}")
        except Exception as err:  # noqa: BLE001
            print(f"[Launcher] Launcher encountered an error: {err}")

    run_league_unlock()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Top-level exception handler to catch any unhandled crashes
        import traceback
        import sys
        
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
                # ctypes already imported at top of file
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"Rose crashed with an unhandled error:\n\n{str(e)}\n\nError type: {type(e).__name__}\n\nPlease check the log file in:\n%LOCALAPPDATA%\\Rose\\logs\\",
                    "Rose - Fatal Error",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except Exception:
                pass
        
        sys.exit(1)
