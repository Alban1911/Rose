"""
Main UI thread for skin name detection
"""

import time
import threading
import logging
from typing import Optional

from .connection import UIConnection
from .detector import UIDetector
from .debug import UIDebugger

log = logging.getLogger(__name__)


class UISkinThread(threading.Thread):
    """Thread for detecting skin names from League of Legends UI"""
    
    def __init__(self, shared_state, name_db, lcu, skin_scraper=None, injection_manager=None, mousehover_debug=False, interval=0.1):
        super().__init__(daemon=True)
        self.shared_state = shared_state
        self.name_db = name_db
        self.lcu = lcu
        self.skin_scraper = skin_scraper
        self.injection_manager = injection_manager
        self.mousehover_debug = mousehover_debug
        self.interval = interval
        
        # Thread control
        self.running = False
        self.stop_event = threading.Event()
        
        # UI components
        self.connection = UIConnection()
        self.detector = None
        self.debugger = None
        
        # State
        self.detection_available = False
        self.skin_name_element = None
        self.last_skin_name = None
        self.last_skin_id = None
    
    def run(self):
        """Main thread loop"""
        self.running = True
        log.info("UI Detection: Thread started")
        
        while self.running and not self.stop_event.is_set():
            try:
                if self._should_run_detection():
                    if not self.detection_available:
                        if self._initialize_detection():
                            self.detection_available = True
                            log.info("UI Detection: Starting - champion locked in ChampSelect (50ms delay)")
                    
                    # Debug mouse hover if enabled
                    if self.mousehover_debug:
                        self._debug_mouse_hover()
                    
                    # Find skin name element if not found yet
                    if self.skin_name_element is None:
                        self.skin_name_element = self.detector.find_skin_name_element()
                    
                    # Get skin name if element is available
                    if self.skin_name_element:
                        skin_name = self._get_skin_name()
                        if skin_name and skin_name != self.last_skin_name:
                            self._process_skin_name(skin_name)
                else:
                    if self.detection_available:
                        log.info("UI Detection: Stopped - waiting for champion lock")
                        self.detection_available = False
                        self.skin_name_element = None
                        self.last_skin_name = None
                        self.last_skin_id = None
                
                # Wait before next iteration
                self.stop_event.wait(self.interval)
                
            except Exception as e:
                log.error(f"UI Detection: Error in main loop - {e}")
                time.sleep(1)
        
        log.info("UI Detection: Thread stopped")
    
    def stop(self):
        """Stop the thread"""
        self.running = False
        self.stop_event.set()
        self.connection.disconnect()
        log.info("UI Detection: Stop requested")
    
    def _should_run_detection(self) -> bool:
        """Check if we should run detection based on current state"""
        if self.shared_state.phase != "ChampSelect" or self.shared_state.locked_champ_id is None:
            return False
        
        # Check if enough time has passed since champion lock
        if self.shared_state.locked_champ_timestamp > 0:
            import time
            from config import UIA_DELAY_MS
            elapsed_ms = (time.time() - self.shared_state.locked_champ_timestamp) * 1000
            return elapsed_ms >= UIA_DELAY_MS
        
        return False
    
    def _initialize_detection(self) -> bool:
        """Initialize UI detection components"""
        try:
            if self.connection.connect():
                self.detector = UIDetector(self.connection.league_window)
                self.debugger = UIDebugger(self.connection.league_window)
                return True
            return False
        except Exception as e:
            log.error(f"Failed to initialize detection: {e}")
            return False
    
    def _debug_mouse_hover(self):
        """Debug mouse hover if enabled"""
        try:
            import win32gui
            x, y = win32gui.GetCursorPos()
            self.debugger.debug_mouse_hover(x, y)
        except ImportError:
            log.debug("win32gui not available for mouse hover debug")
        except Exception as e:
            log.debug(f"Mouse hover debug error: {e}")
    
    def _get_skin_name(self) -> Optional[str]:
        """Get skin name from the detected element"""
        try:
            if self.skin_name_element:
                text = self.skin_name_element.window_text()
                return text.strip() if text else None
            return None
        except Exception as e:
            log.debug(f"Error getting skin name: {e}")
            return None
    
    def _process_skin_name(self, skin_name: str):
        """Process detected skin name"""
        try:
            log.info(f"UI Detection: Found skin name - '{skin_name}'")
            
            # Update shared state
            self.shared_state.ui_last_text = skin_name
            
            # Try to find skin ID
            skin_id = self._find_skin_id(skin_name)
            if skin_id:
                self.shared_state.ui_skin_id = skin_id
                log.info(f"UI Detection: Mapped skin name to ID - {skin_id}")
            
            self.last_skin_name = skin_name
            self.last_skin_id = skin_id
            
        except Exception as e:
            log.error(f"Error processing skin name: {e}")
    
    def _find_skin_id(self, skin_name: str) -> Optional[int]:
        """Find skin ID from skin name"""
        try:
            # Get current champion
            champ_id = self.shared_state.locked_champ_id
            if not champ_id:
                return None
            
            # Get champion slug
            champion_slug = self.name_db.slug_by_id.get(champ_id)
            if not champion_slug:
                return None
            
            # Get skin names for champion
            skin_names = self.name_db.get_english_skin_names_for_champion(champion_slug)
            if not skin_names:
                return None
            
            # Find matching skin
            for skin_id, names in skin_names.items():
                if skin_name in names:
                    return skin_id
            
            return None
            
        except Exception as e:
            log.debug(f"Error finding skin ID: {e}")
            return None
