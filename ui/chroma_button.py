#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Chroma Opening Button - Small circular button to open the chroma panel
"""

import math
from typing import Callable
from PyQt6.QtWidgets import QGraphicsOpacityEffect
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
        
        # No fade animations - instant show/hide
        
        # No opacity effect needed for instant show/hide
        
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
        
        # 3. Button chroma image - replaces gradient ring and inner circle
        painter.setPen(Qt.PenStyle.NoPen)
        
        # Load and draw the button-chroma.png image
        try:
            button_chroma_pixmap = QPixmap("assets/button-chroma.png")
            if not button_chroma_pixmap.isNull():
                # Scale the image to fit the gradient area
                scaled_pixmap = button_chroma_pixmap.scaled(
                    int(gradient_outer_radius * 2), int(gradient_outer_radius * 2),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # Center the image
                image_x = center - scaled_pixmap.width() // 2
                image_y = center - scaled_pixmap.height() // 2
                
                # Apply darkening effect if hovered
                if should_darken:
                    # Create a darker version of the image using overlay mode
                    dark_pixmap = scaled_pixmap.copy()
                    painter_dark = QPainter(dark_pixmap)
                    painter_dark.setCompositionMode(QPainter.CompositionMode.CompositionMode_Overlay)
                    painter_dark.fillRect(dark_pixmap.rect(), QColor(0, 0, 0, 100))  # Semi-transparent black overlay
                    painter_dark.end()
                    painter.drawPixmap(image_x, image_y, dark_pixmap)
                else:
                    painter.drawPixmap(image_x, image_y, scaled_pixmap)
                    
                log.debug(f"[CHROMA] Button chroma image drawn at ({image_x}, {image_y}), size: {scaled_pixmap.width()}x{scaled_pixmap.height()}")
            else:
                log.warning("[CHROMA] Failed to load button-chroma.png")
        except Exception as e:
            log.error(f"[CHROMA] Error loading button-chroma.png: {e}")
    
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
    
    def show_instantly(self):
        """Show the button instantly (no fade)"""
        try:
            # Ensure League window is available before positioning
            if not hasattr(self, '_league_window_hwnd') or not self._league_window_hwnd:
                log.warning("[CHROMA] League window not available, attempting to parent button")
                self._parent_to_league_window()
            
            # Wait a moment for League window to be ready if we just parented
            if not hasattr(self, '_league_window_hwnd') or not self._league_window_hwnd:
                log.warning("[CHROMA] League window still not available, delaying button show")
                # Schedule a retry in 100ms
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, self.show_instantly)
                return
            
            # Ensure button is positioned correctly before showing
            self._update_position()
            
            # Verify position is valid (not 0,0 which indicates positioning failed)
            if self.x() == 0 and self.y() == 0:
                log.warning("[CHROMA] Button position is (0,0), delaying show until positioning is ready")
                # Schedule a retry in 50ms
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(50, self.show_instantly)
                return
            
            # Debug: Check position before showing
            log.debug(f"[CHROMA] Button position before show: ({self.x()}, {self.y()}) size: {self.width()}x{self.height()}")
            
            self.show()
            self.raise_()
            self._bring_to_front()
            
            # Debug: Check position after showing
            log.debug(f"[CHROMA] Button position after show: ({self.x()}, {self.y()}) size: {self.width()}x{self.height()}")
        except RuntimeError:
            pass
    
    def hide_instantly(self):
        """Hide the button instantly (no fade)"""
        try:
            self.hide()
            log.debug("[CHROMA] Button hidden instantly")
        except RuntimeError:
            pass
    
    def show_for_chromas(self):
        """Show button when skin has chromas - instant"""
        try:
            self.show_instantly()
            log.debug("[CHROMA] Button shown for chromas")
        except RuntimeError:
            pass
    
    def hide_for_no_chromas(self):
        """Hide button when skin has no chromas - instant"""
        try:
            self.hide_instantly()
            log.debug("[CHROMA] Button hidden for no chromas")
        except RuntimeError:
            pass
    
    
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


