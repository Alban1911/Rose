#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Professional Chroma Wheel UI using PyQt6
League of Legends style chroma selection
"""

import math
import sys
import threading
from typing import Optional, Callable, List, Dict
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer, QPoint, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QRadialGradient, QPainterPath
from utils.logging import get_logger

log = get_logger()


class ChromaCircle:
    """Represents a single chroma circle in the wheel"""
    
    def __init__(self, chroma_id: int, name: str, color: str, x: int, y: int, radius: int):
        self.chroma_id = chroma_id
        self.name = name
        self.color = color
        self.x = x
        self.y = y
        self.radius = radius
        self.is_hovered = False
        self.is_selected = False
        self.scale = 1.0  # For animation


class ChromaWheelWidget(QWidget):
    """Professional chroma wheel widget with League-style design"""
    
    def __init__(self, on_chroma_selected: Callable[[int, str], None] = None):
        super().__init__()
        
        self.on_chroma_selected = on_chroma_selected
        self.circles = []
        self.skin_name = ""
        self.selected_index = 0  # Default to base (center)
        self.hovered_index = None
        
        # Dimensions
        self.wheel_radius = 180
        self.circle_radius = 35
        self.center_radius = 45
        self.window_width = 500
        self.window_height = 500
        
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
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        
        # Set window size
        self.setFixedSize(self.window_width, self.window_height)
        
        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.window_width) // 2,
            (screen.height() - self.window_height) // 2
        )
        
        # Enable mouse tracking for hover effects
        self.setMouseTracking(True)
        
        # Set initial opacity
        self._opacity = 1.0
        
        # Start with window hidden
        self.hide()
    
    def set_chromas(self, skin_name: str, chromas: List[Dict]):
        """Set the chromas to display"""
        self.skin_name = skin_name
        self.circles = []
        
        # Always add base skin in center
        center_x = self.window_width // 2
        center_y = self.window_height // 2
        
        base_circle = ChromaCircle(
            chroma_id=0,
            name="Base",
            color="#1e2328",
            x=center_x,
            y=center_y,
            radius=self.center_radius
        )
        base_circle.is_selected = True
        self.circles.append(base_circle)
        
        # Add surrounding chromas
        num_chromas = len(chromas)
        for i, chroma in enumerate(chromas):
            angle = (i * (2 * math.pi / num_chromas)) - (math.pi / 2)
            x = center_x + int(self.wheel_radius * math.cos(angle))
            y = center_y + int(self.wheel_radius * math.sin(angle))
            
            # Get color from chroma data
            colors = chroma.get('colors', [])
            color = colors[0] if colors else self._get_default_color(i)
            if not color.startswith('#'):
                color = f"#{color}"
            
            # Extract short name (remove skin name prefix)
            full_name = chroma.get('name', f'Chroma {i+1}')
            short_name = full_name.split(' ')[-1] if ' ' in full_name else full_name
            
            circle = ChromaCircle(
                chroma_id=chroma.get('id', 0),
                name=short_name,
                color=color,
                x=x,
                y=y,
                radius=self.circle_radius
            )
            self.circles.append(circle)
        
        self.selected_index = 0  # Default to base
        self.update()
    
    def _get_default_color(self, index: int) -> str:
        """Get default color for chroma"""
        colors = [
            "#ff6b6b", "#4ecdc4", "#ffe66d", "#a8e6cf", "#ff8b94",
            "#b4a7d6", "#ffd3b6", "#dcedc1", "#f8b195", "#95e1d3"
        ]
        return colors[index % len(colors)]
    
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
        """Paint the chroma wheel"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        
        # Draw semi-transparent background
        painter.fillRect(self.rect(), QColor(10, 14, 39, 200))
        
        # Draw title
        painter.setPen(QColor(240, 230, 210))
        title_font = QFont("Segoe UI", 18, QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.drawText(0, 30, self.window_width, 40, Qt.AlignmentFlag.AlignCenter, "Select Chroma")
        
        # Draw skin name
        painter.setPen(QColor(200, 170, 110))
        name_font = QFont("Segoe UI", 12)
        painter.setFont(name_font)
        painter.drawText(0, 70, self.window_width, 30, Qt.AlignmentFlag.AlignCenter, self.skin_name)
        
        # Draw all chroma circles
        for i, circle in enumerate(self.circles):
            self._draw_chroma_circle(painter, circle, i == self.selected_index)
        
        # Draw hint text
        painter.setPen(QColor(180, 180, 180))
        hint_font = QFont("Segoe UI", 10)
        painter.setFont(hint_font)
        painter.drawText(0, self.window_height - 30, self.window_width, 30, 
                        Qt.AlignmentFlag.AlignCenter, "Click to select • ESC to cancel")
    
    def _draw_chroma_circle(self, painter: QPainter, circle: ChromaCircle, is_selected: bool):
        """Draw a single chroma circle with effects"""
        # Scale for hover/selection
        scale = 1.15 if circle.is_hovered else (1.1 if is_selected else 1.0)
        radius = int(circle.radius * scale)
        
        # Outer glow for selected/hovered
        if is_selected or circle.is_hovered:
            glow_color = QColor(240, 230, 210, 80) if is_selected else QColor(200, 170, 110, 60)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow_color))
            painter.drawEllipse(QPoint(circle.x, circle.y), radius + 8, radius + 8)
        
        # Main circle with gradient
        color = QColor(circle.color)
        gradient = QRadialGradient(circle.x, circle.y, radius)
        gradient.setColorAt(0.0, color.lighter(120))
        gradient.setColorAt(1.0, color)
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QPoint(circle.x, circle.y), radius, radius)
        
        # Border
        border_color = QColor(240, 230, 210) if is_selected else QColor(91, 90, 86)
        border_width = 4 if is_selected else 2
        if circle.is_hovered and not is_selected:
            border_color = QColor(200, 170, 110)
            border_width = 3
        
        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(circle.x, circle.y), radius, radius)
        
        # Text label
        painter.setPen(QColor(255, 255, 255))
        label_font = QFont("Segoe UI", 9 if circle.radius < 40 else 11, QFont.Weight.Bold)
        painter.setFont(label_font)
        
        # Truncate long names
        name = circle.name[:8] if len(circle.name) > 8 else circle.name
        
        text_rect = painter.boundingRect(
            circle.x - radius, circle.y - 10,
            radius * 2, 20,
            Qt.AlignmentFlag.AlignCenter,
            name
        )
        
        # Text shadow
        painter.setPen(QColor(0, 0, 0, 150))
        painter.drawText(text_rect.adjusted(1, 1, 1, 1), Qt.AlignmentFlag.AlignCenter, name)
        
        # Main text
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, name)
    
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
                        QTimer.singleShot(50, call_cb)
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
        
        # Setup window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Position in center of screen
        self.button_size = 60
        self.setFixedSize(self.button_size, self.button_size)
        
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.button_size) // 2,
            (screen.height() - self.button_size) // 2
        )
        
        self.setMouseTracking(True)
        self.hide()
    
    def paintEvent(self, event):
        """Paint the circular button"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw circle
        center = self.button_size // 2
        radius = (self.button_size // 2) - 5
        
        # Glow effect on hover
        if self.is_hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(200, 170, 110, 100)))
            painter.drawEllipse(QPoint(center, center), radius + 4, radius + 4)
        
        # Main circle
        gradient = QRadialGradient(center, center, radius)
        gradient.setColorAt(0.0, QColor(200, 170, 110))
        gradient.setColorAt(1.0, QColor(150, 120, 70))
        
        painter.setPen(QPen(QColor(240, 230, 210), 2))
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QPoint(center, center), radius, radius)
        
        # Draw palette icon (3 small colored circles)
        icon_radius = 6
        icon_y = center
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        
        # Left circle (red)
        painter.setBrush(QBrush(QColor(255, 100, 100)))
        painter.drawEllipse(QPoint(center - 12, icon_y), icon_radius, icon_radius)
        
        # Center circle (green)
        painter.setBrush(QBrush(QColor(100, 255, 100)))
        painter.drawEllipse(QPoint(center, icon_y), icon_radius, icon_radius)
        
        # Right circle (blue)
        painter.setBrush(QBrush(QColor(100, 100, 255)))
        painter.drawEllipse(QPoint(center + 12, icon_y), icon_radius, icon_radius)
    
    def mousePressEvent(self, event):
        """Handle button click"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.on_click:
                def call_cb():
                    self.on_click()
                QTimer.singleShot(10, call_cb)
            self.hide()
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
        self.last_skin_name = None
        self.last_chromas = None
        self.lock = threading.Lock()
    
    def initialize(self):
        """Initialize the widget (must be called from main thread)"""
        if not self.is_initialized:
            # Widget must be created in main thread
            self.widget = ChromaWheelWidget(on_chroma_selected=self._on_chroma_selected_wrapper)
            self.reopen_button = ReopenButton(on_click=self._on_reopen_clicked)
            self.is_initialized = True
            log.debug("[CHROMA] PyQt6 chroma wheel initialized")
    
    def _on_chroma_selected_wrapper(self, chroma_id: int, chroma_name: str):
        """Wrapper for chroma selection - shows reopen button after selection"""
        # Call the original callback
        if self.on_chroma_selected:
            self.on_chroma_selected(chroma_id, chroma_name)
        
        # Show reopen button
        with self.lock:
            self.pending_show_button = True
    
    def _on_reopen_clicked(self):
        """Handle reopen button click - show the wheel again"""
        with self.lock:
            if self.last_skin_name and self.last_chromas:
                log.info(f"[CHROMA] Reopening wheel for {self.last_skin_name}")
                self.pending_show = (self.last_skin_name, self.last_chromas)
                self.pending_hide_button = True
    
    def show(self, skin_name: str, chromas: List[Dict]):
        """Request to show the chroma wheel (thread-safe, will be shown in main thread)"""
        if not chromas or len(chromas) == 0:
            log.debug(f"[CHROMA] No chromas for {skin_name}, skipping wheel")
            return
        
        with self.lock:
            if not self.is_initialized or not self.widget:
                log.warning("[CHROMA] Wheel not initialized - cannot show")
                return
            
            log.info(f"[CHROMA] Request to show wheel for {skin_name} ({len(chromas)} chromas)")
            
            # Store for reopening
            self.last_skin_name = skin_name
            self.last_chromas = chromas
            
            # Store request to be processed by main thread
            self.pending_show = (skin_name, chromas)
            
            # Hide reopen button when showing wheel
            self.pending_hide_button = True
    
    def process_pending(self):
        """Process pending show/hide requests (must be called from main thread)"""
        with self.lock:
            # Process show request
            if self.pending_show:
                skin_name, chromas = self.pending_show
                self.pending_show = None
                
                if self.widget:
                    self.widget.set_chromas(skin_name, chromas)
                    self.widget.show_wheel()
                    self.widget.setVisible(True)
                    self.widget.raise_()
                    log.info(f"[CHROMA] ✓ Wheel displayed for {skin_name}")
            
            # Process hide request
            if self.pending_hide:
                self.pending_hide = False
                if self.widget:
                    self.widget.hide()
            
            # Process reopen button show request
            if self.pending_show_button:
                self.pending_show_button = False
                if self.reopen_button:
                    self.reopen_button.show()
                    self.reopen_button.raise_()
                    log.debug("[CHROMA] Reopen button shown")
            
            # Process reopen button hide request
            if self.pending_hide_button:
                self.pending_hide_button = False
                if self.reopen_button:
                    self.reopen_button.hide()
    
    def hide(self):
        """Request to hide the chroma wheel (thread-safe)"""
        with self.lock:
            self.pending_hide = True
    
    def hide_reopen_button(self):
        """Request to hide the reopen button (thread-safe)"""
        with self.lock:
            self.pending_hide_button = True
    
    def cleanup(self):
        """Clean up resources"""
        with self.lock:
            if self.widget:
                self.widget.close()
                self.widget = None
            if self.reopen_button:
                self.reopen_button.close()
                self.reopen_button = None


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
