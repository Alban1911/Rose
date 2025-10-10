#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Professional Chroma Wheel UI using PyQt6
League of Legends style chroma selection
"""

import math
import sys
import threading
import re
import requests
from pathlib import Path
from typing import Optional, Callable, List, Dict
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer, QPoint, QPropertyAnimation, QEasingCurve, pyqtProperty, QByteArray
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QRadialGradient, QConicalGradient, QPainterPath, QPixmap
from utils.logging import get_logger, log_event, log_success, log_action
from utils.paths import get_skins_dir
from constants import (
    CHROMA_WHEEL_PREVIEW_WIDTH, CHROMA_WHEEL_PREVIEW_HEIGHT, CHROMA_WHEEL_CIRCLE_RADIUS,
    CHROMA_WHEEL_WINDOW_WIDTH, CHROMA_WHEEL_WINDOW_HEIGHT, CHROMA_WHEEL_CIRCLE_SPACING,
    CHROMA_WHEEL_BUTTON_SIZE, CHROMA_WHEEL_SCREEN_EDGE_MARGIN, CHROMA_WHEEL_PREVIEW_X,
    CHROMA_WHEEL_PREVIEW_Y, CHROMA_WHEEL_ROW_Y_OFFSET, CHROMA_WHEEL_GLOW_ALPHA,
    CHROMA_WHEEL_CONICAL_START_ANGLE, UI_QTIMER_CALLBACK_DELAY_MS,
    CHROMA_WHEEL_GOLD_BORDER_PX, CHROMA_WHEEL_DARK_BORDER_PX,
    CHROMA_WHEEL_GRADIENT_RING_PX, CHROMA_WHEEL_INNER_DISK_RADIUS_PX
)

log = get_logger()


class ChromaCircle:
    """Represents a single chroma circle in the wheel"""
    
    def __init__(self, chroma_id: int, name: str, color: str, x: int, y: int, radius: int, preview_image: Optional[QPixmap] = None):
        self.chroma_id = chroma_id
        self.name = name
        self.color = color
        self.x = x
        self.y = y
        self.radius = radius
        self.is_hovered = False
        self.is_selected = False
        self.scale = 1.0  # For animation
        self.preview_image = preview_image  # QPixmap for chroma preview


class ChromaWheelWidget(QWidget):
    """Professional chroma wheel widget with League-style design"""
    
    def __init__(self, on_chroma_selected: Callable[[int, str], None] = None):
        super().__init__()
        
        self.on_chroma_selected = on_chroma_selected
        self.circles = []
        self.skin_name = ""
        self.selected_index = 0  # Default to base (center)
        self.hovered_index = None
        
        # Dimensions - League style with horizontal layout
        self.preview_width = CHROMA_WHEEL_PREVIEW_WIDTH
        self.preview_height = CHROMA_WHEEL_PREVIEW_HEIGHT
        self.circle_radius = CHROMA_WHEEL_CIRCLE_RADIUS
        self.window_width = CHROMA_WHEEL_WINDOW_WIDTH
        self.window_height = CHROMA_WHEEL_WINDOW_HEIGHT
        self.circle_spacing = CHROMA_WHEEL_CIRCLE_SPACING
        
        # Preview image (will be downloaded/loaded)
        self.current_preview_image = None  # QPixmap for current chroma
        
        # Animation
        self._opacity = 0.0
        self.opacity_animation = None
        
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the window and styling"""
        # Frameless, always-on-top window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Remove WA_DeleteOnClose - we'll manage deletion manually with deleteLater()
        # self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        
        # Set window size
        self.setFixedSize(self.window_width, self.window_height)
        
        # Position on right side of screen
        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.width() - self.window_width - CHROMA_WHEEL_SCREEN_EDGE_MARGIN,
            (screen.height() - self.window_height) // 2  # Vertically centered
        )
        
        # Enable mouse tracking for hover effects
        self.setMouseTracking(True)
        
        # Set initial opacity
        self._opacity = 1.0
        
        # Start with window hidden
        self.hide()
    
    def set_chromas(self, skin_name: str, chromas: List[Dict], champion_name: str = None, selected_chroma_id: Optional[int] = None):
        """Set the chromas to display - League horizontal style"""
        self.skin_name = skin_name
        self.circles = []
        
        # Base skin gets no preview (will show red X)
        base_circle = ChromaCircle(
            chroma_id=0,
            name="Base",
            color="#1e2328",
            x=0,  # Will be positioned later
            y=0,
            radius=self.circle_radius,
            preview_image=None  # No preview for base
        )
        base_circle.is_selected = True
        self.circles.append(base_circle)
        
        # Add chroma circles
        for i, chroma in enumerate(chromas):
            # Get color from chroma data
            colors = chroma.get('colors', [])
            color = colors[0] if colors else self._get_default_color(i)
            if not color.startswith('#'):
                color = f"#{color}"
            
            # Extract short name (remove skin name prefix)
            full_name = chroma.get('name', f'Chroma {i+1}')
            
            # Extract just the chroma variant name (last word)
            words = full_name.split()
            short_name = words[-1] if words else full_name
            
            # Load chroma preview image with direct path
            chroma_id = chroma.get('id', 0)
            preview_image = self._load_chroma_preview_image(skin_name, chroma_id, champion_name)
            
            circle = ChromaCircle(
                chroma_id=chroma_id,
                name=short_name,
                color=color,
                x=0,  # Will be positioned later
                y=0,
                radius=self.circle_radius,
                preview_image=preview_image
            )
            self.circles.append(circle)
        
        # Position circles in horizontal row at bottom
        total_chromas = len(self.circles)
        row_y = self.window_height - CHROMA_WHEEL_ROW_Y_OFFSET
        
        # Calculate total width needed
        total_width = total_chromas * self.circle_spacing
        start_x = (self.window_width - total_width) // 2 + self.circle_spacing // 2
        
        for i, circle in enumerate(self.circles):
            circle.x = start_x + (i * self.circle_spacing)
            circle.y = row_y
        
        # Find the index of the currently selected chroma (if provided)
        self.selected_index = 0  # Default to base
        if selected_chroma_id is not None:
            for i, circle in enumerate(self.circles):
                if circle.chroma_id == selected_chroma_id:
                    self.selected_index = i
                    circle.is_selected = True
                    base_circle.is_selected = False  # Unselect base
                    log_event(log, f"Opening wheel at chroma: {circle.name} (Index: {i}, ID: {selected_chroma_id})", "🌈")
                    break
        
        self.hovered_index = None  # Start showing the selected chroma (not hovered)
        self.update()
    
    def _get_default_color(self, index: int) -> str:
        """Get default color for chroma"""
        colors = [
            "#ff6b6b", "#4ecdc4", "#ffe66d", "#a8e6cf", "#ff8b94",
            "#b4a7d6", "#ffd3b6", "#dcedc1", "#f8b195", "#95e1d3"
        ]
        return colors[index % len(colors)]
    
    def _load_chroma_preview_image(self, skin_name: str, chroma_id: Optional[int], champion_name: str = None) -> Optional[QPixmap]:
        """Load chroma preview image - checks cache first, then README if needed"""
        try:
            if chroma_id is None:
                # Base skin - return None (will show red X)
                return None
            
            # FIRST: Try loading directly from cache (fast path)
            # This works even if skins aren't downloaded, only previews
            from utils.chroma_preview_manager import get_preview_manager
            preview_manager = get_preview_manager()
            
            image_path = preview_manager.get_preview_path(chroma_id)
            if image_path:
                log.debug(f"[CHROMA] Loading preview from cache: {image_path.name}")
                return QPixmap(str(image_path))
            
            # SECOND: If not in cache, try to trigger download from README
            # (This path is used when skins are downloaded but previews aren't cached yet)
            skins_dir = get_skins_dir()
            
            # Direct path: skins/{Champion}/chromas/{SkinName}/README.md
            if champion_name:
                # Try direct path with champion name
                readme_path = skins_dir / champion_name / "chromas" / skin_name / "README.md"
                
                if readme_path.exists():
                    log.debug(f"[CHROMA] Found README at: {readme_path}")
                    return self._extract_image_from_readme(readme_path, chroma_id)
            
            # Fallback: search for the skin name in chromas directories
            for champion_dir in skins_dir.iterdir():
                if not champion_dir.is_dir():
                    continue
                
                chromas_dir = champion_dir / "chromas" / skin_name
                readme_path = chromas_dir / "README.md"
                
                if readme_path.exists():
                    log.debug(f"[CHROMA] Found README at: {readme_path}")
                    return self._extract_image_from_readme(readme_path, chroma_id)
            
            log.debug(f"[CHROMA] No preview found for chroma {chroma_id} ('{skin_name}')")
            return None
            
        except Exception as e:
            log.error(f"[CHROMA] Error loading chroma preview: {e}")
            return None
    
    def _extract_image_from_readme(self, readme_path: Path, chroma_id: int) -> Optional[QPixmap]:
        """Load image for specific chroma ID from cache (called when README exists)"""
        try:
            # Load from central previewcache folder
            from utils.chroma_preview_manager import get_preview_manager
            preview_manager = get_preview_manager()
            
            image_path = preview_manager.get_preview_path(chroma_id)
            
            if image_path:
                log.debug(f"[CHROMA] Loading preview from cache: {image_path.name}")
                return QPixmap(str(image_path))
            
            # Image not in cache - could trigger download here if needed
            log.debug(f"[CHROMA] Preview not in cache: {chroma_id}")
            return None
            
        except Exception as e:
            log.warning(f"[CHROMA] Error loading preview image: {e}")
            return None
    
    
    def show_wheel(self):
        """Show the wheel"""
        # Set opacity to 1.0 for visibility
        self._opacity = 1.0
        
        # Show window
        self.show()
        self.raise_()
        
        # Force a repaint
        self.update()
    
    def hide_wheel(self):
        """Hide the wheel immediately"""
        self.hide()
    
    @pyqtProperty(float)
    def opacity(self):
        return self._opacity
    
    @opacity.setter
    def opacity(self, value):
        self._opacity = value
        self.update()
    
    def paintEvent(self, event):
        """Paint the chroma wheel - League style"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        
        # Draw dark background with golden border (League style)
        painter.fillRect(self.rect(), QColor(10, 14, 39, 240))
        painter.setPen(QPen(QColor(200, 170, 110), 2))
        painter.drawRect(2, 2, self.window_width - 4, self.window_height - 4)
        
        # Draw preview area (large image at top)
        preview_x = CHROMA_WHEEL_PREVIEW_X
        preview_y = CHROMA_WHEEL_PREVIEW_Y
        preview_rect = (preview_x, preview_y, self.preview_width, self.preview_height)
        
        # Draw preview background with border on all sides
        painter.fillRect(preview_x, preview_y, self.preview_width, self.preview_height, QColor(20, 20, 30))
        painter.setPen(QPen(QColor(100, 100, 120), 1))
        painter.drawRect(preview_x, preview_y, self.preview_width, self.preview_height)
        
        # Draw hovered chroma preview image
        # If no button is hovered, show the currently selected/applied chroma
        hovered_name = "Base"
        preview_image = None
        
        # Use hovered index if hovering, otherwise use selected index (current applied chroma)
        display_index = self.hovered_index if self.hovered_index is not None else self.selected_index
        
        if display_index is not None and display_index < len(self.circles):
            display_circle = self.circles[display_index]
            hovered_name = display_circle.name
            preview_image = display_circle.preview_image
        
        # Check if this is base skin (chroma_id == 0)
        is_base = display_index == 0 or display_index is None
        
        if is_base:
            # Draw red crossmark (X) for base skin
            center_x = preview_x + self.preview_width // 2
            center_y = preview_y + self.preview_height // 2
            
            # Draw red X (reduced by 25%: 120 * 0.75 = 90)
            painter.setPen(QPen(QColor(220, 60, 60), 6))
            x_size = 90
            painter.drawLine(center_x - x_size, center_y - x_size, center_x + x_size, center_y + x_size)
            painter.drawLine(center_x + x_size, center_y - x_size, center_x - x_size, center_y + x_size)
            
        elif preview_image and not preview_image.isNull():
            # Draw image at native size without scaling for maximum quality
            # Center the image in preview area
            img_x = preview_x + (self.preview_width - preview_image.width()) // 2
            img_y = preview_y + (self.preview_height - preview_image.height()) // 2
            
            # Use high-quality rendering
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(img_x, img_y, preview_image)
        else:
            # No preview image - show placeholder
            painter.setPen(QColor(100, 100, 120))
            placeholder_font = QFont("Segoe UI", 12)
            painter.setFont(placeholder_font)
            painter.drawText(preview_x, preview_y, self.preview_width, self.preview_height,
                           Qt.AlignmentFlag.AlignCenter, "Preview\nNot Available")
        
        # Skin name removed - preview images use full height
        
        # Draw all chroma circles (horizontal row at bottom)
        for i, circle in enumerate(self.circles):
            self._draw_chroma_circle(painter, circle, i == self.selected_index)
    
    def _draw_chroma_circle(self, painter: QPainter, circle: ChromaCircle, is_selected: bool):
        """Draw a single chroma circle - League horizontal style"""
        # Small circles, no scaling
        radius = self.circle_radius
        
        # Main circle fill
        color = QColor(circle.color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPoint(circle.x, circle.y), radius, radius)
        
        # Border - golden ring for selected/hovered
        if is_selected:
            # Thick golden border for selected
            painter.setPen(QPen(QColor(200, 170, 110), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(circle.x, circle.y), radius + 4, radius + 4)
        elif circle.is_hovered:
            # Thin golden border for hovered
            painter.setPen(QPen(QColor(200, 170, 110), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(circle.x, circle.y), radius + 2, radius + 2)
        
        # White outline around circle
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(circle.x, circle.y), radius, radius)
    
    def mouseMoveEvent(self, event):
        """Handle mouse movement for hover effects"""
        pos = event.pos()
        
        # Check which circle is hovered
        hovered = None
        for i, circle in enumerate(self.circles):
            dx = pos.x() - circle.x
            dy = pos.y() - circle.y
            dist = math.sqrt(dx * dx + dy * dy)
            
            if dist <= circle.radius:
                hovered = i
                break
        
        # Update hover state
        if hovered != self.hovered_index:
            self.hovered_index = hovered
            for i, circle in enumerate(self.circles):
                circle.is_hovered = (i == hovered)
            self.update()
    
    def mousePressEvent(self, event):
        """Handle mouse click - instant selection"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            
            # Find clicked circle
            for i, circle in enumerate(self.circles):
                dx = pos.x() - circle.x
                dy = pos.y() - circle.y
                dist = math.sqrt(dx * dx + dy * dy)
                
                if dist <= circle.radius:
                    # Select this chroma
                    self.selected_index = i
                    
                    # Store selection
                    selected_id = circle.chroma_id
                    selected_name = circle.name
                    callback = self.on_chroma_selected
                    
                    # Hide widget first
                    self.hide()
                    
                    # Call callback after a delay (outside widget context)
                    if callback:
                        def call_cb():
                            callback(selected_id, selected_name)
                        QTimer.singleShot(UI_QTIMER_CALLBACK_DELAY_MS, call_cb)
                    return
        
        event.accept()
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        if event.key() == Qt.Key.Key_Escape:
            # Cancel - select base
            callback = self.on_chroma_selected
            self.hide()
            if callback:
                def call_cb():
                    callback(0, "Base")
                QTimer.singleShot(50, call_cb)
                
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            # Confirm current selection
            if self.selected_index < len(self.circles):
                circle = self.circles[self.selected_index]
                selected_id = circle.chroma_id
                selected_name = circle.name
                callback = self.on_chroma_selected
                
                self.hide()
                if callback:
                    def call_cb():
                        callback(selected_id, selected_name)
                    QTimer.singleShot(50, call_cb)
        
        event.accept()


