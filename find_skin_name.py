#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Targeted script to find skin names in League of Legends UI
This script specifically looks for skin names like "M. Mundoverse"
"""

import time
import logging
from pywinauto import Application

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

def find_skin_name():
    """Find skin name in League of Legends UI"""
    try:
        log.info("=" * 80)
        log.info("FINDING SKIN NAME IN LEAGUE OF LEGENDS UI")
        log.info("=" * 80)
        
        # Connect to League of Legends
        log.info("Connecting to League of Legends window...")
        app = Application(backend="uia").connect(title="League of Legends")
        league_window = app.window(title="League of Legends")
        
        log.info("Successfully connected to League of Legends window!")
        
        # Method 1: Search for Static controls with skin-like names
        log.info("\n" + "=" * 60)
        log.info("METHOD 1: Searching Static controls for skin names")
        log.info("=" * 60)
        
        try:
            # Get all Static controls
            static_controls = league_window.descendants(control_type="Text")
            log.info(f"Found {len(static_controls)} Static/Text controls")
            
            skin_candidates = []
            for i, control in enumerate(static_controls):
                try:
                    text = control.window_text()
                    if text and text.strip():
                        # Look for skin name patterns (language-agnostic)
                        text_clean = text.strip()
                        
                        # Skip if it's just a number
                        if text_clean.isdigit():
                            continue
                        
                        # Skip if it contains UI indicators
                        ui_indicators = [":", "!", "x", "⁦", "⁩", "#", "→", "←", "↑", "↓", "•", "○", "●"]
                        if any(pattern in text_clean for pattern in ui_indicators):
                            continue
                        
                        # Must have letters
                        if not any(c.isalpha() for c in text_clean):
                            continue
                        
                        # Reasonable length
                        if len(text_clean) < 3 or len(text_clean) > 50:
                            continue
                        
                        # Skip all uppercase (UI labels)
                        if text_clean.isupper() and len(text_clean) > 8:
                            continue
                        
                        # Skip all lowercase (likely not skin names)
                        if text_clean.islower() and len(text_clean) > 10:
                            continue
                        
                        # Look for skin name patterns
                        has_spaces = ' ' in text_clean
                        has_periods = '.' in text_clean
                        has_hyphens = '-' in text_clean
                        has_mixed_case = any(c.isupper() for c in text_clean) and any(c.islower() for c in text_clean)
                        
                        # Pattern matching
                        is_skin_candidate = False
                        
                        # Pattern 1: Text with periods (like "M. Mundoverse")
                        if has_periods:
                            parts = text_clean.split('.')
                            if (len(parts) == 2 and 
                                len(parts[0].strip()) <= 4 and 
                                len(parts[1].strip()) >= 4 and
                                any(c.isalpha() for c in parts[0]) and
                                any(c.isalpha() for c in parts[1])):
                                is_skin_candidate = True
                        
                        # Pattern 2: Multi-word with mixed case
                        elif has_spaces and has_mixed_case and len(text_clean) > 8:
                            is_skin_candidate = True
                        
                        # Pattern 3: Text with hyphens
                        elif has_hyphens and has_mixed_case and len(text_clean) > 6:
                            is_skin_candidate = True
                        
                        # Pattern 4: Single word with mixed case
                        elif not has_spaces and has_mixed_case and len(text_clean) > 6 and len(text_clean) < 20:
                            is_skin_candidate = True
                        
                        if is_skin_candidate:
                            
                            skin_candidates.append((i, text.strip(), control))
                            
                except Exception as e:
                    log.debug(f"Error processing control {i}: {e}")
            
            log.info(f"Found {len(skin_candidates)} potential skin name candidates:")
            for i, (idx, text, control) in enumerate(skin_candidates):
                try:
                    rect = control.rectangle()
                    log.info(f"Candidate {i+1:2d}: '{text}' at position {rect}")
                except (AttributeError, RuntimeError) as e:
                    log.info(f"Candidate {i+1:2d}: '{text}' (position unknown)")
                    log.debug(f"Could not get rectangle for control: {e}")
            
        except Exception as e:
            log.error(f"Error in Method 1: {e}")
        
        # Method 2: Look for specific pattern - text that looks like skin names
        log.info("\n" + "=" * 60)
        log.info("METHOD 2: Pattern-based skin name detection")
        log.info("=" * 60)
        
        try:
            # Get all text elements
            all_elements = league_window.descendants()
            skin_patterns = []
            
            for elem in all_elements:
                try:
                    text = elem.window_text()
                    if text and text.strip():
                        # Look for skin name patterns (language-agnostic)
                        text_clean = text.strip()
                        
                        # Skip if it's just a number
                        if text_clean.isdigit():
                            continue
                        
                        # Skip if it contains UI indicators
                        ui_indicators = [":", "!", "x", "⁦", "⁩", "#", "→", "←", "↑", "↓", "•", "○", "●"]
                        if any(pattern in text_clean for pattern in ui_indicators):
                            continue
                        
                        # Must have letters
                        if not any(c.isalpha() for c in text_clean):
                            continue
                        
                        # Reasonable length
                        if len(text_clean) < 3 or len(text_clean) > 50:
                            continue
                        
                        # Skip all uppercase (UI labels)
                        if text_clean.isupper() and len(text_clean) > 8:
                            continue
                        
                        # Skip all lowercase (likely not skin names)
                        if text_clean.islower() and len(text_clean) > 10:
                            continue
                        
                        # Look for skin name patterns
                        has_spaces = ' ' in text_clean
                        has_periods = '.' in text_clean
                        has_hyphens = '-' in text_clean
                        has_mixed_case = any(c.isupper() for c in text_clean) and any(c.islower() for c in text_clean)
                        
                        # Pattern matching
                        is_skin_candidate = False
                        
                        # Pattern 1: Text with periods (like "M. Mundoverse")
                        if has_periods:
                            parts = text_clean.split('.')
                            if (len(parts) == 2 and 
                                len(parts[0].strip()) <= 4 and 
                                len(parts[1].strip()) >= 4 and
                                any(c.isalpha() for c in parts[0]) and
                                any(c.isalpha() for c in parts[1])):
                                is_skin_candidate = True
                        
                        # Pattern 2: Multi-word with mixed case
                        elif has_spaces and has_mixed_case and len(text_clean) > 8:
                            is_skin_candidate = True
                        
                        # Pattern 3: Text with hyphens
                        elif has_hyphens and has_mixed_case and len(text_clean) > 6:
                            is_skin_candidate = True
                        
                        # Pattern 4: Single word with mixed case
                        elif not has_spaces and has_mixed_case and len(text_clean) > 6 and len(text_clean) < 20:
                            is_skin_candidate = True
                        
                        if is_skin_candidate:
                            skin_patterns.append((text_clean, elem))
                                
                except (AttributeError, ValueError) as e:
                    log.debug(f"Error processing element for skin pattern: {e}")
                except Exception as e:
                    log.debug(f"Unexpected error processing element: {e}")
            
            log.info(f"Found {len(skin_patterns)} text elements matching skin name patterns:")
            for i, (text, elem) in enumerate(skin_patterns):
                try:
                    rect = elem.rectangle()
                    log.info(f"Pattern {i+1:2d}: '{text}' at position {rect}")
                except (AttributeError, ValueError) as e:
                    log.debug(f"Could not get rectangle for element: {e}")
                    log.info(f"Pattern {i+1:2d}: '{text}' (position unknown)")
                except Exception as e:
                    log.debug(f"Unexpected error getting element position: {e}")
                    log.info(f"Pattern {i+1:2d}: '{text}' (position unknown)")
                    
        except Exception as e:
            log.error(f"Error in Method 2: {e}")
        
        # Method 3: Direct search for known skin name pattern
        log.info("\n" + "=" * 60)
        log.info("METHOD 3: Direct search for 'M. Mundoverse' pattern")
        log.info("=" * 60)
        
        try:
            # Search for elements containing "M. Mundoverse" or similar patterns
            all_elements = league_window.descendants()
            direct_matches = []
            
            for elem in all_elements:
                try:
                    text = elem.window_text()
                    if text and "M. Mundoverse" in text:
                        direct_matches.append((text, elem))
                        log.info(f"DIRECT MATCH: '{text}'")
                except (AttributeError, ValueError) as e:
                    log.debug(f"Error getting window text for direct match: {e}")
                except Exception as e:
                    log.debug(f"Unexpected error in direct match search: {e}")
            
            if not direct_matches:
                log.info("No direct matches found for 'M. Mundoverse'")
            else:
                log.info(f"Found {len(direct_matches)} direct matches")
                
        except Exception as e:
            log.error(f"Error in Method 3: {e}")
        
        log.info("\n" + "=" * 80)
        log.info("SKIN NAME DETECTION COMPLETE")
        log.info("=" * 80)
        
        # 30-second sleep to examine the output
        log.info("Sleeping for 30 seconds to examine results...")
        time.sleep(30)
        log.info("30-second sleep completed!")
        
    except Exception as e:
        log.error(f"Failed to connect to League of Legends: {e}")
        log.error("Make sure League of Legends is running and in champion select!")

if __name__ == "__main__":
    find_skin_name()
