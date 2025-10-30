#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RandomFlag - UI component for showing random skin indicator
Shows random flag overlay when randomization is active
"""

from PyQt6.QtWidgets import QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from ui.chroma_base import ChromaWidgetBase
from ui.chroma_scaling import get_scaled_chroma_values
from ui.z_order_manager import ZOrderManager
from utils.logging import get_logger

log = get_logger()


class RandomFlag(ChromaWidgetBase):
    """UI component showing random flag indicator"""
    
    # Signals for thread-safe operations
    fade_in_requested = pyqtSignal()
    fade_out_requested = pyqtSignal()
    
    def __init__(self, state=None):
        # Initialize with explicit z-level
        super().__init__(
            z_level=ZOrderManager.Z_LEVELS['RANDOM_FLAG'],
            widget_name='random_flag'
        )
        
        # Store reference to shared state
        self.state = state
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        # Get scaled values
        self.scaled = get_scaled_chroma_values()
        
        # Track resolution for change detection
        self._current_resolution = None
        self._updating_resolution = False
        
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
        
        # Flag state
        self.is_visible = False
        
        # Connect signals for thread-safe operations
        self.fade_in_requested.connect(self._do_fade_in)
        self.fade_out_requested.connect(self._do_fade_out)
        
        # Start hidden
        self.opacity_effect.setOpacity(0.0)
        self.hide()
    
    def _create_components(self):
        """Create the random flag component with static positioning"""
        # Clear existing components if they exist (for rebuilds)
        if hasattr(self, 'flag_image') and self.flag_image:
            self.flag_image.deleteLater()
            self.flag_image = None
        
        # Get League window for static positioning
        from utils.window_utils import get_league_window_handle, find_league_window_rect
        import ctypes
        
        # Get League window handle and size
        league_hwnd = get_league_window_handle()
        window_rect = find_league_window_rect()
        if not league_hwnd or not window_rect:
            log.debug("[RandomFlag] Could not get League window for static positioning")
            return
        
        window_left, window_top, window_right, window_bottom = window_rect
        window_width = window_right - window_left
        window_height = window_bottom - window_top
        
        # Load the flag image to get its dimensions
        try:
            from utils.paths import get_asset_path
            flag_pixmap = QPixmap(str(get_asset_path('random_flag.png')))
            if flag_pixmap.isNull():
                log.warning("[RandomFlag] Failed to load random_flag.png")
                return
            
            # Hardcoded positions and sizes for each resolution
            if window_width == 1600 and window_height == 900:
                # 1600x900 resolution
                flag_size = 36
                target_x = 800 - (flag_size // 2)
                target_y = 723 - (flag_size // 2)
            elif window_width == 1024 and window_height == 576:
                # 1024x576 resolution
                flag_size = 24
                target_x = 512 - (flag_size // 2)
                target_y = 463 - (flag_size // 2)
            else:
                # Fallback for other resolutions (use 1280x720 values)
                flag_size = 26
                target_x = 640 - (flag_size // 2)
                target_y = 578 - (flag_size // 2)
            
            # Set static size
            self.setFixedSize(flag_size, flag_size)
            
            # Force geometry update to ensure size is applied
            self.setGeometry(self.x(), self.y(), flag_size, flag_size)
            
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
            HWND_TOP = 0
            ctypes.windll.user32.SetWindowPos(
                widget_hwnd, HWND_TOP, target_x, target_y, 0, 0,
                0x0001 | 0x0004  # SWP_NOSIZE | SWP_NOZORDER
            )
            
            # Create flag image label
            self.flag_image = QLabel(self)
            self.flag_image.setGeometry(0, 0, flag_size, flag_size)
            self.flag_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.flag_image.setScaledContents(True)
            # Scale pixmap to label size for correct rendering after rebuild
            scaled = flag_pixmap.scaled(
                flag_size,
                flag_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.flag_image.setPixmap(scaled)
            
            # Store resolution for change detection
            self._current_resolution = (window_width, window_height)
            
            log.debug(f"[RandomFlag] Created at ({target_x}, {target_y}) size {flag_size}x{flag_size}")
            
        except Exception as e:
            log.error(f"[RandomFlag] Error creating components: {e}")

    def ensure_position(self):
        """Re-apply absolute positioning after parenting/show to avoid (0,0) jumps."""
        try:
            from utils.window_utils import get_league_window_handle, find_league_window_rect
            import ctypes
            league_hwnd = get_league_window_handle()
            window_rect = find_league_window_rect()
            if not league_hwnd or not window_rect:
                return
            window_left, window_top, window_right, window_bottom = window_rect
            window_width = window_right - window_left
            window_height = window_bottom - window_top
            if window_width == 1600 and window_height == 900:
                flag_size = 36
                target_x = 800 - (flag_size // 2)
                target_y = 723 - (flag_size // 2)
            elif window_width == 1024 and window_height == 576:
                flag_size = 24
                target_x = 512 - (flag_size // 2)
                target_y = 463 - (flag_size // 2)
            else:
                flag_size = 26
                target_x = 640 - (flag_size // 2)
                target_y = 578 - (flag_size // 2)
            widget_hwnd = int(self.winId())
            HWND_TOP = 0
            ctypes.windll.user32.SetWindowPos(
                widget_hwnd, HWND_TOP, target_x, target_y, 0, 0,
                0x0001 | 0x0004  # SWP_NOSIZE | SWP_NOZORDER
            )
        except Exception as e:
            log.debug(f"[RandomFlag] ensure_position error: {e}")
    
    def show_flag(self):
        """Show the random flag with fade in"""
        if not self.is_visible:
            self.is_visible = True
            self.show()
            # Ensure proper z-order after showing (with delay to ensure widget is fully shown)
            from PyQt6.QtCore import QTimer
            def delayed_zorder_refresh():
                log.debug("[RandomFlag] Applying delayed z-order refresh after show")
                self.refresh_z_order()
                # Don't call bring_to_front() here - it brings the widget to absolute top, breaking hierarchy
                # The z-order manager already handles RandomFlag(250) appearing above ChromaButton(200)
            QTimer.singleShot(50, delayed_zorder_refresh)
            self.fade_in_requested.emit()
    
    def hide_flag(self):
        """Hide the random flag instantly (no fade)"""
        if self.is_visible:
            self.is_visible = False
            # Stop any ongoing fade animation
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
            # Set opacity to 0 instantly and hide
            self.opacity_effect.setOpacity(0.0)
            self.hide()
    
    def _do_fade_in(self):
        """Fade in animation (reused from UnownedFrame)"""
        if self.fade_timer:
            self.fade_timer.stop()
        
        self.fade_target_opacity = 1.0
        self.fade_start_opacity = self.opacity_effect.opacity()
        self.fade_steps = 20  # 20 steps for smooth animation
        self.fade_current_step = 0
        
        self.fade_timer = QTimer()
        self.fade_timer.timeout.connect(self._fade_step)
        self.fade_timer.start(16)  # ~60 FPS
    
    def _do_fade_out(self):
        """Fade out animation (reused from UnownedFrame)"""
        if self.fade_timer:
            self.fade_timer.stop()
        
        self.fade_target_opacity = 0.0
        self.fade_start_opacity = self.opacity_effect.opacity()
        self.fade_steps = 20  # 20 steps for smooth animation
        self.fade_current_step = 0
        
        self.fade_timer = QTimer()
        self.fade_timer.timeout.connect(self._fade_step)
        self.fade_timer.start(16)  # ~60 FPS
    
    def _fade_step(self):
        """Single step of fade animation"""
        if self.fade_current_step >= self.fade_steps:
            self.fade_timer.stop()
            self.fade_timer = None
            
            # Hide widget when fade out is complete
            if self.fade_target_opacity == 0.0:
                self.hide()
            
            return
        
        # Calculate current opacity
        progress = self.fade_current_step / self.fade_steps
        current_opacity = self.fade_start_opacity + (self.fade_target_opacity - self.fade_start_opacity) * progress
        
        self.opacity_effect.setOpacity(current_opacity)
        self.fade_current_step += 1
    
    def check_resolution_and_update(self):
        """Check for resolution changes and update positioning"""
        try:
            from utils.window_utils import find_league_window_rect
            window_rect = find_league_window_rect()
            
            if not window_rect:
                return
            
            window_left, window_top, window_right, window_bottom = window_rect
            current_resolution = (window_right - window_left, window_bottom - window_top)
            
            if self._current_resolution != current_resolution:
                log.info(f"[RandomFlag] Resolution changed from {self._current_resolution} to {current_resolution}, recreating")
                self._create_components()
                
        except Exception as e:
            log.error(f"[RandomFlag] Error checking resolution: {e}")
    
    def cleanup(self):
        """Clean up the random flag"""
        try:
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
            
            # Properly destroy the PyQt6 widget
            self.hide()
            self.deleteLater()
            log.debug("[RandomFlag] Cleaned up and scheduled for deletion")
        except Exception as e:
            log.debug(f"[RandomFlag] Error during cleanup: {e}")