class ReopenButton(QWidget):
    """Small circular button to reopen chroma wheel"""
    
    def __init__(self, on_click: Callable[[], None] = None):
        super().__init__()
        self.on_click = on_click
        self.is_hovered = False
        self.is_hiding = False  # Flag to prevent painting during hide
        
        # Setup window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Position in center of screen
        self.button_size = CHROMA_WHEEL_BUTTON_SIZE
        self.setFixedSize(self.button_size, self.button_size)
        
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.button_size) // 2,
            (screen.height() - self.button_size) // 2
        )
        
        self.setMouseTracking(True)
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
        gold_border_width = int(CHROMA_WHEEL_GOLD_BORDER_PX * scale_factor)
        transition1_width = int(1 * scale_factor)
        dark_border_width = int(CHROMA_WHEEL_DARK_BORDER_PX * scale_factor)
        transition2_width = int(1 * scale_factor)
        gradient_ring_width = int(CHROMA_WHEEL_GRADIENT_RING_PX * scale_factor)
        transition3_width = int(1 * scale_factor)
        inner_disk_radius = CHROMA_WHEEL_INNER_DISK_RADIUS_PX * scale_factor
        
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
        
        # Glow effect on hover (subtle outer glow)
        if self.is_hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(255, 215, 0, CHROMA_WHEEL_GLOW_ALPHA)))  # Gold glow
            painter.drawEllipse(QPoint(center, center), outer_gold_radius + 3, outer_gold_radius + 3)
        
        # 1. Outer metallic gold border (7% of button size)
        gold_gradient = QRadialGradient(center, center, outer_gold_radius)
        gold_gradient.setColorAt(0.0, QColor(255, 215, 0))  # Bright gold
        gold_gradient.setColorAt(0.7, QColor(255, 165, 0))  # Orange gold
        gold_gradient.setColorAt(1.0, QColor(184, 134, 11))  # Dark gold
        
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
        painter.setBrush(QBrush(QColor(20, 20, 20)))  # Dark border
        painter.drawPath(dark_border_path)
        
        # 3. Rainbow gradient ring (4px width) - yellow starts at top
        # Draw gradient as outer circle, then cut out the inner part with dark color
        rainbow_gradient = QConicalGradient(center, center, CHROMA_WHEEL_CONICAL_START_ANGLE)  # Start angle to position colors
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
        painter.setBrush(QBrush(QColor(20, 20, 20)))  # Same dark color as center
        painter.drawEllipse(center - int(gradient_inner_radius), center - int(gradient_inner_radius), 
                           int(gradient_inner_radius) * 2, int(gradient_inner_radius) * 2)
        
        # 4. Dark central disk (5px diameter = 2.5px radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(20, 20, 20)))  # Very dark center
        painter.drawEllipse(center - int(inner_radius), center - int(inner_radius), 
                           int(inner_radius) * 2, int(inner_radius) * 2)
    
    def mousePressEvent(self, event):
        """Handle button click"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Set hiding flag to prevent any repaints
            self.is_hiding = True
            # Force immediate repaint to clear the button visually
            self.update()
            # Call the callback immediately (manager will handle actual hiding)
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
    
    def leaveEvent(self, event):
        """Handle mouse leave"""
        if self.is_hovered:
            self.is_hovered = False
            self.update()
    
    def showEvent(self, event):
        """Reset hiding flag when button is shown"""
        self.is_hiding = False
        super().showEvent(event)


class ChromaWheelManager:
    """Manages PyQt6 chroma wheel - uses polling instead of QTimer"""
    
    def __init__(self, on_chroma_selected: Callable[[int, str], None] = None):
        self.on_chroma_selected = on_chroma_selected
        self.widget = None
        self.reopen_button = None
        self.is_initialized = False
        self.pending_show = None  # (skin_name, chromas) to show from other threads
        self.pending_hide = False
        self.pending_show_button = False
        self.pending_hide_button = False
        self.pending_create = False  # Request to create widgets
        self.pending_destroy = False  # Request to destroy widgets
        self.current_skin_id = None  # Track current skin for button
        self.current_skin_name = None
        self.current_chromas = None
        self.current_champion_name = None  # Track champion for direct path
        self.current_selected_chroma_id = None  # Track currently applied chroma
        self.lock = threading.Lock()
    
    def request_create(self):
        """Request to create the wheel (thread-safe, will be created in main thread)"""
        with self.lock:
            if not self.is_initialized:
                self.pending_create = True
                log.debug("[CHROMA] Create wheel requested")
    
    def request_destroy(self):
        """Request to destroy the wheel (thread-safe, will be destroyed in main thread)"""
        with self.lock:
            self.pending_destroy = True
            log.debug("[CHROMA] Destroy wheel requested")
    
    def _create_widgets(self):
        """Create widgets (must be called from main thread)"""
        if not self.is_initialized:
            self.widget = ChromaWheelWidget(on_chroma_selected=self._on_chroma_selected_wrapper)
            self.reopen_button = ReopenButton(on_click=self._on_reopen_clicked)
            self.is_initialized = True
            log.info("[CHROMA] Wheel widgets created")
    
    def _destroy_widgets(self):
        """Destroy widgets (must be called from main thread)"""
        if self.is_initialized:
            if self.widget:
                try:
                    # Use hide() + deleteLater() instead of close() to avoid blocking
                    self.widget.hide()
                    self.widget.deleteLater()
                    self.widget = None
                except Exception as e:
                    log.warning(f"[CHROMA] Error destroying wheel widget: {e}")
            if self.reopen_button:
                try:
                    # Use hide() + deleteLater() instead of close() to avoid blocking
                    self.reopen_button.hide()
                    self.reopen_button.deleteLater()
                    self.reopen_button = None
                except Exception as e:
                    log.warning(f"[CHROMA] Error destroying reopen button: {e}")
            self.is_initialized = False
            self.last_skin_name = None
            self.last_chromas = None
            log.info("[CHROMA] Wheel widgets destroyed")
    
    def _on_chroma_selected_wrapper(self, chroma_id: int, chroma_name: str):
        """Wrapper for chroma selection - shows button again after selection"""
        # Call the original callback
        if self.on_chroma_selected:
            self.on_chroma_selected(chroma_id, chroma_name)
        
        # Track the selected chroma ID
        with self.lock:
            self.current_selected_chroma_id = chroma_id if chroma_id != 0 else None
            log_event(log, f"Chroma selected: {chroma_name}" if chroma_id != 0 else "Base skin selected", "✨")
            self.pending_show_button = True
    
    def _on_reopen_clicked(self):
        """Handle button click - show the wheel for current skin"""
        with self.lock:
            if self.current_skin_name and self.current_chromas:
                log_action(log, f"Opening wheel for {self.current_skin_name}", "🎨")
                self.pending_show = (self.current_skin_name, self.current_chromas)
                self.pending_hide_button = True
                self.pending_show_button = False  # Cancel any pending show to prevent blink
    
    def show_button_for_skin(self, skin_id: int, skin_name: str, chromas: List[Dict], champion_name: str = None):
        """Show button for a skin (not the wheel itself)"""
        if not chromas or len(chromas) == 0:
            log.debug(f"[CHROMA] No chromas for {skin_name}, hiding button")
            self.hide_reopen_button()
            return
        
        with self.lock:
            if not self.is_initialized:
                log.warning("[CHROMA] Wheel not initialized - cannot show button")
                return
            
            # If switching to a different skin, hide the wheel and reset selection
            if self.current_skin_id is not None and self.current_skin_id != skin_id:
                log.debug(f"[CHROMA] Switching skins - hiding wheel and resetting selection")
                self.pending_hide = True
                self.current_selected_chroma_id = None  # Reset selection for new skin
            
            # Update current skin data for button (store champion name for later)
            self.current_skin_id = skin_id
            self.current_skin_name = skin_name
            self.current_chromas = chromas
            self.current_champion_name = champion_name  # Store for image loading
            
            log.debug(f"[CHROMA] Showing button for {skin_name} ({len(chromas)} chromas)")
            self.pending_show_button = True
    
    def show_wheel_directly(self):
        """Request to show the chroma wheel for current skin (called by button click)"""
        with self.lock:
            if self.current_skin_name and self.current_chromas:
                log.info(f"[CHROMA] Request to show wheel for {self.current_skin_name}")
                self.pending_show = (self.current_skin_name, self.current_chromas)
                self.pending_hide_button = True
    
    def process_pending(self):
        """Process pending show/hide requests (must be called from main thread)"""
        with self.lock:
            # Process create request
            if self.pending_create:
                self.pending_create = False
                try:
                    self._create_widgets()
                except Exception as e:
                    log.error(f"[CHROMA] Error creating widgets: {e}")
            
            # Process destroy request
            if self.pending_destroy:
                self.pending_destroy = False
                try:
                    log.debug("[CHROMA] Starting widget destruction...")
                    self._destroy_widgets()
                    log.debug("[CHROMA] Widget destruction completed")
                except Exception as e:
                    log.error(f"[CHROMA] Error destroying widgets: {e}")
                return  # Don't process other requests after destroying
            
            # Process show request
            if self.pending_show:
                skin_name, chromas = self.pending_show
                self.pending_show = None
                
                if self.widget:
                    # Pass the currently selected chroma ID so wheel opens at that index
                    self.widget.set_chromas(skin_name, chromas, self.current_champion_name, self.current_selected_chroma_id)
                    self.widget.show_wheel()
                    self.widget.setVisible(True)
                    self.widget.raise_()
                    log_success(log, f"Chroma wheel displayed for {skin_name}", "🎨")
            
            # Process hide request
            if self.pending_hide:
                self.pending_hide = False
                if self.widget:
                    self.widget.hide()
            
            # Process reopen button hide request BEFORE show request to prevent blinking
            if self.pending_hide_button:
                self.pending_hide_button = False
                self.pending_show_button = False  # Cancel any pending show to prevent blink
                if self.reopen_button:
                    self.reopen_button.hide()
            # Process reopen button show request (only if not hiding)
            elif self.pending_show_button:
                self.pending_show_button = False
                if self.reopen_button:
                    self.reopen_button.show()
                    self.reopen_button.raise_()
                    log.debug("[CHROMA] Reopen button shown")
    
    def hide(self):
        """Request to hide the chroma wheel (thread-safe)"""
        with self.lock:
            self.pending_hide = True
    
    def hide_reopen_button(self):
        """Request to hide the reopen button (thread-safe)"""
        with self.lock:
            self.pending_hide_button = True
    
    def cleanup(self):
        """Clean up resources (called on app exit)"""
        self.request_destroy()


# Global instance
_wheel_manager = None


def get_chroma_wheel() -> ChromaWheelManager:
    """Get global chroma wheel manager"""
    global _wheel_manager
    if _wheel_manager is None:
        _wheel_manager = ChromaWheelManager()
    return _wheel_manager


if __name__ == "__main__":
    # Test the wheel
    def on_selected(chroma_id: int, chroma_name: str):
        print(f"Selected: {chroma_name} (ID: {chroma_id})")
    
    app = QApplication(sys.argv)
    
    wheel = ChromaWheelWidget(on_chroma_selected=on_selected)
    
    test_chromas = [
        {'id': 1, 'name': 'Ruby', 'colors': ['#e74c3c']},
        {'id': 2, 'name': 'Sapphire', 'colors': ['#3498db']},
        {'id': 3, 'name': 'Emerald', 'colors': ['#2ecc71']},
        {'id': 4, 'name': 'Amethyst', 'colors': ['#9b59b6']},
        {'id': 5, 'name': 'Pearl', 'colors': ['#ecf0f1']},
        {'id': 6, 'name': 'Obsidian', 'colors': ['#2c3e50']},
    ]
    
    wheel.set_chromas("PROJECT: Ashe", test_chromas)
    wheel.show_wheel()
    
    sys.exit(app.exec())
