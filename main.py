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
from database.multilang_db import MultiLanguageDB
from lcu.client import LCU
from state.shared_state import SharedState
from threads.phase_thread import PhaseThread
from threads.champ_thread import ChampThread
from threads.ocr_thread import OCRSkinThread
from threads.websocket_thread import WSEventThread
from threads.lcu_monitor_thread import LCUMonitorThread
from utils.logging import setup_logging, get_logger
from injection.manager import InjectionManager
from utils.skin_downloader import download_skins_on_startup
from utils.tray_manager import TrayManager
from constants import *

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
                ctypes.windll.user32.MessageBoxW(
                    0, 
                    "Another instance of SkinCloner is already running!\n\nPlease close the existing instance before starting a new one.",
                    "SkinCloner - Instance Already Running",
                    0x10  # MB_ICONERROR
                )
            except Exception:
                # Fallback to console output if MessageBox fails
                print("Error: Another instance of SkinCloner is already running!")
                print("Please close the existing instance before starting a new one.")
        else:
            print("Error: Another instance of SkinCloner is already running!")
            print("Please close the existing instance before starting a new one.")
        sys.exit(1)


def get_ocr_language(lcu_lang: str, manual_lang: str = None) -> str:
    """Get OCR language based on LCU language or manual setting"""
    if manual_lang and manual_lang != "auto":
        return manual_lang
    
    return OCR_LANG_MAP.get(lcu_lang, "eng")  # Default to English


def validate_ocr_language(lang: str) -> bool:
    """Validate that OCR language is available by checking tessdata files"""
    if not lang or lang == "auto":
        return True
    
    try:
        from utils.tesseract_path import get_tesseract_configuration
        config = get_tesseract_configuration()
        tessdata_dir = config.get("tessdata_dir")
        
        if not tessdata_dir or not os.path.isdir(tessdata_dir):
            # If we can't find tessdata, assume only English is available
            return lang == "eng"
        
        # Check if all parts of combined languages are available
        parts = lang.split('+')
        for part in parts:
            lang_file = os.path.join(tessdata_dir, f"{part}.traineddata")
            if not os.path.isfile(lang_file):
                return False
        return True
    except Exception:
        # If validation fails, assume only English is available
        return lang == "eng"


