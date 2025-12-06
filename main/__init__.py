#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for Rose
"""

import argparse
import sys
from typing import Optional

# Python version check
MIN_PYTHON = (3, 11)
if sys.version_info < MIN_PYTHON:
    raise RuntimeError(
        f"Rose requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer. "
        "Please upgrade your interpreter and rebuild the application."
    )

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
from pathlib import Path
import time

log = get_logger()


def _setup_pengu_after_lcu_connection(lcu) -> None:
    """
    Wait for LCU connection, detect and save leaguepath/clientpath, then setup Pengu Loader.
    
    This function:
    1. Waits for LCU to be connected
    2. Detects leaguepath/clientpath from lockfile
    3. Saves paths to config.ini
    4. Verifies paths are written
    5. Sets league path in Pengu Loader
    6. Activates Pengu Loader
    """
    # Wait for LCU connection (with timeout)
    max_wait_time = 60  # seconds
    wait_interval = 0.5  # seconds
    elapsed = 0.0
    
    log.info("Waiting for LCU connection to setup Pengu Loader...")
    while not lcu.ok and elapsed < max_wait_time:
        time.sleep(wait_interval)
        elapsed += wait_interval
        lcu.refresh_if_needed()
    
    if not lcu.ok:
        log.warning("LCU connection not available after %d seconds, skipping Pengu setup", max_wait_time)
        return
    
    log.info("LCU connected, detecting League paths...")
    
    # Detect paths using GameDetector
    config_manager = ConfigManager()
    game_detector = GameDetector(config_manager)
    league_path, client_path = game_detector.detect_paths()
    
    if not league_path or not client_path:
        log.warning("Could not detect League paths, skipping Pengu setup")
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


def run_league_unlock(args: Optional[argparse.Namespace] = None,
                      injection_threshold: Optional[float] = None) -> None:
    """Run the core Rose application startup and main loop."""
    # Check for single instance before doing anything else
    check_single_instance()
    # Parse arguments if they were not provided
    if args is None:
        args = setup_arguments()
    
    # Setup logging and cleanup
    setup_logging_and_cleanup(args)
    
    # Initialize system tray manager immediately to hide console
    tray_manager = initialize_tray_manager(args)
    
    # Initialize app status manager
    app_status = AppStatus(tray_manager)
    log_success(log, "App status manager initialized", "📊")
    
    # Check initial status (will show locked until all components are ready)
    app_status.update_status(force=True)
    
    # Initialize core components
    lcu, skin_scraper, state, injection_manager = initialize_core_components(args, injection_threshold)
    
    # Wait for LCU connection and setup Pengu Loader
    _setup_pengu_after_lcu_connection(lcu)
    
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
    
    # Initialize threads
    thread_manager, t_phase, t_ui, t_ws, t_lcu_monitor = initialize_threads(
        lcu, state, args, injection_manager, skin_scraper, app_status, on_lcu_disconnected
    )
    
    # Run main loop
    try:
        run_main_loop(state, skin_scraper)
    finally:
        # Perform cleanup
        perform_cleanup(state, thread_manager, tray_manager, injection_manager)


def main() -> None:
    """Program entry point that prepares and launches Rose."""
    args = setup_arguments()
    if sys.platform == "win32":
        if not args.dev:
            try:
                from launcher import run_launcher
                run_launcher(dev_mode=args.dev)
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

