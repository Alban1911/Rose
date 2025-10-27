#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Click Blocker - Invisible widget to prevent clicks during skin detection
Positioned at the same location as the Chroma Opening Button
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor, QPixmap
from ui.chroma_base import ChromaWidgetBase
from ui.z_order_manager import ZOrderManager
from utils.logging import get_logger

log = get_logger()


class ClickBlocker(ChromaWidgetBase):
    """Invisible widget to block clicks at the Chroma Button location during skin detection"""
    
    def __init__(self, state=None):
        # Initialize with explicit z-level (above ChromaButton to block clicks)
        super().__init__(
            z_level=500,  # Very high z-level to ensure it's on top of everything
            widget_name='click_blocker'
        )
        
        self.state = state  # Store state reference
        
        # Get current resolution for hardcoded sizing
        from utils.window_utils import get_league_window_client_size
        current_resolution = get_league_window_client_size()
        if not current_resolution:
            current_resolution = (1600, 900)  # Fallback to reference resolution
        
        self._current_resolution = current_resolution
        
        # Use the same sizes as Chroma Opening Button
        window_width, window_height = current_resolution
        if window_width == 1600 and window_height == 900:
            # 1600x900 resolution
            self.button_visual_size = 40  # Visual size (same as OpeningButton)
        elif window_width == 1280 and window_height == 720:
            # 1280x720 resolution
            self.button_visual_size = 30  # Visual size (same as OpeningButton)
        elif window_width == 1024 and window_height == 576:
            # 1024x576 resolution
            self.button_visual_size = 28  # Visual size (same as OpeningButton)
        else:
            # Unsupported resolution - use default 1600x900 values
            log.warning(f"[CLICK_BLOCKER] Unsupported resolution {window_width}x{window_height}, using 1600x900 defaults")
            self.button_visual_size = 40
        
        # Add extra space for the 3px transparent ring on each side (same as OpeningButton)
        self.transparent_ring_width = 3
        self.button_size = self.button_visual_size + (self.transparent_ring_width * 2)
        self.setFixedSize(self.button_size, self.button_size)
        
        # Position at the same location as Chroma Opening Button
        # Check if we're in Swiftplay mode for different positioning
        is_swiftplay = False
        if self.state:
            is_swiftplay = self.state.is_swiftplay_mode
        
        window_width, window_height = current_resolution
        if is_swiftplay:
            # Swiftplay mode - different button positions (same as OpeningButton)
            if window_width == 1600 and window_height == 900:
                button_x = 1041
                button_y = 743
            elif window_width == 1280 and window_height == 720:
                button_x = 833
                button_y = 596
            elif window_width == 1024 and window_height == 576:
                button_x = 664
                button_y = 473
            else:
                # Fallback to 1280*720 Swiftplay values
                button_x = 831
                button_y = 593
        else:
            # Regular mode - Button should be at center X, 80.35% down from top (same as OpeningButton)
            if window_width == 1600 and window_height == 900:
                button_x = 800 - (self.button_size // 2)
                button_y = 723 - (self.button_size // 2)
            elif window_width == 1280 and window_height == 720:
                button_x = 640 - (self.button_size // 2)
                button_y = 578 - (self.button_size // 2)
            elif window_width == 1024 and window_height == 576:
                button_x = 512 - (self.button_size // 2)
                button_y = 463 - (self.button_size // 2)
            else:
                # Unsupported resolution - use default 1600x900 values
                button_x = 800 - (self.button_size // 2)
                button_y = 723 - (self.button_size // 2)
        
        # Position widget absolutely in League window
        self._position_blocker_absolutely(button_x, button_y)
        
        # Load the empty image
        self.load_empty_image()
        
        # Hide by default
        self.hide()
    
    def _position_blocker_absolutely(self, x: int, y: int):
        """Position blocker directly in League window using absolute coordinates"""
        try:
            # Parent the widget to League window
            self._parent_to_league_window()
            
            # Get widget handle
            widget_hwnd = int(self.winId())
            
            # Position it statically in League window client coordinates
            import ctypes
            HWND_TOP = 0
            ctypes.windll.user32.SetWindowPos(
                widget_hwnd, HWND_TOP, x, y, 0, 0,
                0x0010 | 0x0001  # SWP_NOACTIVATE | SWP_NOSIZE
            )
            
            log.debug(f"[CLICK_BLOCKER] Blocker positioned absolutely at ({x}, {y})")
            
        except Exception as e:
            log.error(f"[CLICK_BLOCKER] Error positioning blocker: {e}")
            import traceback
            log.error(traceback.format_exc())
    
    def load_empty_image(self):
        """Load the empty.png image"""
        try:
            from utils.paths import get_asset_path
            empty_image_path = get_asset_path("empty.png")
            self.empty_pixmap = QPixmap(str(empty_image_path))
            if self.empty_pixmap.isNull():
                log.warning("[CLICK_BLOCKER] Failed to load empty.png")
                self.empty_pixmap = QPixmap(self.button_size, self.button_size)
                self.empty_pixmap.fill(QColor(0, 0, 0, 0))  # Transparent fallback
            else:
                log.debug(f"[CLICK_BLOCKER] Loaded empty.png: {self.empty_pixmap.width()}x{self.empty_pixmap.height()}")
        except Exception as e:
            log.error(f"[CLICK_BLOCKER] Error loading empty.png: {e}")
            self.empty_pixmap = QPixmap(self.button_size, self.button_size)
            self.empty_pixmap.fill(QColor(0, 0, 0, 0))
    
    def paintEvent(self, event):
        """Paint the empty image"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw the empty image to fill the button area
        if hasattr(self, 'empty_pixmap') and not self.empty_pixmap.isNull():
            # Scale the image to fit the button size if needed
            if self.empty_pixmap.width() != self.button_size or self.empty_pixmap.height() != self.button_size:
                scaled_pixmap = self.empty_pixmap.scaled(
                    self.button_size, self.button_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                painter.drawPixmap(0, 0, scaled_pixmap)
            else:
                painter.drawPixmap(0, 0, self.empty_pixmap)
        
        # Fill with minimal transparent area to ensure mouse events are captured
        # Even if the image is transparent, we need something to receive mouse events
        painter.fillRect(0, 0, self.button_size, self.button_size, QColor(255, 255, 255, 1))  # 1 alpha = almost invisible but captures events
    
    def mousePressEvent(self, event):
        """Consume mouse events to block clicks"""
        log.debug("[CLICK_BLOCKER] Mouse press event intercepted")
        event.accept()  # Mark event as handled
    
    def mouseReleaseEvent(self, event):
        """Consume mouse events to block clicks"""
        log.debug("[CLICK_BLOCKER] Mouse release event intercepted")
        event.accept()  # Mark event as handled
    
    def show_instantly(self):
        """Show the blocker instantly"""
        try:
            # Ensure League window is available before positioning
            if not hasattr(self, '_league_window_hwnd') or not self._league_window_hwnd:
                log.warning("[CLICK_BLOCKER] League window not available, attempting to parent blocker")
                self._parent_to_league_window()
            
            # Wait a moment for League window to be ready if we just parented
            if not hasattr(self, '_league_window_hwnd') or not self._league_window_hwnd:
                log.warning("[CLICK_BLOCKER] League window still not available, delaying blocker show")
                # Schedule a retry in 100ms
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, self.show_instantly)
                return
            
            log.info(f"[CLICK_BLOCKER] Blocker position before show: ({self.x()}, {self.y()}) size: {self.width()}x{self.height()}")
            log.info(f"[CLICK_BLOCKER] Calling self.show()")
            
            self.show()
            
            # Ensure the widget is raised to the top
            self.raise_()
            
            # Refresh z-order after showing
            try:
                from ui.z_order_manager import get_z_order_manager
                z_manager = get_z_order_manager()
                z_manager.refresh_z_order(force=True)
            except Exception:
                pass
            
            log.info(f"[CLICK_BLOCKER] Blocker shown at ({self.x()}, {self.y()}) size: {self.width()}x{self.height()}, visible: {self.isVisible()}")
        except RuntimeError:
            pass
    
    def hide_instantly(self):
        """Hide the blocker instantly"""
        try:
            self.hide()
            log.debug("[CLICK_BLOCKER] Blocker hidden")
        except RuntimeError:
            pass
    
    def cleanup(self):
        """Clean up the blocker widget"""
        try:
            log.debug("[CLICK_BLOCKER] Starting cleanup")
            self.hide_instantly()
            
            # Un-parent from League window before destroying
            if hasattr(self, '_league_window_hwnd') and self._league_window_hwnd:
                import ctypes
                widget_hwnd = int(self.winId())
                ctypes.windll.user32.SetParent(widget_hwnd, 0)  # Un-parent
                self._league_window_hwnd = None
                log.debug("[CLICK_BLOCKER] Blocker un-parented from League window")
            
            log.debug("[CLICK_BLOCKER] Cleanup completed")
        except Exception as e:
            log.error(f"[CLICK_BLOCKER] Error during cleanup: {e}")

