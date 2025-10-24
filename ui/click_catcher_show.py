#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ClickCatcherShow - UI component for detecting clicks and showing UI elements
Inherits from ClickCatcher and implements show action when click is detected

Usage:
    # Create instance
    click_catcher = ClickCatcherShow(state=state, x=100, y=100, width=50, height=50)
    
    # Connect click detection signal
    click_catcher.click_detected.connect(on_click_handler)
    
    # Show at specific position (e.g., over show button)
    click_catcher.show_catcher()
    
    # Hide when no longer needed
    click_catcher.hide_catcher()

Features:
    - Inherits from ClickCatcher base class
    - Implements show action when click is detected
    - Invisible overlay that doesn't block clicks to League window
    - Positioned using absolute coordinates in League window
    - Automatically handles resolution changes and League window parenting
    - Integrates with z-order management system
"""

from ui.click_catcher import ClickCatcher
from utils.logging import get_logger
import time

log = get_logger()


class ClickCatcherShow(ClickCatcher):
    """
    Click catcher that detects clicks and triggers UI showing action
    Used to trigger UI visibility when show button is pressed
    """
    
    def __init__(self, state=None, x=0, y=0, width=50, height=50, shape='circle', catcher_name=None):
        # Initialize with specific widget name for show functionality
        super().__init__(
            state=state,
            x=x,
            y=y,
            width=width,
            height=height,
            shape=shape,
            catcher_name=catcher_name,
            widget_name='click_catcher_show'
        )
        
        # Connect the click detection signal to our show action
        log.info(f"[ClickCatcherShow] Connecting click_detected signal to on_click_detected method")
        self.click_detected.connect(self.on_click_detected)
        log.info(f"[ClickCatcherShow] Signal connection established successfully")
        
        log.debug(f"[ClickCatcherShow] Show click catcher created at ({self.catcher_x}, {self.catcher_y}) size {self.catcher_width}x{self.catcher_height}")
    
    def on_click_detected(self):
        """
        Called when a click is detected in the click catcher area
        Triggers the show UI action and destroys all show instances
        """
        try:
            # Determine delay based on catcher name
            if self.catcher_name == 'CLOSE_SUM':
                delay_ms = 260
                log.info("[ClickCatcherShow] Click detected - waiting 260ms before triggering show UI action (CLOSE_SUM)")
            else:
                delay_ms = 100
                log.info("[ClickCatcherShow] Click detected - waiting 100ms before triggering show UI action")
            
            # Wait before asking UI to show elements
            time.sleep(delay_ms / 1000.0)  # Convert ms to seconds
            
            # Trigger the show UI action through the shared state
            if self.state and hasattr(self.state, 'ui') and self.state.ui:
                self.state.ui._show_all_ui_elements()
                log.info("[ClickCatcherShow] ✓ UI elements shown successfully")
            else:
                log.warning("[ClickCatcherShow] No UI state available to show elements")
                
        except Exception as e:
            log.error(f"[ClickCatcherShow] Error in show action: {e}")
            import traceback
            log.error(f"[ClickCatcherShow] Traceback: {traceback.format_exc()}")
    


def test_mouse_monitoring():
    """Test function to verify mouse monitoring is working"""
    log.info("[ClickCatcherShow] Testing mouse monitoring functionality...")
    
    # Create a test click catcher
    test_catcher = ClickCatcherShow(x=100, y=100, width=50, height=50, shape='rectangle')
    
    def test_click_handler():
        log.info("[ClickCatcherShow] ✓ Test click detected!")
    
    test_catcher.click_detected.connect(test_click_handler)
    
    log.info("[ClickCatcherShow] Test click catcher created at (100, 100). Click in that area to test.")
    
    return test_catcher
