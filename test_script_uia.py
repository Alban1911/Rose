#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for PyWinAuto UI detection with League of Legends
This script connects to League of Legends and logs all available UI elements
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

def test_league_ui_detection():
    """Test PyWinAuto connection and log all UI elements"""
    try:
        log.info("=" * 80)
        log.info("TESTING PYWINAUTO CONNECTION TO LEAGUE OF LEGENDS")
        log.info("=" * 80)
        
        # Connect to League of Legends
        log.info("Connecting to League of Legends window...")
        app = Application(backend="uia").connect(title="League of Legends")
        league_window = app.window(title="League of Legends")
        
        log.info("Successfully connected to League of Legends window!")
        
        # Log entire PyWinAuto dialog output
        log.info("=" * 80)
        log.info("PYWINAUTO DIALOG OUTPUT - LEAGUE OF LEGENDS")
        log.info("=" * 80)
        
        try:
            # Get all window information
            log.info("Getting window control identifiers...")
            window_info = league_window.print_control_identifiers()
            log.info("WINDOW CONTROL IDENTIFIERS:")
            log.info(str(window_info))
            
            # Get window properties
            log.info("\nWINDOW PROPERTIES:")
            log.info(f"Window text: {league_window.window_text()}")
            log.info(f"Class name: {league_window.class_name()}")
            log.info(f"Control type: {league_window.control_type()}")
            log.info(f"Automation id: {league_window.automation_id()}")
            log.info(f"Handle: {league_window.handle}")
            log.info(f"Rectangle: {league_window.rectangle()}")
            
            # Get all child controls
            log.info("\nCHILD CONTROLS:")
            children = league_window.children()
            log.info(f"Found {len(children)} child controls")
            
            for i, child in enumerate(children):
                try:
                    child_text = child.window_text()
                    child_class = child.class_name()
                    child_type = child.control_type()
                    log.info(f"Child {i:2d}: '{child_text}' | {child_class} | {child_type}")
                except Exception as child_e:
                    log.info(f"Child {i:2d}: Error getting info - {child_e}")
            
            # Try to find text elements that might contain skin names
            log.info("\nSEARCHING FOR TEXT ELEMENTS (potential skin names):")
            try:
                all_elements = league_window.descendants()
                text_elements = []
                for elem in all_elements:
                    try:
                        text = elem.window_text()
                        if text and len(text.strip()) > 0 and text.strip() != "League of Legends":
                            text_elements.append((elem, text.strip()))
                    except:
                        pass
                
                log.info(f"Found {len(text_elements)} text elements with content:")
                for i, (elem, text) in enumerate(text_elements[:50]):  # Limit to first 50
                    try:
                        elem_class = elem.class_name()
                        elem_type = elem.control_type()
                        log.info(f"Text {i:2d}: '{text}' | {elem_class} | {elem_type}")
                    except:
                        log.info(f"Text {i:2d}: '{text}' | [Error getting element info]")
                
                if len(text_elements) > 50:
                    log.info(f"... and {len(text_elements) - 50} more text elements")
                    
            except Exception as search_e:
                log.error(f"Error searching for text elements: {search_e}")
            
        except Exception as log_e:
            log.error(f"Error logging PyWinAuto dialog info: {log_e}")
        
        log.info("=" * 80)
        log.info("END PYWINAUTO DIALOG OUTPUT")
        log.info("=" * 80)
        
        # 50-second sleep to examine the output
        log.info("Sleeping for 50 seconds to examine PyWinAuto output...")
        time.sleep(50)
        log.info("50-second sleep completed!")
        
        log.info("Test completed successfully!")
        
    except Exception as e:
        log.error(f"Failed to connect to League of Legends: {e}")
        log.error("Make sure League of Legends is running and in champion select!")

if __name__ == "__main__":
    test_league_ui_detection()
