#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Chroma Opening Button - Small circular button to open the chroma panel
"""

import math
from typing import Callable
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QPainter, QColor, QBrush, QRadialGradient, QPixmap, QPainterPath
from ui.chroma_base import ChromaWidgetBase
from ui.z_order_manager import ZOrderManager
from utils.logging import get_logger
from utils.resolution_utils import (
    scale_dimension_from_base,
    scale_position_from_base,
)

log = get_logger()


class OpeningButton(ChromaWidgetBase):
    """Small circular button to reopen chroma panel"""
    
    def __init__(self, on_click: Callable[[], None] = None, manager=None):
        # Initialize with explicit z-level instead of relying on creation order
        super().__init__(
            z_level=ZOrderManager.Z_LEVELS['CHROMA_BUTTON'],
            widget_name='chroma_button'
        )
        self.on_click = on_click
        self.manager = manager  # Reference to ChromaPanelManager for rebuild requests
        self.is_hovered = False
        self.is_hiding = False  # Flag to prevent painting during hide
        self.panel_is_open = False  # Flag to show button as hovered when panel is open
        self.current_chroma_color = None  # Current selected chroma color (None = show rainbow)
        self.current_chroma_colors = None  # Both colors for split-circle design (None = show rainbow)
        
        # No fade animations - instant show/hide
        
        # No opacity effect needed for instant show/hide
        
        # Common window flags already set by parent class
        
        # Get current resolution for hardcoded sizing
        from utils.window_utils import get_league_window_client_size
        current_resolution = get_league_window_client_size()
        if not current_resolution:
            current_resolution = (1600, 900)  # Fallback to reference resolution
        
        self._current_resolution = current_resolution  # Track resolution for change detection
        self._updating_resolution = False  # Flag to prevent recursive updates
        
        # Hardcoded button sizes for each resolution
        window_width, window_height = current_resolution
        if window_width == 1600 and window_height == 900:
            # 1600x900 resolution
            self.button_visual_size = 40  # Visual size (golden border)
        elif window_width == 1280 and window_height == 720:
            # 1280x720 resolution
            self.button_visual_size = 30  # Visual size (golden border)
        elif window_width == 1024 and window_height == 576:
            # 1024x576 resolution
            self.button_visual_size = 28  # Visual size (golden border)
        else:
            # Unsupported resolution - scale from baseline values
            self.button_visual_size = scale_dimension_from_base(40, current_resolution, axis='y')
            log.info(
                f"[CHROMA] Scaled button size for unsupported resolution {window_width}x{window_height}: {self.button_visual_size}"
            )
        
        # Add extra space for the 3px transparent ring on each side
        self.transparent_ring_width = 3
        self.button_size = self.button_visual_size + (self.transparent_ring_width * 2)  # Total widget size includes transparent ring
        self.setFixedSize(self.button_size, self.button_size)
        
        # Position button directly relative to League window using absolute coordinates
        # Check if we're in Swiftplay mode for different positioning
        is_swiftplay = False
        if self.manager and self.manager.state:
            is_swiftplay = self.manager.state.is_swiftplay_mode
        
        window_width, window_height = current_resolution
        if is_swiftplay:
            # Swiftplay mode - different button positions
            if window_width == 1600 and window_height == 900:
                button_x = 1041
                button_y = 743
            elif window_width == 1280 and window_height == 720:
                button_x = 833
                button_y = 596
            elif window_width == 1024 and window_height == 576:
                button_x = 664
                button_y = 473
            else:
                button_x = scale_position_from_base(1041, current_resolution, axis='x')
                button_y = scale_position_from_base(743, current_resolution, axis='y')
        else:
            # Regular mode - Button should be at center X, 80.35% down from top (same as anchor point)
            if window_width == 1600 and window_height == 900:
                # 1600x900 resolution (reference)
                button_x = 800 - (self.button_size // 2)  # Center horizontally
                button_y = 723 - (self.button_size // 2)  # 80.35% down from top
            elif window_width == 1280 and window_height == 720:
                # 1280x720 resolution (scale factor 0.8)
                button_x = 640 - (self.button_size // 2)  # Center horizontally
                button_y = 578 - (self.button_size // 2)  # 80.35% down from top
            elif window_width == 1024 and window_height == 576:
                # 1024x576 resolution (scale factor 0.64)
                button_x = 512 - (self.button_size // 2)  # Center horizontally
                button_y = 463 - (self.button_size // 2)  # 80.35% down from top
            else:
                center_x = scale_position_from_base(800, current_resolution, axis='x')
                center_y = scale_position_from_base(723, current_resolution, axis='y')
                button_x = center_x - (self.button_size // 2)
                button_y = center_y - (self.button_size // 2)
        
        # Position button absolutely in League window
        self._position_button_absolutely(button_x, button_y)
        
        # Set cursor to hand pointer for the button
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Create UnownedFrame (contains Lock and OutlineGold, fades when skin is NOT owned)
        log.info("[CHROMA] Creating UnownedFrame...")
        
        self.hide()
    
    def _position_button_absolutely(self, x: int, y: int):
        """Position button directly in League window using absolute coordinates"""
        try:
            # First, parent the widget to League window using the base class method
            self._parent_to_league_window()
            
            # Get button widget handle
            widget_hwnd = int(self.winId())
            
            # Position it statically in League window client coordinates
            import ctypes
            HWND_TOP = 0
            ctypes.windll.user32.SetWindowPos(
                widget_hwnd, HWND_TOP, x, y, 0, 0,
                0x0010 | 0x0001  # SWP_NOACTIVATE | SWP_NOSIZE
            )
            
            log.debug(f"[CHROMA] Button positioned absolutely at ({x}, {y})")
            
        except Exception as e:
            log.error(f"[CHROMA] Error positioning button absolutely: {e}")
            import traceback
            log.error(traceback.format_exc())
    
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
        
        # Check if this is a HOL button - if so, only draw the rectangular image
        if self._is_hol_button():
            self._draw_hol_button_only(painter, center, actual_size)
            return
        
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
        
        # 3. Button chroma image or colored disk - replaces gradient ring and inner circle
        painter.setPen(Qt.PenStyle.NoPen)
        
        # Check if we should use a form-specific image for Elementalist Lux
        form_image_path = self._get_elementalist_form_image()
        if form_image_path:
            # Use form-specific image for Elementalist Lux
            self._draw_form_image(painter, center, gradient_outer_radius, should_darken, form_image_path)
        elif self.current_chroma_colors:
            try:
                # Create a split-circle design with both colors
                self._draw_split_chroma_button(painter, center, gradient_outer_radius, should_darken)
                
                log.debug(f"[CHROMA] Split-circle button drawn with colors: {self.current_chroma_colors}")
                
            except Exception as e:
                log.error(f"[CHROMA] Error drawing split-circle button: {e}")
                # Fallback to rainbow image if split-circle fails
                self._draw_rainbow_image(painter, center, gradient_outer_radius, should_darken)
        elif self.current_chroma_color:
            try:
                # Create a colored disk with the selected chroma color
                chroma_color = QColor(self.current_chroma_color)
                
                # Apply darkening effect if hovered
                if should_darken:
                    # Darken the chroma color by reducing brightness
                    chroma_color = chroma_color.darker(150)  # 150% darker
                
                painter.setBrush(QBrush(chroma_color))
                
                # Draw the colored disk in the gradient area (same size as the button-chroma.png)
                painter.drawEllipse(
                    center - gradient_outer_radius, 
                    center - gradient_outer_radius,
                    gradient_outer_radius * 2, 
                    gradient_outer_radius * 2
                )
                
                log.debug(f"[CHROMA] Colored disk drawn with color: {self.current_chroma_color}")
                
            except Exception as e:
                log.error(f"[CHROMA] Error drawing colored disk: {e}")
                # Fallback to rainbow image if colored disk fails
                self._draw_rainbow_image(painter, center, gradient_outer_radius, should_darken)
        else:
            # No chroma selected, show the rainbow gradient image
            self._draw_rainbow_image(painter, center, gradient_outer_radius, should_darken)
    
    def _draw_rainbow_image(self, painter, center, gradient_outer_radius, should_darken):
        """Draw the rainbow button-chroma.png image or star.png for Elementalist Lux"""
        try:
            from utils.paths import get_asset_path
            
            # Check if current skin is Elementalist Lux (base skin ID 99007 or forms 99991-99998)
            is_elementalist_lux = False
            is_hol_kaisa = False
            if self.manager and hasattr(self.manager, 'current_skin_id') and self.manager.current_skin_id:
                current_skin_id = self.manager.current_skin_id
                # Check if it's Elementalist Lux base skin or one of its forms
                if current_skin_id == 99007 or (99991 <= current_skin_id <= 99998):
                    is_elementalist_lux = True
                # Check if it's Risen Legend Kai'Sa base skin or Immortalized Legend
                elif current_skin_id == 145070 or current_skin_id == 145071:
                    is_hol_kaisa = True
            
            # Choose the appropriate image
            if is_elementalist_lux:
                image_path = "star.png"
                log.debug("[CHROMA] Using star.png for Elementalist Lux")
            elif is_hol_kaisa:
                # Use HOL button image for Risen Legend Kai'Sa - rectangular, no darkening
                self._draw_hol_button(painter, center, gradient_outer_radius)
                return
            else:
                image_path = "button-chroma.png"
                log.debug("[CHROMA] Using button-chroma.png for regular skin")
            
            button_chroma_pixmap = QPixmap(str(get_asset_path(image_path)))
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
                    
                log.debug(f"[CHROMA] Button image ({image_path}) drawn at ({image_x}, {image_y}), size: {scaled_pixmap.width()}x{scaled_pixmap.height()}")
            else:
                log.warning(f"[CHROMA] Failed to load {image_path}")
        except Exception as e:
            log.error(f"[CHROMA] Error loading {image_path}: {e}")
    
    def _get_elementalist_form_image(self):
        """Get the form-specific image path for Elementalist Lux forms"""
        try:
            if not self.manager:
                return None
            
            # Check if current skin is Elementalist Lux (base skin ID 99007 or forms 99991-99998)
            current_skin_id = None
            if hasattr(self.manager, 'current_skin_id'):
                current_skin_id = self.manager.current_skin_id
            
            if not current_skin_id:
                return None
            
            # Check if this is Elementalist Lux base skin or one of its forms
            if current_skin_id == 99007 or (99991 <= current_skin_id <= 99999):
                # If a specific form is selected, use that form's image
                if hasattr(self.manager, 'current_selected_chroma_id') and self.manager.current_selected_chroma_id:
                    selected_chroma_id = self.manager.current_selected_chroma_id
                    if 99991 <= selected_chroma_id <= 99999:
                        return f"{selected_chroma_id}.png"
                
                # If no specific form is selected, use the base skin image (99007.png)
                # This applies to both base skin (99007) and active forms (99991-99998)
                return "99007.png"
            
            return None
        except Exception as e:
            log.debug(f"[CHROMA] Error getting Elementalist form image: {e}")
            return None
    
    def _draw_form_image(self, painter, center, gradient_outer_radius, should_darken, image_path):
        """Draw the form-specific image for Elementalist Lux forms"""
        try:
            from utils.paths import get_asset_path
            
            # Elementalist form images are in the elementalist_buttons subfolder
            full_image_path = f"elementalist_buttons/{image_path}"
            form_pixmap = QPixmap(str(get_asset_path(full_image_path)))
            if not form_pixmap.isNull():
                # Scale the image to fit the gradient area
                scaled_pixmap = form_pixmap.scaled(
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
                    
                log.debug(f"[CHROMA] Form image ({full_image_path}) drawn at ({image_x}, {image_y}), size: {scaled_pixmap.width()}x{scaled_pixmap.height()}")
            else:
                log.warning(f"[CHROMA] Failed to load form image {full_image_path}")
                # Fallback to rainbow image
                self._draw_rainbow_image(painter, center, gradient_outer_radius, should_darken)
        except Exception as e:
            log.error(f"[CHROMA] Error loading form image {image_path}: {e}")
            # Fallback to rainbow image
            self._draw_rainbow_image(painter, center, gradient_outer_radius, should_darken)
    
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
            # Ensure z-order is maintained after visual update
            # Use force=True to bypass refresh interval and ensure immediate z-order fix
            try:
                from ui.z_order_manager import get_z_order_manager
                z_manager = get_z_order_manager()
                z_manager.refresh_z_order(force=True)
            except Exception:
                pass  # Don't fail if z-order refresh fails
        
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
            # Ensure z-order is maintained after visual update
            try:
                from ui.z_order_manager import get_z_order_manager
                z_manager = get_z_order_manager()
                z_manager.refresh_z_order(force=True)
            except Exception:
                pass
        # Cursor remains as hand pointer since widget has it set
    
    def set_wheel_open(self, is_open: bool):
        """Update button appearance based on wheel state"""
        try:
            if self.panel_is_open != is_open:
                self.panel_is_open = is_open
                self.update()
                # Ensure z-order is maintained after visual update
                try:
                    from ui.z_order_manager import get_z_order_manager
                    z_manager = get_z_order_manager()
                    z_manager.refresh_z_order(force=True)
                except Exception:
                    pass
        except RuntimeError as e:
            # Widget may have been deleted
            pass
    
    def set_chroma_color(self, color: str = None, colors: list = None):
        """Set the chroma color(s) to display (None = show rainbow gradient)
        
        Args:
            color: Single color string (legacy support)
            colors: List of two colors for split-circle design
        """
        try:
            if colors and len(colors) >= 2:
                # Check if both colors are identical
                first_color = colors[0] if not colors[0].startswith('#') else colors[0][1:]
                second_color = colors[1] if not colors[1].startswith('#') else colors[1][1:]
                
                if first_color == second_color:
                    # Both colors are the same - use solid circle
                    self.current_chroma_color = colors[0]
                    self.current_chroma_colors = None  # Clear both colors
                else:
                    # Colors are different - use split-circle design
                    self.current_chroma_colors = colors
                    self.current_chroma_color = None  # Clear single color
            elif colors and len(colors) == 1:
                # Use single color for solid circle
                self.current_chroma_color = colors[0]
                self.current_chroma_colors = None  # Clear both colors
            else:
                # Use single color (legacy behavior)
                self.current_chroma_color = color
                self.current_chroma_colors = None  # Clear both colors
            
            self.update()
            # Ensure z-order is maintained after visual update
            try:
                from ui.z_order_manager import get_z_order_manager
                z_manager = get_z_order_manager()
                z_manager.refresh_z_order(force=True)
            except Exception:
                pass
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
            
            # Button position is handled by position_relative_to_anchor() in __init__
            
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
            # Don't call raise_() or bring_to_front() - z-order is managed by ZOrderManager
            # This allows RandomFlag (higher z-level) to properly appear above ChromaButton
            
            # Refresh z-order after showing to ensure button is above UnownedFrame
            try:
                from ui.z_order_manager import get_z_order_manager
                z_manager = get_z_order_manager()
                z_manager.refresh_z_order(force=True)
            except Exception:
                pass  # Don't fail if z-order refresh fails
            
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
            # Check if already shown
            is_already_visible = self.isVisible()
            self.show_instantly()
            log.debug("[CHROMA] Button shown for chromas")
            
            # If it was already visible, trigger z-order refresh to ensure it stays on top
            if is_already_visible:
                try:
                    from ui.z_order_manager import get_z_order_manager
                    z_manager = get_z_order_manager()
                    z_manager.refresh_z_order(force=True)
                except Exception:
                    pass  # Don't fail if z-order refresh fails
        except RuntimeError:
            pass
    
    def hide_for_no_chromas(self):
        """Hide button when skin has no chromas - instant"""
        try:
            self.hide_instantly()
            log.debug("[CHROMA] Button hidden for no chromas")
        except RuntimeError:
            pass
    
    
    def _is_hol_button(self):
        """Check if this is a HOL button (Kai'Sa or Ahri skins)"""
        if self.manager and hasattr(self.manager, 'current_skin_id') and self.manager.current_skin_id:
            current_skin_id = self.manager.current_skin_id
            return (current_skin_id == 145070 or current_skin_id == 145071 or  # Kai'Sa skins
                    current_skin_id == 103085 or current_skin_id == 103086)    # Ahri skins
        return False
    
    def _draw_hol_button_only(self, painter, center, actual_size):
        """Draw only the HOL rectangular image - no circular button background"""
        try:
            from utils.paths import get_asset_path
            
            # Choose image based on hover state
            if self.is_hovered or self.panel_is_open:
                image_path = "hol-button-hover.png"
                log.debug("[CHROMA] Using hol-button-hover.png for Risen Legend Kai'Sa (hovered)")
            else:
                image_path = "hol-button.png"
                log.debug("[CHROMA] Using hol-button.png for Risen Legend Kai'Sa")
            
            hol_pixmap = QPixmap(str(get_asset_path(image_path)))
            if not hol_pixmap.isNull():
                # Scale the image to fit the button area (rectangular) - adjust size based on resolution
                # At lowest res (1024x576), use 4px bigger to prevent cropping
                # At higher res, use 5px bigger
                size_increase = 4 if actual_size <= 50 else 5  # Adjust threshold as needed
                button_size = actual_size + size_increase
                scaled_pixmap = hol_pixmap.scaled(
                    button_size, button_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # Center the image - 1px higher
                image_x = center - scaled_pixmap.width() // 2
                image_y = center - scaled_pixmap.height() // 2 - 1
                
                # Draw the image directly (no circular background)
                painter.drawPixmap(image_x, image_y, scaled_pixmap)
                log.debug(f"[CHROMA] HOL button image ({image_path}) drawn at ({image_x}, {image_y}), size: {scaled_pixmap.width()}x{scaled_pixmap.height()}")
            else:
                log.warning(f"[CHROMA] Failed to load HOL button image: {image_path}")
                
        except Exception as e:
            log.error(f"[CHROMA] Error drawing HOL button: {e}")
    
    def _draw_hol_button(self, painter, center, gradient_outer_radius):
        """Draw HOL button as rectangular image - no circular disk, just image switching"""
        try:
            from utils.paths import get_asset_path
            
            # Choose image based on hover state
            if self.is_hovered or self.panel_is_open:
                image_path = "hol-button-hover.png"
                log.debug("[CHROMA] Using hol-button-hover.png for Risen Legend Kai'Sa (hovered)")
            else:
                image_path = "hol-button.png"
                log.debug("[CHROMA] Using hol-button.png for Risen Legend Kai'Sa")
            
            hol_pixmap = QPixmap(str(get_asset_path(image_path)))
            if not hol_pixmap.isNull():
                # Scale the image to fit the button area (rectangular, not circular)
                # Use the full button size instead of the circular gradient area
                button_size = int(gradient_outer_radius * 2)  # Use same size as circular button
                scaled_pixmap = hol_pixmap.scaled(
                    button_size, button_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # Center the image
                image_x = center - scaled_pixmap.width() // 2
                image_y = center - scaled_pixmap.height() // 2
                
                # Draw the image directly (no darkening effect)
                painter.drawPixmap(image_x, image_y, scaled_pixmap)
                log.debug(f"[CHROMA] HOL button image ({image_path}) drawn at ({image_x}, {image_y}), size: {scaled_pixmap.width()}x{scaled_pixmap.height()}")
            else:
                log.warning(f"[CHROMA] Failed to load HOL button image: {image_path}")
                
        except Exception as e:
            log.error(f"[CHROMA] Error drawing HOL button: {e}")
    
    def _draw_split_chroma_button(self, painter, center, gradient_outer_radius, should_darken):
        """Draw a split-circle button with two half-circles"""
        try:
            if not self.current_chroma_colors or len(self.current_chroma_colors) < 2:
                log.warning("[CHROMA] Not enough colors for split-circle design")
                return
            
            # Get both colors
            first_color = self.current_chroma_colors[0]
            second_color = self.current_chroma_colors[1]
            
            # Ensure colors have # prefix
            if not first_color.startswith('#'):
                first_color = f"#{first_color}"
            if not second_color.startswith('#'):
                second_color = f"#{second_color}"
            
            # Check if both colors are identical
            if first_color == second_color:
                # Both colors are the same - draw solid circle
                color = QColor(first_color)
                
                # Apply darkening effect if hovered
                if should_darken:
                    color = color.darker(150)  # 150% darker
                
                # Use adjusted radius to match chroma panel sizing
                adjusted_radius = gradient_outer_radius - 1
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(color))
                painter.drawEllipse(
                    center - adjusted_radius, 
                    center - adjusted_radius,
                    adjusted_radius * 2, 
                    adjusted_radius * 2
                )
                
                log.debug(f"[CHROMA] Solid button drawn with identical colors: {first_color}")
                return
            
            # Colors are different - use split-circle design
            # Create QColor objects
            color1 = QColor(first_color)
            color2 = QColor(second_color)
            
            # Apply darkening effect if hovered
            if should_darken:
                color1 = color1.darker(150)  # 150% darker
                color2 = color2.darker(150)  # 150% darker
            
            # Draw the button with split design
            painter.setPen(Qt.PenStyle.NoPen)
            
            # Create a clipping path for the circle (subtract 1 to match chroma panel sizing)
            circle_path = QPainterPath()
            adjusted_radius = gradient_outer_radius - 1
            circle_path.addEllipse(center - adjusted_radius, center - adjusted_radius,
                                 adjusted_radius * 2, adjusted_radius * 2)
            painter.setClipPath(circle_path)
            
            # Draw top-left half circle (first color)
            top_left_path = QPainterPath()
            top_left_path.moveTo(center, center)  # Center
            top_left_path.arcTo(center - adjusted_radius, center - adjusted_radius,
                              adjusted_radius * 2, adjusted_radius * 2,
                              45, 180)  # Start at 45 degrees, sweep 180 degrees
            top_left_path.closeSubpath()
            
            painter.setBrush(QBrush(color1))
            painter.drawPath(top_left_path)
            
            # Draw bottom-right half circle (second color)
            bottom_right_path = QPainterPath()
            bottom_right_path.moveTo(center, center)  # Center
            bottom_right_path.arcTo(center - adjusted_radius, center - adjusted_radius,
                                   adjusted_radius * 2, adjusted_radius * 2,
                                   225, 180)  # Start at 225 degrees, sweep 180 degrees
            bottom_right_path.closeSubpath()
            
            painter.setBrush(QBrush(color2))
            painter.drawPath(bottom_right_path)
            
            # Remove clipping
            painter.setClipping(False)
            
            log.debug(f"[CHROMA] Split button drawn with colors: {first_color} (top-left) and {second_color} (bottom-right)")
            
        except Exception as e:
            log.error(f"[CHROMA] Error drawing split chroma button: {e}")
            raise
    
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


