#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for the modularized SkinCloner
"""

import argparse
import atexit
import contextlib
import ctypes
import io
import logging
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Import constants early - needed for Windows setup
from constants import WINDOWS_DPI_AWARENESS_SYSTEM


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
from ocr.backend import OCR
from database.name_db import NameDB
from lcu.client import LCU
from lcu.skin_scraper import LCUSkinScraper
from state.shared_state import SharedState
from threads.phase_thread import PhaseThread
from threads.champ_thread import ChampThread
from threads.ocr_thread import OCRSkinThread
from threads.websocket_thread import WSEventThread
from threads.lcu_monitor_thread import LCUMonitorThread
from utils.logging import setup_logging, get_logger, log_section, log_event, log_action, log_success, log_status
from injection.manager import InjectionManager
from utils.skin_downloader import download_skins_on_startup
from utils.tray_manager import TrayManager
from utils.chroma_selector import init_chroma_selector
from utils.thread_manager import ThreadManager, create_daemon_thread
from constants import *  # Import all other constants

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
# Tell Qt to not print DPI warnings
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.window=false'

# Import PyQt6 for chroma wheel
try:
    # Suppress Qt DPI warnings during import
    with contextlib.redirect_stderr(io.StringIO()):
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QTimer, Qt
    
    PYQT6_AVAILABLE = True
except ImportError:
    PYQT6_AVAILABLE = False
    log = get_logger()
    log.warning("PyQt6 not available - chroma wheel will be disabled")

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
        
        lock_file_path = state_dir / "skincloner.lock"
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
                    "Another instance of SkinCloner is already running!\n\nPlease close the existing instance before starting a new one.",
                    "SkinCloner - Instance Already Running",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except (OSError, AttributeError) as e:
                # Fallback to logging if MessageBox fails
                log.error(f"Failed to show message box: {e}")
                log.error("Another instance of SkinCloner is already running!")
                log.error("Please close the existing instance before starting a new one.")
        else:
            log.error("Another instance of SkinCloner is already running!")
            log.error("Please close the existing instance before starting a new one.")
        sys.exit(1)


def get_ocr_language(lcu_lang: str, manual_lang: str = None) -> str:
    """Get OCR language based on LCU language or manual setting"""
    if manual_lang and manual_lang != "auto":
        return manual_lang
    
    return OCR_LANG_MAP.get(lcu_lang, "eng")  # Default to English


def validate_ocr_language(lang: str) -> bool:
    """Validate that OCR language is available for EasyOCR
    
    Note: EasyOCR will automatically download models for supported languages,
    so we just check if the language code is valid.
    """
    if not lang or lang == "auto":
        return True
    
    # EasyOCR supported languages (through our mapping in backend.py)
    supported_langs = [
        "eng", "rus", "kor", "chi_sim", "chi_tra", "jpn", "ara",
        "fra", "deu", "spa", "por", "ita", "pol", "ron", "hun",
        "tur", "tha", "vie", "ell"
    ]
    
    # Check if all parts of combined languages are supported
    parts = lang.split('+')
    for part in parts:
        if part not in supported_langs:
            return False
    
    return True


def setup_arguments() -> argparse.Namespace:
    """Parse and return command line arguments"""
    ap = argparse.ArgumentParser(
        description="Combined LCU + OCR Tracer (ChampSelect) — ROI lock + burst OCR + locks/timer fixes"
    )
    
    # OCR arguments
    ap.add_argument("--tessdata", type=str, default=None, help="[DEPRECATED] Not used with EasyOCR")
    ap.add_argument("--psm", type=int, default=DEFAULT_TESSERACT_PSM, 
                   help="[DEPRECATED] Not used with EasyOCR (kept for compatibility)")
    ap.add_argument("--min-conf", type=float, default=OCR_MIN_CONFIDENCE_DEFAULT)
    ap.add_argument("--lang", type=str, default=DEFAULT_OCR_LANG, 
                   help="OCR lang (EasyOCR): 'auto', 'fra', 'kor', 'chi_sim', 'ell', etc.")
    ap.add_argument("--tesseract-exe", type=str, default=None, help="[DEPRECATED] Not used with EasyOCR")
    ap.add_argument("--debug-ocr", action="store_true", default=DEFAULT_DEBUG_OCR, 
                   help="Save OCR images to debug folder")
    ap.add_argument("--no-debug-ocr", action="store_false", dest="debug_ocr", 
                   help="Disable OCR debug image saving")
    
    # Capture arguments
    ap.add_argument("--capture", choices=["window", "screen"], default=DEFAULT_CAPTURE_MODE)
    ap.add_argument("--monitor", choices=["all", "primary"], default=DEFAULT_MONITOR)
    ap.add_argument("--window-hint", type=str, default=DEFAULT_WINDOW_HINT)
    
    # Database arguments
    ap.add_argument("--dd-lang", type=str, default=DEFAULT_DD_LANG, 
                   help="DDragon language(s): 'fr_FR' | 'fr_FR,en_US,es_ES' | 'all'")
    
    # General arguments
    ap.add_argument("--verbose", action="store_true", default=DEFAULT_VERBOSE)
    ap.add_argument("--lockfile", type=str, default=None)
    
    # OCR performance arguments
    ap.add_argument("--burst-hz", type=float, default=OCR_BURST_HZ_DEFAULT)
    ap.add_argument("--idle-hz", type=float, default=OCR_IDLE_HZ_DEFAULT, 
                   help="periodic re-emission (0=off)")
    ap.add_argument("--diff-threshold", type=float, default=OCR_DIFF_THRESHOLD_DEFAULT)
    ap.add_argument("--burst-ms", type=int, default=OCR_BURST_MS_DEFAULT)
    ap.add_argument("--min-ocr-interval", type=float, default=OCR_MIN_INTERVAL)
    ap.add_argument("--second-shot-ms", type=int, default=OCR_SECOND_SHOT_MS_DEFAULT)
    ap.add_argument("--roi-lock-s", type=float, default=OCR_ROI_LOCK_DURATION)
    
    # Threading arguments
    ap.add_argument("--phase-hz", type=float, default=PHASE_HZ_DEFAULT)
    ap.add_argument("--ws", action="store_true", default=DEFAULT_WEBSOCKET_ENABLED)
    ap.add_argument("--no-ws", action="store_false", dest="ws", help="Disable WebSocket mode")
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
    
    # Multi-language arguments (DEPRECATED - now using LCU scraper)
    ap.add_argument("--multilang", action="store_true", default=False, 
                   help="[DEPRECATED] Multi-language support now automatic via LCU scraper")
    ap.add_argument("--no-multilang", action="store_false", dest="multilang", 
                   help="[DEPRECATED] Multi-language support now automatic via LCU scraper")
    ap.add_argument("--language", type=str, default=DEFAULT_OCR_LANG, 
                   help="[DEPRECATED] Language is now auto-detected from LCU")
    
    # Skin download arguments
    ap.add_argument("--download-skins", action="store_true", default=DEFAULT_DOWNLOAD_SKINS, 
                   help="Automatically download skins at startup")
    ap.add_argument("--no-download-skins", action="store_false", dest="download_skins", 
                   help="Disable automatic skin downloading")
    ap.add_argument("--force-update-skins", action="store_true", default=DEFAULT_FORCE_UPDATE_SKINS, 
                   help="Force update all skins (re-download existing ones)")
    ap.add_argument("--max-champions", type=int, default=None, 
                   help="Limit number of champions to download skins for (for testing)")
    
    # Log management arguments
    ap.add_argument("--log-max-files", type=int, default=LOG_MAX_FILES_DEFAULT, 
                   help=f"Maximum number of log files to keep (default: {LOG_MAX_FILES_DEFAULT})")
    ap.add_argument("--log-max-total-size-mb", type=int, default=LOG_MAX_TOTAL_SIZE_MB_DEFAULT, 
                   help=f"Maximum total size of all log files in MB (default: {LOG_MAX_TOTAL_SIZE_MB_DEFAULT}MB)")

    return ap.parse_args()


def setup_logging_and_cleanup(args: argparse.Namespace) -> None:
    """Setup logging and clean up old logs and debug folders"""
    # Clean up old log files on startup
    from utils.logging import cleanup_logs
    cleanup_logs(max_files=args.log_max_files, max_total_size_mb=args.log_max_total_size_mb)
    
    # Setup logging first
    setup_logging(args.verbose)
    
    # Suppress PIL/Pillow debug messages for optional image plugins
    logging.getLogger("PIL").setLevel(logging.INFO)
    
    log_section(log, "SkinCloner Starting", "🚀", {
        "Verbose Mode": "Enabled" if args.verbose else "Disabled",
        "Download Skins": "Enabled" if args.download_skins else "Disabled",
        "OCR Debug": "Enabled" if args.debug_ocr else "Disabled"
    })
    
    # Clean up OCR debug folder on startup (only if debug mode is enabled)
    if args.debug_ocr:
        ocr_debug_dir = Path(__file__).resolve().parent / "ocr_debug"
        if ocr_debug_dir.exists():
            try:
                shutil.rmtree(ocr_debug_dir)
                log_success(log, f"Cleared OCR debug folder: {ocr_debug_dir}", "🧹")
            except (OSError, PermissionError) as e:
                log.warning(f"Failed to clear OCR debug folder: {e}")


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
        
        # Set downloading status immediately if downloads are enabled
        if args.download_skins:
            tray_manager.set_downloading(True)
            log_status(log, "Download mode", "Active (orange indicator shown)", "📥")
        
        return tray_manager
    except Exception as e:
        log.warning(f"Failed to initialize system tray: {e}")
        log.info("Application will continue without system tray icon")
        return None


def initialize_qt_and_chroma(skin_scraper, state: SharedState):
    """Initialize PyQt6 and chroma selector"""
    qt_app = None
    chroma_selector = None
    
    if not PYQT6_AVAILABLE:
        return qt_app, chroma_selector
    
    try:
        # Try to get existing QApplication or create new one
        existing_app = QApplication.instance()
        if existing_app is None:
            qt_app = QApplication([sys.argv[0]])
            log_success(log, "PyQt6 QApplication created for chroma wheel", "🎨")
        else:
            qt_app = existing_app
            log_success(log, "Using existing QApplication instance for chroma wheel", "🎨")
        
        # Initialize chroma selector (widgets will be created on champion lock)
        try:
            chroma_selector = init_chroma_selector(skin_scraper, state)
            log_success(log, "Chroma selector initialized (widgets will be created on champion lock)", "🌈")
        except Exception as e:
            log.warning(f"Failed to initialize chroma wheel: {e}")
            log.warning("Chroma selection will be disabled, but app will continue")
            chroma_selector = None
            
    except Exception as e:
        log.warning(f"Failed to initialize PyQt6: {e}")
        log.warning("Chroma wheel will be disabled, but app will continue normally")
        qt_app = None
        chroma_selector = None
    
    return qt_app, chroma_selector


def initialize_ocr(args: argparse.Namespace, lcu: LCU):
    """Initialize OCR with language detection"""
    ocr_lang = args.lang
    
    if args.lang == "auto":
        # Try to get LCU language immediately, but don't block if not available
        if lcu.ok:
            try:
                lcu_lang = lcu.client_language
                if lcu_lang:
                    log.info(f"LCU connected - detected language: {lcu_lang}")
                    ocr_lang = get_ocr_language(lcu_lang, args.lang)
                    log.info(f"Auto-detected OCR language: {ocr_lang} (LCU: {lcu_lang})")
                else:
                    log.info("LCU connected but language not yet available - using English fallback")
                    ocr_lang = "eng"
            except Exception as e:
                log.debug(f"Failed to get LCU language: {e}")
                log.info("LCU connected but language detection failed - using English fallback")
                ocr_lang = "eng"
        else:
            log.info("LCU not yet connected - using English fallback, will auto-detect when connected")
            ocr_lang = "eng"
    
    # Validate OCR language
    if not validate_ocr_language(ocr_lang):
        log.warning(f"OCR language '{ocr_lang}' may not be available. Falling back to English.")
        ocr_lang = "eng"
    
    # Initialize OCR with determined language (CPU mode only)
    try:
        ocr = OCR(lang=ocr_lang, psm=args.psm, tesseract_exe=args.tesseract_exe)
        log.info(f"OCR: {ocr.backend} (lang: {ocr_lang}, mode: CPU)")
        return ocr
    except Exception as e:
        log.warning(f"Failed to initialize OCR with language '{ocr_lang}': {e}")
        log.info("Attempting fallback to English OCR...")
        
        try:
            ocr = OCR(lang="eng", psm=args.psm, tesseract_exe=args.tesseract_exe)
            log.info(f"OCR: {ocr.backend} (lang: eng, mode: CPU)")
            return ocr
        except Exception as fallback_e:
            log.error(f"OCR initialization failed: {fallback_e}")
            log.error("EasyOCR is not properly installed or configured.")
            log.error("Install with: pip install easyocr torch torchvision")
            sys.exit(1)


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
    
    # Initialize system tray manager immediately to hide console
    tray_manager = initialize_tray_manager(args)
    
    # Initialize core components
    lcu = LCU(args.lockfile)
    skin_scraper = LCUSkinScraper(lcu)
    state = SharedState()
    
    # Initialize PyQt6 and chroma selector
    qt_app, chroma_selector = initialize_qt_and_chroma(skin_scraper, state)
    
    # Initialize OCR with language detection
    ocr = initialize_ocr(args, lcu)
    
    # Initialize database
    db = NameDB(lang=args.dd_lang)
    
    # Initialize injection manager with database (lazy initialization)
    injection_manager = InjectionManager(name_db=db)
    
    # Download skins if enabled (run in background to avoid blocking startup)
    if args.download_skins:
        log.info("Starting automatic skin download in background...")
        
        def download_skins_background():
            try:
                success = download_skins_on_startup(
                    force_update=args.force_update_skins,
                    max_champions=args.max_champions,
                    tray_manager=tray_manager,
                    injection_manager=injection_manager
                )
                if success:
                    log.info("Background skin download completed successfully")
                else:
                    log.warning("Background skin download completed with some issues")
            except Exception as e:
                log.error(f"Failed to download skins in background: {e}")
        
        # Start skin download in a separate thread to avoid blocking
        skin_download_thread = create_daemon_thread(target=download_skins_background, 
                                                    name="SkinDownload")
        skin_download_thread.start()
    else:
        log.info("Automatic skin download disabled")
        # Initialize injection system immediately when download is disabled
        injection_manager.initialize_when_ready()
    
    # Multi-language support is no longer needed - we use LCU scraper + English DB
    # Skin names are matched using: OCR (client lang) → LCU scraper → skinId → English DB
    
    
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

    # Function to update OCR language dynamically
    def update_ocr_language(new_lcu_lang: str):
        """Update OCR language when LCU language changes"""
        if args.lang == "auto":
            new_ocr_lang = get_ocr_language(new_lcu_lang, args.lang)
            if new_ocr_lang != ocr.lang:
                try:
                    # Validate that the new OCR language is available before updating
                    if validate_ocr_language(new_ocr_lang):
                        # Recreate OCR with new language (force reload)
                        log.info(f"Reloading OCR with new language: {new_ocr_lang} (LCU: {new_lcu_lang})")
                        
                        # Create new OCR instance with new language
                        new_ocr = OCR(
                            lang=new_ocr_lang,
                            psm=args.psm,
                            tesseract_exe=args.tesseract_exe
                        )
                        
                        # Update the global OCR reference
                        ocr.__dict__.update(new_ocr.__dict__)
                        
                        log.info(f"✅ OCR successfully reloaded with language: {new_ocr_lang}")
                    else:
                        # Keep current OCR language (likely English fallback) but log the LCU language
                        log.info(f"OCR language kept at: {ocr.lang} (LCU: {new_lcu_lang}, OCR language not available)")
                except Exception as e:
                    log.warning(f"Failed to update OCR language: {e}")

    # Initialize thread manager for organized thread lifecycle
    thread_manager = ThreadManager()
    
    # Create and register threads
    t_phase = PhaseThread(lcu, state, interval=1.0/max(PHASE_POLL_INTERVAL_DEFAULT, args.phase_hz), 
                         log_transitions=not args.ws, injection_manager=injection_manager)
    thread_manager.register("Phase", t_phase)
    
    t_champ = None
    if not args.ws:
        t_champ = ChampThread(lcu, db, state, interval=CHAMP_POLL_INTERVAL, 
                             injection_manager=injection_manager, skin_scraper=skin_scraper)
        thread_manager.register("Champion", t_champ)
    
    t_ocr = OCRSkinThread(state, db, ocr, args, lcu, skin_scraper=skin_scraper)
    thread_manager.register("OCR", t_ocr)
    
    t_ws = None
    if args.ws:
        t_ws = WSEventThread(lcu, db, state, ping_interval=args.ws_ping, 
                            ping_timeout=WS_PING_TIMEOUT_DEFAULT, timer_hz=args.timer_hz, 
                            fallback_ms=args.fallback_loadout_ms, injection_manager=injection_manager, 
                            skin_scraper=skin_scraper)
        thread_manager.register("WebSocket", t_ws, stop_method=t_ws.stop)
    
    t_lcu_monitor = LCUMonitorThread(lcu, state, update_ocr_language, t_ws)
    thread_manager.register("LCU Monitor", t_lcu_monitor)
    
    # Start all threads
    thread_manager.start_all()

    log.info("System ready - OCR active only in Champion Select")
    if args.debug_ocr:
        log.info("OCR Debug Mode: ON - Images will be saved to 'ocr_debug/' folder")
    else:
        log.info("OCR Debug Mode: OFF - Use --debug-ocr to enable")

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
                    # Process pending chroma wheel requests first
                    if chroma_selector and chroma_selector.wheel:
                        chroma_start = time.time()
                        chroma_selector.wheel.process_pending()
                        chroma_elapsed = time.time() - chroma_start
                        if chroma_elapsed > CHROMA_WHEEL_PROCESSING_THRESHOLD_S:
                            log.warning(f"[WATCHDOG] Chroma wheel processing took {chroma_elapsed:.2f}s")
                    
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
    main()
