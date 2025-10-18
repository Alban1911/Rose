#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Chroma Opening Button - Small circular button to open the chroma panel
"""

import math
from typing import Callable
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget
from PyQt6.QtCore import Qt, QPoint, QTimer, QMetaObject, pyqtSlot
from PyQt6.QtGui import QPainter, QColor, QBrush, QRadialGradient, QConicalGradient, QPixmap
from ui.chroma_base import ChromaWidgetBase
from ui.chroma_scaling import get_scaled_chroma_values
from utils.logging import get_logger
import config

log = get_logger()


class OpeningButton(ChromaWidgetBase):
    """Small circular button to reopen chroma panel"""
    
    def __init__(self, on_click: Callable[[], None] = None, manager=None):
        super().__init__()
        self.on_click = on_click
        self.manager = manager  # Reference to ChromaPanelManager for rebuild requests
        self.is_hovered = False
        self.is_hiding = False  # Flag to prevent painting during hide
        self.panel_is_open = False  # Flag to show button as hovered when panel is open
        self.current_chroma_color = None  # Current selected chroma color (None = show rainbow)
        
        # Fade animation state
        self.fade_timer = None
        self.fade_target_opacity = 1.0
        self.fade_start_opacity = 1.0
        self.fade_steps = 0
        self.fade_current_step = 0
        self.fade_in_timer = None  # Timer to schedule fade in after delay
        
        # Create opacity effect for fading
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self.opacity_effect)
        
        # Common window flags already set by parent class
        
        # Get scaled values for current resolution
        self.scaled = get_scaled_chroma_values()
        self._current_resolution = self.scaled.resolution  # Track resolution for change detection
        self._updating_resolution = False  # Flag to prevent recursive updates
        
        # Setup button size and position (using scaled values)
        # Add extra space for the 3px transparent ring on each side
        self.transparent_ring_width = 3
        self.button_visual_size = self.scaled.button_size  # Visual size (golden border)
        self.button_size = self.button_visual_size + (self.transparent_ring_width * 2)  # Total widget size includes transparent ring
        self.setFixedSize(self.button_size, self.button_size)
        
        # Position using the synchronized positioning system
        # Button is centered at anchor (offset = 0, 0)
        self.position_relative_to_anchor(
            width=self.button_size,
            height=self.button_size,
            offset_x=0,  # No offset - button center is at anchor
            offset_y=0
        )
        
        # Set cursor to hand pointer for the button
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Create UnownedFrame (contains Lock and OutlineGold, fades when skin is NOT owned)
        log.info("[CHROMA] Creating UnownedFrame...")
        
        self.hide()
    
    
    def paintEvent(self, event):
        """Paint the circular button with new design"""
        # Don't paint if we're hiding
        if self.is_hiding:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Use actual widget size (includes transparent ring)
        actual_size = min(self.width(), self.height())
        center = actual_size // 2
        
        # Transparent ring parameters (3px on each side)
        transparent_ring_width = self.transparent_ring_width
        
        # Calculate radii from center
        # Widget edge is at center ± (actual_size / 2)
        # Transparent ring outer edge is at widget edge (margin 0)
        transparent_outer_radius = (actual_size // 2)
        
        # Golden border is inside the transparent ring
        outer_radius = transparent_outer_radius - transparent_ring_width  # Golden border outer edge
        
        # Use less internal margin at small resolutions
        # Reference button size at 900p is 33px visual, smallest at ~576p is ~21px visual
        internal_margin = 2 if self.button_visual_size <= 25 else 3
        outer_radius -= internal_margin  # Adjust for internal spacing
        
        # Calculate border widths as direct ratios of button radius
        # This ensures proper scaling at all resolutions
        # Reference ratios based on measurements from a 33px button (radius ~13.5px after margin)
        # Measurements: 2px gold, 1px trans, 2px dark, 1px trans, 4px gradient, 1px trans, 2.5px inner
        
        # Calculate widths as percentages of outer_radius for consistent scaling
        gold_border_width = max(1, int(outer_radius * 0.15))      # ~15% of radius (2px at 13.5px radius)
        transition1_width = max(1, int(outer_radius * 0.074))     # ~7.4% of radius (1px at 13.5px radius)
        dark_border_width = max(1, int(outer_radius * 0.15))      # ~15% of radius (2px at 13.5px radius)
        transition2_width = max(1, int(outer_radius * 0.074))     # ~7.4% of radius (1px at 13.5px radius)
        gradient_ring_width = max(2, int(outer_radius * 0.30))    # ~30% of radius (4px at 13.5px radius)
        transition3_width = max(1, int(outer_radius * 0.074))     # ~7.4% of radius (1px at 13.5px radius)
        inner_disk_radius = max(1.5, outer_radius * 0.185)        # ~18.5% of radius (2.5px at 13.5px radius)
        
        # Calculate actual radii from outside in (starting from outer_radius)
        outer_gold_radius = outer_radius
        inner_gold_radius = outer_radius - gold_border_width
        after_transition1_radius = inner_gold_radius - transition1_width
        inner_dark_radius = after_transition1_radius - dark_border_width
        after_transition2_radius = inner_dark_radius - transition2_width
        gradient_outer_radius = after_transition2_radius
        gradient_inner_radius = gradient_outer_radius - gradient_ring_width
        after_transition3_radius = gradient_inner_radius - transition3_width
        inner_radius = inner_disk_radius  # Central dark disk
        
        # Determine if button should be darkened (hovered but wheel not open)
        should_darken = self.is_hovered and not self.panel_is_open
        
        # 0. Transparent ring around golden border (3px wide)
        # Provides clickable area around the visible button
        from PyQt6.QtGui import QPainterPath
        transparent_ring_path = QPainterPath()
        transparent_ring_path.addEllipse(
            center - transparent_outer_radius, 
            center - transparent_outer_radius,
            transparent_outer_radius * 2, 
            transparent_outer_radius * 2
        )
        transparent_ring_path.addEllipse(
            center - outer_radius, 
            center - outer_radius,
            outer_radius * 2, 
            outer_radius * 2
        )
        transparent_ring_path.setFillRule(Qt.FillRule.OddEvenFill)
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 1)))  # Alpha=1 (invisible but Qt detects for mouse events)
        painter.drawPath(transparent_ring_path)
        
        # 1. Outer metallic gold border - matches wheel border color
        # Darker when wheel is open
        gold_gradient = QRadialGradient(center, center, outer_gold_radius)
        if self.panel_is_open:
            # Darker gold gradient when wheel is open
            gold_gradient.setColorAt(0.0, QColor("#a57828"))  # Dark gold
            gold_gradient.setColorAt(0.7, QColor("#8f6620"))  # Darker main gold
            gold_gradient.setColorAt(1.0, QColor("#75551a"))  # Very dark gold
        elif should_darken:
            # Even darker when hovered (entire button dark)
            gold_gradient.setColorAt(0.0, QColor("#8a6420"))  # Darker gold
            gold_gradient.setColorAt(0.7, QColor("#705218"))  # Much darker gold
            gold_gradient.setColorAt(1.0, QColor("#5a4212"))  # Very dark gold
        else:
            # Normal gold gradient
            gold_gradient.setColorAt(0.0, QColor("#d4a747"))  # Light gold
            gold_gradient.setColorAt(0.7, QColor("#b78c34"))  # Main gold (matches wheel border)
            gold_gradient.setColorAt(1.0, QColor("#9a7328"))  # Dark gold
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gold_gradient))
        painter.drawEllipse(QPoint(center, center), outer_gold_radius, outer_gold_radius)
        
        # 2. Dark border ring (2px width) - between gold and gradient
        # Create a thin dark ring using QPainterPath
        dark_border_path = QPainterPath()
        # Add outer circle (after_transition1_radius)
        dark_border_path.addEllipse(center - after_transition1_radius, center - after_transition1_radius, 
                                   after_transition1_radius * 2, after_transition1_radius * 2)
        # Add inner circle (after_transition2_radius) to be subtracted
        dark_border_path.addEllipse(center - after_transition2_radius, center - after_transition2_radius, 
                                   after_transition2_radius * 2, after_transition2_radius * 2)
        dark_border_path.setFillRule(Qt.FillRule.OddEvenFill)  # Subtract inner from outer
        
        painter.setPen(Qt.PenStyle.NoPen)
        # Darker border when button is darkened
        border_color = QColor(10, 10, 10) if should_darken else QColor(20, 20, 20)
        painter.setBrush(QBrush(border_color))
        painter.drawPath(dark_border_path)
        
        # 3. Gradient ring (4px width) - shows rainbow or chroma color
        # If a chroma is selected, show chroma color; otherwise show rainbow
        painter.setPen(Qt.PenStyle.NoPen)
        
        if self.current_chroma_color:
            # Chroma selected - fill entire center with chroma color (gradient ring + center)
            chroma_color = QColor(self.current_chroma_color)
            
            # Darken if hovered
            if should_darken:
                chroma_color = chroma_color.darker(200)  # 50% darker
            
            # Fill entire center with chroma color (no gradient, no dark center - just solid color)
            painter.setBrush(QBrush(chroma_color))
            painter.drawEllipse(QPoint(center, center), gradient_outer_radius, gradient_outer_radius)
        else:
            # Base skin - show rainbow gradient with dark center
            rainbow_gradient = QConicalGradient(center, center, config.CHROMA_PANEL_CONICAL_START_ANGLE)
            
            if should_darken:
                # Darker rainbow when hovered (50% darker)
                rainbow_gradient.setColorAt(0.0, QColor(128, 0, 128))    # Darker Magenta
                rainbow_gradient.setColorAt(0.16, QColor(128, 0, 0))     # Darker Red
                rainbow_gradient.setColorAt(0.33, QColor(128, 82, 0))    # Darker Orange
                rainbow_gradient.setColorAt(0.5, QColor(128, 128, 0))    # Darker Yellow
                rainbow_gradient.setColorAt(0.66, QColor(0, 128, 0))     # Darker Green
                rainbow_gradient.setColorAt(0.83, QColor(0, 0, 128))     # Darker Blue
                rainbow_gradient.setColorAt(1.0, QColor(64, 0, 64))      # Darker Purple
            else:
                # Normal rainbow gradient
                rainbow_gradient.setColorAt(0.0, QColor(255, 0, 255))    # Magenta
                rainbow_gradient.setColorAt(0.16, QColor(255, 0, 0))     # Red
                rainbow_gradient.setColorAt(0.33, QColor(255, 165, 0))   # Orange
                rainbow_gradient.setColorAt(0.5, QColor(255, 255, 0))    # Yellow (now at top)
                rainbow_gradient.setColorAt(0.66, QColor(0, 255, 0))     # Green
                rainbow_gradient.setColorAt(0.83, QColor(0, 0, 255))     # Blue
                rainbow_gradient.setColorAt(1.0, QColor(128, 0, 128))    # Purple
            
            painter.setBrush(QBrush(rainbow_gradient))
            painter.drawEllipse(QPoint(center, center), gradient_outer_radius, gradient_outer_radius)
            
            # Cut out the inner part of the gradient ring to create the ring shape (only for base/rainbow)
            center_color = QColor(10, 10, 10) if should_darken else QColor(20, 20, 20)
            
            painter.setBrush(QBrush(center_color))
            painter.drawEllipse(center - int(gradient_inner_radius), center - int(gradient_inner_radius), 
                               int(gradient_inner_radius) * 2, int(gradient_inner_radius) * 2)
            
            # 4. Dark central disk (only for base/rainbow)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(center_color))
            painter.drawEllipse(center - int(inner_radius), center - int(inner_radius), 
                               int(inner_radius) * 2, int(inner_radius) * 2)
    
    def mousePressEvent(self, event):
        """Handle button press - track that button was pressed"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Don't accept clicks when button is faded out (invisible)
            if self.opacity_effect.opacity() < 0.1:
                event.ignore()
                return
            # Just accept the press event, action happens on release
            pass
        event.accept()
    
    def mouseReleaseEvent(self, event):
        """Handle button release - trigger action on click+release"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Don't accept clicks when button is faded out (invisible)
            if self.opacity_effect.opacity() < 0.1:
                event.ignore()
                return
            
            # Check if mouse is still over the button
            # Clickable zone includes the transparent ring + 30% extra for easier clicking
            center = self.button_size // 2
            # Transparent ring extends to widget edge
            transparent_outer_radius = self.button_size // 2
            clickable_radius = int(transparent_outer_radius * 1.3)  # 30% bigger than transparent ring
            dx = event.pos().x() - center
            dy = event.pos().y() - center
            dist = math.sqrt(dx * dx + dy * dy)
            
            # Only trigger if released while still over the button (using larger clickable radius)
            if dist <= clickable_radius:
                if self.on_click:
                    self.on_click()
        event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle mouse hover"""
        center = self.button_size // 2
        # Transparent ring extends to widget edge
        transparent_outer_radius = self.button_size // 2
        clickable_radius = int(transparent_outer_radius * 1.3)  # 30% bigger than transparent ring
        dx = event.pos().x() - center
        dy = event.pos().y() - center
        dist = math.sqrt(dx * dx + dy * dy)
        
        # Visual hover includes the entire transparent ring (up to widget edge)
        was_hovered = self.is_hovered
        self.is_hovered = dist <= transparent_outer_radius
        
        if was_hovered != self.is_hovered:
            self.update()
        
        # Cursor changes to pointer in the extended clickable area (30% bigger than transparent ring)
        if dist <= clickable_radius:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def leaveEvent(self, event):
        """Handle mouse leave"""
        if self.is_hovered:
            self.is_hovered = False
            self.update()
        # Cursor remains as hand pointer since widget has it set
    
    def set_wheel_open(self, is_open: bool):
        """Update button appearance based on wheel state"""
        try:
            if self.panel_is_open != is_open:
                self.panel_is_open = is_open
                self.update()
        except RuntimeError as e:
            # Widget may have been deleted
            pass
    
    def set_chroma_color(self, color: str = None):
        """Set the chroma color to display (None = show rainbow gradient)"""
        try:
            self.current_chroma_color = color
            self.update()
        except RuntimeError as e:
            # Widget may have been deleted
            pass
    
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
                log.info(f"[CHROMA] Button resolution changed from {self._current_resolution} to {current_resolution}, requesting rebuild")
                
                # Update current resolution to prevent re-detection
                self._current_resolution = current_resolution
                
                # Request rebuild from manager instead of updating in place
                # This prevents flickering and ensures clean scaling
                if self.manager:
                    self.manager.request_rebuild()
                else:
                    log.warning("[CHROMA] Button has no manager reference, cannot request rebuild")
                
                # Clear update flag
                self._updating_resolution = False
        except Exception as e:
            log.error(f"[CHROMA] Error checking button resolution: {e}")
            import traceback
            log.error(traceback.format_exc())
            # Clear flag even on error
            self._updating_resolution = False
    
    def _fade_step(self):
        """Execute one step of the fade animation"""
        try:
            if self.fade_current_step >= self.fade_steps:
                # Animation complete
                self.opacity_effect.setOpacity(self.fade_target_opacity)
                if self.fade_timer:
                    self.fade_timer.stop()
                    self.fade_timer = None
                return
            
            # Calculate progress
            progress = self.fade_current_step / self.fade_steps
            
            # Apply easing based on fade direction
            if self.fade_target_opacity > self.fade_start_opacity:
                # Fade in: use logarithmic easing for smooth, gradual fade
                # Using a gentler curve: log(1 + progress * 3) / log(4)
                eased_progress = math.log(1 + progress * 3) / math.log(4)
            else:
                # Fade out: use linear (50ms, fast and direct)
                eased_progress = progress
            
            current_opacity = self.fade_start_opacity + (self.fade_target_opacity - self.fade_start_opacity) * eased_progress
            self.opacity_effect.setOpacity(current_opacity)
            
            self.fade_current_step += 1
        except RuntimeError:
            # Widget may have been deleted
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
    
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
            
            log.info(f"[CHROMA] Starting fade: {self.fade_start_opacity:.2f} → {target_opacity:.2f} over {duration_ms}ms ({self.fade_steps} steps)")
            
            # Create timer for animation
            self.fade_timer = QTimer(self)
            self.fade_timer.timeout.connect(self._fade_step)
            self.fade_timer.start(frame_interval_ms)
            
        except RuntimeError:
            # Widget may have been deleted
            pass
    
    def fade_has_to_has(self):
        """Chromas → Chromas: fade out 50ms, wait 100ms, fade in 50ms - thread-safe"""
        try:
            QMetaObject.invokeMethod(self, "_do_has_to_has", Qt.ConnectionType.QueuedConnection)
        except RuntimeError:
            pass
    
    def fade_none_to_has(self):
        """No chromas → Chromas: wait 150ms, fade in 50ms - thread-safe"""
        try:
            QMetaObject.invokeMethod(self, "_do_none_to_has", Qt.ConnectionType.QueuedConnection)
        except RuntimeError:
            pass
    
    def fade_has_to_none(self):
        """Chromas → No chromas: fade out 50ms - thread-safe"""
        try:
            QMetaObject.invokeMethod(self, "_do_has_to_none", Qt.ConnectionType.QueuedConnection)
        except RuntimeError:
            pass
    
    @pyqtSlot()
    def _do_has_to_has(self):
        """Chromas → Chromas: fade out 50ms, wait 100ms, fade in exponentially"""
        try:
            if not self.isVisible():
                return
            
            # Cancel any pending animations
            self._cancel_animations()
            
            # Fade out (50ms, linear)
            self._start_fade(0.0, config.CHROMA_FADE_OUT_DURATION_MS)
            
            # Schedule fade in after: fade_out_duration + wait_time
            total_delay = config.CHROMA_FADE_OUT_DURATION_MS + config.CHROMA_FADE_DELAY_BEFORE_SHOW_MS
            self.fade_in_timer = QTimer(self)
            self.fade_in_timer.setSingleShot(True)
            self.fade_in_timer.timeout.connect(lambda: self._start_fade(1.0, config.CHROMA_FADE_IN_DURATION_MS))
            self.fade_in_timer.start(total_delay)
            
        except RuntimeError:
            pass
    
    @pyqtSlot()
    def _do_none_to_has(self):
        """No chromas → Chromas: wait 150ms, fade in exponentially"""
        try:
            if not self.isVisible():
                return
            
            # Cancel any pending animations
            self._cancel_animations()
            
            # Set to 0 opacity immediately
            self.opacity_effect.setOpacity(0.0)
            
            # Wait 150ms, then fade in (exponential)
            self.fade_in_timer = QTimer(self)
            self.fade_in_timer.setSingleShot(True)
            self.fade_in_timer.timeout.connect(lambda: self._start_fade(1.0, config.CHROMA_FADE_IN_DURATION_MS))
            self.fade_in_timer.start(150)  # 150ms wait
            
        except RuntimeError:
            pass
    
    @pyqtSlot()
    def _do_has_to_none(self):
        """Chromas → No chromas: fade out 50ms (linear)"""
        try:
            # Don't check visibility - button might be hidden during animation
            
            # Cancel any pending animations
            self._cancel_animations()
            
            # Fade out only (50ms, linear)
            self._start_fade(0.0, config.CHROMA_FADE_OUT_DURATION_MS)
            
        except RuntimeError:
            pass
    
    def _cancel_animations(self):
        """Cancel all pending animations"""
        if self.fade_timer:
            self.fade_timer.stop()
            self.fade_timer = None
        if self.fade_in_timer:
            self.fade_in_timer.stop()
            self.fade_in_timer = None
    
    
    # ===== LOCK FADE METHODS (INVERTED: shown when NOT owned) =====
    
    def lock_fade_not_owned_to_not_owned(self):
        """NOT owned → NOT owned: fade out 50ms, wait 100ms, fade in 50ms (lock stays visible)"""
        try:
            QMetaObject.invokeMethod(self, "_do_lock_not_owned_to_not_owned", Qt.ConnectionType.QueuedConnection)
        except RuntimeError:
            pass
    
    def lock_fade_not_owned_to_owned(self):
        """NOT owned → Owned: fade out 50ms (hide lock)"""
        try:
            QMetaObject.invokeMethod(self, "_do_lock_not_owned_to_owned", Qt.ConnectionType.QueuedConnection)
        except RuntimeError:
            pass
    
    def lock_fade_owned_to_not_owned(self):
        """Owned → NOT owned: wait 150ms, fade in 50ms (show lock)"""
        try:
            QMetaObject.invokeMethod(self, "_do_lock_owned_to_not_owned", Qt.ConnectionType.QueuedConnection)
        except RuntimeError:
            pass
    
    def lock_fade_owned_to_not_owned_first(self):
        """First skin NOT owned: just fade in 50ms (no wait)"""
        try:
            QMetaObject.invokeMethod(self, "_do_lock_owned_to_not_owned_first", Qt.ConnectionType.QueuedConnection)
        except RuntimeError:
            pass
    
    @pyqtSlot()
    def _do_lock_not_owned_to_not_owned(self):
        """NOT owned → NOT owned: fade out 50ms, wait 100ms, fade in exponentially (lock stays visible)"""
        try:
            log.info(f"[CHROMA] Lock fade: NOT owned→NOT owned (current opacity: {self.lock_opacity_effect.opacity():.2f})")
            self._cancel_lock_animations()
            self._start_lock_fade(0.0, config.CHROMA_FADE_OUT_DURATION_MS)
            total_delay = config.CHROMA_FADE_OUT_DURATION_MS + config.CHROMA_FADE_DELAY_BEFORE_SHOW_MS
            self.lock_fade_in_timer = QTimer(self)
            self.lock_fade_in_timer.setSingleShot(True)
            self.lock_fade_in_timer.timeout.connect(lambda: self._start_lock_fade(1.0, config.CHROMA_FADE_IN_DURATION_MS))
            self.lock_fade_in_timer.start(total_delay)
        except RuntimeError:
            pass
    
    @pyqtSlot()
    def _do_lock_not_owned_to_owned(self):
        """NOT owned → Owned: fade out 50ms linear (hide lock)"""
        try:
            log.info(f"[CHROMA] Lock fade: NOT owned→owned (HIDE lock, opacity: {self.lock_opacity_effect.opacity():.2f})")
            self._cancel_lock_animations()
            self._start_lock_fade(0.0, config.CHROMA_FADE_OUT_DURATION_MS)
        except RuntimeError:
            pass
    
    @pyqtSlot()
    def _do_lock_owned_to_not_owned(self):
        """Owned → NOT owned: wait 150ms, fade in exponentially (show lock)"""
        try:
            log.info(f"[CHROMA] Lock fade: owned→NOT owned (SHOW lock, opacity: {self.lock_opacity_effect.opacity():.2f})")
            self._cancel_lock_animations()
            self.lock_opacity_effect.setOpacity(0.0)
            self.lock_fade_in_timer = QTimer(self)
            self.lock_fade_in_timer.setSingleShot(True)
            self.lock_fade_in_timer.timeout.connect(lambda: self._start_lock_fade(1.0, config.CHROMA_FADE_IN_DURATION_MS))
            self.lock_fade_in_timer.start(150)
        except RuntimeError:
            pass
    
    @pyqtSlot()
    def _do_lock_owned_to_not_owned_first(self):
        """First skin NOT owned: just fade in exponentially (no wait)"""
        try:
            log.info(f"[CHROMA] Lock fade: FIRST NOT owned (immediate fade in, opacity: {self.lock_opacity_effect.opacity():.2f})")
            self._cancel_lock_animations()
            self._start_lock_fade(1.0, config.CHROMA_FADE_IN_DURATION_MS)
        except RuntimeError:
            pass
    
    def _start_lock_fade(self, target_opacity: float, duration_ms: int):
        """Start Lock fade animation"""
        try:
            if self.lock_fade_timer:
                self.lock_fade_timer.stop()
                self.lock_fade_timer = None
            
            self.lock_fade_start_opacity = self.lock_opacity_effect.opacity()
            self.lock_fade_target_opacity = target_opacity
            self.lock_fade_current_step = 0
            self.lock_fade_steps = max(1, duration_ms // 16)
            
            self.lock_fade_timer = QTimer(self)
            self.lock_fade_timer.timeout.connect(self._lock_fade_step)
            self.lock_fade_timer.start(16)
        except RuntimeError:
            pass
    
    def _lock_fade_step(self):
        """Execute one step of the Lock fade animation"""
        try:
            if self.lock_fade_current_step >= self.lock_fade_steps:
                self.lock_opacity_effect.setOpacity(self.lock_fade_target_opacity)
                if self.lock_fade_timer:
                    self.lock_fade_timer.stop()
                    self.lock_fade_timer = None
                return
            
            # Calculate progress
            progress = self.lock_fade_current_step / self.lock_fade_steps
            
            # Apply easing based on fade direction
            if self.lock_fade_target_opacity > self.lock_fade_start_opacity:
                # Fade in: use logarithmic easing for smooth, gradual fade
                # Using a gentler curve: log(1 + progress * 3) / log(4)
                eased_progress = math.log(1 + progress * 3) / math.log(4)
            else:
                # Fade out: use linear (50ms, fast and direct)
                eased_progress = progress
            
            current_opacity = self.lock_fade_start_opacity + (self.lock_fade_target_opacity - self.lock_fade_start_opacity) * eased_progress
            self.lock_opacity_effect.setOpacity(current_opacity)
            self.lock_fade_current_step += 1
        except RuntimeError:
            if self.lock_fade_timer:
                self.lock_fade_timer.stop()
                self.lock_fade_timer = None
    
    def _cancel_lock_animations(self):
        """Cancel all pending Lock animations"""
        if self.lock_fade_timer:
            self.lock_fade_timer.stop()
            self.lock_fade_timer = None
        if self.lock_fade_in_timer:
            self.lock_fade_in_timer.stop()
            self.lock_fade_in_timer = None
    
    
    def showEvent(self, event):
        """Reset hiding flag when button is shown"""
        self.is_hiding = False
        super().showEvent(event)
    
    def moveEvent(self, event):
        """Button moved"""
        super().moveEvent(event)
    
    def hideEvent(self, event):
        """Button is hidden"""
        super().hideEvent(event)


