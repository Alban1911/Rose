#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for the modularized LeagueUnlocked
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
from typing import TYPE_CHECKING, Optional

# Local imports - constants first (needed for Windows setup)
from config import WINDOWS_DPI_AWARENESS_SYSTEM, CONSOLE_BUFFER_CLEAR_INTERVAL_S

if TYPE_CHECKING:
    from lcu.client import LCU
    from lcu.skin_scraper import LCUSkinScraper
    from state.shared_state import SharedState
    from state.app_status import AppStatus
    from threads.phase_thread import PhaseThread
    from threads.champ_thread import ChampThread
    from uia import UISkinThread
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
from uia import UISkinThread
from threads.websocket_thread import WSEventThread
from threads.lcu_monitor_thread import LCUMonitorThread

# Local imports - utilities
from utils.logging import setup_logging, get_logger, log_section, log_success, log_status, get_log_mode
from utils.skin_downloader import download_skins_on_startup
from utils.tray_manager import TrayManager
from utils.thread_manager import ThreadManager, create_daemon_thread
from utils.license_client import LicenseClient

# Local imports - UI and injection
from ui.user_interface import get_user_interface
from injection.manager import InjectionManager

# Local imports - configuration
from config import (
    DEFAULT_DD_LANG,
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
    QT_EVENT_PROCESSING_THRESHOLD_S,
    MAIN_LOOP_SLEEP,
    THREAD_JOIN_TIMEOUT_S,
    THREAD_FORCE_EXIT_TIMEOUT_S,
    MAIN_LOOP_STALL_THRESHOLD_S,
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
    # Force exit if we're stuck
    import os
    os._exit(0)

def force_quit_handler():
    """Force quit handler that can be called from anywhere"""
    if _app_state.shutting_down:
        return
    _app_state.shutting_down = True
    
    print("\nForce quit initiated...")
    os._exit(0)

# Set up signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# Set Qt environment variables BEFORE anything else
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '0'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '0'
# Tell Qt to not print DPI warnings and suppress QWindowsContext COM errors
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.window=false;qt.qpa.windows.debug=false'

# Import PyQt6 for chroma wheel
PYQT6_AVAILABLE = False
QApplication = None
QTimer = None
Qt = None

# Third-party imports - PyQt6
try:
    # Set Qt plugin path for frozen executables BEFORE import
    if getattr(sys, 'frozen', False):
        # Try multiple possible plugin paths
        possible_paths = [
            Path(sys.executable).parent / "PyQt6" / "Qt6" / "plugins",
            Path(sys.executable).parent / "PyQt6" / "Qt" / "plugins",
            Path(sys.executable).parent / "qt6" / "plugins",
        ]
        for path in possible_paths:
            if path.exists():
                os.environ['QT_PLUGIN_PATH'] = str(path)
                break
    
    # Suppress Qt DPI warnings during import
    with contextlib.redirect_stderr(io.StringIO()):
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QTimer, Qt
    
    PYQT6_AVAILABLE = True
except ImportError as e:
    # PyQt6 not installed
    PYQT6_AVAILABLE = False
except Exception as e:
    # Qt platform plugin or other error
    PYQT6_AVAILABLE = False
    import traceback
    # Don't log yet, logger not initialized
    print(f"Warning: PyQt6 import failed: {e}")
    print(f"Traceback: {traceback.format_exc()}")

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
        
        lock_file_path = state_dir / "leagueunlocked.lock"
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
                    "Another instance of LeagueUnlocked is already running!\n\nPlease close the existing instance before starting a new one.",
                    "LeagueUnlocked - Instance Already Running",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except (OSError, AttributeError) as e:
                # Fallback to logging if MessageBox fails
                log.error(f"Failed to show message box: {e}")
                log.error("Another instance of LeagueUnlocked is already running!")
                log.error("Please close the existing instance before starting a new one.")
        else:
            log.error("Another instance of LeagueUnlocked is already running!")
            log.error("Please close the existing instance before starting a new one.")
        sys.exit(1)


def show_license_activation_dialog(error_message: str) -> Optional[str]:
    """Show the PyQt6 license dialog to enter license key"""
    try:
        # Import the license dialog
        from utils.license_dialog import show_enhanced_license_dialog
        
        # Show the PyQt6-based dialog
        license_key = show_enhanced_license_dialog(error_message)
        return license_key
        
    except ImportError as e:
        # PyQt6 not available - show error and exit
        print(f"ERROR: PyQt6 not available: {e}")
        if sys.platform == "win32":
            try:
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"PyQt6 is required for the license dialog but is not available.\n\nError: {str(e)}\n\nPlease install PyQt6 or contact support.",
                    "LeagueUnlocked - Missing Dependency",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except (OSError, AttributeError):
                pass
        return None
    except Exception as e:
        # Log the error with full traceback for debugging
        import traceback
        error_details = traceback.format_exc()
        print(f"ERROR: Failed to show license dialog: {e}")
        print(f"Traceback:\n{error_details}")
        
        # Show error message
        if sys.platform == "win32":
            try:
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"Failed to show license dialog:\n\n{str(e)}\n\nPlease contact support.",
                    "LeagueUnlocked - Dialog Error",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except (OSError, AttributeError):
                pass
        return None




def check_license():
    """Check and validate license on startup"""
    print("[LICENSE] Starting license check...")
    
    # Load public key used for RSA verification and log encryption
    from utils.public_key import PUBLIC_KEY
    
    print("[LICENSE] Initializing license client...")
    # Initialize license client
    license_client = LicenseClient(
        server_url="https://api.leagueunlocked.net",
        license_file="license.dat",
        public_key_pem=PUBLIC_KEY  # Public key for verifying server signatures
    )
    print("[LICENSE] License client initialized")
    
    # Check if license is valid (offline check first for speed)
    print("[LICENSE] Checking license validity (offline)...")
    valid, message = license_client.is_license_valid(check_online=False)
    print(f"[LICENSE] Validation result: valid={valid}, message={message}")
    
    if not valid:
        # License is invalid or missing - prompt for activation
        print(f"[LICENSE] License validation failed: {message}")
        log.warning(f"License validation failed: {message}")
        
        # Show dialog to enter license key
        max_attempts = 3
        print(f"[LICENSE] Showing activation dialog (max {max_attempts} attempts)...")
        for attempt in range(max_attempts):
            print(f"[LICENSE] Attempt {attempt + 1}/{max_attempts}")
            license_key = show_license_activation_dialog(message)
            print(f"[LICENSE] Dialog returned: {bool(license_key)}")
            
            if not license_key:
                # User cancelled or didn't enter anything
                if sys.platform == "win32":
                    try:
                        ctypes.windll.user32.MessageBoxW(
                            0,
                            "No license key entered.\n\nThe application will now exit.",
                            "LeagueUnlocked - License Required",
                            0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                        )
                    except (OSError, AttributeError):
                        print("No license key entered. Exiting.")
                sys.exit(1)
            
            # Try to activate the license
            log.info(f"Attempting to activate license (attempt {attempt + 1}/{max_attempts})...")
            success, activation_message = license_client.activate_license(license_key)
            
            if success:
                log_success(log, f"License activated successfully: {activation_message}", "✅")
                
                # Show success message
                if sys.platform == "win32":
                    try:
                        import tkinter as tk
                        from tkinter import messagebox
                        root = tk.Tk()
                        root.withdraw()
                        root.attributes('-topmost', True)
                        messagebox.showinfo(
                            "License Activated",
                            f"Success!\n\n{activation_message}\n\nLeagueUnlocked will now start."
                        )
                        root.destroy()
                    except (ImportError, AttributeError, RuntimeError) as e:
                        # Fallback to console output if tkinter fails
                        print(f"License activated: {activation_message}")
                        log.debug(f"Tkinter dialog failed: {e}")
                
                # Update valid status and message
                valid = True
                break
            else:
                log.warning(f"License activation failed: {activation_message}")
                message = activation_message  # Update message for next attempt
                
                if attempt < max_attempts - 1:
                    # Not the last attempt - show error and prompt again
                    continue
                else:
                    # Last attempt failed - show final error and exit
                    if sys.platform == "win32":
                        try:
                            ctypes.windll.user32.MessageBoxW(
                                0,
                                f"License activation failed after {max_attempts} attempts:\n\n{activation_message}\n\nPlease contact support for assistance.",
                                "LeagueUnlocked - Activation Failed",
                                0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                            )
                        except (OSError, AttributeError):
                            print(f"License activation failed: {activation_message}")
                    sys.exit(1)
    
    # License is valid - log the info
    info = license_client.get_license_info()
    if info:
        # License validation - mode-aware logging
        if get_log_mode() == 'customer':
            log.info(f"✅ License Valid ({info['days_remaining']} days remaining)")
        else:
            log_section(log, "License Validated", "✅", {
                "Status": "Active",
                "Days Remaining": str(info['days_remaining']),
                "Expires": info['expires_at']
            })
    
    return True




def setup_arguments() -> argparse.Namespace:
    """Parse and return command line arguments"""
    ap = argparse.ArgumentParser(
        description="LeagueUnlocked - Windows UI API skin detection"
    )
    
    # Database arguments
    ap.add_argument("--dd-lang", type=str, default=DEFAULT_DD_LANG, 
                   help="DDragon language(s): 'fr_FR' | 'fr_FR,en_US,es_ES' | 'all'")
    
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
    
    # Development arguments
    ap.add_argument("--dev", action="store_true", default=False,
                   help="Development mode - disable log sanitization (shows full paths, ports, PIDs)")
    
    return ap.parse_args()


def setup_logging_and_cleanup(args: argparse.Namespace) -> None:
    """Setup logging and clean up old logs and debug folders"""
    # Clean up old log files on startup
    from utils.logging import cleanup_logs
    cleanup_logs()
    
    # Check if running as frozen executable (PyInstaller)
    is_frozen = getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')
    
    # Force production mode in frozen builds (disable dev/verbose/debug)
    if is_frozen:
        original_dev = args.dev
        original_verbose = args.verbose
        original_debug = args.debug
        
        args.dev = False
        args.verbose = False
        args.debug = False
        
        # Log if flags were overridden
        if original_dev or original_verbose or original_debug:
            print("[WARNING] Development flags disabled in frozen build (--dev, --verbose, --debug ignored)")
    
    # Determine log mode based on flags
    if args.debug:
        log_mode = 'debug'
    elif args.verbose:
        log_mode = 'verbose'
    else:
        log_mode = 'customer'
    
    # Determine production mode (--dev disables sanitization)
    production_mode = not args.dev  # False if --dev, True otherwise
    
    # Setup logging first
    setup_logging(log_mode, production_mode)
    
    # Log dev mode status after logging is set up
    if args.dev:
        log.info("🛠️  Development mode enabled - log sanitization disabled")
    
    # Suppress PIL/Pillow debug messages for optional image plugins
    logging.getLogger("PIL").setLevel(logging.INFO)
    
    # Show startup banner (mode-aware via log_section)
    if log_mode == 'customer':
        # Simple startup for customer mode
        pass  # Already shown in setup_logging()
    else:
        # Detailed startup for verbose/debug
        log_section(log, "LeagueUnlocked Starting", "🚀", {
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


def initialize_qt_and_chroma(skin_scraper, state: SharedState, db=None, app_status: Optional[AppStatus] = None, lcu=None):
    """Initialize PyQt6 and chroma selector"""
    qt_app = None
    chroma_selector = None
    
    if not PYQT6_AVAILABLE:
        log.info("PyQt6 not available - chroma selector will be disabled")
        return qt_app, chroma_selector
    
    try:
        log.debug("Checking for existing QApplication instance...")
        # Try to get existing QApplication or create new one
        existing_app = QApplication.instance()
        
        if existing_app is None:
            log.debug("Creating new QApplication instance...")
            # Set Qt platform plugin path explicitly for frozen executables
            if getattr(sys, 'frozen', False):
                import os
                qt_plugin_path = Path(sys.executable).parent / "PyQt6" / "Qt6" / "plugins"
                if qt_plugin_path.exists():
                    os.environ['QT_PLUGIN_PATH'] = str(qt_plugin_path)
                    log.debug(f"Set QT_PLUGIN_PATH: {qt_plugin_path}")
            
            try:
                qt_app = QApplication([sys.argv[0]])
                log_success(log, "PyQt6 QApplication created for chroma wheel", "🎨")
            except Exception as qapp_error:
                log.error(f"Failed to create QApplication: {qapp_error}")
                log.error("This is usually due to missing Qt platform plugins")
                log.warning("Chroma selector will be disabled")
                return None, None
        else:
            qt_app = existing_app
            log_success(log, "Using existing QApplication instance for chroma panel", "🎨")
        
        # UI will be initialized when entering ChampSelect phase
        chroma_selector = None
            
    except Exception as e:
        log.warning(f"Failed to initialize PyQt6: {e}")
        log.warning("Chroma panel will be disabled, but app will continue normally")
        import traceback
        log.debug(f"PyQt6 init traceback: {traceback.format_exc()}")
        qt_app = None
        chroma_selector = None
    
    return qt_app, chroma_selector




def main():
    """Main entry point - orchestrates application startup and main loop"""
    # Check for admin rights FIRST (required for injection to work)
    from utils.admin_utils import ensure_admin_rights
    ensure_admin_rights()
    
    # Check for single instance before doing anything else
    check_single_instance()
    
    # Parse arguments
    args = setup_arguments()
    
    # Setup logging and cleanup
    setup_logging_and_cleanup(args)
    
    # Check license validity before continuing
    check_license()
    
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
                    f"LeagueUnlocked failed to initialize:\n\n{str(e)}\n\nCheck the log file for details:\n{log.handlers[0].baseFilename if log.handlers else 'N/A'}",
                    "LeagueUnlocked - Initialization Error",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except Exception:
                pass
        sys.exit(1)
    
    # Database initialization no longer needed - LCU provides all skin and champion data
    db = None

    # Initialize PyQt6 (UI will be initialized when entering ChampSelect)
    try:
        log.info("Initializing PyQt6...")
        qt_app, chroma_selector = initialize_qt_and_chroma(skin_scraper, state, db, app_status, lcu)
        log.info("✓ PyQt6 initialized (UI will be created when entering ChampSelect)")
    except Exception as e:
        log.error("=" * 80)
        log.error("ERROR DURING PYQT6 INITIALIZATION")
        log.error("=" * 80)
        log.error(f"Failed to initialize PyQt6: {e}")
        log.error(f"Error type: {type(e).__name__}")
        import traceback
        log.error(f"Traceback:\n{traceback.format_exc()}")
        log.error("=" * 80)
        log.warning("Continuing without PyQt6...")
        qt_app = None
        chroma_selector = None
    
    
    # Initialize injection manager with database (lazy initialization)
    try:
        log.info("Initializing injection manager...")
        injection_manager = InjectionManager(shared_state=state)
        log.info("✓ Injection manager initialized")
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
                    f"LeagueUnlocked failed to initialize injection system:\n\n{str(e)}\n\nCheck the log file for details:\n{log.handlers[0].baseFilename if log.handlers else 'N/A'}",
                    "LeagueUnlocked - Injection Error",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except Exception:
                pass
        sys.exit(1)
    
    # Download skins if enabled (run in background to avoid blocking startup)
    if args.download_skins:
        separator = "=" * 80
        log.info(separator)
        log.info("📥 STARTING SKIN DOWNLOAD")
        log.info("   📋 Mode: Background (non-blocking)")
        log.info(separator)
        
        def download_skins_background():
            try:
                # Download skins first
                success = download_skins_on_startup(
                    force_update=args.force_update_skins,
                    max_champions=args.max_champions,
                    tray_manager=tray_manager,
                    injection_manager=injection_manager
                )
                
                # Preview images are now included in the merged database
                # Mark previews as downloaded since they're included with skins
                if not app_status.check_previews_downloaded():
                    app_status.mark_previews_downloaded()
                
                separator = "=" * 80
                if success:
                    log.info(separator)
                    log.info("✅ SKIN DOWNLOAD COMPLETED")
                    log.info("   📋 Status: Success")
                    log.info(separator)
                    # Only mark if not already detected
                    if not app_status.check_skins_downloaded():
                        app_status.mark_skins_downloaded()
                    # Mark download process as complete
                    app_status.mark_download_process_complete()
                else:
                    log.info(separator)
                    log.info("⚠️ SKIN DOWNLOAD COMPLETED WITH ISSUES")
                    log.info("   📋 Status: Partial Success")
                    log.info(separator)
                    # Still mark as downloaded even with issues (files may still exist)
                    if not app_status.check_skins_downloaded():
                        app_status.mark_skins_downloaded()
                    # Mark download process as complete
                    app_status.mark_download_process_complete()
            except Exception as e:
                separator = "=" * 80
                log.info(separator)
                log.error(f"❌ SKIN DOWNLOAD FAILED")
                log.error(f"   📋 Error: {e}")
                log.info(separator)
                # Check if skins exist anyway
                if not app_status.check_skins_downloaded():
                    app_status.mark_skins_downloaded()
        
        # Start skin download in a separate thread to avoid blocking
        skin_download_thread = create_daemon_thread(target=download_skins_background, 
                                                    name="SkinDownload")
        skin_download_thread.start()
    else:
        log.info("Automatic skin download disabled")
        # Check if skins already exist
        if not app_status.check_skins_downloaded():
            app_status.mark_skins_downloaded()
        # Mark download process as complete since it's disabled
        app_status.mark_download_process_complete()
        # Initialize injection system immediately when download is disabled
        injection_manager.initialize_when_ready()
    
    # Multi-language support is no longer needed - we use LCU scraper + English DB
    # Skin names are matched using: Windows UI API (client lang) → LCU scraper → skinId → English DB
    
    
    # Configure skin writing
    state.skin_write_ms = int(getattr(args, 'skin_threshold_ms', 2000) or 2000)
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
                log.debug(f"[Main] Failed to reset UISkinThread after disconnection: {e}")

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
    
    t_ui = UISkinThread(state, lcu, skin_scraper=skin_scraper, injection_manager=injection_manager)
    state.ui_skin_thread = t_ui  # Store reference for access during champion exchange
    thread_manager.register("UIA Detection", t_ui)
    
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

    log.info("System ready - UIA Detection active only in Champion Select")

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
            
            
            # Process Qt events if available (process ALL pending events)
            if qt_app:
                try:
                    # Check for skin changes and notify UI (modular architecture)
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
                        if not hasattr(main, '_swiftplay_ui_hidden'):
                            try:
                                from ui.user_interface import get_user_interface
                                user_interface = get_user_interface()
                                if user_interface.is_ui_initialized():
                                    if user_interface.chroma_ui:
                                        user_interface.chroma_ui.hide()
                                    if user_interface.unowned_frame:
                                        user_interface.unowned_frame.hide()
                                    main._swiftplay_ui_hidden = True
                                    log.debug("[MAIN] Hiding UI - no skin detected in Swiftplay mode")
                            except Exception as e:
                                log.debug(f"[MAIN] Error hiding UI: {e}")
                    
                    if current_skin_id:
                        # Check if we need to reset skin notification debouncing
                        if state.reset_skin_notification:
                            if hasattr(main, '_last_notified_skin_id'):
                                delattr(main, '_last_notified_skin_id')
                            state.reset_skin_notification = False
                            log.debug("[MAIN] Reset skin notification debouncing for new ChampSelect")
                        
                        # Check if this is a new skin (debouncing at main loop level)
                        last_notified = getattr(main, '_last_notified_skin_id', None)
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
                                    main._last_notified_skin_id = current_skin_id
                                    # Reset hide flag since we're showing a skin
                                    if hasattr(main, '_swiftplay_ui_hidden'):
                                        delattr(main, '_swiftplay_ui_hidden')
                                        log.debug("[MAIN] Reset UI hide flag - skin detected")
                                else:
                                    # Only log once per skin to avoid spam
                                    if not hasattr(main, '_ui_not_initialized_logged') or main._ui_not_initialized_logged != current_skin_id:
                                        log.debug(f"[MAIN] UI not initialized yet - skipping skin notification for {current_skin_id}")
                                        main._ui_not_initialized_logged = current_skin_id
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
                                
                                # Hide UnownedFrame by setting opacity to 0
                                if user_interface.unowned_frame and hasattr(user_interface.unowned_frame, 'opacity_effect'):
                                    user_interface.unowned_frame.opacity_effect.setOpacity(0.0)
                                    log.debug("[exchange] UnownedFrame hidden")
                                
                                # Hide Chroma Opening Button by hiding it
                                if (user_interface.chroma_ui and 
                                    user_interface.chroma_ui.chroma_selector and 
                                    user_interface.chroma_ui.chroma_selector.panel and
                                    user_interface.chroma_ui.chroma_selector.panel.reopen_button):
                                    button = user_interface.chroma_ui.chroma_selector.panel.reopen_button
                                    button.hide()
                                    log.debug("[exchange] Chroma Opening Button hidden")
                                
                                # Hide RandomFlag (random mode is disabled on champion swap)
                                if user_interface.random_flag:
                                    try:
                                        user_interface.random_flag.hide_flag()
                                        log.debug("[exchange] RandomFlag hidden")
                                    except Exception as e:
                                        log.debug(f"[exchange] Failed to hide RandomFlag: {e}")

                                # Ensure ClickBlocker is visible during exchange (create if missing)
                                try:
                                    user_interface._show_click_blocker_on_main_thread()
                                except Exception:
                                    pass
                        except Exception as e:
                            log.error(f"[MAIN] Failed to hide UI during champion exchange: {e}")
                    
                    if user_interface.is_ui_initialized() and user_interface.chroma_ui and user_interface.chroma_ui.chroma_selector and user_interface.chroma_ui.chroma_selector.panel:
                        chroma_start = time.time()
                        user_interface.chroma_ui.chroma_selector.panel.process_pending()
                        # Update positions to follow League window
                        user_interface.chroma_ui.chroma_selector.panel.update_positions()
                        # Refresh z-order for all UI components
                        user_interface.refresh_z_order()
                        chroma_elapsed = time.time() - chroma_start
                        if chroma_elapsed > CHROMA_PANEL_PROCESSING_THRESHOLD_S:
                            log.warning(f"[WATCHDOG] Chroma panel processing took {chroma_elapsed:.2f}s")
                    
                    # Check for resolution changes and update UI components
                    if user_interface.is_ui_initialized():
                        user_interface.check_resolution_and_update()
                    
                    # Process all Qt events
                    qt_start = time.time()
                    qt_app.processEvents()
                    qt_elapsed = time.time() - qt_start
                    if qt_elapsed > QT_EVENT_PROCESSING_THRESHOLD_S:
                        log.warning(f"[WATCHDOG] Qt event processing took {qt_elapsed:.2f}s")
                except Exception as e:
                    log.debug(f"Qt event processing error: {e}")
            
            time.sleep(MAIN_LOOP_SLEEP)
    except KeyboardInterrupt:
        log_section(log, "Shutting Down (Keyboard Interrupt)", "⚠️")
        log.debug(f"[DEBUG] Keyboard interrupt - setting state.stop = True")
        state.stop = True
    finally:
        log.debug(f"[DEBUG] Finally block - setting state.stop = True")
        state.stop = True
        
        log_section(log, "Cleanup", "🧹")
        
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
        
        # Clean up z-order manager
        try:
            from ui.z_order_manager import cleanup_z_order_manager
            cleanup_z_order_manager()
            log.debug("[MAIN] Z-order manager cleaned up")
        except Exception as e:
            log.debug(f"[MAIN] Error cleaning up z-order manager: {e}")
        
        # Clean up console if we allocated one
        if sys.platform == "win32":
            try:
                console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if console_hwnd:
                    # Free the console
                    ctypes.windll.kernel32.FreeConsole()
            except (OSError, AttributeError) as e:
                log.debug(f"Console cleanup error (non-critical): {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Top-level exception handler to catch any unhandled crashes
        import traceback
        import sys
        
        error_msg = f"""
================================================================================
FATAL ERROR - LeagueUnlocked Crashed
================================================================================
Error: {e}
Type: {type(e).__name__}

Traceback:
{traceback.format_exc()}
================================================================================

This error has been logged. Please report this issue with the log file.
Log location: Check %LOCALAPPDATA%\\LeagueUnlocked\\logs\\
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
                    f"LeagueUnlocked crashed with an unhandled error:\n\n{str(e)}\n\nError type: {type(e).__name__}\n\nPlease check the log file in:\n%LOCALAPPDATA%\\LeagueUnlocked\\logs\\",
                    "LeagueUnlocked - Fatal Error",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except Exception:
                pass
        
        sys.exit(1)
