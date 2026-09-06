#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU Core Package
Contains core connection, API, and lockfile functionality
"""

from .client import LCU
from .lcu_connection import LCUConnection
from .lcu_api import LCUAPI
from .lockfile import Lockfile, find_lockfile, parse_lockfile, SWIFTPLAY_MODES, SWIFTPLAY_QUEUE_ID, SWIFTPLAY_QUEUE_IDS

__all__ = [
    'LCU',
    'LCUConnection',
    'LCUAPI',
    'Lockfile',
    'find_lockfile',
    'parse_lockfile',
    'SWIFTPLAY_MODES',
    'SWIFTPLAY_QUEUE_ID',
    'SWIFTPLAY_QUEUE_IDS',
]

