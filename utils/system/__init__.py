#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Utilities

This subpackage contains system and OS-specific utilities:
- admin_utils: Admin/elevation utilities
- win32_base: Windows-specific utilities
- window_utils: Window detection and monitoring
- resolution_utils: Resolution handling
"""

from utils.system.admin_utils import (
    is_admin, request_admin_elevation, ensure_admin_rights,
    is_registered_for_autostart, register_autostart, unregister_autostart,
    show_message_box_threaded
)

__all__ = [
    # Admin
    'is_admin', 'request_admin_elevation', 'ensure_admin_rights',
    'is_registered_for_autostart', 'register_autostart', 'unregister_autostart',
    'show_message_box_threaded',
]

