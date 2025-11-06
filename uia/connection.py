"""
UI connection management for League of Legends
"""

import logging
from pywinauto.application import Application

log = logging.getLogger(__name__)


class UIConnection:
    """Manages connection to League of Legends window"""
    
    def __init__(self):
        self.league_window = None
        self.connected = False
    
    def connect(self) -> bool:
        """Connect to League of Legends window - always creates a fresh connection"""
        try:
            # Ensure we're disconnected first to avoid stale references
            if self.connected:
                self.disconnect()
            
            log.debug("[UIA] Initializing connection to League of Legends...")
            # Always create a fresh Application connection
            app = Application(backend="uia").connect(title="League of Legends")
            self.league_window = app.window(title="League of Legends")
            self.connected = True
            log.debug("Successfully connected to League of Legends window")
            return True
            
        except Exception as e:
            log.debug(f"Failed to connect to League of Legends: {e}")
            self.connected = False
            self.league_window = None
            return False
    
    def disconnect(self):
        """Disconnect from League of Legends window"""
        # Clear the window reference first
        if self.league_window is not None:
            try:
                # Try to close any references to the window
                self.league_window = None
            except Exception:
                pass
        self.league_window = None
        self.connected = False
        log.debug("Disconnected from League of Legends window")
    
    def is_connected(self) -> bool:
        """Check if connected to League of Legends"""
        return self.connected and self.league_window is not None
