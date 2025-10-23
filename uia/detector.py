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
            
            # Find the element right after the second 'YOUR TEAM'S BANS'
            log.info("\nSearching for element after second 'YOUR TEAM'S BANS' equivalent (depends on the language)...")
            
            your_teams_bans_count = 0
            chosen_candidate = None
            chosen_index = -1
            
            for i, element in enumerate(text_elements):
                try:
                    text = element.window_text().upper()
                    if text in your_teams_bans_text:
                        your_teams_bans_count += 1
                        log.info(f"Found {text} #{your_teams_bans_count} at index {i}")
                        
                        # If this is the second occurrence, the next element should be the skin name
                        if your_teams_bans_count == 2:
                            if i + 1 < len(text_elements):
                                chosen_candidate = text_elements[i + 1]
                                chosen_index = i + 1
                                log.info(f"Found second {text} at index {i}, taking next element at index {i + 1}")
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
                    log.info(f"✓ Found skin name element: '{skin_name}' (candidate #{chosen_index})")
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
            
            log.debug(f"UI Detection: Checking '{text}' against {len(scraped_skins)} scraped skins for champion {champ_id}")
            
            # Log all scraped skin names for debugging
            scraped_names = [skin_data.get('skinName', '') for skin_data in scraped_skins if skin_data.get('skinName')]
            log.info(f"UI Detection: Available scraped skin names: {scraped_names}")
            
            # Check if any skin name matches with high similarity (0.95 threshold)
            for skin_data in scraped_skins:
                skin_name_from_scraper = skin_data.get('skinName', '')
                if skin_name_from_scraper:
                    similarity = levenshtein_score(text, skin_name_from_scraper)
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
    