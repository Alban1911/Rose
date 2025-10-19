#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UnownedFrame - UI component for showing unowned skin indicator
Shows golden border and lock icon for unowned skins
"""

from PyQt6.QtWidgets import QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QPixmap
from ui.chroma_base import ChromaWidgetBase
from ui.chroma_scaling import get_scaled_chroma_values
from ui.z_order_manager import ZOrderManager
from utils.logging import get_logger
import config

log = get_logger()


class UnownedFrame(ChromaWidgetBase):
    """UI component showing golden border and lock for unowned skins"""
    
    # Signals for thread-safe operations
    fade_in_requested = pyqtSignal()
    fade_out_requested = pyqtSignal()
    
    def __init__(self, state=None):
        # Initialize with explicit z-level instead of relying on creation order
        super().__init__(
            z_level=ZOrderManager.Z_LEVELS['UNOWNED_FRAME'],
            widget_name='unowned_frame'
        )
        
        # Store reference to shared state for ownership checking
        self.state = state
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        # Get scaled values
        self.scaled = get_scaled_chroma_values()
        
        # Track resolution for change detection
        self._current_resolution = None
        self._updating_resolution = False  # Flag to prevent recursive updates
        
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
        
        # Connect signals for thread-safe operations
        self.fade_in_requested.connect(self._do_fade_in)
        self.fade_out_requested.connect(self._do_fade_out)
        
        # Start visible but transparent (opacity 0)
        self.opacity_effect.setOpacity(0.0)
        self.show()
    
    def _create_components(self):
        """Create the merged unowned frame component with static positioning"""
        # Clear existing components if they exist (for rebuilds)
        if hasattr(self, 'unowned_frame_image') and self.unowned_frame_image:
            self.unowned_frame_image.deleteLater()
            self.unowned_frame_image = None
        
        # Get League window for static positioning
        from utils.window_utils import get_league_window_handle, find_league_window_rect
        import ctypes
        
        # Get League window handle and size
        league_hwnd = get_league_window_handle()
        window_rect = find_league_window_rect()
        if not league_hwnd or not window_rect:
            log.debug("[UnownedFrame] Could not get League window for static positioning")
            return
        
        window_left, window_top, window_right, window_bottom = window_rect
        window_width = window_right - window_left
        window_height = window_bottom - window_top
        
        # Hardcoded positions for each resolution (no scaling)
        if window_width == 1600 and window_height == 900:
            # 1600x900 resolution
            frame_width = 148
            frame_height = 84
            target_x = 726
            target_y = 642
        elif window_width == 1280 and window_height == 720:
            # 1280x720 resolution
            frame_width = 118
            frame_height = 67
            target_x = 581
            target_y = 513
        elif window_width == 1024 and window_height == 576:
            # 1024x576 resolution
            frame_width = 95
            frame_height = 54
            target_x = 465
            target_y = 411
        else:
            # Unsupported resolution - use default 1600x900 values
            log.warning(f"[UnownedFrame] Unsupported resolution {window_width}x{window_height}, using 1600x900 defaults")
            frame_width = 148
            frame_height = 84
            target_x = 726
            target_y = 642
        
        log.debug(f"[UnownedFrame] Hardcoded positioning: window={window_width}x{window_height}, frame={frame_width}x{frame_height}, pos=({target_x}, {target_y})")
        
        # Set static size
        self.setFixedSize(frame_width, frame_height)
        
        # Force geometry update to ensure size is applied
        self.setGeometry(self.x(), self.y(), frame_width, frame_height)
        
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
        # Use HWND_TOP to place it in front of League window, but it will be behind chroma button
        # because chroma button is created after this and uses HWND_TOP as well
        HWND_TOP = 0
        
        # First, ensure the widget is properly shown and positioned
        self.show()
        
        # Apply positioning with multiple flags to ensure it works
        result = ctypes.windll.user32.SetWindowPos(
            widget_hwnd, HWND_TOP, target_x, target_y, frame_width, frame_height,
            0x0010 | 0x0004 | 0x0001  # SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOSIZE
        )
        
        log.debug(f"[UnownedFrame] Static positioning: window={window_width}x{window_height}, position=({target_x}, {target_y}), size={frame_width}x{frame_height}, SetWindowPos result={result}")
        
        # Force a position update using PyQt6 methods as well
        self.move(target_x, target_y)
        self.resize(frame_width, frame_height)
        
        # Verify the positioning was applied correctly
        import time
        time.sleep(0.01)  # Small delay to ensure positioning is applied
        actual_x = self.x()
        actual_y = self.y()
        log.debug(f"[UnownedFrame] Position verification: expected=({target_x}, {target_y}), actual=({actual_x}, {actual_y})")
        
        # Create unowned frame image
        self.unowned_frame_image = QLabel(self)
        self.unowned_frame_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Load unowned frame image
        try:
            # Completely clear any existing pixmap first
            self.unowned_frame_image.clear()
            self.unowned_frame_image.setPixmap(QPixmap())  # Set empty pixmap
            
            log.debug(f"[UnownedFrame] Loading FRESH image from: assets/unownedframe.png")
            # Force reload from file system - create completely new QPixmap
            unowned_pixmap = QPixmap()
            unowned_pixmap.load("assets/unownedframe.png")
            log.debug(f"[UnownedFrame] Image loaded: null={unowned_pixmap.isNull()}, size={unowned_pixmap.width()}x{unowned_pixmap.height()}")
            
            if not unowned_pixmap.isNull():
                # Scale the image to EXACTLY fit the calculated frame size (ignore aspect ratio)
                scaled_pixmap = unowned_pixmap.scaled(
                    frame_width, frame_height,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # Set the scaled pixmap
                self.unowned_frame_image.setPixmap(scaled_pixmap)
                
                # Force the QLabel to update its display
                self.unowned_frame_image.update()
                
                # Debug: Check if QLabel has pixmap and is visible
                has_pixmap = not self.unowned_frame_image.pixmap().isNull()
                log.debug(f"[UnownedFrame] QLabel pixmap: has_pixmap={has_pixmap}, visible={self.unowned_frame_image.isVisible()}, size={self.unowned_frame_image.size().width()}x{self.unowned_frame_image.size().height()}")
                
                log.info(f"[UnownedFrame] Image scaled: original={unowned_pixmap.width()}x{unowned_pixmap.height()}, scaled={scaled_pixmap.width()}x{scaled_pixmap.height()}, target={frame_width}x{frame_height}")
            else:
                log.error("[UnownedFrame] Failed to load unownedframe.png image - pixmap is null")
        except Exception as e:
            log.error(f"[UnownedFrame] Error loading unowned frame: {e}")
            import traceback
            log.error(traceback.format_exc())
        
        # Position unowned frame to fill the entire widget
        self.unowned_frame_image.move(0, 0)
        self.unowned_frame_image.resize(frame_width, frame_height)
        
        # Force QLabel to update its display after resizing
        self.unowned_frame_image.update()
        self.unowned_frame_image.repaint()
        
        # Force widget update to ensure all changes are applied
        self.update()
        self.repaint()
        
        # Debug: Final check of QLabel state
        final_pixmap = self.unowned_frame_image.pixmap()
        log.debug(f"[UnownedFrame] Final QLabel state: has_pixmap={not final_pixmap.isNull() if final_pixmap else False}, size={self.unowned_frame_image.size().width()}x{self.unowned_frame_image.size().height()}, visible={self.unowned_frame_image.isVisible()}")
        
        log.debug(f"[UnownedFrame] QLabel resized to: {frame_width}x{frame_height}")
        
        log.info("[UnownedFrame] Unowned frame component created successfully")
        
        # Z-order is now managed centrally - no need for manual z-order management
        # The UnownedFrame is automatically positioned behind interactive elements
        
        # Make sure it's visible (but transparent)
        self.show()
        
        # Ensure the QLabel is also visible
        self.unowned_frame_image.show()
        self.unowned_frame_image.update()
        self.unowned_frame_image.repaint()
        log.debug(f"[UnownedFrame] QLabel visibility set to: {self.unowned_frame_image.isVisible()}")
        
        # Force a complete refresh of the entire widget
        self.update()
        self.repaint()
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
    
    def fade_in(self):
        """Fade in the UnownedFrame (thread-safe)"""
        try:
            log.info("[UnownedFrame] Requesting fade in")
            self.fade_in_requested.emit()
        except Exception as e:
            log.error(f"[UnownedFrame] Error requesting fade in: {e}")
    
    def fade_out(self):
        """Fade out the UnownedFrame (thread-safe)"""
        try:
            log.info("[UnownedFrame] Requesting fade out")
            self.fade_out_requested.emit()
        except Exception as e:
            log.error(f"[UnownedFrame] Error requesting fade out: {e}")
    
    @pyqtSlot()
    def _do_fade_in(self):
        """Actually perform fade in (called in main thread)"""
        try:
            log.info("[UnownedFrame] Fading in")
            self._start_fade(1.0, config.CHROMA_FADE_IN_DURATION_MS)
            self.show()
            
            # Ensure proper z-order after showing (with small delay to ensure widget is fully shown)
            from PyQt6.QtCore import QTimer
            def delayed_zorder_refresh():
                log.debug("[UnownedFrame] Applying delayed z-order refresh after fade-in")
                self.refresh_z_order()
                # Also force the chroma button to come to front to ensure it's above the unowned frame
                try:
                    from ui.z_order_manager import get_z_order_manager
                    z_manager = get_z_order_manager()
                    z_manager.bring_to_front('chroma_button')
                    log.debug("[UnownedFrame] Forced chroma button to front after unowned frame fade-in")
                except Exception as e:
                    log.debug(f"[UnownedFrame] Error bringing chroma button to front: {e}")
            QTimer.singleShot(50, delayed_zorder_refresh)  # Increased delay to 50ms
            
            # Debug: Check if widget is visible and positioned correctly
            log.debug(f"[UnownedFrame] After show - visible: {self.isVisible()}, size: {self.size().width()}x{self.size().height()}, pos: ({self.x()}, {self.y()})")
            
            # Debug: Check visibility after showing
            log.debug(f"[UnownedFrame] After show - visible: {self.isVisible()}, size: {self.size().width()}x{self.size().height()}, pos: ({self.x()}, {self.y()})")
        except Exception as e:
            log.error(f"[UnownedFrame] Error fading in: {e}")
    
    @pyqtSlot()
    def _do_fade_out(self):
        """Actually perform fade out (called in main thread)"""
        try:
            log.info("[UnownedFrame] Fading out")
            self._start_fade(0.0, config.CHROMA_FADE_OUT_DURATION_MS)
        except Exception as e:
            log.error(f"[UnownedFrame] Error fading out: {e}")
    
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
            
            log.debug(f"[UnownedFrame] Starting fade: {self.fade_start_opacity:.2f} → {target_opacity:.2f} over {duration_ms}ms ({self.fade_steps} steps)")
            
            # Create timer for animation
            self.fade_timer = QTimer(self)
            self.fade_timer.timeout.connect(self._fade_step)
            self.fade_timer.start(frame_interval_ms)
            
        except RuntimeError:
            # Widget may have been deleted
            pass
    
    def _fade_step(self):
        """Execute one step of the fade animation"""
        try:
            if self.fade_current_step >= self.fade_steps:
                # Animation complete
                self.fade_timer.stop()
                self.fade_timer = None
                self.opacity_effect.setOpacity(self.fade_target_opacity)
                
                # Hide if fully transparent
                if self.fade_target_opacity <= 0.0:
                    self.hide()
                # Z-order is managed centrally - no manual adjustment needed
                
                log.debug(f"[UnownedFrame] Fade complete: opacity={self.fade_target_opacity:.2f}")
                return
            
            # Calculate current opacity (exponential easing)
            progress = self.fade_current_step / self.fade_steps
            if self.fade_target_opacity > self.fade_start_opacity:
                # Fade in: exponential ease-in
                eased_progress = progress * progress
            else:
                # Fade out: exponential ease-out
                eased_progress = 1.0 - (1.0 - progress) * (1.0 - progress)
            
            current_opacity = self.fade_start_opacity + (self.fade_target_opacity - self.fade_start_opacity) * eased_progress
            self.opacity_effect.setOpacity(current_opacity)
            
            # Z-order is managed centrally - no manual adjustments needed during fade
            
            self.fade_current_step += 1
            
        except RuntimeError:
            # Widget may have been deleted
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
    
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
                # Check if we just rebuilt recently (within last 100ms) to prevent conflicts
                import time
                current_time = time.time()
                if hasattr(self, '_last_rebuild_time') and (current_time - self._last_rebuild_time) < 0.1:
                    log.debug(f"[UnownedFrame] Skipping rebuild - just rebuilt {current_time - self._last_rebuild_time:.3f}s ago")
                    return
                
                self._updating_resolution = True  # Set flag
                log.info(f"[UnownedFrame] Resolution changed from {self._current_resolution} to {current_resolution}, requesting rebuild")
                
                # Update current resolution to prevent re-detection
                self._current_resolution = current_resolution
                
                # Request rebuild
                self._rebuild_for_resolution_change()
                
                # Record rebuild time
                self._last_rebuild_time = current_time
                
                # Clear update flag
                self._updating_resolution = False
        except Exception as e:
            log.error(f"[UnownedFrame] Error checking resolution: {e}")
            import traceback
            log.error(traceback.format_exc())
            # Clear flag even on error
            self._updating_resolution = False
    
    def _rebuild_for_resolution_change(self):
        """Completely rebuild UnownedFrame for resolution change - clean start"""
        try:
            log.info("[UnownedFrame] Starting complete rebuild for resolution change...")
            
            # Save current opacity state
            current_opacity = self.opacity_effect.opacity() if self.opacity_effect else 0.0
            
            # Completely clear existing components
            if hasattr(self, 'unowned_frame_image') and self.unowned_frame_image:
                self.unowned_frame_image.deleteLater()
                self.unowned_frame_image = None
            
            # Get fresh scaled values for new resolution
            self.scaled = get_scaled_chroma_values(force_reload=True)
            
            # Small delay to ensure cleanup
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()
            
            # Recreate all components from scratch with new resolution values
            self._create_components()
            
            # Force a complete widget refresh to ensure image is properly displayed
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()
            self.update()
            self.repaint()
            
            # Restore opacity state based on current skin ownership
            if self.opacity_effect:
                # Check if current skin should show UnownedFrame
                should_show = self._should_show_for_current_skin()
                if should_show:
                    # If current skin is unowned and not base, set opacity to 1.0
                    self.opacity_effect.setOpacity(1.0)
                    log.info("[UnownedFrame] Restored opacity to 1.0 for unowned skin after rebuild")
                else:
                    # If current skin is owned or base, keep it hidden
                    self.opacity_effect.setOpacity(0.0)
                    log.info("[UnownedFrame] Kept opacity at 0.0 for owned/base skin after rebuild")
            
            # Ensure proper z-order
            self.refresh_z_order()
            
            # Final refresh to ensure everything is displayed
            QApplication.processEvents()
            
            log.info(f"[UnownedFrame] Complete rebuild finished, restored opacity: {current_opacity:.2f}")
            
        except Exception as e:
            log.error(f"[UnownedFrame] Error in complete rebuild: {e}")
            import traceback
            log.error(traceback.format_exc())
    
    def _should_show_for_current_skin(self):
        """Check if UnownedFrame should be visible for the current skin"""
        try:
            if not self.state:
                log.debug("[UnownedFrame] No state available for ownership check")
                return False
            
            # Get current skin ID from state
            current_skin_id = self.state.last_hovered_skin_id
            if not current_skin_id:
                log.debug("[UnownedFrame] No current skin ID in state")
                return False
            
            # Check ownership and base skin status
            is_owned = current_skin_id in self.state.owned_skin_ids
            is_base_skin = current_skin_id % 1000 == 0
            should_show = not is_owned and not is_base_skin
            
            log.debug(f"[UnownedFrame] Ownership check: skin_id={current_skin_id}, is_owned={is_owned}, is_base_skin={is_base_skin}, should_show={should_show}")
            return should_show
            
        except Exception as e:
            log.error(f"[UnownedFrame] Error checking current skin ownership: {e}")
            return False
    
    def cleanup(self):
        """Clean up resources"""
        try:
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
            self.hide()
            log.debug("[UnownedFrame] Cleaned up")
        except Exception as e:
            log.debug(f"[UnownedFrame] Error during cleanup: {e}")
