#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ClickCatcherHide - UI component for detecting clicks and hiding UI elements
Inherits from ClickCatcher and implements hide action when click is detected

Usage:
    # Create instance
    click_catcher = ClickCatcherHide(state=state, x=100, y=100, width=50, height=50)
    
    # Connect click detection signal
    click_catcher.click_detected.connect(on_click_handler)
    
    # Show at specific position (e.g., over settings button)
    click_catcher.show_catcher()
    
    # Hide when no longer needed
    click_catcher.hide_catcher()

Features:
    - Inherits from ClickCatcher base class
    - Implements hide action when click is detected
    - Invisible overlay that doesn't block clicks to League window
    - Positioned using absolute coordinates in League window
    - Automatically handles resolution changes and League window parenting
    - Integrates with z-order management system
"""

from ui.click_catcher import ClickCatcher
from utils.logging import get_logger

log = get_logger()


class ClickCatcherHide(ClickCatcher):
    """
    Click catcher that detects clicks and triggers UI hiding action
    Used to trigger UI opacity changes when settings button is pressed
    """
    
    def __init__(self, state=None, x=0, y=0, width=50, height=50, shape='circle', catcher_name=None):
        # Initialize with specific widget name for hide functionality
        super().__init__(
            state=state,
            x=x,
            y=y,
            width=width,
            height=height,
            shape=shape,
            catcher_name=catcher_name,
            widget_name='click_catcher_hide'
        )
        
        # Connect the click detection signal to our hide action
        self.click_detected.connect(self.on_click_detected)
        
        log.debug(f"[ClickCatcherHide] Hide click catcher created at ({self.catcher_x}, {self.catcher_y}) size {self.catcher_width}x{self.catcher_height}")
    
    def on_click_detected(self):
        """
        Called when a click is detected in the click catcher area
        Triggers the hide UI action
        """
        try:
            log.info("[ClickCatcherHide] Click detected - triggering hide UI action")
            
            # Trigger the hide UI action through the shared state
            if self.state and hasattr(self.state, 'ui') and self.state.ui:
                self.state.ui._hide_all_ui_elements()
                log.info("[ClickCatcherHide] ✓ UI elements hidden successfully")
            else:
                log.warning("[ClickCatcherHide] No UI state available to hide elements")
                
        except Exception as e:
            log.error(f"[ClickCatcherHide] Error in hide action: {e}")
            import traceback
            log.error(f"[ClickCatcherHide] Traceback: {traceback.format_exc()}")


def test_mouse_monitoring():
    """Test function to verify mouse monitoring is working"""
    log.info("[ClickCatcherHide] Testing mouse monitoring functionality...")
    
    # Create a test click catcher
    test_catcher = ClickCatcherHide(x=100, y=100, width=50, height=50, shape='rectangle')
    
    def test_click_handler():
        log.info("[ClickCatcherHide] ✓ Test click detected!")
    
    test_catcher.click_detected.connect(test_click_handler)
    
    log.info("[ClickCatcherHide] Test click catcher created at (100, 100). Click in that area to test.")
    
    return test_catcher