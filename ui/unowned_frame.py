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
        
        # Start invisible
        self.opacity_effect.setOpacity(0.0)
        self.hide()
    
    def _create_components(self):
        """Create the merged unowned frame component with static positioning"""
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
        
        # Set static size
        self.setFixedSize(frame_width, frame_height)
        
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
        # Set z-order to 0 (behind other windows) - UnownedFrame should be behind chroma button
        ctypes.windll.user32.SetWindowPos(
            widget_hwnd, 0, target_x, target_y, 0, 0,
            0x0010 | 0x0001  # SWP_NOACTIVATE | SWP_NOSIZE
        )
        
        log.debug(f"[UnownedFrame] Static positioning: window={window_width}x{window_height}, position=({target_x}, {target_y}), size={frame_width}x{frame_height}")
        
        # Create unowned frame image
        self.unowned_frame_image = QLabel(self)
        self.unowned_frame_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Load unowned frame image
        try:
            unowned_pixmap = QPixmap("assets/unownedframe.png")
            if not unowned_pixmap.isNull():
                # Scale the image to fit the calculated frame size
                scaled_pixmap = unowned_pixmap.scaled(
                    frame_width, frame_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.unowned_frame_image.setPixmap(scaled_pixmap)
                log.debug(f"[UnownedFrame] Unowned frame loaded, size: {scaled_pixmap.width()}x{scaled_pixmap.height()}")
            else:
                log.warning("[UnownedFrame] Failed to load unownedframe.png image")
        except Exception as e:
            log.error(f"[UnownedFrame] Error loading unowned frame: {e}")
        
        # Position unowned frame to fill the entire widget
        self.unowned_frame_image.move(0, 0)
        self.unowned_frame_image.resize(frame_width, frame_height)
        
        log.info("[UnownedFrame] Unowned frame component created successfully")
    
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
            
            self.fade_current_step += 1
            
        except RuntimeError:
            # Widget may have been deleted
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
    
    
    
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
