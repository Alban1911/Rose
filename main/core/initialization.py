#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Core component initialization
"""

import ctypes
import sys
from typing import Optional, Tuple

from lcu import LCU, LCUSkinScraper
from state import SharedState, AppStatus
from injection import InjectionManager
from injection.mods.storage import ModStorageService
from utils.core.logging import get_logger, log_success
from utils.system.admin_utils import ensure_admin_rights
from config import APP_VERSION, set_config_option

log = get_logger()


def initialize_core_components(args, injection_threshold: Optional[float] = None) -> Tuple[LCU, LCUSkinScraper, SharedState, InjectionManager]:
    """
    Initialize core application components
    
    Returns:
        Tuple of (lcu, skin_scraper, state, injection_manager)
    """
    set_config_option("General", "installed_version", APP_VERSION)
    
    # Check for admin rights FIRST (required for injection to work)
    ensure_admin_rights()

    # Ensure mods directory layout exists early (and clean unknown root categories)
    try:
        ModStorageService()
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to initialize mods storage directories: %s", exc)
    
    # Initialize core components with error handling
    try:
        log.info("Initializing LCU client...")
        lcu = LCU(args.lockfile)
        log.info("LCU client initialized")

        log.info("Initializing skin scraper...")
        skin_scraper = LCUSkinScraper(lcu)
        log.info("Skin scraper initialized")
        
        log.info("Initializing shared state...")
        state = SharedState()
        log.info("Shared state initialized")
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
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"Rose failed to initialize:\n\n{str(e)}\n\nCheck the log file for details:\n{log.handlers[0].baseFilename if log.handlers else 'N/A'}",
                    "Rose - Initialization Error",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except Exception:
                pass
        sys.exit(1)
    
    # Initialize injection manager with database (lazy initialization)
    try:
        log.info("Initializing injection manager...")
        injection_manager = InjectionManager(shared_state=state)
        if injection_threshold is not None:
            log.info(f"Launcher override: setting injection threshold to {injection_threshold:.2f}s")
            injection_manager.injection_threshold = max(0.0, injection_threshold)
        log.info("Injection manager initialized")
        # Don't initialize injection system yet - wait for WebSocket to be active
        # This will be called in main/__init__.py after WebSocket is ready
        
        # Hash check is now handled by the launcher before the app starts
        # No need to check again here - launcher ensures hashes are ready
        if getattr(args, "dev", False):
            log.info("Skipping hashes.game.txt check (dev mode)")
        else:
            log.debug("Hashes should already be ready (checked by launcher)")
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
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"Rose failed to initialize injection system:\n\n{str(e)}\n\nCheck the log file for details:\n{log.handlers[0].baseFilename if log.handlers else 'N/A'}",
                    "Rose - Injection Error",
                    0x50010  # MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST
                )
            except Exception:
                pass
        sys.exit(1)
    
    return lcu, skin_scraper, state, injection_manager

