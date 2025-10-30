#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DiceButton - UI component for random skin selection
States simplified to two visuals: disabled and enabled.
Hover, pressed, and enabled all use the enabled visual.
"""

from PyQt6.QtWidgets import QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QMouseEvent
from ui.chroma_base import ChromaWidgetBase
from ui.chroma_scaling import get_scaled_chroma_values
from ui.z_order_manager import ZOrderManager
from utils.logging import get_logger

log = get_logger()


class DiceButton(ChromaWidgetBase):
    """UI component showing dice button for random skin selection"""
    
    # Signals for thread-safe operations
    fade_in_requested = pyqtSignal()
    fade_out_requested = pyqtSignal()
    dice_clicked = pyqtSignal(str)  # Emits state: 'disabled' or 'enabled'
    
    def __init__(self, state=None):
        # Initialize with explicit z-level
        super().__init__(
            z_level=ZOrderManager.Z_LEVELS['DICE_BUTTON'],
            widget_name='dice_button'
        )
        
        # Store reference to shared state
        self.state = state
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Enable mouse events for clicking
        self.setMouseTracking(True)
        
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
        
        # Button state
        self.current_state = 'disabled'  # 'disabled' or 'enabled'
        self.is_visible = False

        # Track press state to emit on release
        self._pressed_inside = False
        
        # Connect signals for thread-safe operations
        self.fade_in_requested.connect(self._do_fade_in)
        self.fade_out_requested.connect(self._do_fade_out)
        
        # Start hidden
        self.opacity_effect.setOpacity(0.0)
        self.hide()
    
    def _create_components(self):
        """Create the dice button component with static positioning"""
        # Clear existing components if they exist (for rebuilds)
        if hasattr(self, 'dice_image') and self.dice_image:
            self.dice_image.deleteLater()
            self.dice_image = None
        
        # Get League window for static positioning
        from utils.window_utils import get_league_window_handle, find_league_window_rect
        import ctypes
        
        # Get League window handle and size
        league_hwnd = get_league_window_handle()
        window_rect = find_league_window_rect()
        if not league_hwnd or not window_rect:
            log.debug("[DiceButton] Could not get League window for static positioning")
            return
        
        window_left, window_top, window_right, window_bottom = window_rect
        window_width = window_right - window_left
        window_height = window_bottom - window_top
        
        # Hardcoded positions for each resolution (no scaling)
        if window_width == 1600 and window_height == 900:
            # 1600x900 resolution (maximum)
            button_width = 46
            button_height = 27
            target_x = 800 - (button_width // 2)
            target_y = 754 - (button_height // 2)
        elif window_width == 1024 and window_height == 576:
            # 1024x576 resolution (minimum)
            button_width = 28
            button_height = 18
            target_x = 512 - (button_width // 2)
            target_y = 483 - (button_height // 2)
        else:
            # Fallback for other resolutions (use 1280x720 size)
            button_width = 38
            button_height = 23
            target_x = 640 - (button_width // 2)
            target_y = 602 - (button_height // 2)
        
        # Set static size
        self.setFixedSize(button_width, button_height)
        
        # Force geometry update to ensure size is applied
        self.setGeometry(self.x(), self.y(), button_width, button_height)
        
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
        
        # Create dice image label
        self.dice_image = QLabel(self)
        self.dice_image.setGeometry(0, 0, button_width, button_height)
        self.dice_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dice_image.setScaledContents(True)
        
        # Load initial state (disabled)
        self._load_state_image('disabled')
        
        # Store resolution for change detection
        self._current_resolution = (window_width, window_height)
        
        log.debug(f"[DiceButton] Created at ({target_x}, {target_y}) size {button_width}x{button_height}")
    
    def _load_state_image(self, state: str):
        """Load the appropriate image for the given state"""
        try:
            from utils.paths import get_asset_path
            
            # Map state to image file
            # Only two visuals remain; map any transient states to 'enabled'
            visual_state = state
            if state in ('hover', 'click'):
                visual_state = 'enabled'

            image_files = {
                'disabled': 'dice-disabled.png',
                'enabled': 'dice-enabled.png'
            }
            
            if visual_state not in image_files:
                log.warning(f"[DiceButton] Unknown state: {state}")
                return
            
            image_filename = image_files[visual_state]
            image_path = get_asset_path(image_filename)
            pixmap = QPixmap(str(image_path))
            
            if pixmap.isNull():
                log.warning(f"[DiceButton] Failed to load image: {image_path}")
                return
            
            self.dice_image.setPixmap(pixmap)
            # Only update the logical state for base states
            if state in ('enabled', 'disabled'):
                self.current_state = state
            
        except Exception as e:
            log.error(f"[DiceButton] Error loading state image {state}: {e}")
    
    def set_state(self, state: str):
        """Set the button state and update image"""
        if state != self.current_state:
            self._load_state_image(state)
    
    def show_button(self):
        """Show the dice button with fade in"""
        log.debug(f"[DiceButton] show_button called, is_visible: {self.is_visible}")
        if not self.is_visible:
            self.is_visible = True
            self.show()
            log.debug("[DiceButton] Showing button and starting fade in")
            self.fade_in_requested.emit()
        else:
            log.debug("[DiceButton] Button already visible")
    
    def hide_button(self):
        """Hide the dice button with fade out"""
        if self.is_visible:
            self.is_visible = False
            self.fade_out_requested.emit()
    
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
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press events (no visual change; act on release)"""
        log.debug(f"[DiceButton] Mouse press event received: {event.button()}")
        if event.button() == Qt.MouseButton.LeftButton:
            # Track if press started inside the button
            self._pressed_inside = self.rect().contains(event.position().toPoint())
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """Show enabled visual on hover without changing logical state."""
        if self.rect().contains(event.position().toPoint()):
            # Show hover visual mapped to enabled
            if self.current_state in ['disabled', 'enabled']:
                self._load_state_image('hover')

    def enterEvent(self, event):
        """Ensure enabled visual appears immediately on hover enter."""
        if self.current_state in ['disabled', 'enabled']:
            self._load_state_image('hover')
    
    def leaveEvent(self, event):
        """Restore visual to the logical base state when cursor leaves."""
        if self.state and hasattr(self.state, 'random_mode_active') and self.state.random_mode_active:
            self._load_state_image('enabled')
        else:
            self._load_state_image('disabled')
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """Emit click on release if press started inside the button."""
        log.debug(f"[DiceButton] Mouse release event received: {event.button()}")
        if event.button() == Qt.MouseButton.LeftButton:
            released_inside = self.rect().contains(event.position().toPoint())
            if self._pressed_inside and released_inside:
                base_state = self.current_state
                log.debug(f"[DiceButton] Emitting signal on release with state: {base_state}")
                self.dice_clicked.emit(base_state)
        self._pressed_inside = False
    
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
                log.info(f"[DiceButton] Resolution changed from {self._current_resolution} to {current_resolution}, recreating")
                self._create_components()
                
        except Exception as e:
            log.error(f"[DiceButton] Error checking resolution: {e}")
    
    def cleanup(self):
        """Clean up the dice button"""
        try:
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
            
            # Properly destroy the PyQt6 widget
            self.hide()
            self.deleteLater()
            log.debug("[DiceButton] Cleaned up and scheduled for deletion")
        except Exception as e:
            log.debug(f"[DiceButton] Error during cleanup: {e}")
