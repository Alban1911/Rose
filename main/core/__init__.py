#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Core subpackage
"""

from .state import AppState, get_app_state
from .lockfile import check_single_instance, cleanup_lock_file
from .signals import setup_signal_handlers, force_quit_handler
from .initialization import initialize_core_components
from .threads import initialize_threads
from .lcu_handler import create_lcu_disconnection_handler
from .cleanup import perform_cleanup

__all__ = [
    'AppState',
    'get_app_state',
    'check_single_instance',
    'cleanup_lock_file',
    'setup_signal_handlers',
    'force_quit_handler',
    'initialize_core_components',
    'initialize_threads',
    'create_lcu_disconnection_handler',
    'perform_cleanup',
]

