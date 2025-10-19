#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UnownedFrame - UI component for showing unowned skin indicator
Shows golden border and lock icon for unowned skins
"""

from PyQt6.QtWidgets import QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QPixmap
from ui.chroma_base import ChromaWidgetBase
from ui.chroma_scaling import get_scaled_chroma_values
from utils.logging import get_logger
import config

log = get_logger()


class UnownedFrame(ChromaWidgetBase):
    """UI component showing golden border and lock for unowned skins"""
    
    # Signals for thread-safe operations
    fade_in_requested = pyqtSignal()
    fade_out_requested = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        # Get scaled values
        self.scaled = get_scaled_chroma_values()
        
        # Track resolution for change detection
        self._current_resolution = None
        self._updating_resolution = False  # Flag to prevent recursive updates
        
        # Create opacity effect for fade animations
        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)
        
        # Create UI components
        self._create_components()
        
        # Fade animation state
        self.fade_timer = None
        self.fade_target_opacity = 0.0
        self.fade_start_opacity = 0.0
        self.fade_steps = 0
        self.fade_current_step = 0
        
        # Connect signals for thread-safe operations
        self.fade_in_requested.connect(self._do_fade_in)
        self.fade_out_requested.connect(self._do_fade_out)
        
        # Start visible but transparent (opacity 0)
        self.opacity_effect.setOpacity(0.0)
        self.show()
    
    def _create_components(self):
        """Create the merged unowned frame component with static positioning"""
        # Clear existing components if they exist (for rebuilds)
        if hasattr(self, 'unowned_frame_image') and self.unowned_frame_image:
            self.unowned_frame_image.deleteLater()
            self.unowned_frame_image = None
        
        # Get League window for static positioning
        from utils.window_utils import get_league_window_handle, find_league_window_rect
        import ctypes
        
        # Get League window handle and size
        league_hwnd = get_league_window_handle()
        window_rect = find_league_window_rect()
        if not league_hwnd or not window_rect:
            log.debug("[UnownedFrame] Could not get League window for static positioning")
            return
        
        window_left, window_top, window_right, window_bottom = window_rect
        window_width = window_right - window_left
        window_height = window_bottom - window_top
        
        # Calculate static size and position using config ratios
        frame_width = int(window_width * config.UNOWNED_FRAME_WIDTH_RATIO)
        frame_height = int(window_height * config.UNOWNED_FRAME_HEIGHT_RATIO)
        
        log.debug(f"[UnownedFrame] New size calculation: window={window_width}x{window_height}, frame={frame_width}x{frame_height}")
        
        # Set static size
        self.setFixedSize(frame_width, frame_height)
        
        # Force geometry update to ensure size is applied
        self.setGeometry(self.x(), self.y(), frame_width, frame_height)
        
        # Calculate static position relative to League window TOP-LEFT (0,0)
        # Use ratio-based coordinates that scale with window size
        target_x = int(window_width * config.UNOWNED_FRAME_ANCHOR_OFFSET_X_RATIO)
        target_y = int(window_height * config.UNOWNED_FRAME_ANCHOR_OFFSET_Y_RATIO)
        
        # Make this widget a child of League window (static embedding)
        widget_hwnd = int(self.winId())
        ctypes.windll.user32.SetParent(widget_hwnd, league_hwnd)
        
        # For child windows, use client coordinates directly
        # But first, make sure the window style is WS_CHILD
        GWL_STYLE = -16
        WS_CHILD = 0x40000000
        WS_POPUP = 0x80000000
        
        # Set window style to WS_CHILD (64-bit compatible)
        if ctypes.sizeof(ctypes.c_void_p) == 8:  # 64-bit
            # Use SetWindowLongPtrW for 64-bit
            SetWindowLongPtr = ctypes.windll.user32.SetWindowLongPtrW
            SetWindowLongPtr.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
            SetWindowLongPtr.restype = ctypes.c_longlong
            GetWindowLongPtr = ctypes.windll.user32.GetWindowLongPtrW
            GetWindowLongPtr.argtypes = [ctypes.c_void_p, ctypes.c_int]
            GetWindowLongPtr.restype = ctypes.c_longlong
            
            current_style = GetWindowLongPtr(widget_hwnd, GWL_STYLE)
            new_style = (current_style & ~WS_POPUP) | WS_CHILD
            SetWindowLongPtr(widget_hwnd, GWL_STYLE, new_style)
        else:
            # Use SetWindowLongW for 32-bit
            current_style = ctypes.windll.user32.GetWindowLongW(widget_hwnd, GWL_STYLE)
            new_style = (current_style & ~WS_POPUP) | WS_CHILD
            ctypes.windll.user32.SetWindowLongW(widget_hwnd, GWL_STYLE, new_style)
        
        # Position it statically in League window client coordinates
        # Use HWND_TOP to place it in front of League window, but it will be behind chroma button
        # because chroma button is created after this and uses HWND_TOP as well
        HWND_TOP = 0
        ctypes.windll.user32.SetWindowPos(
            widget_hwnd, HWND_TOP, target_x, target_y, 0, 0,
            0x0010 | 0x0001  # SWP_NOACTIVATE | SWP_NOSIZE
        )
        
        log.debug(f"[UnownedFrame] Static positioning: window={window_width}x{window_height}, position=({target_x}, {target_y}), size={frame_width}x{frame_height}")
        
        # Create unowned frame image
        self.unowned_frame_image = QLabel(self)
        self.unowned_frame_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Load unowned frame image
        try:
            # Clear any existing pixmap first
            self.unowned_frame_image.clear()
            
            log.debug(f"[UnownedFrame] Loading image from: assets/unownedframe.png")
            unowned_pixmap = QPixmap("assets/unownedframe.png")
            log.debug(f"[UnownedFrame] Image loaded: null={unowned_pixmap.isNull()}, size={unowned_pixmap.width()}x{unowned_pixmap.height()}")
            
            if not unowned_pixmap.isNull():
                # Scale the image to fit the calculated frame size
                scaled_pixmap = unowned_pixmap.scaled(
                    frame_width, frame_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # Set the scaled pixmap
                self.unowned_frame_image.setPixmap(scaled_pixmap)
                
                # Force the QLabel to update its display
                self.unowned_frame_image.update()
                
                # Debug: Check if QLabel has pixmap and is visible
                has_pixmap = not self.unowned_frame_image.pixmap().isNull()
                log.debug(f"[UnownedFrame] QLabel pixmap: has_pixmap={has_pixmap}, visible={self.unowned_frame_image.isVisible()}, size={self.unowned_frame_image.size().width()}x{self.unowned_frame_image.size().height()}")
                
                log.info(f"[UnownedFrame] Image scaled: original={unowned_pixmap.width()}x{unowned_pixmap.height()}, scaled={scaled_pixmap.width()}x{scaled_pixmap.height()}, target={frame_width}x{frame_height}")
            else:
                log.error("[UnownedFrame] Failed to load unownedframe.png image - pixmap is null")
        except Exception as e:
            log.error(f"[UnownedFrame] Error loading unowned frame: {e}")
            import traceback
            log.error(traceback.format_exc())
        
        # Position unowned frame to fill the entire widget
        self.unowned_frame_image.move(0, 0)
        self.unowned_frame_image.resize(frame_width, frame_height)
        
        # Force QLabel to update its display after resizing
        self.unowned_frame_image.update()
        self.unowned_frame_image.repaint()
        
        log.debug(f"[UnownedFrame] QLabel resized to: {frame_width}x{frame_height}")
        
        log.info("[UnownedFrame] Unowned frame component created successfully")
        
        # Ensure UnownedFrame stays behind other UI elements
        self.ensure_behind_other_ui()
        
        # Make sure it's visible (but transparent)
        self.show()
    
    def ensure_behind_other_ui(self):
        """Ensure UnownedFrame stays behind other UI elements but in front of League window"""
        try:
            import ctypes
            widget_hwnd = int(self.winId())
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            
            # Use HWND_TOP to keep in front of League window
            # The chroma button will naturally appear on top since it's created after
            HWND_TOP = 0
            ctypes.windll.user32.SetWindowPos(
                widget_hwnd,
                HWND_TOP,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            )
            log.debug("[UnownedFrame] Forced to top of z-order (behind chroma button due to creation order)")
        except Exception as e:
            log.debug(f"[UnownedFrame] Error ensuring z-order: {e}")
    
    def fade_in(self):
        """Fade in the UnownedFrame (thread-safe)"""
        try:
            log.info("[UnownedFrame] Requesting fade in")
            self.fade_in_requested.emit()
        except Exception as e:
            log.error(f"[UnownedFrame] Error requesting fade in: {e}")
    
    def fade_out(self):
        """Fade out the UnownedFrame (thread-safe)"""
        try:
            log.info("[UnownedFrame] Requesting fade out")
            self.fade_out_requested.emit()
        except Exception as e:
            log.error(f"[UnownedFrame] Error requesting fade out: {e}")
    
    @pyqtSlot()
    def _do_fade_in(self):
        """Actually perform fade in (called in main thread)"""
        try:
            log.info("[UnownedFrame] Fading in")
            self._start_fade(1.0, config.CHROMA_FADE_IN_DURATION_MS)
            self.show()
            
            # Debug: Check if widget is visible and positioned correctly
            log.debug(f"[UnownedFrame] After show - visible: {self.isVisible()}, size: {self.size().width()}x{self.size().height()}, pos: ({self.x()}, {self.y()})")
            
            # Ensure z-order is maintained after showing
            self.ensure_behind_other_ui()
            
            # Debug: Check again after z-order adjustment
            log.debug(f"[UnownedFrame] After z-order - visible: {self.isVisible()}, size: {self.size().width()}x{self.size().height()}, pos: ({self.x()}, {self.y()})")
        except Exception as e:
            log.error(f"[UnownedFrame] Error fading in: {e}")
    
    @pyqtSlot()
    def _do_fade_out(self):
        """Actually perform fade out (called in main thread)"""
        try:
            log.info("[UnownedFrame] Fading out")
            self._start_fade(0.0, config.CHROMA_FADE_OUT_DURATION_MS)
        except Exception as e:
            log.error(f"[UnownedFrame] Error fading out: {e}")
    
    def _start_fade(self, target_opacity: float, duration_ms: int):
        """Start fade animation to target opacity over duration_ms"""
        try:
            # Stop any existing fade animation
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
            
            # Setup fade animation
            self.fade_start_opacity = self.opacity_effect.opacity()
            self.fade_target_opacity = target_opacity
            self.fade_current_step = 0
            
            # Calculate steps (60 FPS = ~16.67ms per frame)
            frame_interval_ms = 16  # ~60 FPS
            self.fade_steps = max(1, duration_ms // frame_interval_ms)
            
            log.debug(f"[UnownedFrame] Starting fade: {self.fade_start_opacity:.2f} → {target_opacity:.2f} over {duration_ms}ms ({self.fade_steps} steps)")
            
            # Create timer for animation
            self.fade_timer = QTimer(self)
            self.fade_timer.timeout.connect(self._fade_step)
            self.fade_timer.start(frame_interval_ms)
            
        except RuntimeError:
            # Widget may have been deleted
            pass
    
    def _fade_step(self):
        """Execute one step of the fade animation"""
        try:
            if self.fade_current_step >= self.fade_steps:
                # Animation complete
                self.fade_timer.stop()
                self.fade_timer = None
                self.opacity_effect.setOpacity(self.fade_target_opacity)
                
                # Hide if fully transparent
                if self.fade_target_opacity <= 0.0:
                    self.hide()
                else:
                    # Ensure z-order is maintained after fade completion
                    self.ensure_behind_other_ui()
                
                log.debug(f"[UnownedFrame] Fade complete: opacity={self.fade_target_opacity:.2f}")
                return
            
            # Calculate current opacity (exponential easing)
            progress = self.fade_current_step / self.fade_steps
            if self.fade_target_opacity > self.fade_start_opacity:
                # Fade in: exponential ease-in
                eased_progress = progress * progress
            else:
                # Fade out: exponential ease-out
                eased_progress = 1.0 - (1.0 - progress) * (1.0 - progress)
            
            current_opacity = self.fade_start_opacity + (self.fade_target_opacity - self.fade_start_opacity) * eased_progress
            self.opacity_effect.setOpacity(current_opacity)
            
            # Skip z-order adjustments during fade to prevent flickering
            # The z-order is set once at the beginning and should remain stable
            
            self.fade_current_step += 1
            
        except RuntimeError:
            # Widget may have been deleted
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
    
    def check_resolution_and_update(self):
        """Check if resolution changed and request rebuild if needed"""
        # Prevent recursive calls
        if self._updating_resolution:
            return
        
        try:
            # Get current League resolution directly (bypass cache)
            from utils.window_utils import get_league_window_client_size
            current_resolution = get_league_window_client_size()
            
            if not current_resolution:
                return  # League window not found
            
            # Check if resolution actually changed
            if current_resolution != self._current_resolution:
                self._updating_resolution = True  # Set flag
                log.info(f"[UnownedFrame] Resolution changed from {self._current_resolution} to {current_resolution}, requesting rebuild")
                
                # Update current resolution to prevent re-detection
                self._current_resolution = current_resolution
                
                # Request rebuild
                self._rebuild_for_resolution_change()
                
                # Clear update flag
                self._updating_resolution = False
        except Exception as e:
            log.error(f"[UnownedFrame] Error checking resolution: {e}")
            import traceback
            log.error(traceback.format_exc())
            # Clear flag even on error
            self._updating_resolution = False
    
    def _rebuild_for_resolution_change(self):
        """Rebuild UnownedFrame for resolution change"""
        try:
            log.info("[UnownedFrame] Rebuilding for resolution change...")
            
            # Get fresh scaled values for new resolution
            self.scaled = get_scaled_chroma_values(force_reload=True)
            
            # Log current widget size before rebuild
            current_size = self.size()
            log.debug(f"[UnownedFrame] Current widget size before rebuild: {current_size.width()}x{current_size.height()}")
            
            # Recreate components with new resolution
            self._create_components()
            
            # Log new widget size after rebuild
            new_size = self.size()
            log.debug(f"[UnownedFrame] New widget size after rebuild: {new_size.width()}x{new_size.height()}")
            
            # Force widget update to ensure size changes are applied
            self.updateGeometry()
            self.update()
            self.repaint()
            
            # Ensure it's visible (but transparent)
            self.show()
            
            log.info("[UnownedFrame] Rebuild completed")
        except Exception as e:
            log.error(f"[UnownedFrame] Error during rebuild: {e}")
            import traceback
            log.error(traceback.format_exc())
    
    def cleanup(self):
        """Clean up resources"""
        try:
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
            self.hide()
            log.debug("[UnownedFrame] Cleaned up")
        except Exception as e:
            log.debug(f"[UnownedFrame] Error during cleanup: {e}")
