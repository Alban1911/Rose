#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Chroma Panel Widget - Main UI component for chroma selection
"""

import math
from typing import Optional, Callable, List, Dict
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QPixmap
from ui.chroma_base import ChromaWidgetBase
from ui.z_order_manager import ZOrderManager
from utils.logging import get_logger, log_event
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
    
    def __init__(self, on_chroma_selected: Callable[[int, str], None] = None, manager=None, lcu=None):
        # Initialize with explicit z-level instead of relying on creation order
        super().__init__(
            z_level=ZOrderManager.Z_LEVELS['CHROMA_PANEL'],
            widget_name='chroma_panel'
        )
        
        self.on_chroma_selected = on_chroma_selected
        self.manager = manager  # Reference to ChromaPanelManager for rebuild requests
        self.lcu = lcu  # LCU client for game mode detection
        self.circles = []
        self.skin_name = ""
        self.selected_index = 0  # Default to base (center)
        self.hovered_index = None
        self.reopen_button_ref = None  # Reference to button widget for click detection
        
        # Track mouse press position for click-and-release detection
        self._press_pos = None
        
        # Get current resolution for hardcoded sizing
        from utils.window_utils import get_league_window_client_size
        current_resolution = get_league_window_client_size()
        if not current_resolution:
            current_resolution = (1600, 900)  # Fallback to reference resolution
        
        self._current_resolution = current_resolution  # Track resolution for change detection
        self._updating_resolution = False  # Flag to prevent recursive updates
        
        # Use hard-coded values from ScaledChromaValues
        from ui.chroma_scaling import get_scaled_chroma_values
        scaled_values = get_scaled_chroma_values(current_resolution)
        
        self.preview_width = scaled_values.preview_width
        self.preview_height = scaled_values.preview_height
        self.circle_radius = scaled_values.circle_radius
        self.window_width = scaled_values.window_width
        self.window_height = scaled_values.window_height
        self.circle_spacing = scaled_values.circle_spacing
        self.button_size = scaled_values.button_size
        self.button_width = scaled_values.button_width
        self.button_height = scaled_values.button_height
        self.screen_edge_margin = scaled_values.screen_edge_margin
        self.preview_x = scaled_values.preview_x
        self.preview_y = scaled_values.preview_y
        self.row_y_offset = scaled_values.row_y_offset
        self.gold_border_px = scaled_values.gold_border_px
        self.dark_border_px = scaled_values.dark_border_px
        self.gradient_ring_px = scaled_values.gradient_ring_px
        self.inner_disk_radius_px = scaled_values.inner_disk_radius_px
        
        # Track actual display dimensions (may differ from scaled at very small resolutions)
        self._display_width = self.window_width
        self._display_height = self.window_height
        self._scale_factor = 1.0  # Scale factor for constrained layouts
        self._updating_resolution = False  # Flag to prevent recursive updates
        
        # Initialize preview positions from hardcoded values
        self._preview_x = self.preview_x
        self._preview_y = self.preview_y
        
        # Preview image (will be downloaded/loaded)
        self.current_preview_image = None  # QPixmap for current chroma
        
        # Background image
        self.background_image = None  # QPixmap for dynamic background (ARAM or SR)
        self._load_background_image()
        
        # Animation
        self._opacity = 0.0
        self.opacity_animation = None
        
        # Install event filter to detect clicks outside the widget
        QApplication.instance().installEventFilter(self)
        
        self.setup_ui()
    
    def _load_background_image(self):
        """Load the appropriate background image based on game mode"""
        try:
            # Import asset path helper for PyInstaller compatibility
            from utils.paths import get_asset_path
            
            # Determine background filename based on game mode
            background_filename = self._get_background_filename()
            
            # Get background image path (works in both dev and frozen environments)
            background_path = get_asset_path(background_filename)
            if background_path.exists():
                self.background_image = QPixmap(str(background_path))
                log.debug(f"Loaded background image: {background_path}")
            else:
                log.debug(f"Background image not found: {background_path}")
                self.background_image = None
        except Exception as e:
            log.debug(f"Failed to load background image: {e}")
            self.background_image = None

    def _get_background_filename(self) -> str:
        """Get the appropriate background filename based on stored game mode"""
        try:
            # Get game mode from shared state (detected once in champion select)
            if self.manager and self.manager.state:
                map_id = self.manager.state.current_map_id
                game_mode = self.manager.state.current_game_mode
                
                log.info(f"[CHROMA] Using stored game mode: {game_mode} (Map ID: {map_id})")
                
                # Check if we're in ARAM mode
                if map_id == 12 or game_mode == "ARAM":
                    log.info("[CHROMA] ARAM mode detected - using ARAM background")
                    return "champ-select-flyout-background-aram.png"
                else:
                    log.info("[CHROMA] Summoner's Rift mode detected - using SR background")
                    return "champ-select-flyout-background-sr.jpg"
            else:
                log.info("[CHROMA] No game mode data available - defaulting to SR background")
                return "champ-select-flyout-background-sr.jpg"
        except Exception as e:
            log.info(f"[CHROMA] Error getting game mode: {e} - defaulting to SR background")
            return "champ-select-flyout-background-sr.jpg"

    def reload_background(self):
        """Reload the background image based on current game mode"""
        log.info("[CHROMA] Reloading background image...")
        self._load_background_image()
        # Force a repaint to show the new background
        self.update()
        
    def setup_ui(self):
        """Setup the window and styling"""
        # Common window flags already set by parent class
        
        # Set window size - add extra height for notch extending outside (15px for 45° angles)
        self.notch_height = 15
        self.setFixedSize(self.window_width, self.window_height + self.notch_height)
        
        # Create window mask to define the visible shape (including notch)
        self._update_window_mask()
        
        # Position panel directly relative to League window (not relative to button)
        # Use panel position from config for each resolution
        # Use panel position from config for each resolution
        window_width, window_height = self._current_resolution
        
        # Get scaled values for current resolution
        from ui.chroma_scaling import get_scaled_chroma_values
        scaled_values = get_scaled_chroma_values(self._current_resolution)
        
        # Get panel position from scaled values (config-based)
        panel_x = scaled_values.panel_x  # X position from left edge of League window
        panel_y = scaled_values.panel_y  # Y position from top edge of League window
        
        # Position panel directly in League window using absolute coordinates
        self._position_panel_absolutely(panel_x, panel_y)
        
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
    
    def _position_panel_absolutely(self, x: int, y: int):
        """Position panel directly in League window using absolute coordinates"""
        try:
            # First, parent the widget to League window using the base class method
            self._parent_to_league_window()
            
            # Get panel widget handle
            widget_hwnd = int(self.winId())
            
            # Position it statically in League window client coordinates
            import ctypes
            HWND_TOP = 0
            ctypes.windll.user32.SetWindowPos(
                widget_hwnd, HWND_TOP, x, y, 0, 0,
                0x0010 | 0x0001  # SWP_NOACTIVATE | SWP_NOSIZE
            )
            
            log.debug(f"[CHROMA] Panel positioned absolutely at ({x}, {y})")
            
        except Exception as e:
            log.error(f"[CHROMA] Error positioning panel absolutely: {e}")
            import traceback
            log.error(traceback.format_exc())
    
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
        preview_x = self._preview_x if hasattr(self, '_preview_x') else self.preview_x
        preview_y = self._preview_y if hasattr(self, '_preview_y') else self.preview_y
        preview_height = self.preview_height
        
        # Button zone starts after preview and uses hard-coded button dimensions
        button_zone_y = preview_y + preview_height
        button_zone_width = self.button_width
        button_zone_height = self.button_height
        button_zone_x = (actual_width - button_zone_width) // 2  # Center the button zone
        
        # Position circles in the center of the button zone
        row_y = button_zone_y + (button_zone_height // 2)
        
        # Recalculate horizontal row positions (same logic as set_chromas)
        num_circles = len(self.circles)
        total_width = num_circles * self.circle_spacing
        start_x = button_zone_x + (button_zone_width - total_width) // 2 + self.circle_spacing // 2
        
        # Update circle positions and radius
        for i, circle in enumerate(self.circles):
            circle.x = start_x + (i * self.circle_spacing)
            circle.y = row_y
            circle.radius = self.circle_radius  # Update radius to hardcoded value
    
    def set_chromas(self, skin_name: str, chromas: List[Dict], champion_name: str = None, selected_chroma_id: Optional[int] = None, skin_id: Optional[int] = None):
        """Set the chromas to display - League horizontal style
        
        Note: The chromas list should already be filtered to only include unowned chromas
        by the ChromaSelector before being passed to this method.
        """
        self.skin_name = skin_name
        self.skin_id = skin_id  # Store skin_id for Elementalist Lux detection
        self.circles = []
        
        # For preview loading, use the base skin name (remove chroma ID if present)
        # This ensures we load previews from the correct base skin folder
        base_skin_name_for_previews = self._get_base_skin_name_for_previews(skin_name, skin_id)
        log.debug(f"[CHROMA] Preview loading: original='{skin_name}' -> base='{base_skin_name_for_previews}'")
        
        # Load base skin preview
        # For Elementalist Lux forms, always use base skin ID (99007) for the base circle preview
        base_preview_skin_id = skin_id
        if (99991 <= skin_id <= 99999) or skin_id == 99007:
            base_preview_skin_id = 99007  # Always use base skin ID for Elementalist Lux base circle
            log.debug(f"[CHROMA] Elementalist Lux detected - using base skin ID {base_preview_skin_id} for base circle preview instead of {skin_id}")
        
        base_preview = self._load_chroma_preview_image(base_skin_name_for_previews, chroma_id=0, champion_name=champion_name, skin_id=base_preview_skin_id)
        
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
            
            # Use chroma_id directly (no more fake IDs)
            preview_image = self._load_chroma_preview_image(base_skin_name_for_previews, chroma_id, champion_name, skin_id)
            
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
        
        # Position circles in horizontal row, centered in button zone
        total_chromas = len(self.circles)
        # Button zone starts after preview and uses hard-coded button dimensions
        button_zone_y = self.preview_y + self.preview_height
        button_zone_width = self.button_width
        button_zone_height = self.button_height
        button_zone_x = (self.window_width - button_zone_width) // 2  # Center the button zone
        
        # Position circles in the center of the button zone
        row_y = button_zone_y + (button_zone_height // 2)
        
        # Calculate total width needed for circles
        total_width = total_chromas * self.circle_spacing
        start_x = button_zone_x + (button_zone_width - total_width) // 2 + self.circle_spacing // 2
        
        for i, circle in enumerate(self.circles):
            circle.x = start_x + (i * self.circle_spacing)
            circle.y = row_y
        
        # Find the index of the currently selected chroma (if provided)
        self.selected_index = 0  # Default to base
        
        # Special handling for Kai'Sa skins - if we're opening for Immortalized Legend (145071), 
        # select the HOL chroma instead of the base skin
        if skin_id == 145071:
            # Immortalized Legend Kai'Sa is treated as a chroma selection
            for i, circle in enumerate(self.circles):
                if circle.chroma_id == 145071:  # HOL chroma real ID
                    self.selected_index = i
                    circle.is_selected = True
                    base_circle.is_selected = False  # Unselect base
                    log.debug(f"[CHROMA] Immortalized Legend Kai'Sa detected - selecting HOL chroma circle")
                    break
        
        # Special handling for Ahri skins - if we're opening for Immortalized Legend (103086), 
        # select the HOL chroma instead of the base skin
        elif skin_id == 103086:
            # Immortalized Legend Ahri is treated as a chroma selection
            for i, circle in enumerate(self.circles):
                if circle.chroma_id == 103086:  # HOL chroma real ID
                    self.selected_index = i
                    circle.is_selected = True
                    base_circle.is_selected = False  # Unselect base
                    log.debug(f"[CHROMA] Immortalized Legend Ahri detected - selecting HOL chroma circle")
                    break
        elif selected_chroma_id is not None:
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
    
    def _load_chroma_preview_image(self, skin_name: str, chroma_id: Optional[int], champion_name: str = None, skin_id: Optional[int] = None) -> Optional[QPixmap]:
        """Load chroma preview image from SkinPreviews repository"""
        try:
            if champion_name is None:
                log.warning(f"[CHROMA] No champion name provided for preview")
                return None
            
            log.debug(f"[CHROMA] Loading chroma preview: skin_name='{skin_name}', chroma_id={chroma_id}, champion_name='{champion_name}', skin_id={skin_id}")
            
            # Load from SkinPreviews repository
            from ui.chroma_preview_manager import get_preview_manager
            # Get database from chroma selector if available
            from ui.chroma_selector import get_chroma_selector
            chroma_selector = get_chroma_selector()
            db = chroma_selector.db if chroma_selector else None
            preview_manager = get_preview_manager(db)
            
            image_path = preview_manager.get_preview_path(champion_name, skin_name, chroma_id, skin_id)
            
            if image_path:
                log.debug(f"[CHROMA] Loading preview: {image_path.name}")
                pixmap = QPixmap(str(image_path))
                if pixmap.isNull():
                    log.error(f"[CHROMA] Failed to load pixmap from {image_path}")
                    return None
                log.debug(f"[CHROMA] Successfully loaded preview: {image_path.name} ({pixmap.size().width()}x{pixmap.size().height()})")
                return pixmap
            
            log.warning(f"[CHROMA] No preview found for {champion_name}/{skin_name}/chroma_{chroma_id}")
            return None
            
        except Exception as e:
            log.error(f"[CHROMA] Error loading chroma preview: {e}")
            import traceback
            log.error(traceback.format_exc())
            return None
    
    
    def set_button_reference(self, button_widget):
        """Set reference to the reopen button for click detection"""
        self.reopen_button_ref = button_widget
    
    def show_wheel(self, button_pos=None):
        """Show the panel (button_pos parameter kept for backward compatibility but unused)"""
        # Set opacity to 1.0 for visibility
        self._opacity = 1.0
        
        # Position is handled by _position_panel_absolutely() in setup_ui()
        # Panel is positioned directly relative to League window, not relative to button
        
        # Show window
        self.show()
        self.raise_()
        self.bring_to_front()
        
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
        notch_width = 29  # Width of the triangle base (odd number for true center, made 1px narrower)
        notch_height = self.notch_height  # Height of the triangle (pointing outward)
        notch_center_x = actual_width // 2
        # For odd notch_width (29): left side gets 14 pixels, right side gets 14 pixels, center is at center
        notch_start_x = notch_center_x - (notch_width // 2)
        notch_end_x = notch_center_x + (notch_width // 2) + 1  # +1 to get full 29 pixels
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
        preview_x = self._preview_x if hasattr(self, '_preview_x') else self.preview_x
        preview_y = self._preview_y if hasattr(self, '_preview_y') else self.preview_y
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
            # Fallback: Fill the widget with black background
            painter.fillPath(widget_path, QBrush(QColor(0, 0, 0, 255)))
        
        # LAYER 2: Draw button zone background including notch (behind all golden borders)
        # Fill the rectangular button zone using hard-coded button dimensions
        button_zone_y = preview_y + self.preview_height
        button_zone_width = self.button_width
        button_zone_height = self.button_height
        button_zone_x = (actual_width - button_zone_width) // 2  # Center the button zone
        
        # Ensure button zone background is drawn behind borders
        painter.setPen(Qt.PenStyle.NoPen)  # No border on the background fill
        painter.setBrush(QBrush(QColor(0, 0, 0, 255)))
        painter.drawRect(button_zone_x, button_zone_y, button_zone_width, button_zone_height)
        
        # LAYER 3: Draw most golden borders (but not lower border yet)
        painter.setPen(QPen(QColor("#b78c34"), 1))
        # Top edge
        painter.drawLine(1, 1, actual_width - 1, 1)
        # Right edge
        painter.drawLine(actual_width - 1, 1, actual_width - 1, panel_height)
        # Left edge
        painter.drawLine(1, 1, 1, panel_height)
        
        # LAYER 4: Draw lower border segments (above rectangle, behind triangle)
        # Bottom right to notch
        painter.drawLine(actual_width - 1, panel_height, notch_end_x, notch_base_y)
        # Bottom left to notch
        painter.drawLine(1, panel_height, notch_start_x, notch_base_y)
        
        # LAYER 5: Draw triangle notch on top of lower border
        # Use clipping to ensure triangle completely covers the border area
        from PyQt6.QtGui import QPolygon, QRegion
        
        notch_points = [
            QPoint(notch_start_x, notch_base_y),
            QPoint(notch_center_x, notch_tip_y),
            QPoint(notch_end_x, notch_base_y),
        ]
        notch_polygon = QPolygon(notch_points)
        
        # Create a clipping region for the triangle area to ensure clean coverage
        triangle_region = QRegion(notch_polygon)
        painter.setClipRegion(triangle_region)
        
        # Fill the triangle area completely
        painter.setBrush(QBrush(QColor(0, 0, 0, 255)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(notch_polygon)
        
        # Remove clipping
        painter.setClipping(False)
        
        # LAYER 6: Draw golden border on the notch edges (on top of triangle)
        painter.setPen(QPen(QColor("#b78c34"), 1))
        painter.drawLine(notch_start_x, notch_base_y, notch_center_x, notch_tip_y)  # Left edge
        painter.drawLine(notch_center_x, notch_tip_y, notch_end_x, notch_base_y)  # Right edge
        
        # Draw golden separator line between preview and buttons (on top of button zone)
        # Disable antialiasing to ensure exact 1px thickness
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor("#2b2f1c"), 1))  # Golden separator color, 1px thickness
        separator_y = preview_y + self.preview_height
        painter.drawLine(2, separator_y, actual_width - 3, separator_y)
        # Re-enable antialiasing for other elements
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
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
            # Check if this is Elementalist Lux base skin
            if circle.chroma_id == 0 and hasattr(self, 'skin_id') and (self.skin_id == 99007 or (99991 <= self.skin_id <= 99999)):
                # Elementalist Lux base skin: use form-specific image
                self._draw_elementalist_form_circle(painter, circle, radius)
            # Check if this is Risen Legend Kai'Sa base skin
            elif circle.chroma_id == 0 and hasattr(self, 'skin_id') and (self.skin_id == 145070 or self.skin_id == 145071):
                # Risen Legend Kai'Sa base skin: use risen.png image
                self._draw_hol_chroma_circle(painter, circle, radius)
            # Check if this is Risen Legend Ahri base skin
            elif circle.chroma_id == 0 and hasattr(self, 'skin_id') and (self.skin_id == 103085 or self.skin_id == 103086):
                # Risen Legend Ahri base skin: use risen.png image
                self._draw_hol_chroma_circle(painter, circle, radius)
            else:
                # Regular base skin: cream background with red diagonal line
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#f1e6d3")))  # Cream/beige
                painter.drawEllipse(QPoint(circle.x, circle.y), radius - 1, radius - 1)
                
                # Draw diagonal red line across the circle (top-right to bottom-left)
                painter.setPen(QPen(QColor("#bf1f37"), 2))  # Red diagonal
                offset = int(radius * 0.7)  # Diagonal line from corner to corner
                painter.drawLine(circle.x + offset, circle.y - offset, circle.x - offset, circle.y + offset)
        else:
            # Check if this is an Elementalist Lux form (fake IDs 99991-99999) or base skin (99007)
            if 99991 <= circle.chroma_id <= 99999 or circle.chroma_id == 99007:
                # Elementalist Lux form or base skin: use form-specific image
                self._draw_elementalist_form_circle(painter, circle, radius)
            # Check if this is a Risen Legend Kai'Sa base skin (145070) or Immortalized Legend (145071)
            elif circle.chroma_id == 145070 or circle.chroma_id == 145071:
                # Risen Legend Kai'Sa base skin or Immortalized Legend: use HOL-specific image
                self._draw_hol_chroma_circle(painter, circle, radius)
            # Check if this is a Risen Legend Ahri base skin (103085) or Immortalized Legend (103086)
            elif circle.chroma_id == 103085 or circle.chroma_id == 103086:
                # Risen Legend Ahri base skin or Immortalized Legend: use HOL-specific image
                self._draw_hol_chroma_circle(painter, circle, radius)
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
    
    def _draw_elementalist_form_circle(self, painter: QPainter, circle: ChromaCircle, radius: int):
        """Draw an Elementalist Lux form circle with form-specific image"""
        try:
            from utils.paths import get_asset_path
            
            # For base skin (chroma_id = 0), always use base skin ID (99007) for Elementalist Lux
            if circle.chroma_id == 0:
                # Always use base skin ID (99007) for Elementalist Lux base circle
                image_id = 99007
            else:
                image_id = circle.chroma_id
            
            # Use form-specific image based on image_id
            image_path = f"{image_id}.png"
            # Elementalist form images are in the elementalist_buttons subfolder
            full_image_path = f"elementalist_buttons/{image_path}"
            form_pixmap = QPixmap(str(get_asset_path(full_image_path)))
            
            if not form_pixmap.isNull():
                # Scale the image to fit the circle
                scaled_pixmap = form_pixmap.scaled(
                    (radius - 1) * 2, (radius - 1) * 2,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # Center the image in the circle
                image_x = circle.x - scaled_pixmap.width() // 2
                image_y = circle.y - scaled_pixmap.height() // 2
                
                # Draw the form image
                painter.drawPixmap(image_x, image_y, scaled_pixmap)
                
                log.debug(f"[CHROMA] Elementalist form image ({full_image_path}) drawn at ({image_x}, {image_y})")
            else:
                # Fallback to chroma color if image not found
                log.warning(f"[CHROMA] Failed to load Elementalist form image: {full_image_path}")
                color = QColor(circle.color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(color))
                painter.drawEllipse(QPoint(circle.x, circle.y), radius - 1, radius - 1)
                
        except Exception as e:
            log.error(f"[CHROMA] Error drawing Elementalist form circle: {e}")
            # Fallback to chroma color
            color = QColor(circle.color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPoint(circle.x, circle.y), radius - 1, radius - 1)
    
    def _draw_hol_chroma_circle(self, painter, circle, radius):
        """Draw a HOL chroma circle with HOL-specific image (Kai'Sa or Ahri)"""
        try:
            from utils.paths import get_asset_path
            
            # Determine which champion and which image to use
            if circle.chroma_id == 0 or circle.chroma_id == 145070 or circle.chroma_id == 103085:
                # Base skins: use risen image
                image_name = "risen.png"
                folder_name = "kaisa_buttons" if (circle.chroma_id == 0 or circle.chroma_id == 145070) else "ahri_buttons"
            else:
                # Immortalized Legend skins: use immortal image
                image_name = "immortal.png"
                folder_name = "kaisa_buttons" if circle.chroma_id == 145071 else "ahri_buttons"
            
            # Use HOL-specific image from appropriate folder
            full_image_path = f"{folder_name}/{image_name}"
            form_pixmap = QPixmap(str(get_asset_path(full_image_path)))
            
            if not form_pixmap.isNull():
                # Scale the image to fit the circle
                scaled_pixmap = form_pixmap.scaled(
                    int(radius * 2), int(radius * 2),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # Center the image in the circle
                image_x = circle.x - scaled_pixmap.width() // 2
                image_y = circle.y - scaled_pixmap.height() // 2
                
                # Draw the HOL image
                painter.drawPixmap(image_x, image_y, scaled_pixmap)
                
                log.debug(f"[CHROMA] HOL chroma image ({full_image_path}) drawn at ({image_x}, {image_y})")
            else:
                # Fallback to chroma color if image not found
                log.warning(f"[CHROMA] Failed to load HOL chroma image: {full_image_path}")
                color = QColor(circle.color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(color))
                painter.drawEllipse(QPoint(circle.x, circle.y), radius - 1, radius - 1)
                
        except Exception as e:
            log.error(f"[CHROMA] Error drawing HOL chroma circle: {e}")
            # Fallback to chroma color
            color = QColor(circle.color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPoint(circle.x, circle.y), radius - 1, radius - 1)
    
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

    def _get_base_skin_name_for_previews(self, skin_name: str, skin_id: Optional[int] = None) -> str:
        """Get the base skin name for preview loading, removing any chroma ID suffixes
        
        This ensures we load preview images from the correct base skin folder
        instead of trying to find a folder named after the chroma ID.
        
        Args:
            skin_name: Current skin name (may include chroma ID)
            skin_id: Optional skin ID to help determine if this is a chroma
            
        Returns:
            Base skin name for preview loading
        """
        try:
            # If this is a chroma ID, we need to get the base skin name
            if skin_id and skin_id % 1000 != 0:
                # This is likely a chroma ID, get the base skin ID using skin scraper
                from ui.chroma_selector import get_chroma_selector
                chroma_selector = get_chroma_selector()
                if chroma_selector and chroma_selector.skin_scraper and chroma_selector.skin_scraper.cache:
                    # Use the chroma cache to get the base skin ID
                    chroma_data = chroma_selector.skin_scraper.cache.chroma_id_map.get(skin_id)
                    if chroma_data:
                        base_skin_id = chroma_data.get('skinId')
                        log.debug(f"[CHROMA] Found base skin ID {base_skin_id} for chroma {skin_id}")
                        
                        # Try to get the base skin name from database
                        if chroma_selector.db:
                            try:
                                base_skin_name = chroma_selector.db.get_english_skin_name_by_id(base_skin_id)
                                if base_skin_name:
                                    log.debug(f"[CHROMA] Using base skin name from database: '{base_skin_name}' for chroma {skin_id}")
                                    return base_skin_name
                            except Exception as e:
                                log.debug(f"[CHROMA] Database lookup failed for base skin {base_skin_id}: {e}")
            
            # Fallback: remove any trailing chroma IDs from the skin name
            # Split by spaces and remove any words that are purely numeric (chroma IDs)
            words = skin_name.split()
            clean_words = []
            for word in words:
                # Skip words that look like chroma IDs (numbers)
                if not word.isdigit():
                    clean_words.append(word)
                else:
                    # Stop at the first number we encounter (base skin ID or chroma ID)
                    break
            
            base_skin_name = ' '.join(clean_words)
            
            if base_skin_name != skin_name:
                log.debug(f"[CHROMA] Cleaned skin name for previews: '{skin_name}' -> '{base_skin_name}'")
            
            return base_skin_name
            
        except Exception as e:
            log.debug(f"[CHROMA] Error getting base skin name for previews: {e}")
            return skin_name


