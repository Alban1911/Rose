"""
UI element detection methods for League of Legends
"""

import logging
from typing import Optional
from pywinauto import Application
import config

log = logging.getLogger(__name__)


class UIDetector:
    """Handles UI element detection for skin names"""
    
    def __init__(self, league_window, skin_scraper=None, shared_state=None):
        self.league_window = league_window
        self.skin_scraper = skin_scraper
        self.shared_state = shared_state
        # Cache for found skin name element and its position
        self.cached_element = None
        self.cached_element_position = None
        self.cache_valid = False
    
    def find_skin_name_element(self) -> Optional[object]:
        """Find the skin name element using element path navigation"""
        try:
            # First, try to use cached element if it's still valid
            if self.cache_valid and self.cached_element:
                if self._is_cached_element_still_valid():
                    log.debug("Using cached skin name element")
                    return self.cached_element
                else:
                    log.debug("Cached element no longer valid, clearing cache")
                    self._clear_cache()
            
            # If no valid cache, try to find element using path navigation
            element = self._find_by_element_path()
            if element:
                # Cache the found element
                self._cache_element(element)
                return element
            
            return None
            
        except Exception as e:
            log.debug(f"Error finding skin name element: {e}")
            return None
    
    def _find_by_element_path(self) -> Optional[object]:
        """Find skin name using element path navigation"""
        try:
            log.info("=" * 80)
            log.info("SEARCHING FOR SKIN NAME ELEMENT USING PATH NAVIGATION")
            log.info("=" * 80)
            
            # Get all Text controls (role 41) in the League window
            text_elements = self.league_window.descendants(control_type="Text")
            log.info(f"Found {len(text_elements)} Text elements")
            
            # Skip expensive logging - go straight to candidate #54
            
            # Optimized: Take candidate #54 directly (skin name is always there)
            log.info("\nTaking candidate #54 directly (known skin name position)...")
            if len(text_elements) >= 54:
                candidate_54 = text_elements[53]  # 0-indexed, so 53 = candidate 54
                skin_name = candidate_54.window_text()
                
                # Log all available information about the element
                log.info("=" * 80)
                log.info("SKIN NAME ELEMENT DETAILS:")
                log.info("=" * 80)
                log.info(f"Text: '{skin_name}'")
                log.info(f"Element Type: {type(candidate_54)}")
                
                try:
                    control_type = candidate_54.control_type()
                    log.info(f"Control Type: {control_type}")
                except Exception as e:
                    log.info(f"Control Type: Error - {e}")
                
                try:
                    class_name = candidate_54.class_name()
                    log.info(f"Class Name: {class_name}")
                except Exception as e:
                    log.info(f"Class Name: Error - {e}")
                
                try:
                    automation_id = candidate_54.automation_id()
                    log.info(f"Automation ID: '{automation_id}'")
                except Exception as e:
                    log.info(f"Automation ID: Error - {e}")
                
                
                # Get parent hierarchy information and validate expected pattern
                try:
                    parent_count = 0
                    current = candidate_54
                    parent_chain = []
                    while current.parent() and parent_count < 20:
                        current = current.parent()
                        parent_count += 1
                        try:
                            parent_text = current.window_text()[:50] if current.window_text() else "No text"
                            parent_type = str(type(current))
                            parent_chain.append(f"Level {parent_count}: {parent_type} - '{parent_text}'")
                        except:
                            parent_chain.append(f"Level {parent_count}: {type(current)} - Error reading")
                    
                    log.info(f"Parent Depth: {parent_count}")
                    log.info("Parent Chain:")
                    for parent_info in parent_chain[-5:]:  # Show last 5 levels
                        log.info(f"  {parent_info}")
                    
                    # Validate expected hierarchy pattern
                    expected_pattern = [
                        "UIAWrapper - 'No text'",  # Level 2
                        "UIAWrapper - 'No text'",  # Level 3  
                        "UIAWrapper - 'League of Legends'",  # Level 4
                        "UIAWrapper - 'Desktop 1'"  # Level 5
                    ]
                    
                    hierarchy_valid = True
                    if len(parent_chain) >= 4:
                        for i, expected in enumerate(expected_pattern):
                            if i < len(parent_chain):
                                actual = parent_chain[-(i+1)]  # Check from bottom up
                                if expected not in actual:
                                    hierarchy_valid = False
                                    break
                    
                    if hierarchy_valid:
                        log.info("✓ Parent hierarchy matches expected pattern")
                    else:
                        log.info("⚠ Parent hierarchy does not match expected pattern")
                        
                except Exception as e:
                    log.info(f"Parent Info: Error - {e}")
                
                # Get useful properties in a clean format
                try:
                    log.info("Useful Properties:")
                    log.info(f"  Element Info: {candidate_54.element_info}")
                    log.info(f"  Can Be Label: {candidate_54.can_be_label}")
                    log.info(f"  Has Title: {candidate_54.has_title}")
                    log.info(f"  Is Enabled: {candidate_54.is_enabled()}")
                    log.info(f"  Is Visible: {candidate_54.is_visible()}")
                    log.info(f"  Is Keyboard Focusable: {candidate_54.is_keyboard_focusable()}")
                    log.info(f"  Process ID: {candidate_54.process_id()}")
                    log.info(f"  Window Classes: {candidate_54.windowclasses}")
                    log.info(f"  Writable Props: {candidate_54.writable_props}")
                except Exception as e:
                    log.info(f"Properties: Error - {e}")
                
                log.info("=" * 80)
                log.info(f"✓ Found skin name element: '{skin_name}' (candidate #54)")
                return candidate_54
            else:
                log.info("✗ Not enough candidates (need at least 54)")
            
            # No fallback needed - we know position #54 is always the skin name
            log.info("✗ No skin name element found (not enough candidates)")
            return None
            
        except Exception as e:
            log.error(f"Error in element path search: {e}")
            return None
    
    def _is_skin_name_element(self, element) -> bool:
        """Validate if an element is a skin name element based on Levenshtein distance with scraped skins"""
        try:
            # Get element text
            text = element.window_text()
            if not text or len(text.strip()) < 1:
                return False
            
            text_clean = text.strip()
            
            # Basic length check
            if len(text_clean) < 3:
                return False
            
            # Must contain letters
            if not any(c.isalpha() for c in text_clean):
                return False
            
            # Check if it matches any scraped skin names with Levenshtein distance
            return self._matches_scraped_skin_names(text_clean)
            
        except Exception as e:
            log.debug(f"Error validating element: {e}")
            return False
    
    def _matches_scraped_skin_names(self, text: str) -> bool:
        """Check if text matches any of the locked champion's scraped skin names using Levenshtein distance"""
        try:
            # Get current champion
            if not self.shared_state or not self.shared_state.locked_champ_id:
                return False
            
            champ_id = self.shared_state.locked_champ_id
            
            # Use the skin scraper to get the current language skin names
            if not self.skin_scraper:
                return False
            
            # Ensure we have the champion skins scraped
            if not self.skin_scraper.scrape_champion_skins(champ_id):
                return False
            
            # Get the scraped skin names for this champion from the cache
            if not self.skin_scraper.cache.is_loaded_for_champion(champ_id):
                return False
            
            scraped_skins = self.skin_scraper.cache.all_skins
            if not scraped_skins:
                return False
            
            log.debug(f"UI Detection: Checking '{text}' against {len(scraped_skins)} scraped skins for champion {champ_id}")
            
            # Log all scraped skin names for debugging
            scraped_names = [skin_data.get('skinName', '') for skin_data in scraped_skins if skin_data.get('skinName')]
            log.info(f"UI Detection: Available scraped skin names: {scraped_names}")
            
            # Check if any skin name matches with high similarity (0.95 threshold)
            for skin_data in scraped_skins:
                skin_name_from_scraper = skin_data.get('skinName', '')
                if skin_name_from_scraper:
                    similarity = self._levenshtein_similarity(text, skin_name_from_scraper)
                    if similarity >= 0.95:
                        log.info(f"UI Detection: '{text}' matches scraped skin '{skin_name_from_scraper}' with similarity {similarity:.3f}")
                        return True
                    else:
                        log.info(f"UI Detection: '{text}' vs '{skin_name_from_scraper}' similarity: {similarity:.3f}")
            
            log.debug(f"UI Detection: '{text}' does not match any scraped skin for champion {champ_id}")
            return False
            
        except Exception as e:
            log.debug(f"Error validating skin name for champion: {e}")
            return False
    
    def _levenshtein_similarity(self, s1: str, s2: str) -> float:
        """Calculate Levenshtein similarity between two strings (0.0 to 1.0)"""
        if len(s1) < len(s2):
            return self._levenshtein_similarity(s2, s1)
        
        if len(s2) == 0:
            return 0.0
        
        previous_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        max_len = max(len(s1), len(s2))
        distance = previous_row[-1]
        similarity = 1.0 - (distance / max_len)
        return similarity
    
    def _is_cached_element_still_valid(self) -> bool:
        """Check if the cached element is still valid"""
        try:
            if not self.cached_element:
                return False
            
            # Try to access the element's text to see if it's still valid
            text = self.cached_element.window_text()
            return text is not None
            
        except Exception as e:
            log.debug(f"Error validating cached element: {e}")
            return False
    
    def _cache_element(self, element):
        """Cache the found element"""
        self.cached_element = element
        self.cache_valid = True
        log.debug("Element cached successfully")
    
    def _clear_cache(self):
        """Clear the element cache"""
        self.cached_element = None
        self.cached_element_position = None
        self.cache_valid = False
        log.debug("Element cache cleared")
    
    def find_skin_name_by_mouse_hover(self) -> Optional[object]:
        """Find skin name by mouse hover detection (only when --mousehover flag is used)"""
        try:
            # This function would be called only when --mousehover flag is enabled
            # Implementation would depend on how you want to handle mouse hover detection
            # For now, return None as this is a placeholder
            log.debug("Mouse hover detection not implemented yet")
            return None
            
        except Exception as e:
            log.debug(f"Error in mouse hover detection: {e}")
            return None