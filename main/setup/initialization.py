#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Initialization setup (logging and tray manager)
"""

import logging
import time
from typing import Optional

import argparse

from config import TRAY_INIT_SLEEP_S
from utils.core.logging import setup_logging, get_logger, log_section, log_success
from utils.core.paths import get_user_data_dir, get_detected_user_info
from utils.integration.tray_manager import TrayManager

log = get_logger()


def setup_logging_and_cleanup(args: argparse.Namespace) -> None:
    """Setup logging and clean up old logs and debug folders"""
    # Clean up old log files on startup
    from utils.core.logging import cleanup_logs
    cleanup_logs()
    
    # Determine log mode based on flags
    if args.debug:
        log_mode = 'debug'
    elif args.verbose:
        log_mode = 'verbose'
    else:
        log_mode = 'customer'
    
    # Setup logging (skip log files in dev mode unless explicitly forced)
    force_logs = bool(getattr(args, "logs", False))
    write_logs = (not bool(getattr(args, "dev", False))) or force_logs
    setup_logging(log_mode, write_logs=write_logs)

    # Log user detection info (helps diagnose "Run as Administrator" issues)
    current_user, target_user, is_mismatch = get_detected_user_info()
    data_dir = get_user_data_dir()
    if is_mismatch:
        log.info(f"User mismatch detected: Running as '{current_user}', using '{target_user}' data directory")
        log.info(f"Data directory: {data_dir}")
    else:
        log.debug(f"User: {current_user}, Data directory: {data_dir}")

    # Suppress PIL/Pillow debug messages for optional image plugins
    logging.getLogger("PIL").setLevel(logging.INFO)

    # Show startup banner (mode-aware via log_section)
    if log_mode == 'customer':
        # Simple startup for customer mode
        pass  # Already shown in setup_logging()
    else:
        # Detailed startup for verbose/debug
        log_section(log, "Rose Starting", "", {
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
        log_success(log, "System tray icon initialized - console hidden", "")
        
        # Give tray icon a moment to fully initialize
        time.sleep(TRAY_INIT_SLEEP_S)
        
        # Note: Status will be managed by AppStatus class
        
        return tray_manager
    except Exception as e:
        log.warning(f"Failed to initialize system tray: {e}")
        log.info("Application will continue without system tray icon")
        return None

