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
    
    def __init__(self, league_window):
        self.league_window = league_window
    
    def find_skin_name_element(self) -> Optional[object]:
        """Find the skin name element using exact pixel coordinates"""
        try:
            # Use exact pixel coordinates for instant detection
            element = self._find_by_pixel_coordinates()
            if element:
                return element
            
            return None
            
        except Exception as e:
            log.debug(f"Error finding skin name element: {e}")
            return None
    
    def _find_by_pixel_coordinates(self) -> Optional[object]:
        """Find skin name using exact pixel coordinates for instant detection"""
        try:
            # Get window position and dimensions
            window_rect = self.league_window.rectangle()
            window_left = window_rect.left
            window_top = window_rect.top
            window_width = window_rect.width()
            window_height = window_rect.height()
            
            # Use percentage-based coordinates for skin name detection
            # These constants are defined in config.py and tested to be correct
            relative_x = int(window_width * config.UI_DETECTION_SKIN_NAME_X_RATIO)  # 50% of window width (center)
            relative_y = int(window_height * config.UI_DETECTION_SKIN_NAME_Y_RATIO)  # 63.9% of window height (constant)
            
            # Convert to absolute screen coordinates
            # PyWinAuto's element_info_from_point() expects screen coordinates, not window-relative
            target_x = window_left + relative_x
            target_y = window_top + relative_y
            
            # Debug logging
            log.debug(f"Window position: ({window_left}, {window_top})")
            log.debug(f"Window size: {window_width}x{window_height}")
            log.debug(f"Relative coordinates: ({relative_x}, {relative_y})")
            log.debug(f"Target screen coordinates: ({target_x}, {target_y})")
            
            # Try to find element at this exact pixel location (screen coordinates)
            try:
                # Use the correct PyWinAuto method for pixel-based detection
                element = self.league_window.from_point(target_x, target_y)
                log.debug(f"Element found at pixel: {element}")
            except Exception as e:
                log.debug(f"Error calling from_point: {e}")
                return None
            
            if element:
                try:
                    # Get text directly from the element
                    text = element.window_text()
                    log.debug(f"Text found: '{text}'")
                    
                    if text and len(text.strip()) >= 2:
                        # Basic validation
                        if (any(c.isalpha() for c in text) and 
                            not any(indicator in text for indicator in ["!", "⁦", "⁩", "#", "→", "←", "↑", "↓", "•", "○", "●"])):
                            log.info(f"Found skin name via pixel coordinates: '{text}'")
                            return element
                        else:
                            log.debug(f"Text failed validation: '{text}'")
                    else:
                        log.debug(f"Text too short: '{text}'")
                        
                except Exception as e:
                    log.debug(f"Error processing element: {e}")
            else:
                log.debug("No element found at target pixel location")
            
            # Since you know the exact pixel location, no need for area search
            # The exact pixel should always hit the skin name
            
            return None
            
        except Exception as e:
            log.debug(f"Error in pixel coordinate search: {e}")
            return None
    
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