def main():
    """Main entry point"""
    
    # Check for single instance before doing anything else
    check_single_instance()
    
    ap = argparse.ArgumentParser(description="Combined LCU + OCR Tracer (ChampSelect) — ROI lock + burst OCR + locks/timer fixes")
    
    # OCR arguments
    ap.add_argument("--tessdata", type=str, default=None, help="Path to tessdata folder (e.g., C:\\Program Files\\Tesseract-OCR\\tessdata)")
    ap.add_argument("--psm", type=int, default=DEFAULT_TESSERACT_PSM)
    ap.add_argument("--min-conf", type=float, default=OCR_MIN_CONFIDENCE_DEFAULT)
    ap.add_argument("--lang", type=str, default=DEFAULT_OCR_LANG, help="OCR lang (tesseract): 'auto', 'fra+eng', 'kor', 'chi_sim', 'ell', etc.")
    ap.add_argument("--tesseract-exe", type=str, default=None)
    
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
    # Use user data directory for skin file to avoid permission issues
    from utils.paths import get_state_dir
    default_skin_file = str(get_state_dir() / DEFAULT_SKIN_FILE_NAME)
    ap.add_argument("--skin-file", type=str, default=default_skin_file, help="Path to last_hovered_skin.txt file")
    ap.add_argument("--inject-batch", type=str, default="", help="Batch to execute right after skin write (leave empty to disable)")
    
    # Multi-language arguments
    ap.add_argument("--multilang", action="store_true", default=DEFAULT_MULTILANG_ENABLED, help="Enable multi-language support")
    ap.add_argument("--no-multilang", action="store_false", dest="multilang", help="Disable multi-language support")
    ap.add_argument("--language", type=str, default=DEFAULT_OCR_LANG, help="Manual language selection (e.g., 'fr_FR', 'en_US', 'zh_CN', 'auto' for detection)")
    
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
    
    setup_logging(args.verbose)
    log.info("Starting...")
    
    # Initialize system tray manager immediately to hide console
    tray_manager = None
    try:
        def tray_quit_callback():
            """Callback for tray quit - set the shared state stop flag"""
            log.info("Setting stop flag from tray quit")
            # We'll set the stop flag later when state is initialized
        
        tray_manager = TrayManager(quit_callback=tray_quit_callback)
        tray_manager.start()
        log.info("System tray icon initialized - console hidden")
        
        # Give tray icon a moment to fully initialize
        time.sleep(0.2)
    except Exception as e:
        log.warning(f"Failed to initialize system tray: {e}")
        log.info("Application will continue without system tray icon")
    
    # Initialize injection manager early (lazy initialization)
    injection_manager = InjectionManager()
    
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
    
    # Initialize components
    # Initialize LCU first
    lcu = LCU(args.lockfile)
    
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
    
    # Initialize OCR with determined language
    try:
        ocr = OCR(lang=ocr_lang, psm=args.psm, tesseract_exe=args.tesseract_exe)
        ocr.tessdata_dir = args.tessdata
        log.info(f"OCR: {ocr.backend} (lang: {ocr_lang})")
    except Exception as e:
        log.warning(f"Failed to initialize OCR with language '{ocr_lang}': {e}")
        log.info("Attempting fallback to English OCR...")
        
        try:
            ocr = OCR(lang="eng", psm=args.psm, tesseract_exe=args.tesseract_exe)
            ocr.tessdata_dir = args.tessdata
            log.info(f"OCR: {ocr.backend} (lang: eng)")
        except Exception as fallback_e:
            log.error(f"OCR initialization failed: {fallback_e}")
            log.error("Tesseract OCR is not properly installed or configured.")
            log.error("Run 'python utils/check_tesseract.py' for detailed diagnostic information.")
            log.error("Install Tesseract from: https://github.com/UB-Mannheim/tesseract/wiki")
            sys.exit(1)
    
    db = NameDB(lang=args.dd_lang)
    state = SharedState()
    
    # Initialize multi-language database (after LCU connection is established)
    if args.multilang:
        auto_detect = args.language.lower() == "auto"
        if auto_detect:
            # For auto-detect mode, use English as fallback but let LCU determine the primary language
            multilang_db = MultiLanguageDB(auto_detect=True, fallback_lang="en_US", lcu_client=lcu)
            log.info("Multi-language auto-detection enabled")
        else:
            # For manual mode, use the specified language
            multilang_db = MultiLanguageDB(auto_detect=False, fallback_lang=args.language, lcu_client=lcu)
            log.info(f"Multi-language mode: manual language '{args.language}'")
    else:
        multilang_db = None
        log.info("Multi-language support disabled")
    
    
    # Configure skin writing
    state.skin_write_ms = int(getattr(args, 'skin_threshold_ms', 2000) or 2000)
    state.skin_file = getattr(args, 'skin_file', state.skin_file) or state.skin_file
    state.inject_batch = getattr(args, 'inject_batch', state.inject_batch) or state.inject_batch
    
    # Update tray manager quit callback now that state is available
    if tray_manager:
        def updated_tray_quit_callback():
            """Callback for tray quit - set the shared state stop flag"""
            log.info("Setting stop flag from tray quit")
            state.stop = True
        
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
                        # Update OCR language
                        ocr.lang = new_ocr_lang
                        log.info(f"OCR language updated to: {new_ocr_lang} (LCU: {new_lcu_lang})")
                    else:
                        # Keep current OCR language (likely English fallback) but log the LCU language
                        log.info(f"OCR language kept at: {ocr.lang} (LCU: {new_lcu_lang}, OCR language not available)")
                    
                    # Update multilang database if needed
                    if multilang_db and multilang_db.auto_detect:
                        multilang_db.current_language = new_lcu_lang
                        if new_lcu_lang not in multilang_db.databases:
                            try:
                                multilang_db.databases[new_lcu_lang] = NameDB(lang=new_lcu_lang)
                                log.info(f"Loaded multilang database for {new_lcu_lang}")
                            except Exception as e:
                                log.debug(f"Failed to load multilang database for {new_lcu_lang}: {e}")
                except Exception as e:
                    log.warning(f"Failed to update OCR language: {e}")

    # Initialize threads
    t_phase = PhaseThread(lcu, state, interval=1.0/max(PHASE_POLL_INTERVAL_DEFAULT, args.phase_hz), log_transitions=not args.ws, injection_manager=injection_manager)
    t_champ = None if args.ws else ChampThread(lcu, db, state, interval=CHAMP_POLL_INTERVAL, injection_manager=injection_manager)
    t_ocr = OCRSkinThread(state, db, ocr, args, lcu, multilang_db)
    t_ws = WSEventThread(lcu, db, state, ping_interval=args.ws_ping, ping_timeout=WS_PING_TIMEOUT_DEFAULT, timer_hz=args.timer_hz, fallback_ms=args.fallback_loadout_ms, injection_manager=injection_manager) if args.ws else None
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

    last_phase = None
    try:
        while not state.stop:
            ph = state.phase
            if ph != last_phase:
                if ph == "InProgress":
                    if state.last_hovered_skin_key:
                        log.info(f"[launch:last-skin] {state.last_hovered_skin_key} (skinId={state.last_hovered_skin_id}, champ={state.last_hovered_skin_slug})")
                    else:
                        log.info("[launch:last-skin] (no hovered skin detected)")
                last_phase = ph
            time.sleep(MAIN_LOOP_SLEEP)
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")
        state.stop = True
    finally:
        state.stop = True
        
        # Stop system tray
        if tray_manager:
            try:
                tray_manager.stop()
                log.info("System tray stopped")
            except Exception as e:
                log.warning(f"Error stopping system tray: {e}")
        
        # Stop all threads
        t_phase.join(timeout=1.0)
        if t_champ: 
            t_champ.join(timeout=1.0)
        t_ocr.join(timeout=1.0)
        if t_ws: 
            t_ws.join(timeout=1.0)
        t_lcu_monitor.join(timeout=1.0)
        
        # Clean up pre-built overlays
        if injection_manager:
            try:
                injection_manager.cleanup_prebuilt_overlays()
                log.info("Cleaned up pre-built overlays")
            except Exception as e:
                log.warning(f"Error cleaning up pre-built overlays: {e}")
        
        # Clean up lock file on exit
        cleanup_lock_file()


if __name__ == "__main__":
    main()
