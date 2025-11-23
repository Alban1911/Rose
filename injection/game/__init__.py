#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Game management package
Handles game detection and monitoring
"""

from .game_monitor import GameMonitor
from .game_detector import GameDetector

__all__ = ['GameMonitor', 'GameDetector']

