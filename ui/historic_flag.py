#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HistoricFlag - UI component for showing historic skin indicator
Uses same location/size logic as RandomFlag but different image.
"""

from PyQt6.QtWidgets import QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from ui.chroma_base import ChromaWidgetBase
from ui.chroma_scaling import get_scaled_chroma_values
from ui.z_order_manager import ZOrderManager
from utils.logging import get_logger
from utils.resolution_utils import (
    scale_dimension_from_base,
    scale_position_from_base,
)

log = get_logger()


class HistoricFlag(ChromaWidgetBase):
    """UI component showing historic flag indicator"""
    fade_in_requested = pyqtSignal()
    fade_out_requested = pyqtSignal()

    def __init__(self, state=None):
        super().__init__(
            z_level=ZOrderManager.Z_LEVELS['RANDOM_FLAG'],
            widget_name='historic_flag'
        )

        self.state = state
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.scaled = get_scaled_chroma_values()

        self._current_resolution = None
        self._updating_resolution = False

        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)

        self._create_components()

        self.fade_timer = None
        self.fade_target_opacity = 0.0
        self.fade_start_opacity = 0.0
        self.fade_steps = 0
        self.fade_current_step = 0

        self.is_visible = False

        self.fade_in_requested.connect(self._do_fade_in)
        self.fade_out_requested.connect(self._do_fade_out)

        self.opacity_effect.setOpacity(0.0)
        self.hide()

    def _create_components(self):
        if hasattr(self, 'flag_image') and self.flag_image:
            self.flag_image.deleteLater()
            self.flag_image = None

        from utils.window_utils import get_league_window_handle, find_league_window_rect
        import ctypes

        league_hwnd = get_league_window_handle()
        window_rect = find_league_window_rect()
        if not league_hwnd or not window_rect:
            log.debug("[HistoricFlag] Could not get League window for static positioning")
            return

        window_left, window_top, window_right, window_bottom = window_rect
        window_width = window_right - window_left
        window_height = window_bottom - window_top

        try:
            from utils.paths import get_asset_path
            flag_pixmap = QPixmap(str(get_asset_path('historic_flag.png')))
            if flag_pixmap.isNull():
                log.warning("[HistoricFlag] Failed to load historic_flag.png")
                return

            if window_width == 1600 and window_height == 900:
                flag_size = 32
                target_x = 851
                target_y = 634
            elif window_width == 1280 and window_height == 720:
                flag_size = 26
                target_x = 680
                target_y = 507
            elif window_width == 1024 and window_height == 576:
                flag_size = 20
                target_x = 544
                target_y = 406
            else:
                flag_size = scale_dimension_from_base(32, (window_width, window_height), axis='y')
                target_x = scale_position_from_base(851, (window_width, window_height), axis='x')
                target_y = scale_position_from_base(634, (window_width, window_height), axis='y')
                log.info(
                    f"[HistoricFlag] Scaled position for unsupported resolution {window_width}x{window_height}: {target_x},{target_y} size {flag_size}"
                )

            self.setFixedSize(flag_size, flag_size)
            self.setGeometry(self.x(), self.y(), flag_size, flag_size)

            widget_hwnd = int(self.winId())
            ctypes.windll.user32.SetParent(widget_hwnd, league_hwnd)

            GWL_STYLE = -16
            WS_CHILD = 0x40000000
            WS_POPUP = 0x80000000

            if ctypes.sizeof(ctypes.c_void_p) == 8:
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
                current_style = ctypes.windll.user32.GetWindowLongW(widget_hwnd, GWL_STYLE)
                new_style = (current_style & ~WS_POPUP) | WS_CHILD
                ctypes.windll.user32.SetWindowLongW(widget_hwnd, GWL_STYLE, new_style)

            HWND_TOP = 0
            ctypes.windll.user32.SetWindowPos(
                widget_hwnd, HWND_TOP, target_x, target_y, 0, 0,
                0x0001 | 0x0004
            )

            self.flag_image = QLabel(self)
            self.flag_image.setGeometry(0, 0, flag_size, flag_size)
            self.flag_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.flag_image.setScaledContents(True)
            scaled = flag_pixmap.scaled(
                flag_size,
                flag_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.flag_image.setPixmap(scaled)

            self._current_resolution = (window_width, window_height)
            log.debug(f"[HistoricFlag] Created at ({target_x}, {target_y}) size {flag_size}x{flag_size}")

        except Exception as e:
            log.error(f"[HistoricFlag] Error creating components: {e}")

    def ensure_position(self):
        try:
            from utils.window_utils import get_league_window_handle, find_league_window_rect
            import ctypes
            league_hwnd = get_league_window_handle()
            window_rect = find_league_window_rect()
            if not league_hwnd or not window_rect:
                return
            window_left, window_top, window_right, window_bottom = window_rect
            window_width = window_right - window_left
            window_height = window_bottom - window_top
            if window_width == 1600 and window_height == 900:
                flag_size = 32
                target_x = 851
                target_y = 634
            elif window_width == 1280 and window_height == 720:
                flag_size = 26
                target_x = 680
                target_y = 507
            elif window_width == 1024 and window_height == 576:
                flag_size = 20
                target_x = 544
                target_y = 406
            else:
                flag_size = scale_dimension_from_base(32, (window_width, window_height), axis='y')
                target_x = scale_position_from_base(851, (window_width, window_height), axis='x')
                target_y = scale_position_from_base(634, (window_width, window_height), axis='y')
            widget_hwnd = int(self.winId())
            HWND_TOP = 0
            ctypes.windll.user32.SetWindowPos(
                widget_hwnd, HWND_TOP, target_x, target_y, 0, 0,
                0x0001 | 0x0004
            )
        except Exception as e:
            log.debug(f"[HistoricFlag] ensure_position error: {e}")

    def show_flag(self):
        if not self.is_visible:
            self.is_visible = True
            log.debug("[HistoricFlag] show_flag() called")
            self.show()
            def delayed_zorder_refresh():
                log.debug("[HistoricFlag] Applying delayed z-order refresh after show")
                self.refresh_z_order()
            QTimer.singleShot(50, delayed_zorder_refresh)
            self.fade_in_requested.emit()

    def hide_flag(self):
        if self.is_visible:
            self.is_visible = False
            log.debug("[HistoricFlag] hide_flag() called")
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
            self.opacity_effect.setOpacity(0.0)
            self.hide()
    
    def show_flag_instantly(self):
        """Show the historic flag instantly without fade, preserving state"""
        if not self.is_visible:
            self.is_visible = True
            log.debug("[HistoricFlag] show_flag_instantly() called")
            # Stop any ongoing fade animation
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
        # Always set opacity to 1.0 instantly (even if already visible)
        self.opacity_effect.setOpacity(1.0)
        self.show()
        # Ensure proper z-order after showing
        from PyQt6.QtCore import QTimer
        def delayed_zorder_refresh():
            log.debug("[HistoricFlag] Applying delayed z-order refresh after instant show")
            self.refresh_z_order()
        QTimer.singleShot(50, delayed_zorder_refresh)

    def _do_fade_in(self):
        if self.fade_timer:
            self.fade_timer.stop()
        self.fade_target_opacity = 1.0
        self.fade_start_opacity = self.opacity_effect.opacity()
        self.fade_steps = 20
        self.fade_current_step = 0
        self.fade_timer = QTimer()
        self.fade_timer.timeout.connect(self._fade_step)
        self.fade_timer.start(16)

    def _do_fade_out(self):
        if self.fade_timer:
            self.fade_timer.stop()
        self.fade_target_opacity = 0.0
        self.fade_start_opacity = self.opacity_effect.opacity()
        self.fade_steps = 20
        self.fade_current_step = 0
        self.fade_timer = QTimer()
        self.fade_timer.timeout.connect(self._fade_step)
        self.fade_timer.start(16)

    def _fade_step(self):
        if self.fade_current_step >= self.fade_steps:
            self.fade_timer.stop()
            self.fade_timer = None
            
            # Set final opacity to target
            self.opacity_effect.setOpacity(self.fade_target_opacity)
            
            if self.fade_target_opacity == 0.0:
                self.hide()
            return
        progress = self.fade_current_step / self.fade_steps
        current_opacity = self.fade_start_opacity + (self.fade_target_opacity - self.fade_start_opacity) * progress
        self.opacity_effect.setOpacity(current_opacity)
        self.fade_current_step += 1

    def check_resolution_and_update(self):
        try:
            from utils.window_utils import find_league_window_rect
            window_rect = find_league_window_rect()
            if not window_rect:
                return
            window_left, window_top, window_right, window_bottom = window_rect
            current_resolution = (window_right - window_left, window_bottom - window_top)
            if self._current_resolution != current_resolution:
                log.info(f"[HistoricFlag] Resolution changed from {self._current_resolution} to {current_resolution}, recreating")
                self._create_components()
        except Exception as e:
            log.error(f"[HistoricFlag] Error checking resolution: {e}")

    def cleanup(self):
        try:
            if self.fade_timer:
                self.fade_timer.stop()
                self.fade_timer = None
            self.hide()
            self.deleteLater()
            log.debug("[HistoricFlag] Cleaned up and scheduled for deletion")
        except Exception as e:
            log.debug(f"[HistoricFlag] Error during cleanup: {e}")


