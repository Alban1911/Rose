"""
Main UI thread for skin name detection
"""

import time
import threading
import logging
import json
from typing import Optional, Dict
from pathlib import Path

from .connection import UIConnection
from .detector import UIDetector
from .debug import UIDebugger
from config import UIA_DELAY_MS
from utils.paths import get_user_data_dir
from utils.utilities import get_champion_id_from_skin_id


log = logging.getLogger(__name__)


class UISkinThread(threading.Thread):
    """Thread for detecting skin names from League of Legends UI"""
    
    def __init__(self, shared_state, lcu, skin_scraper=None, injection_manager=None, interval=0.1):
        super().__init__(daemon=True)
        self.shared_state = shared_state
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
        
        # Skin ID mapping cache for Swiftplay
        self.skin_id_mapping: Dict[str, int] = {}
        self.skin_mapping_loaded = False
    
    def run(self):
        """Main thread loop"""
        self.running = True
        log.info("[UIA] Thread started")
        
        
        while self.running and not self.stop_event.is_set():
            try:
                # Handle PyWinAuto connection (connect when entering ChampSelect)
                if self._should_connect():
                    if not self.connection.is_connected():
                        if self.connection.connect():
                            self.detector = UIDetector(self.connection.league_window, self.skin_scraper, self.shared_state)
                            self.debugger = UIDebugger(self.connection.league_window)
                            log.info("[UIA] PyWinAuto connected in ChampSelect phase")
                else:
                    if self.connection.is_connected():
                        self.connection.disconnect()
                        self.detector = None
                        self.debugger = None
                        log.info("[UIA] PyWinAuto disconnected - left ChampSelect phase")
                        self.detection_available = False
                        self.skin_name_element = None
                        self.last_skin_name = None
                        self.last_skin_id = None
                        self.detection_attempts = 0
                
                # Handle skin name detection (only when champion is locked and delay has passed)
                if self._should_run_detection() and self.connection.is_connected():
                    if not self.detection_available:
                        self.detection_available = True
                        if self.shared_state.is_swiftplay_mode:
                            log.info(f"[UIA] Starting - Swiftplay mode detected in lobby")
                        else:
                            log.info(f"[UIA] Starting - champion locked in ChampSelect ({UIA_DELAY_MS}ms delay)")
                    
                    # Find skin name element if not found yet
                    if self.skin_name_element is None:
                        self.skin_name_element = self._find_skin_element_with_retry()
                        
                        # If in Swiftplay mode and no element found, wait 50ms for cosmetics text to appear
                        if (self.skin_name_element is None and 
                            self.shared_state.is_swiftplay_mode and 
                            self.shared_state.phase == "Lobby"):
                            log.debug("[UIA] Waiting 50ms for cosmetics text to appear...")
                            self.stop_event.wait(0.05)  # 50ms delay
                    else:
                        # Validate that the cached element is still valid
                        if not self._is_element_still_valid():
                            log.debug("[UIA] Cached element is no longer valid, clearing cache and resetting retry")
                            self.skin_name_element = None
                            self.last_skin_name = None
                            self.last_skin_id = None
                            # Reset detection attempts so we can retry finding the element
                            self.detection_attempts = 0
                            # Also clear the detector's cached element
                            if self.detector:
                                self.detector._clear_cache()
                            
                            # Hide UI when losing track of skin
                            self.shared_state.ui_skin_id = None
                            self.shared_state.ui_last_text = None
                            
                            # Try to find the element again immediately (especially important for Swiftplay)
                            self.skin_name_element = self._find_skin_element_with_retry()
                    
                    # Get skin name if element is available
                    if self.skin_name_element:
                        skin_name = self._get_skin_name()
                        # In Swiftplay, if we can't get skin name (panel closed), clear and retry
                        if not skin_name:
                            if self.shared_state.is_swiftplay_mode:
                                log.debug("[UIA] Cannot get skin name (panel may be closed), clearing and retrying...")
                                self.skin_name_element = None
                                self.last_skin_name = None
                                self.detection_attempts = 0
                                if self.detector:
                                    self.detector._clear_cache()
                                
                                # Hide UI when panel is closed
                                self.shared_state.ui_skin_id = None
                                self.shared_state.ui_last_text = None
                        elif skin_name != self.last_skin_name:
                            if self.shared_state.is_swiftplay_mode:
                                log.info(f"[UIA] Swiftplay skin name detected: '{skin_name}'")
                            # The detector already validated this is a valid skin name
                            self._process_skin_name(skin_name)
                else:
                    if self.detection_available:
                        log.info("[UIA] Stopped - waiting for champion lock")
                        self.detection_available = False
                        self.skin_name_element = None
                        self.last_skin_name = None
                        self.last_skin_id = None
                        # Reset detection attempts when stopping
                        self.detection_attempts = 0
                
                # Wait before next iteration
                self.stop_event.wait(self.interval)
                
            except Exception as e:
                log.error(f"[UIA] Error in main loop - {e}")
                time.sleep(1)
        
        log.info("[UIA] Thread stopped")
    
    def stop(self):
        """Stop the thread"""
        self.running = False
        self.stop_event.set()
        self.connection.disconnect()
        log.info("[UIA] Stop requested")
    
    def clear_cache(self):
        """Clear all cached elements and state - called during champion exchange"""
        log.info("[UIA] Clearing all UIA cache")
        self.skin_name_element = None
        self.last_skin_name = None
        self.last_skin_id = None
        self.detection_attempts = 0
        
        # Also clear the detector's cached element
        if self.detector:
            self.detector._clear_cache()
        
        # Clear shared state UI detection variables
        self.shared_state.ui_skin_id = None
        self.shared_state.ui_last_text = None
    
    def _should_connect(self) -> bool:
        """Check if we should establish PyWinAuto connection"""
        # For Swiftplay, also connect in Lobby phase
        if self.shared_state.phase == "Lobby" and self.shared_state.is_swiftplay_mode:
            return True
        return self.shared_state.phase in ["ChampSelect", "OwnChampionLocked", "FINALIZATION"]
    
    def _should_run_detection(self) -> bool:
        """Check if we should run detection based on current state"""
        # For Swiftplay, run detection in Lobby phase
        if self.shared_state.phase == "Lobby" and self.shared_state.is_swiftplay_mode:
            return True
        
        # OwnChampionLocked phase - our champion is locked, activate UIA Detection
        if self.shared_state.phase == "OwnChampionLocked":
            return True
        
        # Also allow FINALIZATION phase for backwards compatibility
        if self.shared_state.phase == "FINALIZATION":
            return True
        
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
            log.info(f"[UIA] Found skin name - '{skin_name}'")
            
            # Update shared state
            self.shared_state.ui_last_text = skin_name
            
            # For Swiftplay mode, try to match skin to the correct champion
            if self.shared_state.is_swiftplay_mode:
                self._process_swiftplay_skin_name(skin_name)
            else:
                # Regular mode processing
                self._process_regular_skin_name(skin_name)
            
            self.last_skin_name = skin_name
            
        except Exception as e:
            log.error(f"Error processing skin name: {e}")
    
    def _load_skin_id_mapping(self) -> bool:
        """Load skin ID mapping from JSON file based on current language"""
        try:
            # Get language code from shared state
            language = self.shared_state.current_language
            if not language:
                log.warning("[UIA] No language detected, cannot load skin mapping")
                return False
            
            # Construct path to skin mapping file
            user_data_dir = get_user_data_dir()
            mapping_path = user_data_dir / "skinid_mapping" / language / "skin_ids.json"
            
            if not mapping_path.exists():
                log.warning(f"[UIA] Skin mapping file not found: {mapping_path}")
                return False
            
            # Load the JSON file
            with open(mapping_path, 'r', encoding='utf-8') as f:
                mapping_data = json.load(f)
            
            # Convert to name -> skin_id mapping (reverse the dict)
            # The JSON has structure: {skin_id: skin_name}
            # If multiple skins have the same normalized name, store the first one found
            self.skin_id_mapping = {}
            for skin_id_str, skin_name in mapping_data.items():
                try:
                    skin_id = int(skin_id_str)
                    # Store as normalized name -> skin_id for easier lookup
                    normalized_name = skin_name.strip().lower()
                    # Only store if not already present (keep first occurrence)
                    if normalized_name not in self.skin_id_mapping:
                        self.skin_id_mapping[normalized_name] = skin_id
                except (ValueError, TypeError):
                    continue
            
            log.info(f"[UIA] Loaded {len(self.skin_id_mapping)} skin mappings for language '{language}'")
            self.skin_mapping_loaded = True
            return True
            
        except Exception as e:
            log.error(f"Error loading skin ID mapping: {e}")
            return False
    
    def _find_skin_id_by_name(self, skin_name: str) -> Optional[int]:
        """Find skin ID by name in the loaded mapping - returns FIRST match found"""
        try:
            if not self.skin_mapping_loaded:
                if not self._load_skin_id_mapping():
                    return None
            
            normalized_name = skin_name.strip().lower()
            
            # First try exact match (normalized)
            if normalized_name in self.skin_id_mapping:
                skin_id = self.skin_id_mapping[normalized_name]
                log.debug(f"[UIA] Exact match found: '{skin_name}' -> ID {skin_id}")
                return skin_id
            
            # Try fuzzy matching - return the FIRST match found
            # Search through the mapping and return immediately on first match
            for mapped_name, skin_id in self.skin_id_mapping.items():
                # Check if detected name is contained in mapped name or vice versa
                if normalized_name in mapped_name or mapped_name in normalized_name:
                    log.debug(f"[UIA] Fuzzy match found: '{skin_name}' -> '{mapped_name}' (ID: {skin_id})")
                    return skin_id  # Return FIRST match
            
            log.debug(f"[UIA] No skin ID found for '{skin_name}'")
            return None
            
        except Exception as e:
            log.error(f"Error finding skin ID by name: {e}")
            return None
    
    def _process_swiftplay_skin_name(self, skin_name: str):
        """Process skin name for Swiftplay mode - lookup skin ID and store in dictionary"""
        try:
            log.info(f"[UIA] Swiftplay skin name detected: '{skin_name}'")
            
            # Find skin ID from the mapping
            skin_id = self._find_skin_id_by_name(skin_name)
            if not skin_id:
                log.warning(f"[UIA] Could not find skin ID for '{skin_name}'")
                return
            
            # Calculate champion ID from skin ID
            champion_id = get_champion_id_from_skin_id(skin_id)
            
            # Store in dictionary (replacing any previous value for this champion)
            self.shared_state.swiftplay_skin_tracking[champion_id] = skin_id
            
            # Update UI state - this is the last detected skin for UI display
            self.shared_state.ui_skin_id = skin_id
            self.shared_state.last_hovered_skin_id = skin_id
            
            log.info(f"[UIA] Mapped skin '{skin_name}' -> Champion {champion_id}, Skin {skin_id}")
            log.debug(f"[UIA] Current skin tracking: {self.shared_state.swiftplay_skin_tracking}")
            
        except Exception as e:
            log.error(f"Error processing Swiftplay skin name: {e}")
    
    def _process_regular_skin_name(self, skin_name: str):
        """Process skin name for regular mode"""
        try:
            # Try to find skin ID using local database
            skin_id = self._find_skin_id(skin_name)
            if skin_id:
                log.debug(f"[UI] Found skin ID {skin_id} for '{skin_name}'")
                self.shared_state.ui_skin_id = skin_id
                # Also set last_hovered_skin_id for injection pipeline
                self.shared_state.last_hovered_skin_id = skin_id
                
                # Get English skin name from LCU skin scraper cache
                english_skin_name = None
                if self.skin_scraper and self.skin_scraper.cache.is_loaded_for_champion(self.shared_state.locked_champ_id):
                    skin_data = self.skin_scraper.cache.get_skin_by_id(skin_id)
                    if skin_data:
                        english_skin_name = skin_data.get('skinName', '').strip()
                        log.debug(f"[UIA] Found English name '{english_skin_name}' for skin ID {skin_id}")
                
                if not english_skin_name:
                    log.warning(f"[UIA] Skin ID {skin_id} not found in LCU data, using localized name '{skin_name}'")
                
                # Set skin key for injection (use English name from database)
                self.shared_state.last_hovered_skin_key = english_skin_name or skin_name
                log.info(f"[UIA] Mapped skin name to ID - {skin_id} (using: {self.shared_state.last_hovered_skin_key})")
            else:
                log.debug(f"[UI] No skin ID found for '{skin_name}'")
                
                # The main thread will detect this state change and notify chroma UI
            
            self.last_skin_id = skin_id
            
        except Exception as e:
            log.error(f"Error processing regular skin name: {e}")
    
    
    
    def _is_skin_name_match(self, detected_text: str, skin_name: str) -> bool:
        """Check if detected text matches a skin name"""
        try:
            # Normalize both strings for comparison
            detected_normalized = detected_text.lower().strip()
            skin_normalized = skin_name.lower().strip()
            
            log.debug(f"Comparing: '{detected_normalized}' vs '{skin_normalized}'")
            
            # Exact match
            if detected_normalized == skin_normalized:
                log.debug("Exact match found!")
                return True
            
            # Check if detected text contains skin name or vice versa
            if detected_normalized in skin_normalized or skin_normalized in detected_normalized:
                log.debug("Substring match found!")
                return True
            
            # Check for partial matches (useful for localized names)
            detected_words = set(detected_normalized.split())
            skin_words = set(skin_normalized.split())
            
            # If more than half the words match, consider it a match
            if len(detected_words) > 0 and len(skin_words) > 0:
                common_words = detected_words.intersection(skin_words)
                match_ratio = len(common_words) / min(len(detected_words), len(skin_words))
                log.debug(f"Word match ratio: {match_ratio} (common: {common_words})")
                if match_ratio >= 0.5:  # 50% word match
                    log.debug("Word match found!")
                    return True
            
            log.debug("No match found")
            return False
            
        except Exception as e:
            log.debug(f"Error checking skin name match: {e}")
            return False
    
    
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
            log.info(f"[UIA] Found skin element after {self.detection_attempts} attempts")
            return element
        else:
            # Failed, use backoff delay
            if self.detection_attempts > 10:  # After 1 second of trying
                log.debug(f"[UIA] Attempt {self.detection_attempts}/{self.max_detection_attempts} - League may still be loading")
                # Use longer delay for subsequent attempts
                self.stop_event.wait(self.detection_backoff_delay)
            return None
    
    def _find_skin_id(self, skin_name: str) -> Optional[int]:
        """Find skin ID from skin name using LCU skin scraper"""
        try:
            # Get current champion
            champ_id = self.shared_state.locked_champ_id
            if not champ_id:
                log.debug(f"[UI] No locked champion ID for skin '{skin_name}'")
                return None
            
            log.debug(f"[UI] Looking up skin '{skin_name}' for champion ID {champ_id}")
            
            # Use LCU skin scraper for skin name lookup
            if not self.skin_scraper:
                log.debug(f"[UI] No skin scraper available for skin lookup")
                return None
            
            # Ensure we have the champion skins scraped from LCU
            if not self.skin_scraper.scrape_champion_skins(champ_id):
                log.debug(f"[UI] Failed to scrape skins for champion {champ_id}")
                return None
            
            # Use the fuzzy matching from skin scraper
            result = self.skin_scraper.find_skin_by_text(skin_name)
            if result:
                skin_id, matched_name, similarity = result
                log.info(f"[UIA] LCU match found - '{skin_name}' -> '{matched_name}' (ID: {skin_id}, similarity: {similarity:.2f})")
                return skin_id
            
            log.debug(f"[UI] No skin ID found for '{skin_name}' in LCU data")
            return None
            
        except Exception as e:
            log.debug(f"Error finding skin ID: {e}")
            return None
