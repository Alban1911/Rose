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
from pengu.integration import (
    ActivationErrorKind,
    ActivationResult,
    ActivationStage,
    PenguStatus,
    activate,
    activate_on_start,
    deactivate,
    deactivate_on_exit,
    get_status,
    is_available,
    PENGU_DIR,
    PENGU_CORE,
    recover_stale_session,
    restart_client,
)

__all__ = [
    'TrayManager',
    'ActivationErrorKind',
    'ActivationResult',
    'ActivationStage',
    'PenguStatus',
    'activate',
    'activate_on_start',
    'deactivate',
    'deactivate_on_exit',
    'get_status',
    'is_available',
    'PENGU_DIR',
    'PENGU_CORE',
    'recover_stale_session',
    'restart_client',
]

