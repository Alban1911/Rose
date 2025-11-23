#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Signal handlers for graceful shutdown
"""

import os
import signal
import sys

import utils.integration.pengu_loader as pengu_loader

from .state import get_app_state


def signal_handler(signum, frame):
    """Handle system signals for graceful shutdown"""
    app_state = get_app_state()
    if app_state.shutting_down:
        return  # Prevent multiple shutdown attempts
    app_state.shutting_down = True
    
    print(f"\nReceived signal {signum}, initiating graceful shutdown...")
    try:
        pengu_loader.deactivate_on_exit()
    except Exception:
        pass
    # Force exit if we're stuck
    os._exit(0)


def force_quit_handler():
    """Force quit handler that can be called from anywhere"""
    app_state = get_app_state()
    if app_state.shutting_down:
        return
    app_state.shutting_down = True
    
    print("\nForce quit initiated...")
    try:
        pengu_loader.deactivate_on_exit()
    except Exception:
        pass
    os._exit(0)


def setup_signal_handlers() -> None:
    """Set up signal handlers"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

