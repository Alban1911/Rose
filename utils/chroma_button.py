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
from config import (
    CHROMA_PANEL_BUTTON_SIZE,
    CHROMA_PANEL_CONICAL_START_ANGLE,
    CHROMA_PANEL_GOLD_BORDER_PX,
    CHROMA_PANEL_DARK_BORDER_PX,
    CHROMA_PANEL_GRADIENT_RING_PX,
    CHROMA_PANEL_INNER_DISK_RADIUS_PX
)


class OpeningButton(ChromaWidgetBase):
    """Small circular button to reopen chroma panel"""
    
    def __init__(self, on_click: Callable[[], None] = None):
        super().__init__()
        self.on_click = on_click
        self.is_hovered = False
        self.is_hiding = False  # Flag to prevent painting during hide
        self.panel_is_open = False  # Flag to show button as hovered when panel is open
        
        # Common window flags already set by parent class
        
        # Setup button size and position
        self.button_size = CHROMA_PANEL_BUTTON_SIZE
        self.setFixedSize(self.button_size, self.button_size)
        
        # Position using the synchronized positioning system
        self.position_relative_to_anchor(
            width=self.button_size,
            height=self.button_size,
            offset_x=ChromaUIConfig.BUTTON_OFFSET_X,
            offset_y=ChromaUIConfig.BUTTON_OFFSET_Y
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
        
        center = self.button_size // 2
        outer_radius = (self.button_size // 2) - 3  # Leave small margin
        
        # Calculate ratios from official button measurements and scale to current button
        # Official measurements: 2px gold, 1px trans, 2px dark, 1px trans, 4px gradient, 1px trans, 5px inner
        # Total official radius = 2+1+2+1+4+1+2.5 = 13.5px (assuming ~15px total radius for official button)
        
        # Calculate scale factor based on current button size
        # Current button: 60px total, 6px margin = 54px usable = 27px radius
        # Scale factor = current_radius / official_radius = 27 / 15 = 1.8
        scale_factor = outer_radius / 15.0  # Scale from official button size
        
        # Apply ratios scaled to current button size
        gold_border_width = int(CHROMA_PANEL_GOLD_BORDER_PX * scale_factor)
        transition1_width = int(1 * scale_factor)
        dark_border_width = int(CHROMA_PANEL_DARK_BORDER_PX * scale_factor)
        transition2_width = int(1 * scale_factor)
        gradient_ring_width = int(CHROMA_PANEL_GRADIENT_RING_PX * scale_factor)
        transition3_width = int(1 * scale_factor)
        inner_disk_radius = CHROMA_PANEL_INNER_DISK_RADIUS_PX * scale_factor
        
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
            center = self.button_size // 2
            radius = (self.button_size // 2) - 5
            dx = event.pos().x() - center
            dy = event.pos().y() - center
            dist = math.sqrt(dx * dx + dy * dy)
            
            # Only trigger if released while still over the button
            if dist <= radius:
                if self.on_click:
                    self.on_click()
        event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle mouse hover"""
        center = self.button_size // 2
        radius = (self.button_size // 2) - 5
        dx = event.pos().x() - center
        dy = event.pos().y() - center
        dist = math.sqrt(dx * dx + dy * dy)
        
        was_hovered = self.is_hovered
        self.is_hovered = dist <= radius
        
        if was_hovered != self.is_hovered:
            self.update()
        
        # Cursor is always hand pointer since entire button widget is clickable
        # (already set in __init__)
    
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
    
    def showEvent(self, event):
        """Reset hiding flag when button is shown"""
        self.is_hiding = False
        super().showEvent(event)


