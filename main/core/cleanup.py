#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cleanup logic for application shutdown
"""

import os
import sys

import utils.integration.pengu_loader as pengu_loader
from utils.core.logging import get_logger, log_section, log_success
from utils.threading.thread_manager import ThreadManager
from utils.integration.tray_manager import TrayManager
from state import SharedState
from config import THREAD_JOIN_TIMEOUT_S, THREAD_FORCE_EXIT_TIMEOUT_S
from .lockfile import cleanup_lock_file
from .state import get_app_state
from main.setup.console import cleanup_console

log = get_logger()


def perform_cleanup(state: SharedState, thread_manager: ThreadManager, tray_manager: TrayManager, injection_manager=None) -> None:
    """Perform application cleanup"""
    # The main loop is done: the tray's force-quit timeout stands down, or it
    # ends the cleanup halfway (restoring the client alone takes seconds)
    get_app_state().shutting_down = True
    log_section(log, "Cleanup", "")

    # A game held for the patcher outlives Rose: resume it first, or quitting
    # Rose during the hold freezes the game for good
    try:
        from injection.game.game_monitor import resume_orphaned_game
        resume_orphaned_game()
    except Exception as e:
        log.warning(f"Error resuming a held game during cleanup: {e}")

    try:
        pengu_loader.deactivate_on_exit()
    except Exception as e:
        log.warning(f"Error deactivating Pengu Loader during cleanup: {e}")

    # Kill every LTK Manager before shutting down
    if injection_manager:
        try:
            log.info("Killing LTK Manager processes...")
            injection_manager.kill_all_modtools_processes()
            log_success(log, "LTK Manager processes killed", "")
        except Exception as e:
            log.warning(f"Error killing LTK Manager processes: {e}")
    
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
        log_success(log, f"All threads stopped cleanly in {elapsed:.1f}s", "")
    
    # Clean up lock file on exit
    cleanup_lock_file()
    
    # Clean up console if we allocated one
    cleanup_console()

