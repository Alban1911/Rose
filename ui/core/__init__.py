#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Core UI Components

This subpackage contains the main UI orchestration and lifecycle management.
"""

from ui.core.user_interface import UserInterface, get_user_interface
from ui.core.lifecycle_manager import UILifecycleManager

__all__ = [
    'UserInterface',
    'get_user_interface',
    'UILifecycleManager',
]

