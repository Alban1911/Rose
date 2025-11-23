#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Setup subpackage
"""

from .console import setup_console, redirect_none_streams, start_console_buffer_manager
from .arguments import setup_arguments
from .initialization import setup_logging_and_cleanup, initialize_tray_manager

__all__ = [
    'setup_console',
    'redirect_none_streams',
    'start_console_buffer_manager',
    'setup_arguments',
    'setup_logging_and_cleanup',
    'initialize_tray_manager',
]

