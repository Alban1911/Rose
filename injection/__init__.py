#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Injection package
Main entry point for injection functionality
"""

# Re-export main classes for backward compatibility
from .core.manager import InjectionManager
from .core.injector import SkinInjector

# Re-export subpackage classes for convenience
from .game.game_monitor import GameMonitor
from .game.game_detector import GameDetector
from .config.config_manager import ConfigManager
from .config.threshold_manager import ThresholdManager
from .mods.mod_manager import ModManager
from .mods.zip_resolver import ZipResolver
from .overlay.overlay_manager import OverlayManager
from .overlay.process_manager import ProcessManager
from .tools.tools_manager import ToolsManager

__all__ = [
    'InjectionManager',
    'SkinInjector',
    'GameMonitor',
    'GameDetector',
    'ConfigManager',
    'ThresholdManager',
    'ModManager',
    'ZipResolver',
    'OverlayManager',
    'ProcessManager',
    'ToolsManager',
]

