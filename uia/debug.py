"""
Debug utilities for UI automation
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)


class UIDebugger:
    """Handles UI debugging functionality"""
    
    def __init__(self, league_window):
        self.league_window = league_window
    
    def debug_mouse_hover(self, x: int, y: int):
        """Debug information about element at mouse position"""
        try:
            element = self.league_window.from_point(x, y)
            if element:
                log.info("=" * 80)
                log.info(f"🖱️  MOUSE HOVER DEBUG at ({x}, {y})")
                log.info("=" * 80)
                
                # Basic properties
                log.info(f"Control Type: {element.control_type()}")
                log.info(f"Class Name: {element.class_name()}")
                log.info(f"Text: '{element.window_text()}'")
                log.info(f"Automation ID: '{element.automation_id()}'")
                
                # Rectangle
                try:
                    rect = element.rectangle()
                    log.info(f"Rectangle: ({rect.left}, {rect.top}, {rect.right}, {rect.bottom})")
                    log.info(f"Size: {rect.width()}x{rect.height()}")
                except Exception as e:
                    log.info(f"Rectangle: Error - {e}")
                
                # Parent info
                try:
                    parent = element.parent()
                    if parent:
                        log.info(f"Parent Type: {parent.control_type()}")
                        log.info(f"Parent Text: '{parent.window_text()}'")
                    else:
                        log.info("Parent: None")
                except Exception as e:
                    log.info(f"Parent: Error - {e}")
                
                log.info("=" * 80)
            else:
                log.info(f"🖱️  MOUSE HOVER DEBUG at ({x}, {y}): No element found")
                
        except Exception as e:
            log.info(f"🖱️  MOUSE HOVER DEBUG at ({x}, {y}): Error - {e}")
