"""
UI connection management for League of Legends
"""

import logging
from typing import Optional
from pywinauto.application import Application

log = logging.getLogger(__name__)


class UIConnection:
    """Manages connection to League of Legends window"""
    
    def __init__(self):
        self.league_window = None
        self.connected = False
    
    def connect(self) -> bool:
        """Connect to League of Legends window"""
        try:
            log.debug("Initializing PyWinAuto connection to League of Legends...")
            app = Application(backend="uia").connect(title="League of Legends")
            self.league_window = app.window(title="League of Legends")
            self.connected = True
            log.debug("Successfully connected to League of Legends window")
            return True
            
        except Exception as e:
            log.debug(f"Failed to connect to League of Legends: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Disconnect from League of Legends window"""
        self.league_window = None
        self.connected = False
        log.debug("Disconnected from League of Legends window")
    
    def is_connected(self) -> bool:
        """Check if connected to League of Legends"""
        return self.connected and self.league_window is not None
