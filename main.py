#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for the modularized SkinCloner
"""

import argparse
import os
import sys
import time
import ctypes
import atexit
import signal
from pathlib import Path


# Fix for windowed mode - allocate console to prevent blocking operations
if sys.platform == "win32":
    try:
        # Set DPI awareness to SYSTEM_AWARE before any GUI operations
        # This prevents Qt from trying to change it later (which causes "Access denied")
        # PROCESS_SYSTEM_DPI_AWARE
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(WINDOWS_DPI_AWARENESS_SYSTEM)
        except Exception:
            try:
                # Fallback for older Windows versions
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass  # If both fail, continue anyway
        
        # Check if we're in windowed mode (no console attached)
        console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not console_hwnd:
            # Allocate a console for the process to prevent blocking operations
            ctypes.windll.kernel32.AllocConsole()
            # Hide the console window immediately
            console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if console_hwnd:
                ctypes.windll.user32.ShowWindow(console_hwnd, 0)  # SW_HIDE = 0
    except Exception:
        pass  # If console allocation fails, continue with original approach

# Fix for windowed mode - redirect None streams to devnull to prevent blocking
if sys.stdin is None:
    sys.stdin = open(os.devnull, 'r')
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')
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
from constants import *
from constants import THREAD_FORCE_EXIT_TIMEOUT_S  # Explicit import for new constant

# Global variable to track if we're shutting down
_shutting_down = False

def signal_handler(signum, frame):
    """Handle system signals for graceful shutdown"""
    global _shutting_down
    if _shutting_down:
        return  # Prevent multiple shutdown attempts
    _shutting_down = True
    
    print(f"\nReceived signal {signum}, initiating graceful shutdown...")
    # Force exit if we're stuck
    import os
    os._exit(0)

def force_quit_handler():
    """Force quit handler that can be called from anywhere"""
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    
    print("\nForce quit initiated...")
    import os
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
    import io
    import contextlib
    
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

# Global variable to hold the lock file
_lock_file = None

def create_lock_file():
    """Create a lock file to prevent multiple instances"""
    global _lock_file
    
    try:
        # Create a lock file in the state directory
        from utils.paths import get_state_dir
        state_dir = get_state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        
        lock_file_path = state_dir / "skincloner.lock"
        
        # Windows-only approach using file creation
        try:
            # Try to create the lock file exclusively
            _lock_file = open(lock_file_path, 'x')
            _lock_file.write(f"{os.getpid()}\n")
            _lock_file.write(f"{time.time()}\n")
            _lock_file.flush()
            
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
                            except:
                                pass  # Process doesn't exist, we can proceed
                    
                    # Old lock file is stale, remove it
                    os.remove(lock_file_path)
                    
                    # Try again
                    _lock_file = open(lock_file_path, 'x')
                    _lock_file.write(f"{os.getpid()}\n")
                    _lock_file.write(f"{time.time()}\n")
                    _lock_file.flush()
                    atexit.register(cleanup_lock_file)
                    return True
                    
            except Exception:
                # If we can't read the lock file, assume it's stale
                try:
                    os.remove(lock_file_path)
                    _lock_file = open(lock_file_path, 'x')
                    _lock_file.write(f"{os.getpid()}\n")
                    _lock_file.write(f"{time.time()}\n")
                    _lock_file.flush()
                    atexit.register(cleanup_lock_file)
                    return True
                except Exception:
                    return False
                
    except Exception:
        return False

def cleanup_lock_file():
    """Clean up the lock file"""
    global _lock_file
    
    try:
        if _lock_file:
            _lock_file.close()
            _lock_file = None
            
        # Remove the lock file
        from utils.paths import get_state_dir
        lock_file_path = get_state_dir() / "skincloner.lock"
        if lock_file_path.exists():
            lock_file_path.unlink()
    except Exception:
        pass  # Ignore cleanup errors

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
            except Exception:
                # Fallback to logging if MessageBox fails
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


def main():
    """Main entry point"""
    
    # Check for admin rights FIRST (required for injection to work)
    from utils.admin_utils import ensure_admin_rights
    ensure_admin_rights()
    
    # Check for single instance before doing anything else
    check_single_instance()
    
    ap = argparse.ArgumentParser(description="Combined LCU + OCR Tracer (ChampSelect) — ROI lock + burst OCR + locks/timer fixes")
    
    # OCR arguments
    ap.add_argument("--tessdata", type=str, default=None, help="[DEPRECATED] Not used with EasyOCR")
    ap.add_argument("--psm", type=int, default=DEFAULT_TESSERACT_PSM, help="[DEPRECATED] Not used with EasyOCR (kept for compatibility)")
    ap.add_argument("--min-conf", type=float, default=OCR_MIN_CONFIDENCE_DEFAULT)
    ap.add_argument("--lang", type=str, default=DEFAULT_OCR_LANG, help="OCR lang (EasyOCR): 'auto', 'fra', 'kor', 'chi_sim', 'ell', etc.")
    ap.add_argument("--tesseract-exe", type=str, default=None, help="[DEPRECATED] Not used with EasyOCR")
    ap.add_argument("--debug-ocr", action="store_true", default=DEFAULT_DEBUG_OCR, help="Save OCR images to debug folder")
    ap.add_argument("--no-debug-ocr", action="store_false", dest="debug_ocr", help="Disable OCR debug image saving")
    
    # Capture arguments
    ap.add_argument("--capture", choices=["window", "screen"], default=DEFAULT_CAPTURE_MODE)
    ap.add_argument("--monitor", choices=["all", "primary"], default=DEFAULT_MONITOR)
    ap.add_argument("--window-hint", type=str, default=DEFAULT_WINDOW_HINT)
    
    # Database arguments
    ap.add_argument("--dd-lang", type=str, default=DEFAULT_DD_LANG, help="DDragon language(s): 'fr_FR' | 'fr_FR,en_US,es_ES' | 'all'")
    
    # General arguments
    ap.add_argument("--verbose", action="store_true", default=DEFAULT_VERBOSE)
    ap.add_argument("--lockfile", type=str, default=None)
    
    # OCR performance arguments
    ap.add_argument("--burst-hz", type=float, default=OCR_BURST_HZ_DEFAULT)
    ap.add_argument("--idle-hz", type=float, default=OCR_IDLE_HZ_DEFAULT, help="periodic re-emission (0=off)")
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
    ap.add_argument("--timer-hz", type=int, default=TIMER_HZ_DEFAULT, help="Loadout countdown display frequency (Hz)")
    ap.add_argument("--fallback-loadout-ms", type=int, default=FALLBACK_LOADOUT_MS_DEFAULT, help="(deprecated) Old fallback ms if LCU doesn't provide timer — ignored")
    ap.add_argument("--skin-threshold-ms", type=int, default=SKIN_THRESHOLD_MS_DEFAULT, help="Write last skin at T<=threshold (ms)")
    ap.add_argument("--inject-batch", type=str, default="", help="Batch to execute right after skin write (leave empty to disable)")
    
    # Multi-language arguments (DEPRECATED - now using LCU scraper)
    ap.add_argument("--multilang", action="store_true", default=False, help="[DEPRECATED] Multi-language support now automatic via LCU scraper")
    ap.add_argument("--no-multilang", action="store_false", dest="multilang", help="[DEPRECATED] Multi-language support now automatic via LCU scraper")
    ap.add_argument("--language", type=str, default=DEFAULT_OCR_LANG, help="[DEPRECATED] Language is now auto-detected from LCU")
    
    # Skin download arguments
    ap.add_argument("--download-skins", action="store_true", default=DEFAULT_DOWNLOAD_SKINS, help="Automatically download skins at startup")
    ap.add_argument("--no-download-skins", action="store_false", dest="download_skins", help="Disable automatic skin downloading")
    ap.add_argument("--force-update-skins", action="store_true", default=DEFAULT_FORCE_UPDATE_SKINS, help="Force update all skins (re-download existing ones)")
    ap.add_argument("--max-champions", type=int, default=None, help="Limit number of champions to download skins for (for testing)")
    
    # Log management arguments
    ap.add_argument("--log-max-files", type=int, default=LOG_MAX_FILES_DEFAULT, help="Maximum number of log files to keep (default: 20)")
    ap.add_argument("--log-max-total-size-mb", type=int, default=LOG_MAX_TOTAL_SIZE_MB_DEFAULT, help="Maximum total size of all log files in MB (default: 100MB)")

    args = ap.parse_args()

    # Clean up old log files on startup
    from utils.logging import cleanup_logs
    cleanup_logs(max_files=args.log_max_files, max_total_size_mb=args.log_max_total_size_mb)
    
    # Setup logging first
    setup_logging(args.verbose)
    
    # Suppress PIL/Pillow debug messages for optional image plugins
    import logging
    logging.getLogger("PIL").setLevel(logging.INFO)
    
    log_section(log, "SkinCloner Starting", "🚀", {
        "Verbose Mode": "Enabled" if args.verbose else "Disabled",
        "Download Skins": "Enabled" if args.download_skins else "Disabled",
        "OCR Debug": "Enabled" if args.debug_ocr else "Disabled"
    })
    
    # Clean up OCR debug folder on startup (only if debug mode is enabled)
    if args.debug_ocr:
        import shutil
        # Use project directory (where main.py is)
        ocr_debug_dir = Path(__file__).resolve().parent / "ocr_debug"
        if ocr_debug_dir.exists():
            try:
                shutil.rmtree(ocr_debug_dir)
                log_success(log, f"Cleared OCR debug folder: {ocr_debug_dir}", "🧹")
            except Exception as e:
                log.warning(f"Failed to clear OCR debug folder: {e}")
    
    # Initialize system tray manager immediately to hide console
    tray_manager = None
    try:
        def tray_quit_callback():
            """Callback for tray quit - set the shared state stop flag"""
            log.info("Setting stop flag from tray quit")
            # We'll set the stop flag later when state is initialized
        
        tray_manager = TrayManager(quit_callback=tray_quit_callback)
        tray_manager.start()
        log_success(log, "System tray icon initialized - console hidden", "📍")
        
        # Give tray icon a moment to fully initialize
        time.sleep(TRAY_INIT_SLEEP_S)
        
        # Set downloading status immediately if downloads are enabled
        # This makes the orange dot appear right away, before OCR initialization
        if args.download_skins:
            tray_manager.set_downloading(True)
            log_status(log, "Download mode", "Active (orange indicator shown)", "📥")
    except Exception as e:
        log.warning(f"Failed to initialize system tray: {e}")
        log.info("Application will continue without system tray icon")
    
    # Initialize components
    # Initialize LCU first
    lcu = LCU(args.lockfile)
    
    # Initialize LCU skin scraper for champion-specific skin lookup
    skin_scraper = LCUSkinScraper(lcu)
    
    # Load owned skins if LCU is already connected
    state = SharedState()
    
    # Initialize PyQt6 QApplication for chroma wheel (must be done early)
    qt_app = None
    chroma_selector = None
    
    if PYQT6_AVAILABLE:
        try:
            # Try to get existing QApplication or create new one
            existing_app = QApplication.instance()
            if existing_app is None:
                # Create new QApplication with minimal arguments
                import sys
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
    # Owned skins will be loaded when WebSocket connects (no need to load at startup)
    
    # Initialize OCR language (will be updated when LCU connects)
    ocr_lang = args.lang
    if args.lang == "auto":
        # Try to get LCU language immediately, but don't block if not available
        lcu_lang = None
        
        if lcu.ok:
            try:
                lcu_lang = lcu.get_client_language()
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
        
        # Note: Language will be updated automatically by LCUMonitorThread when LCU connects
    
    # Validate OCR language
    if not validate_ocr_language(ocr_lang):
        log.warning(f"OCR language '{ocr_lang}' may not be available. Falling back to English.")
        ocr_lang = "eng"
    
    # Initialize OCR with determined language (CPU mode only)
    try:
        ocr = OCR(lang=ocr_lang, psm=args.psm, tesseract_exe=args.tesseract_exe)
        log.info(f"OCR: {ocr.backend} (lang: {ocr_lang}, mode: CPU)")
    except Exception as e:
        log.warning(f"Failed to initialize OCR with language '{ocr_lang}': {e}")
        log.info("Attempting fallback to English OCR...")
        
        try:
            ocr = OCR(lang="eng", psm=args.psm, tesseract_exe=args.tesseract_exe)
            log.info(f"OCR: {ocr.backend} (lang: eng, mode: CPU)")
        except Exception as fallback_e:
            log.error(f"OCR initialization failed: {fallback_e}")
            log.error("EasyOCR is not properly installed or configured.")
            log.error("Install with: pip install easyocr torch torchvision")
            sys.exit(1)
    
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
        import threading
        skin_download_thread = threading.Thread(target=download_skins_background, daemon=True)
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
                    import msvcrt
                    if msvcrt.kbhit():
                        msvcrt.getch()  # Consume any pending input
                except Exception:
                    pass
            
            # Add a timeout to force quit if main loop doesn't exit
            def force_quit_timeout():
                import time
                time.sleep(2.0)  # Reduced to 2 seconds
                if not _shutting_down:
                    log.warning("Main loop did not exit within 2 seconds - forcing quit")
                    force_quit_handler()
            
            import threading
            timeout_thread = threading.Thread(target=force_quit_timeout, daemon=True)
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

    # Initialize threads
    t_phase = PhaseThread(lcu, state, interval=1.0/max(PHASE_POLL_INTERVAL_DEFAULT, args.phase_hz), log_transitions=not args.ws, injection_manager=injection_manager)
    t_champ = None if args.ws else ChampThread(lcu, db, state, interval=CHAMP_POLL_INTERVAL, injection_manager=injection_manager, skin_scraper=skin_scraper)
    t_ocr = OCRSkinThread(state, db, ocr, args, lcu, skin_scraper=skin_scraper)
    t_ws = WSEventThread(lcu, db, state, ping_interval=args.ws_ping, ping_timeout=WS_PING_TIMEOUT_DEFAULT, timer_hz=args.timer_hz, fallback_ms=args.fallback_loadout_ms, injection_manager=injection_manager, skin_scraper=skin_scraper) if args.ws else None
    t_lcu_monitor = LCUMonitorThread(lcu, state, update_ocr_language, t_ws)
    # Start threads
    t_phase.start()
    if t_champ: 
        t_champ.start()
    t_ocr.start()
    if t_ws: 
        t_ws.start()
    t_lcu_monitor.start()

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
            if time_since_last_loop > 5.0:  # More than 5 seconds is suspicious
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
                        if chroma_elapsed > 1.0:
                            log.warning(f"[WATCHDOG] Chroma wheel processing took {chroma_elapsed:.2f}s")
                    
                    # Process all Qt events
                    qt_start = time.time()
                    qt_app.processEvents()
                    qt_elapsed = time.time() - qt_start
                    if qt_elapsed > 1.0:
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
        
        cleanup_start = time.time()
        
        # Stop WebSocket connection first (needs explicit close)
        if t_ws and t_ws.is_alive():
            try:
                log.info("Closing WebSocket connection...")
                t_ws.stop()
            except Exception as e:
                log.warning(f"Error closing WebSocket: {e}")
        
        # Stop system tray
        if tray_manager:
            try:
                log.info("Stopping system tray...")
                tray_manager.stop()
                log_success(log, "System tray stopped", "✓")
            except Exception as e:
                log.warning(f"Error stopping system tray: {e}")
        
        # Stop all threads with better tracking
        threads_to_stop = [
            ("Phase", t_phase),
            ("Champion", t_champ) if t_champ else None,
            ("OCR", t_ocr),
            ("WebSocket", t_ws) if t_ws else None,
            ("LCU Monitor", t_lcu_monitor)
        ]
        threads_to_stop = [t for t in threads_to_stop if t is not None]
        
        still_alive = []
        for name, thread in threads_to_stop:
            if thread.is_alive():
                log.info(f"Waiting for {name} thread to stop...")
                thread.join(timeout=THREAD_JOIN_TIMEOUT_S)
                if thread.is_alive():
                    log.warning(f"{name} thread did not stop within {THREAD_JOIN_TIMEOUT_S}s timeout")
                    still_alive.append(name)
                else:
                    log_success(log, f"{name} thread stopped", "✓")
        
        # Check if any threads are still alive
        elapsed = time.time() - cleanup_start
        if still_alive:
            log.warning(f"Some threads did not stop: {', '.join(still_alive)}")
            log.warning(f"Cleanup took {elapsed:.1f}s - forcing exit")
            
            # Clean up lock file before forced exit
            cleanup_lock_file()
            
            # Force exit after timeout
            if elapsed > THREAD_FORCE_EXIT_TIMEOUT_S:
                log.error(f"Forced exit after {elapsed:.1f}s - threads still running")
                import os
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
            except Exception:
                pass


if __name__ == "__main__":
    main()
