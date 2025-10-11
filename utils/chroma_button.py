#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Chroma Opening Button - Small circular button to open the chroma panel
"""

import math
from typing import Callable
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QPainter, QColor, QBrush, QRadialGradient, QConicalGradient, QPainterPath
from utils.chroma_base import ChromaWidgetBase, ChromaUIConfig
from utils.chroma_scaling import get_scaled_chroma_values
from config import CHROMA_PANEL_CONICAL_START_ANGLE


class OpeningButton(ChromaWidgetBase):
    """Small circular button to reopen chroma panel"""
    
    def __init__(self, on_click: Callable[[], None] = None):
        super().__init__()
        self.on_click = on_click
        self.is_hovered = False
        self.is_hiding = False  # Flag to prevent painting during hide
        self.panel_is_open = False  # Flag to show button as hovered when panel is open
        
        # Common window flags already set by parent class
        
        # Get scaled values for current resolution
        self.scaled = get_scaled_chroma_values()
        self._current_resolution = self.scaled.resolution  # Track resolution for change detection
        
        # Setup button size and position (using scaled values)
        self.button_size = self.scaled.button_size
        self.setFixedSize(self.button_size, self.button_size)
        
        # Position using the synchronized positioning system
        self.position_relative_to_anchor(
            width=self.button_size,
            height=self.button_size,
            offset_x=self.scaled.button_offset_x,
            offset_y=self.scaled.button_offset_y
        )
        
        # Set cursor to hand pointer for the button
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.hide()
    
    def paintEvent(self, event):
        """Paint the circular button with new design"""
        # Don't paint if we're hiding
        if self.is_hiding:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Use actual widget size (may be constrained at small resolutions)
        actual_size = min(self.width(), self.height())
        center = actual_size // 2
        # Use less margin at small resolutions (give golden border more space)
        # Reference button size at 900p is 33px, smallest at ~576p is ~21px
        margin = 2 if actual_size <= 25 else 3  # Smaller margin for small resolutions
        outer_radius = (actual_size // 2) - margin
        
        # Calculate ratios from official button measurements and scale to current button
        # Official measurements: 2px gold, 1px trans, 2px dark, 1px trans, 4px gradient, 1px trans, 5px inner
        # Total official radius = 2+1+2+1+4+1+2.5 = 13.5px (assuming ~15px total radius for official button)
        
        # Calculate scale factor based on current button size
        # Current button: 60px total, 6px margin = 54px usable = 27px radius
        # Scale factor = current_radius / official_radius = 27 / 15 = 1.8
        scale_factor = outer_radius / 15.0  # Scale from official button size
        
        # Apply ratios scaled to current button size (using pre-calculated scaled values)
        gold_border_width = int(self.scaled.gold_border_px * scale_factor)
        # Make golden border more visible at small resolutions
        if self.button_size <= 25:
            gold_border_width += 1  # +1 for better visibility at smallest resolution
        transition1_width = int(1 * scale_factor)
        dark_border_width = int(self.scaled.dark_border_px * scale_factor) + 1  # +1 for better visibility at small resolutions
        transition2_width = int(1 * scale_factor)
        gradient_ring_width = int(self.scaled.gradient_ring_px * scale_factor)
        transition3_width = int(1 * scale_factor)
        inner_disk_radius = self.scaled.inner_disk_radius_px * scale_factor
        
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
        
        # 1. Outer metallic gold border - matches wheel border color (7% of button size)
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
        
        # 3. Rainbow gradient ring (4px width) - yellow starts at top
        # Draw gradient as outer circle, then cut out the inner part with dark color
        rainbow_gradient = QConicalGradient(center, center, CHROMA_PANEL_CONICAL_START_ANGLE)
        
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
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(rainbow_gradient))
        painter.drawEllipse(QPoint(center, center), gradient_outer_radius, gradient_outer_radius)
        
        # Cut out the inner part of the gradient ring to create the ring shape
        center_color = QColor(10, 10, 10) if should_darken else QColor(20, 20, 20)
        painter.setBrush(QBrush(center_color))
        painter.drawEllipse(center - int(gradient_inner_radius), center - int(gradient_inner_radius), 
                           int(gradient_inner_radius) * 2, int(gradient_inner_radius) * 2)
        
        # 4. Dark central disk (5px diameter = 2.5px radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(center_color))
        painter.drawEllipse(center - int(inner_radius), center - int(inner_radius), 
                           int(inner_radius) * 2, int(inner_radius) * 2)
    
    def mousePressEvent(self, event):
        """Handle button press - track that button was pressed"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Just accept the press event, action happens on release
            pass
        event.accept()
    
    def mouseReleaseEvent(self, event):
        """Handle button release - trigger action on click+release"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if mouse is still over the button
            # Clickable zone is 20% bigger than visual button for easier clicking
            center = self.button_size // 2
            visual_radius = (self.button_size // 2) - 5
            clickable_radius = int(visual_radius * 1.2)  # 20% bigger clickable area
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
        visual_radius = (self.button_size // 2) - 5
        clickable_radius = int(visual_radius * 1.2)  # 20% bigger clickable area
        dx = event.pos().x() - center
        dy = event.pos().y() - center
        dist = math.sqrt(dx * dx + dy * dy)
        
        # Visual hover uses standard radius
        was_hovered = self.is_hovered
        self.is_hovered = dist <= visual_radius
        
        if was_hovered != self.is_hovered:
            self.update()
        
        # Cursor changes to pointer in the extended clickable area (20% bigger)
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
    
    def check_resolution_and_update(self):
        """Check if resolution changed and update UI if needed"""
        try:
            # Get current League resolution directly (bypass cache)
            from utils.window_utils import get_league_window_client_size
            current_resolution = get_league_window_client_size()
            
            if not current_resolution:
                return  # League window not found
            
            # Check if resolution actually changed
            if current_resolution != self._current_resolution:
                from utils.logging import get_logger
                log = get_logger()
                log.info(f"[CHROMA] Button resolution changed from {self._current_resolution} to {current_resolution}, updating UI")
                
                # Capture old size BEFORE updating
                old_size = self.button_size
                
                # Force recalculation with new resolution
                new_scaled = get_scaled_chroma_values(resolution=current_resolution, force_reload=False)
                
                # Update stored values
                self.scaled = new_scaled
                self._current_resolution = current_resolution
                
                # Update button size with new scaled value
                self.button_size = self.scaled.button_size
                
                # Calculate constrained size to fit within League window
                # At very small resolutions, ensure button fits within window
                window_width, window_height = current_resolution
                
                # Use more aggressive constraints for very small windows
                if window_height < 600:  # Very small resolution (576p)
                    max_allowed_size = min(int(window_width * 0.04), int(window_height * 0.04))  # Max 4% for small windows
                else:
                    max_allowed_size = min(int(window_width * 0.08), int(window_height * 0.08))  # Max 8% for normal windows
                
                # Constrain button size if needed  
                constrained_size = min(self.button_size, max_allowed_size)
                
                # Hide widget during resize to prevent visual glitches
                was_visible = self.isVisible()
                if was_visible:
                    self.hide()
                
                # Update button size with constrained value
                self.setFixedSize(constrained_size, constrained_size)
                
                # Force geometry update
                self.updateGeometry()
                
                log.debug(f"[CHROMA] Button resized from {old_size}px to {constrained_size}px (scaled: {self.button_size}px)")
                
                # Update position with CONSTRAINED size and offsets
                self.position_relative_to_anchor(
                    width=constrained_size,
                    height=constrained_size,
                    offset_x=self.scaled.button_offset_x,
                    offset_y=self.scaled.button_offset_y
                )
                
                # Show widget again if it was visible
                if was_visible:
                    self.show()
                    self.raise_()
                    
                # Force immediate repaint
                self.repaint()
        except Exception as e:
            from utils.logging import get_logger
            log = get_logger()
            log.error(f"[CHROMA] Error updating button resolution: {e}")
            import traceback
            log.error(traceback.format_exc())
    
    def showEvent(self, event):
        """Reset hiding flag when button is shown"""
        self.is_hiding = False
        super().showEvent(event)


