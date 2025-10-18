#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Find correct skin name coordinates when in champion select
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

def find_skin_coords():
    """Find skin name coordinates in champion select"""
    try:
        log.info("=" * 80)
        log.info("FINDING SKIN NAME COORDINATES IN CHAMPION SELECT")
        log.info("Make sure you're in champion select and hover over a skin!")
        log.info("=" * 80)
        
        # Connect to League of Legends
        app = Application(backend="uia").connect(title="League of Legends")
        league_window = app.window(title="League of Legends")
        
        log.info("Connected to League of Legends!")
        
        # Get window dimensions
        window_rect = league_window.rectangle()
        window_left = window_rect.left
        window_top = window_rect.top
        window_width = window_rect.width()
        window_height = window_rect.height()
        
        log.info(f"Window: ({window_left}, {window_top}) {window_width}x{window_height}")
        
        # Get all text elements and look for skin names
        log.info("\nSearching for skin names in all text elements...")
        log.info("=" * 60)
        
        text_elements = league_window.descendants(control_type="Text")
        log.info(f"Found {len(text_elements)} text elements")
        
        skin_candidates = []
        for i, elem in enumerate(text_elements):
            try:
                text = elem.window_text()
                if text and text.strip():
                    # Look for skin name patterns
                    text_clean = text.strip()
                    
                    # Skip UI elements
                    ui_indicators = [":", "!", "x", "⁦", "⁩", "#", "→", "←", "↑", "↓", "•", "○", "●", "PVP", "COOP", "ENTRAÎNEMENT", "BANNISSEMENTS", "MODE AVEUGLE", "QUITTER", "VOIR LES COMPÉTENCES", "Trier par", "Aléatoire", "SOCIAL", "HORS LIGNE", "En ligne", "En jeu", "Absent", "Hors ligne", "RIOT MOBILE", "GÉNÉRAL", "JOUER", "LOL", "TFT", "Difficile", "Cliquer", "Entrée", "pour voir"]
                    if any(pattern in text_clean for pattern in ui_indicators):
                        continue
                    
                    # Must have letters and reasonable length
                    if (any(c.isalpha() for c in text_clean) and 
                        3 <= len(text_clean) <= 50 and
                        not text_clean.isdigit()):
                        
                        # Get element position
                        try:
                            rect = elem.rectangle()
                            rel_x = rect.left - window_left
                            rel_y = rect.top - window_top
                            
                            skin_candidates.append((text_clean, rel_x, rel_y, rect))
                            
                        except:
                            skin_candidates.append((text_clean, None, None, None))
                            
            except:
                pass
        
        # Show skin candidates
        log.info(f"\nFound {len(skin_candidates)} potential skin names:")
        for i, (text, x, y, rect) in enumerate(skin_candidates):
            if x is not None and y is not None:
                log.info(f"Skin {i+1:2d}: '{text}' at ({x:3d}, {y:3d})")
            else:
                log.info(f"Skin {i+1:2d}: '{text}' (position unknown)")
        
        # Look for specific patterns that might be skin names
        log.info("\nLooking for specific skin name patterns...")
        skin_names = []
        for text, x, y, rect in skin_candidates:
            if any(keyword in text.lower() for keyword in ['garen', 'darkin', 'universe', 'mundo', 'darius']): # basically put the skin names you want to test here
                log.info(f"*** POTENTIAL SKIN: '{text}' at ({x}, {y}) ***")
                if x is not None and y is not None:
                    skin_names.append((text, x, y))
        
        # Show scaling calculations
        if skin_names:
            log.info(f"\n" + "=" * 60)
            log.info("SCALING CALCULATIONS")
            log.info("=" * 60)
            log.info(f"Current window size: {window_width}x{window_height}")
            log.info(f"Base resolution (where we tested): 1280x720")
            log.info("")
            
            for text, x, y in skin_names:
                # Calculate relative position as percentage
                rel_x_pct = (x / window_width) * 100
                rel_y_pct = (y / window_height) * 100
                
                # Calculate what this would be at base resolution
                base_x = int((x / window_width) * 1280)
                base_y = int((y / window_height) * 720)
                
                log.info(f"Skin: '{text}'")
                log.info(f"  Current coords: ({x:3d}, {y:3d})")
                log.info(f"  Relative pos:   ({rel_x_pct:5.1f}%, {rel_y_pct:5.1f}%)")
                log.info(f"  At 1280x720:    ({base_x:3d}, {base_y:3d})")
                log.info("")
        
        log.info("=" * 80)
        log.info("COORDINATE SEARCH COMPLETE")
        log.info("Look for coordinates that show actual skin names!")
        log.info("Run this script with different skins to see which coordinates are constant!")
        log.info("=" * 80)
        
    except Exception as e:
        log.error(f"Error: {e}")

if __name__ == "__main__":
    find_skin_coords()
