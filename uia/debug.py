"""
Debug utilities for UI automation
"""

import logging

log = logging.getLogger(__name__)


class UIDebugger:
    """Handles UI debugging functionality"""
    
    def __init__(self, league_window):
        self.league_window = league_window
    
