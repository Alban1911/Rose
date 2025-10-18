#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UnownedFrame - UI component for showing unowned skin indicator
Shows golden border and lock icon for unowned skins
"""

import time
from PyQt6.QtWidgets import QWidget, QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QTimer, QMetaObject, pyqtSlot
from PyQt6.QtGui import QPixmap
from ui.chroma_base import ChromaWidgetBase
from ui.chroma_scaling import get_scaled_chroma_values
from utils.logging import get_logger
import config

log = get_logger()


class UnownedFrame(ChromaWidgetBase):
    """UI component showing golden border and lock for unowned skins"""
    
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        # Get scaled values
        self.scaled = get_scaled_chroma_values()
        
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
        
        # Start invisible
        self.opacity_effect.setOpacity(0.0)
        self.hide()
    
    def _create_components(self):
        """Create the golden border and lock components"""
        # Set size based on scaled values
        frame_size = int(self.scaled.button_size * 6)
        self.setFixedSize(frame_size, frame_size)
        
        # Create golden border (OutlineGold)
        self.outline_gold = QLabel(self)
        self.outline_gold.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Load golden border image
        try:
            gold_pixmap = QPixmap("assets/carousel-outline-gold.png")
            if not gold_pixmap.isNull():
                # Scale the image to fit the frame
                scaled_pixmap = gold_pixmap.scaled(
                    frame_size, frame_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.outline_gold.setPixmap(scaled_pixmap)
                log.debug(f"[UnownedFrame] Golden border loaded, size: {scaled_pixmap.width()}x{scaled_pixmap.height()}")
            else:
                log.warning("[UnownedFrame] Failed to load golden border image")
        except Exception as e:
            log.error(f"[UnownedFrame] Error loading golden border: {e}")
        
        # Position golden border in center
        self.outline_gold.move(0, 0)
        self.outline_gold.resize(frame_size, frame_size)
        
        # Create lock icon
        self.lock_icon = QLabel(self)
        self.lock_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Load lock image (you'll need to add a lock image asset)
        try:
            # For now, create a simple text-based lock
            self.lock_icon.setText("🔒")
            self.lock_icon.setStyleSheet("""
                QLabel {
                    color: #FFD700;
                    font-size: 24px;
                    font-weight: bold;
                    background: transparent;
                }
            """)
            log.debug("[UnownedFrame] Lock icon created")
        except Exception as e:
            log.error(f"[UnownedFrame] Error creating lock icon: {e}")
        
        # Position lock in center
        lock_size = 56  # Fixed size for lock
        lock_x = (frame_size - lock_size) // 2
        lock_y = (frame_size - lock_size) // 2
        self.lock_icon.move(lock_x, lock_y)
        self.lock_icon.resize(lock_size, lock_size)
        
        log.info("[UnownedFrame] Components created successfully")
    
    def fade_in(self):
        """Fade in the UnownedFrame"""
        try:
            log.info("[UnownedFrame] Fading in")
            self._start_fade(1.0, config.CHROMA_FADE_IN_DURATION_MS)
            self.show()
        except Exception as e:
            log.error(f"[UnownedFrame] Error fading in: {e}")
    
    def fade_out(self):
        """Fade out the UnownedFrame"""
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
            
            self.fade_current_step += 1
            
        except RuntimeError:
            # Widget may have been deleted
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
    
    def _update_position(self, button_pos):
        """Update position relative to button"""
        try:
            # Position UnownedFrame centered on the button
            frame_size = int(self.scaled.button_size * 6)
            x = button_pos.x() - (frame_size - self.scaled.button_size) // 2
            y = button_pos.y() - (frame_size - self.scaled.button_size) // 2
            self.move(x, y)
            log.debug(f"[UnownedFrame] Position updated to ({x}, {y})")
        except Exception as e:
            log.debug(f"[UnownedFrame] Error updating position: {e}")
    
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
