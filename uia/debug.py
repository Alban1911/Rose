"""
Debug utilities for UI automation
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)


class UIDebugger:
    """Handles UI debugging functionality"""
    
    def __init__(self, league_window):
        self.league_window = league_window
    
