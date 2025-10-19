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
from config import UIA_DELAY_MS


log = logging.getLogger(__name__)


class UISkinThread(threading.Thread):
    """Thread for detecting skin names from League of Legends UI"""
    
    def __init__(self, shared_state, name_db, lcu, skin_scraper=None, injection_manager=None, interval=0.1):
        super().__init__(daemon=True)
        self.shared_state = shared_state
        self.name_db = name_db
        self.lcu = lcu
        self.skin_scraper = skin_scraper
        self.injection_manager = injection_manager
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
        
        # Detection retry logic
        self.detection_attempts = 0
        self.max_detection_attempts = 50  # Try for ~5 seconds at 0.1s interval
        self.detection_backoff_delay = 0.5  # Wait longer between attempts after failures
    
    def run(self):
        """Main thread loop"""
        self.running = True
        log.info("UI Detection: Thread started")
        
        while self.running and not self.stop_event.is_set():
            try:
                # Handle PyWinAuto connection (connect when entering ChampSelect)
                if self._should_connect():
                    if not self.connection.is_connected():
                        if self.connection.connect():
                            self.detector = UIDetector(self.connection.league_window, self.skin_scraper, self.shared_state)
                            self.debugger = UIDebugger(self.connection.league_window)
                            log.info("UI Detection: PyWinAuto connected in ChampSelect phase")
                else:
                    if self.connection.is_connected():
                        self.connection.disconnect()
                        self.detector = None
                        self.debugger = None
                        log.info("UI Detection: PyWinAuto disconnected - left ChampSelect phase")
                        self.detection_available = False
                        self.skin_name_element = None
                        self.last_skin_name = None
                        self.last_skin_id = None
                        self.detection_attempts = 0
                
                # Handle skin name detection (only when champion is locked and delay has passed)
                if self._should_run_detection() and self.connection.is_connected():
                    if not self.detection_available:
                        self.detection_available = True
                        log.info(f"UI Detection: Starting - champion locked in ChampSelect ({UIA_DELAY_MS}ms delay)")
                    
                    # Find skin name element if not found yet
                    if self.skin_name_element is None:
                        self.skin_name_element = self._find_skin_element_with_retry()
                    
                    # Get skin name if element is available
                    if self.skin_name_element:
                        # Validate that the cached element is still valid
                        if not self._is_element_still_valid():
                            log.debug("UI Detection: Cached element is no longer valid, clearing cache")
                            self.skin_name_element = None
                            self.last_skin_name = None
                            self.last_skin_id = None
                        else:
                            skin_name = self._get_skin_name()
                            if skin_name and skin_name != self.last_skin_name:
                                # The detector already validated this is a valid skin name
                                self._process_skin_name(skin_name)
                else:
                    if self.detection_available:
                        log.info("UI Detection: Stopped - waiting for champion lock")
                        self.detection_available = False
                        self.skin_name_element = None
                        self.last_skin_name = None
                        self.last_skin_id = None
                        # Reset detection attempts when stopping
                        self.detection_attempts = 0
                
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
    
    def _should_connect(self) -> bool:
        """Check if we should establish PyWinAuto connection"""
        return self.shared_state.phase == "ChampSelect"
    
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
                # Also set last_hovered_skin_id for injection pipeline
                self.shared_state.last_hovered_skin_id = skin_id
                # Set skin key for injection
                self.shared_state.last_hovered_skin_key = skin_name
                log.info(f"UI Detection: Mapped skin name to ID - {skin_id}")
                
                # The main thread will detect this state change and notify chroma UI
            
            self.last_skin_name = skin_name
            self.last_skin_id = skin_id
            
        except Exception as e:
            log.error(f"Error processing skin name: {e}")
    
    
    def _is_element_still_valid(self) -> bool:
        """Check if the cached element is still valid"""
        try:
            if not self.skin_name_element:
                return False
            
            # Try to access the element's text to see if it's still valid
            text = self.skin_name_element.window_text()
            return text is not None
            
        except Exception as e:
            log.debug(f"Error validating cached element: {e}")
            return False
    
    
    def _find_skin_element_with_retry(self) -> Optional[object]:
        """Find skin element with retry logic and backoff"""
        if self.detection_attempts >= self.max_detection_attempts:
            # Reset attempts after max reached
            self.detection_attempts = 0
            return None
        
        self.detection_attempts += 1
        
        # Try to find the element
        element = self.detector.find_skin_name_element()
        
        if element:
            # Success! Reset attempts
            self.detection_attempts = 0
            log.info(f"UI Detection: Found skin element after {self.detection_attempts} attempts")
            return element
        else:
            # Failed, use backoff delay
            if self.detection_attempts > 10:  # After 1 second of trying
                log.debug(f"UI Detection: Attempt {self.detection_attempts}/{self.max_detection_attempts} - League may still be loading")
                # Use longer delay for subsequent attempts
                self.stop_event.wait(self.detection_backoff_delay)
            return None
    
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
            
            # Use fuzzy matching to find the best skin match
            if self.skin_scraper:
                # Ensure we have the champion skins scraped
                if self.skin_scraper.scrape_champion_skins(champ_id):
                    # Use the fuzzy matching from skin scraper
                    result = self.skin_scraper.find_skin_by_text(skin_name)
                    if result:
                        skin_id, matched_name, similarity = result
                        log.info(f"UI Detection: Fuzzy match found - '{skin_name}' -> '{matched_name}' (ID: {skin_id}, similarity: {similarity:.2f})")
                        return skin_id
            
            # Fallback to exact match if fuzzy matching fails
            for skin_id, names in skin_names.items():
                if skin_name == names:
                    return skin_id
            
            # Last resort: substring match
            for skin_id, names in skin_names.items():
                if skin_name in names:
                    return skin_id
            
            return None
            
        except Exception as e:
            log.debug(f"Error finding skin ID: {e}")
            return None
