#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration Utilities

This subpackage contains UI and system integration utilities:
- tray_manager: System tray manager
- tray_settings: Tray settings management
- pengu_loader: Pengu Loader integration
"""

from utils.integration.tray_manager import TrayManager
from utils.integration.pengu_loader import (
    activate_on_start, deactivate_on_exit, PENGU_DIR, PENGU_EXE
)

__all__ = [
    'TrayManager',
    'activate_on_start',
    'deactivate_on_exit',
    'PENGU_DIR',
    'PENGU_EXE',
]

