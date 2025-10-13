#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Chroma Panel Widget - Main UI component for chroma selection
"""

import math
from pathlib import Path
from typing import Optional, Callable, List, Dict
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QPixmap
from utils.chroma_base import ChromaWidgetBase
from utils.chroma_scaling import get_scaled_chroma_values
from utils.logging import get_logger, log_event
from utils.paths import get_skins_dir
import config

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


class ChromaPanelWidget(ChromaWidgetBase):
    """Professional chroma panel widget with League-style design"""
    
    def __init__(self, on_chroma_selected: Callable[[int, str], None] = None, manager=None):
        super().__init__()
        
        self.on_chroma_selected = on_chroma_selected
        self.manager = manager  # Reference to ChromaPanelManager for rebuild requests
        self.circles = []
        self.skin_name = ""
        self.selected_index = 0  # Default to base (center)
        self.hovered_index = None
        self.reopen_button_ref = None  # Reference to button widget for click detection
        
        # Track mouse press position for click-and-release detection
        self._press_pos = None
        
        # Get scaled values for current resolution
        self.scaled = get_scaled_chroma_values()
        self._current_resolution = self.scaled.resolution  # Track resolution for change detection
        
        # Dimensions - League style with horizontal layout (using scaled values)
        self._update_dimensions_from_scaled()
        
        # Track actual display dimensions (may differ from scaled at very small resolutions)
        self._display_width = self.window_width
        self._display_height = self.window_height
        self._scale_factor = 1.0  # Scale factor for constrained layouts
        self._updating_resolution = False  # Flag to prevent recursive updates
        
        # Initialize preview positions from scaled values (will be overridden on resolution change)
        self._preview_x = self.scaled.preview_x
        self._preview_y = self.scaled.preview_y
        
        # Preview image (will be downloaded/loaded)
        self.current_preview_image = None  # QPixmap for current chroma
        
        # Background image
        self.background_image = None  # QPixmap for champ-select-flyout-background.jpg
        self._load_background_image()
        
        # Animation
        self._opacity = 0.0
        self.opacity_animation = None
        
        # Install event filter to detect clicks outside the widget
        QApplication.instance().installEventFilter(self)
        
        self.setup_ui()
    
    def _load_background_image(self):
        """Load the champ-select-flyout-background.jpg image"""
        try:
            # Try to load the background image from the assets folder
            background_path = Path(__file__).parent.parent / "assets" / "champ-select-flyout-background.jpg"
            if background_path.exists():
                self.background_image = QPixmap(str(background_path))
                log.debug(f"Loaded background image: {background_path}")
            else:
                log.debug(f"Background image not found: {background_path}")
                self.background_image = None
        except Exception as e:
            log.debug(f"Failed to load background image: {e}")
            self.background_image = None
        
    def setup_ui(self):
        """Setup the window and styling"""
        # Common window flags already set by parent class
        
        # Set window size - add extra height for notch extending outside (15px for 45° angles)
        self.notch_height = 15
        self.setFixedSize(self.window_width, self.window_height + self.notch_height)
        
        # Create window mask to define the visible shape (including notch)
        self._update_window_mask()
        
        # Position using the synchronized positioning system
        # Panel offset from anchor point (button is also centered on anchor)
        # Calculate offset based on config ratio
        import config
        from utils.window_utils import get_league_window_client_size
        
        current_res = get_league_window_client_size()
        if not current_res:
            log.error("[CHROMA] Cannot create panel - League window not found")
            return  # Cannot setup UI without League window
        
        window_width, window_height = current_res
        
        # Calculate panel offset using config ratio
        # X offset uses WIDTH, Y offset uses HEIGHT for proper scaling
        panel_offset_x = int(window_width * config.CHROMA_UI_PANEL_OFFSET_X_RATIO)
        panel_offset_y = int(window_height * config.CHROMA_UI_PANEL_OFFSET_Y_BASE_RATIO)
        
        self.position_relative_to_anchor(
            width=self.window_width,
            height=self.window_height + self.notch_height,
            offset_x=panel_offset_x,  # Now uses config!
            offset_y=panel_offset_y   # Now uses config even in test mode!
        )
        
        # Set initial opacity
        self._opacity = 1.0
        
        # Track if we should ignore next deactivate (when clicking button to close)
        self.ignore_next_deactivate = False
        self.deactivate_timer = None
        
        # Start with window hidden
        self.hide()
    
    def _update_window_mask(self):
        """Update the window mask to define the visible region including the notch"""
        from PyQt6.QtGui import QRegion, QPolygon
        from PyQt6.QtCore import QPoint
        
        # Get ACTUAL widget size from Qt (what's really set)
        actual_width = self.width()
        actual_height = self.height()
        
        # Panel height is total height minus notch
        panel_height = actual_height - self.notch_height
        
        # Calculate notch geometry (must match paintEvent parameters exactly)
        notch_width = 31  # Width of the triangle base (odd number for true center)
        notch_height = self.notch_height
        notch_center_x = actual_width // 2
        notch_start_x = notch_center_x - (notch_width // 2)
        notch_end_x = notch_center_x + (notch_width // 2) + 1  # +1 to get full 31 pixels
        notch_base_y = panel_height  # Base at panel bottom (before notch area)
        notch_tip_y = actual_height - 1  # Tip at total widget height
        
        # Create polygon for the entire window shape (rectangle + notch triangle)
        points = [
            QPoint(0, 0),                              # Top-left
            QPoint(actual_width, 0),                   # Top-right
            QPoint(actual_width, panel_height),        # Bottom-right (before notch)
            QPoint(notch_end_x, notch_base_y),         # Right side of notch base
            QPoint(notch_center_x, notch_tip_y),       # Notch tip
            QPoint(notch_start_x, notch_base_y),       # Left side of notch base
            QPoint(0, panel_height),                   # Bottom-left (before notch)
        ]
        
        polygon = QPolygon(points)
        region = QRegion(polygon)
        self.setMask(region)
    
    def _update_dimensions_from_scaled(self):
        """Update all dimension properties from scaled values"""
        self.preview_width = self.scaled.preview_width
        self.preview_height = self.scaled.preview_height
        self.circle_radius = self.scaled.circle_radius
        self.window_width = self.scaled.window_width
        self.window_height = self.scaled.window_height
        self.circle_spacing = self.scaled.circle_spacing
    
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
                log.info(f"[CHROMA] Panel resolution changed from {self._current_resolution} to {current_resolution}, requesting rebuild")
                
                # Update current resolution to prevent re-detection
                self._current_resolution = current_resolution
                
                # Request rebuild from manager instead of updating in place
                # This prevents flickering and ensures clean scaling
                if self.manager:
                    self.manager.request_rebuild()
                else:
                    log.warning("[CHROMA] Panel has no manager reference, cannot request rebuild")
                
                # Clear update flag
                self._updating_resolution = False
        except Exception as e:
            log.error(f"[CHROMA] Error checking panel resolution: {e}")
            import traceback
            log.error(traceback.format_exc())
            # Clear flag even on error
            self._updating_resolution = False
    
    def _recalculate_circle_positions(self):
        """Recalculate circle positions after resolution change"""
        if not self.circles:
            return
        
        # Use actual display dimensions (hardcoded for each resolution)
        actual_width = self._display_width if hasattr(self, '_display_width') else self.window_width
        actual_height = self._display_height if hasattr(self, '_display_height') else self.window_height
        
        # Use hardcoded preview dimensions
        preview_x = self._preview_x if hasattr(self, '_preview_x') else self.scaled.preview_x
        preview_y = self._preview_y if hasattr(self, '_preview_y') else self.scaled.preview_y
        preview_height = self.preview_height
        
        # Recalculate horizontal row positions (same logic as set_chromas)
        num_circles = len(self.circles)
        total_width = num_circles * self.circle_spacing
        start_x = (actual_width - total_width) // 2 + self.circle_spacing // 2
        
        # Calculate Y position in button zone (between separator and bottom)
        separator_y = preview_y + preview_height
        bottom_y = actual_height - 1
        row_y = (separator_y + bottom_y) // 2
        
        # Update circle positions and radius
        for i, circle in enumerate(self.circles):
            circle.x = start_x + (i * self.circle_spacing)
            circle.y = row_y
            circle.radius = self.circle_radius  # Update radius to hardcoded value
    
    def set_chromas(self, skin_name: str, chromas: List[Dict], champion_name: str = None, selected_chroma_id: Optional[int] = None):
        """Set the chromas to display - League horizontal style
        
        Note: The chromas list should already be filtered to only include unowned chromas
        by the ChromaSelector before being passed to this method.
        """
        self.skin_name = skin_name
        self.circles = []
        
        # Load base skin preview
        base_preview = self._load_chroma_preview_image(skin_name, chroma_id=0, champion_name=champion_name)
        
        base_circle = ChromaCircle(
            chroma_id=0,
            name="Base",
            color="#1e2328",
            x=0,  # Will be positioned later
            y=0,
            radius=self.circle_radius,
            preview_image=base_preview  # Load base skin preview
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
        
        # Position circles in horizontal row, centered vertically in button zone
        total_chromas = len(self.circles)
        # Button zone is between separator line and bottom border
        separator_y = self.scaled.preview_y + self.preview_height
        bottom_border_y = self.window_height - 1
        row_y = (separator_y + bottom_border_y) // 2
        
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
        """Load chroma preview image from SkinPreviews repository"""
        try:
            if champion_name is None:
                log.debug(f"[CHROMA] No champion name provided for preview")
                return None
            
            # Load from SkinPreviews repository
            from utils.chroma_preview_manager import get_preview_manager
            preview_manager = get_preview_manager()
            
            image_path = preview_manager.get_preview_path(champion_name, skin_name, chroma_id)
            
            if image_path:
                log.debug(f"[CHROMA] Loading preview: {image_path.name}")
                return QPixmap(str(image_path))
            
            log.debug(f"[CHROMA] No preview found for {champion_name}/{skin_name}/chroma_{chroma_id}")
            return None
            
        except Exception as e:
            log.error(f"[CHROMA] Error loading chroma preview: {e}")
            return None
    
    
    def set_button_reference(self, button_widget):
        """Set reference to the reopen button for click detection"""
        self.reopen_button_ref = button_widget
    
    def show_wheel(self, button_pos=None):
        """Show the panel (button_pos parameter kept for backward compatibility but unused)"""
        # Set opacity to 1.0 for visibility
        self._opacity = 1.0
        
        # Position is handled by base class position_relative_to_anchor()
        # No manual positioning needed - the anchor-based system handles alignment perfectly
        
        # Show window
        self.show()
        self.raise_()
        
        # Force a repaint
        self.update()
    
    def hide(self):
        """Override hide to cancel deactivate timer"""
        # Cancel any pending deactivate timer
        if self.deactivate_timer:
            self.deactivate_timer.stop()
            self.deactivate_timer = None
        super().hide()
    
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
        """Paint the chroma panel - League style"""
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        
        # Get ACTUAL widget dimensions from Qt
        actual_width = self.width()
        actual_height = self.height()
        
        # Panel height is widget height minus notch extension
        panel_height = actual_height - self.notch_height
        
        # Define notch parameters
        notch_width = 31  # Width of the triangle base (odd number for true center)
        notch_height = self.notch_height  # Height of the triangle (pointing outward)
        notch_center_x = actual_width // 2
        # For odd notch_width (31): left side gets 15 pixels, right side gets 15 pixels, center is at center
        notch_start_x = notch_center_x - (notch_width // 2)
        notch_end_x = notch_center_x + (notch_width // 2) + 1  # +1 to get full 31 pixels
        notch_base_y = panel_height  # Base of the notch (at panel bottom)
        notch_tip_y = actual_height - 1  # Tip at total widget height
        
        # Create widget path with triangular notch pointing outward
        widget_path = QPainterPath()
        widget_path.moveTo(1, 1)  # Top-left (inside border)
        widget_path.lineTo(actual_width - 1, 1)  # Top-right (inside border)
        widget_path.lineTo(actual_width - 1, panel_height)  # Bottom-right (at notch base)
        widget_path.lineTo(notch_end_x, notch_base_y)  # Right side of notch base
        widget_path.lineTo(notch_center_x, notch_tip_y)  # Tip pointing outward
        widget_path.lineTo(notch_start_x, notch_base_y)  # Left side of notch base
        widget_path.lineTo(1, panel_height)  # Bottom-left (at notch base)
        widget_path.closeSubpath()
        
        # Enable antialiasing for images
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # LAYER 1: Draw background image first (behind everything)
        # Use hardcoded preview positions if available (set during resolution changes)
        preview_x = self._preview_x if hasattr(self, '_preview_x') else self.scaled.preview_x
        preview_y = self._preview_y if hasattr(self, '_preview_y') else self.scaled.preview_y
        preview_rect = (preview_x, preview_y, self.preview_width, self.preview_height)
        
        if self.background_image and not self.background_image.isNull():
            # Clip to the widget shape so background respects borders
            painter.setClipPath(widget_path)
            
            # Scale background to exactly fit the panel (not including notch)
            scaled_bg = self.background_image.scaled(
                actual_width, panel_height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # Draw background starting at (0, 0) behind everything
            painter.drawPixmap(0, 0, scaled_bg)
            
            # Remove clipping
            painter.setClipping(False)
            
            # Draw semi-transparent overlay for better contrast (only over preview area)
            painter.fillRect(preview_x, preview_y, self.preview_width, self.preview_height, QColor(0, 0, 0, 80))
        else:
            # Fallback: Fill the widget with dark background
            painter.fillPath(widget_path, QBrush(QColor(10, 14, 39, 240)))
        
        # LAYER 2: Draw button zone background including notch (behind all golden borders)
        # Fill the rectangular button zone
        button_zone_y = preview_y + self.preview_height
        button_zone_height = panel_height - button_zone_y
        painter.fillRect(1, button_zone_y, actual_width - 2, button_zone_height, QColor(10, 14, 39, 240))
        
        # Also fill the notch triangle area (reuse calculated values from above)
        from PyQt6.QtGui import QPolygon
        
        notch_points = [
            QPoint(notch_start_x, notch_base_y),
            QPoint(notch_center_x, notch_tip_y),
            QPoint(notch_end_x, notch_base_y),
        ]
        notch_polygon = QPolygon(notch_points)
        painter.setBrush(QBrush(QColor(10, 14, 39, 240)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(notch_polygon)
        
        # LAYER 3: Draw golden borders on top of backgrounds
        painter.setPen(QPen(QColor("#b78c34"), 1))
        # Top edge
        painter.drawLine(1, 1, actual_width - 1, 1)
        # Right edge
        painter.drawLine(actual_width - 1, 1, actual_width - 1, panel_height)
        # Bottom right to notch
        painter.drawLine(actual_width - 1, panel_height, notch_end_x, notch_base_y)
        # Left edge
        painter.drawLine(1, 1, 1, panel_height)
        # Bottom left to notch
        painter.drawLine(1, panel_height, notch_start_x, notch_base_y)
        
        # Draw golden border on the notch edges (the two angled edges extending outward)
        painter.drawLine(notch_start_x, notch_base_y, notch_center_x, notch_tip_y)  # Left edge
        painter.drawLine(notch_center_x, notch_tip_y, notch_end_x, notch_base_y)  # Right edge
        
        # Draw golden separator line between preview and buttons (on top of button zone)
        painter.setPen(QPen(QColor("#b78c34"), 1))  # Golden separator color
        separator_y = preview_y + self.preview_height
        painter.drawLine(1, separator_y, actual_width - 1, separator_y)
        
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
        
        # Draw preview image (for both base skin and chromas)
        if preview_image and not preview_image.isNull():
            # Scale image to fit preview area (maintains aspect ratio)
            scaled_preview = preview_image.scaled(
                self.preview_width, 
                self.preview_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # Center the scaled image in preview area
            img_x = preview_x + (self.preview_width - scaled_preview.width()) // 2
            img_y = preview_y + (self.preview_height - scaled_preview.height()) // 2
            
            # Use high-quality rendering
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(img_x, img_y, scaled_preview)
        else:
            # No preview image - show placeholder
            painter.setPen(QColor(100, 100, 120))
            placeholder_font = QFont("Segoe UI", 12)
            painter.setFont(placeholder_font)
            painter.drawText(preview_x, preview_y, self.preview_width, self.preview_height,
                           Qt.AlignmentFlag.AlignCenter, "Preview\nNot Available")
        
        # Skin name removed - preview images use full height
        
        # Draw all chroma circles (horizontal row at bottom) - TWO PASSES for layering
        # Pass 1: Draw circle fills (no borders)
        for i, circle in enumerate(self.circles):
            self._draw_chroma_circle_fill(painter, circle, i == self.selected_index)
        
        # Pass 2: Draw selection borders OVER all circles (creates layering effect)
        for i, circle in enumerate(self.circles):
            if i == self.selected_index:
                self._draw_chroma_circle_selection(painter, circle)
    
    def _draw_chroma_circle_fill(self, painter: QPainter, circle: ChromaCircle, is_selected: bool):
        """Draw a single chroma circle fill (without selection border)"""
        # Small circles, no scaling
        radius = self.circle_radius
        
        # Special styling for base skin (chroma_id == 0)
        is_base = (circle.chroma_id == 0)
        
        # Dark border around all circles (drawn first as outline)
        # At lowest resolution (576p), reduce border to make circles more visible
        from utils.window_utils import get_league_window_client_size
        current_res = get_league_window_client_size()
        if current_res and current_res[1] <= 576:
            # Lowest resolution - thinner border for better visibility
            border_width = 0  # No dark border at lowest resolution
        else:
            # Normal resolutions - standard border
            border_width = 1
        
        if border_width > 0:
            painter.setPen(QPen(QColor(20, 20, 20), border_width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(circle.x, circle.y), radius, radius)
        
        if is_base:
            # Base skin: cream background with red diagonal line
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#f1e6d3")))  # Cream/beige
            painter.drawEllipse(QPoint(circle.x, circle.y), radius - 1, radius - 1)
            
            # Draw diagonal red line across the circle (top-right to bottom-left)
            painter.setPen(QPen(QColor("#bf1f37"), 2))  # Red diagonal
            offset = int(radius * 0.7)  # Diagonal line from corner to corner
            painter.drawLine(circle.x + offset, circle.y - offset, circle.x - offset, circle.y + offset)
        else:
            # Regular chroma: use chroma color
            color = QColor(circle.color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPoint(circle.x, circle.y), radius - 1, radius - 1)
        
        # Draw hover border (thin golden ring) - drawn in first pass
        if circle.is_hovered and not is_selected:
            painter.setPen(QPen(QColor("#b78c34"), 1))  # Golden hover color
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(circle.x, circle.y), radius + 1, radius + 1)
    
    def _draw_chroma_circle_selection(self, painter: QPainter, circle: ChromaCircle):
        """Draw selection border on top of circle (second pass for layering)"""
        radius = self.circle_radius
        
        # Thick golden border for selected - drawn OVER everything
        painter.setPen(QPen(QColor("#b78c34"), 2))  # Golden selection color
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(circle.x, circle.y), radius + 3, radius + 3)
    
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
        
        # Update cursor based on hover state
        if hovered is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
    
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
                    
                    # Hide panel through manager (to properly destroy click catcher)
                    if self.manager:
                        self.manager.hide()
                    else:
                        self.hide()
                    
                    # Call callback after a delay (outside widget context)
                    if callback:
                        def call_cb():
                            callback(selected_id, selected_name)
                        QTimer.singleShot(config.UI_QTIMER_CALLBACK_DELAY_MS, call_cb)
                    return
        
        event.accept()
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        if event.key() == Qt.Key.Key_Escape:
            # Cancel - select base
            callback = self.on_chroma_selected
            
            # Hide panel through manager (to properly destroy click catcher)
            if self.manager:
                self.manager.hide()
            else:
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
                
                # Hide panel through manager (to properly destroy click catcher)
                if self.manager:
                    self.manager.hide()
                else:
                    self.hide()
                
                if callback:
                    def call_cb():
                        callback(selected_id, selected_name)
                    QTimer.singleShot(50, call_cb)
        
        event.accept()
    
    def changeEvent(self, event):
        """Handle window state changes"""
        # Close the panel when it loses focus (clicking on League window or anywhere else)
        if event.type() == event.Type.WindowDeactivate:
            if not self.ignore_next_deactivate:
                # Close immediately when focus is lost
                log.debug("[CHROMA] Panel lost focus (League window clicked or focus changed), closing")
                
                # Hide panel through manager (to properly destroy click catcher)
                if self.manager:
                    self.manager.hide()
                else:
                    self.hide()
            else:
                self.ignore_next_deactivate = False
        
        super().changeEvent(event)
    
    def eventFilter(self, obj, event):
        """Filter application events to detect clicks outside the chroma UI
        
        Note: When parented to League window, we detect mouse clicks on League to close panel.
        """
        # In parented mode, detect clicks on League window to close panel
        if hasattr(self, '_league_window_hwnd') and self._league_window_hwnd and self.isVisible():
            if event.type() == event.Type.MouseButtonPress:
                try:
                    # Check if click was on League window (parent)
                    # If user clicks anywhere on League that's not our panel/button, close
                    import ctypes
                    from ctypes import wintypes
                    
                    # Get click position in screen coordinates
                    cursor_pos = wintypes.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor_pos))
                    
                    # Check which window was clicked
                    clicked_hwnd = ctypes.windll.user32.WindowFromPoint(cursor_pos)
                    
                    # Get our widget handle and button handle
                    panel_hwnd = int(self.winId())
                    button_hwnd = int(self.reopen_button_ref.winId()) if self.reopen_button_ref else None
                    
                    # If clicked window is League (our parent) and not panel/button, close panel
                    if clicked_hwnd == self._league_window_hwnd:
                        log.debug("[CHROMA] Click detected on League window, closing panel")
                        
                        # Hide panel through manager (to properly destroy click catcher)
                        if self.manager:
                            self.manager.hide()
                        else:
                            self.hide()
                        return False
                    elif clicked_hwnd != panel_hwnd and clicked_hwnd != button_hwnd:
                        # Clicked somewhere else (not League, not panel, not button)
                        # Could be a child control of League - check if it's a descendant
                        parent_hwnd = ctypes.windll.user32.GetParent(clicked_hwnd)
                        if parent_hwnd == self._league_window_hwnd:
                            log.debug("[CHROMA] Click detected on League UI element, closing panel")
                            
                            # Hide panel through manager (to properly destroy click catcher)
                            if self.manager:
                                self.manager.hide()
                            else:
                                self.hide()
                            return False
                except Exception as e:
                    log.debug(f"[CHROMA] Error in click detection: {e}")
            
            return super().eventFilter(obj, event)
        
        # Original event filtering for non-parented mode
        if self.isVisible():
            # Track mouse press position
            if event.type() == event.Type.MouseButtonPress:
                try:
                    self._press_pos = event.globalPosition().toPoint()
                except AttributeError:
                    self._press_pos = event.globalPos()
                return False
            
            # Mouse button release - check if still outside chroma UI
            elif event.type() == event.Type.MouseButtonRelease:
                try:
                    release_pos = event.globalPosition().toPoint()
                except AttributeError:
                    release_pos = event.globalPos()
                
                try:
                    local_pos = self.mapFromGlobal(release_pos)
                    if self.rect().contains(local_pos):
                        return False
                except Exception:
                    pass
                
                if self.reopen_button_ref is not None:
                    try:
                        button_local_pos = self.reopen_button_ref.mapFromGlobal(release_pos)
                        if self.reopen_button_ref.rect().contains(button_local_pos):
                            self.ignore_next_deactivate = True
                            return False
                    except (RuntimeError, AttributeError, Exception):
                        pass
                
                log.debug("[CHROMA] Mouse released outside chroma UI, closing panel")
                
                # Hide panel through manager (to properly destroy click catcher)
                if self.manager:
                    self.manager.hide()
                else:
                    self.hide()
                return False
            
            # Focus out event
            elif event.type() == event.Type.FocusOut:
                log.debug("[CHROMA] Panel lost focus (FocusOut), closing")
                
                # Hide panel through manager (to properly destroy click catcher)
                if self.manager:
                    self.manager.hide()
                else:
                    self.hide()
                return False
        
        return super().eventFilter(obj, event)


