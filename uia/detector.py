"""
UI element detection methods for League of Legends
"""

import logging
from typing import Optional
from utils.normalization import levenshtein_score

log = logging.getLogger(__name__)

your_teams_bans_text = {"عمليات استبعاد فريقك".upper(), "Zákazy tvého týmu".upper(), "Auswahl deines Teams".upper(), "Οι αποκλεισμοί της ομάδας σας".upper(), "Your Team's Bans".upper(), "Bloqueos de tu equipo".upper(),
"Bannissements de votre équipe".upper(), "Saját csapat kitiltásai".upper(), "Ban Timmu".upper(), "Ban della tua squadra".upper(), "あなたのチームのバン".upper(), "아군 팀 금지 챔피언".upper(), "Bany twojej drużyny".upper(),
"Banimentos da sua equipe".upper(), "Blocările echipei tale".upper(), "Блокировки вашей команды".upper(), "การแบนของทีมคุณ".upper(), "Takımının Yasaklamaları".upper(), "Đội mình cấm".upper(), "己方队伍的禁用".upper(), "友方禁用英雄".upper()}

# Cosmetics text in all languages for Swiftplay mode
cosmetics_text = {
    "COSMÉTIQUES".upper(),  # French
    "COSMETICS".upper(),  # English
    "KOSMETIK".upper(),  # German
    "COSMÉTICOS".upper(),  # Spanish
    "COSMETICI".upper(),  # Italian
    "КОСМЕТИКА".upper(),  # Russian
    "КОСМЕТИКИ".upper(),  # Russian (alt)
    "SKÖNHETSSKÖTSEL".upper(),  # Swedish
    "SKONHETSSKOTEL".upper(),  # Swedish (alt)
    "コスメティクス".upper(),  # Japanese
    "化粧品".upper(),  # Japanese (alt)
    "화장품".upper(),  # Korean
    "COSMÉTICOS".upper(),  # Portuguese
    "KOZMETIKA".upper(),  # Czech
    "KOZMETIKA".upper(),  # Slovak
    "KOSMETIKA".upper(),  # Polish
    "КОЗМЕТИКА".upper(),  # Bulgarian
    "KOZMETIKA".upper(),  # Croatian
    "COSMETICĂ".upper(),  # Romanian
    "MAKYAJ".upper(),  # Turkish
    "MỸ PHẨM".upper(),  # Vietnamese
    "化妆品".upper(),  # Chinese Simplified
    "化妝品".upper(),  # Chinese Traditional
    "קוסמטיקה".upper(),  # Hebrew
    "مستحضرات التجميل".upper(),  # Arabic
    "КОСМЕТИКА".upper(),  # Serbian
    "ΚΟΣΜΗΤΙΚΑ".upper(),  # Greek
    "KÖZMETIKA".upper(),  # Hungarian
}


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
            # First, try to use cached element if available
            if self.cache_valid and self.cached_element:
                log.debug("Using cached skin name element")
                return self.cached_element
            
            # Check if we're in Swiftplay mode and use different detection logic
            if (self.shared_state and 
                self.shared_state.phase == "Lobby" and 
                self.shared_state.is_swiftplay_mode):
                element = self._find_swiftplay_skin_element()
            else:
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
    
    def _find_swiftplay_skin_element(self) -> Optional[object]:
        """Find skin name element in Swiftplay lobby using different detection logic"""
        try:
            # Get all Text controls in the League window
            text_elements = self.league_window.descendants(control_type="Text")
            log.debug(f"Found {len(text_elements)} Text elements in Swiftplay lobby")
            
            # In Swiftplay, we need to find skin names and match them to champions
            # Look for potential skin names in text elements
            potential_skin_elements = []
            for i, element in enumerate(text_elements):
                try:
                    text = element.window_text()
                    if text and len(text.strip()) > 0:
                        text_clean = text.strip()
                        
                        # Basic validation for skin name
                        if len(text_clean) >= 3 and any(c.isalpha() for c in text_clean):
                            potential_skin_elements.append((i, element, text_clean))
                except Exception as e:
                    log.debug(f"Error processing element [{i}]: {e}")
            
            if potential_skin_elements:
                log.debug(f"Found {len(potential_skin_elements)} potential skin elements")
                
                # Check if we should lock on the last element (index -1)
                # Only lock if the element at index -2 contains cosmetics text (in any language)
                if len(potential_skin_elements) >= 2:
                    last_element = potential_skin_elements[-1]  # Index -1
                    second_last_element = potential_skin_elements[-2]  # Index -2
                    
                    # Check if the second last element contains any cosmetics text translation
                    second_last_text = second_last_element[2].upper()
                    found_cosmetics = False
                    for cosmetics_translation in cosmetics_text:
                        if cosmetics_translation in second_last_text:
                            found_cosmetics = True
                            log.debug(f"Found cosmetics text '{cosmetics_translation}' at index -2, locking on skin element")
                            break
                    
                    if found_cosmetics:
                        # Try to match skin names to champions
                        matched_element = self._match_swiftplay_skin_to_champion(potential_skin_elements)
                        if matched_element:
                            return matched_element
                        
                        # Fallback: return the last potential skin element
                        return last_element[1]
                    else:
                        log.debug("Index -2 element does not contain cosmetics text, waiting...")
                        return None  # Wait and try again
                else:
                    log.debug("Not enough elements to check for cosmetics text at index -2, waiting...")
                    return None  # Wait and try again
            else:
                log.debug("No potential skin elements found in Swiftplay lobby")
            
            return None
            
        except Exception as e:
            log.error(f"Error in Swiftplay skin element search: {e}")
            return None
    
    def _match_swiftplay_skin_to_champion(self, potential_skin_elements: list) -> Optional[object]:
        """Match detected skin names to the correct champion"""
        try:
            # Get current champion data from shared state
            if not hasattr(self, 'state') or not self.state:
                log.warning("No shared state available for skin matching")
                return None
            
            champion_1_id = getattr(self.state, 'swiftplay_champion_1_id', None)
            champion_2_id = getattr(self.state, 'swiftplay_champion_2_id', None)
            
            if not champion_1_id and not champion_2_id:
                log.warning("No champions available for skin matching")
                return None
            
            # Get skin scraper cache for skin matching
            if not self.skin_scraper or not hasattr(self.skin_scraper, 'cache'):
                log.warning("No skin scraper cache available for skin matching")
                return None
            
            log.debug(f"Matching skins to champions: Champion 1 (ID: {champion_1_id}), Champion 2 (ID: {champion_2_id})")
            
            # Try to match each potential skin element to a champion
            for i, element, skin_text in potential_skin_elements:
                
                # Check if this skin belongs to champion 1
                if champion_1_id:
                    champion_1_skins = self._get_champion_skins_from_cache(self.skin_scraper, champion_1_id)
                    if champion_1_skins:
                        for skin_data in champion_1_skins:
                            skin_name = skin_data.get('skinName', '')
                            if skin_name and self._is_skin_name_match(skin_text, skin_name):
                                log.debug(f"Matched skin to Champion 1 (ID: {champion_1_id})")
                                return element
                
                # Check if this skin belongs to champion 2
                if champion_2_id:
                    champion_2_skins = self._get_champion_skins_from_cache(self.skin_scraper, champion_2_id)
                    if champion_2_skins:
                        for skin_data in champion_2_skins:
                            skin_name = skin_data.get('skinName', '')
                            if skin_name and self._is_skin_name_match(skin_text, skin_name):
                                log.debug(f"Matched skin to Champion 2 (ID: {champion_2_id})")
                                return element
            
            log.debug("No skin matches found")
            return None
            
        except Exception as e:
            log.error(f"Error matching Swiftplay skin to champion: {e}")
            return None
    
    def _get_champion_skins_from_cache(self, skin_scraper, champion_id: int) -> list:
        """Get skins for a specific champion from the cache"""
        try:
            if not hasattr(skin_scraper, 'cache'):
                return []
            
            # Check if cache is loaded for this champion
            if not skin_scraper.cache.is_loaded_for_champion(champion_id):
                log.debug(f"Skin cache not loaded for champion {champion_id}")
                return []
            
            return skin_scraper.cache.all_skins
            
        except Exception as e:
            log.debug(f"Error getting skins from cache for champion {champion_id}: {e}")
            return []
    
    def _is_skin_name_match(self, detected_text: str, skin_name: str) -> bool:
        """Check if detected text matches a skin name"""
        try:
            # Normalize both strings for comparison
            detected_normalized = detected_text.lower().strip()
            skin_normalized = skin_name.lower().strip()
            
            # Exact match
            if detected_normalized == skin_normalized:
                return True
            
            # Check if detected text contains skin name or vice versa
            if detected_normalized in skin_normalized or skin_normalized in detected_normalized:
                return True
            
            # Check for partial matches (useful for localized names)
            detected_words = set(detected_normalized.split())
            skin_words = set(skin_normalized.split())
            
            # If more than half the words match, consider it a match
            if len(detected_words) > 0 and len(skin_words) > 0:
                common_words = detected_words.intersection(skin_words)
                match_ratio = len(common_words) / min(len(detected_words), len(skin_words))
                if match_ratio >= 0.5:  # 50% word match
                    return True
            
            return False
            
        except Exception as e:
            log.debug(f"Error checking skin name match: {e}")
            return False
    
    def _find_by_element_path(self) -> Optional[object]:
        """Find skin name using element path navigation"""
        try:
            log.info("[UIA] " + "=" * 80)
            log.info("[UIA] SEARCHING FOR SKIN NAME ELEMENT USING PATH NAVIGATION")
            log.info("[UIA] " + "=" * 80)
            
            # Get all Text controls (role 41) in the League window
            text_elements = self.league_window.descendants(control_type="Text")
            log.info(f"[UIA] Found {len(text_elements)} Text elements")
            
            # Find the element right after the second 'YOUR TEAM'S BANS'
            log.info("[UIA] Searching for element after second 'YOUR TEAM'S BANS' equivalent (depends on the language)...")
            
            your_teams_bans_count = 0
            chosen_candidate = None
            chosen_index = -1
            
            for i, element in enumerate(text_elements):
                try:
                    text = element.window_text().upper()
                    if text in your_teams_bans_text:
                        your_teams_bans_count += 1
                        log.info(f"[UIA] Found {text} #{your_teams_bans_count} at index {i}")
                        
                        # If this is the second occurrence, the next element should be the skin name
                        if your_teams_bans_count == 2:
                            if i + 1 < len(text_elements):
                                chosen_candidate = text_elements[i + 1]
                                chosen_index = i + 1
                                log.info(f"[UIA] Found second {text} at index {i}, taking next element at index {i + 1}")
                                break
                            else:
                                log.warning(f"Second {text} found but no element follows it")
                                break
                except Exception as e:
                    log.debug(f"Error checking element {i}: {e}")
                    continue
            
            if chosen_candidate:
                try:
                    skin_name = chosen_candidate.window_text()
                    log.info(f"[UIA] ✓ Found skin name element: '{skin_name}' (candidate #{chosen_index})")
                    return chosen_candidate
                except Exception as e:
                    log.error(f"Error getting skin name from chosen candidate: {e}")
            else:
                log.warning(f"Could not find element after second {text}")
            
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
            
            log.debug(f"[UIA] Checking '{text}' against {len(scraped_skins)} scraped skins for champion {champ_id}")
            
            # Log all scraped skin names for debugging
            scraped_names = [skin_data.get('skinName', '') for skin_data in scraped_skins if skin_data.get('skinName')]
            log.info(f"[UIA] Available scraped skin names: {scraped_names}")
            
            # Check if any skin name matches with high similarity (0.95 threshold)
            for skin_data in scraped_skins:
                skin_name_from_scraper = skin_data.get('skinName', '')
                if skin_name_from_scraper:
                    similarity = levenshtein_score(text, skin_name_from_scraper)
                    if similarity >= 0.95:
                        log.info(f"[UIA] '{text}' matches scraped skin '{skin_name_from_scraper}' with similarity {similarity:.3f}")
                        return True
                    else:
                        log.info(f"[UIA] '{text}' vs '{skin_name_from_scraper}' similarity: {similarity:.3f}")
            
            log.debug(f"[UIA] '{text}' does not match any scraped skin for champion {champ_id}")
            return False
            
        except Exception as e:
            log.debug(f"Error validating skin name for champion: {e}")
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
    