"""
System tray settings dialog for adjusting injection threshold.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import tempfile
import threading
from typing import Optional

try:
    from PIL import Image  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    Image = None  # type: ignore

from config import get_config_float, set_config_option
from utils.logging import get_logger
from utils.paths import get_asset_path
from utils.license_client import LicenseClient
from utils.public_key import PUBLIC_KEY
from utils.win32_base import (
    BS_DEFPUSHBUTTON,
    BS_PUSHBUTTON,
    MAKELPARAM,
    SW_SHOWNORMAL,
    TBM_GETPOS,
    TBM_SETPOS,
    TBM_SETRANGE,
    WS_CAPTION,
    WS_CHILD,
    WS_EX_APPWINDOW,
    WS_EX_CLIENTEDGE,
    WS_SYSMENU,
    WS_TABSTOP,
    WS_VISIBLE,
    Win32Window,
    init_common_controls,
    user32,
)

log = get_logger()

MB_OK = 0x00000000
MB_ICONINFORMATION = 0x00000040
MB_ICONERROR = 0x00000010
MB_TOPMOST = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080


class InjectionSettingsWindow(Win32Window):
    TRACKBAR_ID = 3101
    VALUE_LABEL_ID = 3102
    SAVE_ID = 3103
    CANCEL_ID = 3104
    LICENSE_LABEL_ID = 3105
    LICENSE_SERVER_URL = "https://api.leagueunlocked.net"

    def __init__(self, initial_threshold: float) -> None:
        super().__init__(
            class_name="LeagueUnlockedSettingsDialog",
            window_title="Settings",
            width=360,
            height=220,
            style=WS_CAPTION | WS_SYSMENU,
        )
        self.initial_threshold = max(0.3, min(2.0, float(initial_threshold)))
        self.current_threshold = self.initial_threshold
        self.trackbar_hwnd: Optional[int] = None
        self.value_label_hwnd: Optional[int] = None
        self.license_label_hwnd: Optional[int] = None
        self.result: Optional[float] = None
        self._done = threading.Event()
        self._icon_temp_path: Optional[str] = None
        self._icon_source_path: Optional[str] = self._prepare_window_icon()
        self._license_status_text = self._load_license_status_text()
        init_common_controls()

    @staticmethod
    def _handle_value(hwnd) -> Optional[int]:
        if hwnd is None:
            return None
        if isinstance(hwnd, int):
            return hwnd
        return getattr(hwnd, "value", None)

    def _handles_equal(self, first, second) -> bool:
        first_val = self._handle_value(first)
        second_val = self._handle_value(second)
        if first_val is None or second_val is None:
            return False
        return first_val == second_val

    def _update_threshold_from_trackbar(self, raw_position: Optional[int] = None) -> None:
        if not self.trackbar_hwnd:
            return
        if raw_position is not None:
            pos = raw_position
        else:
            pos = self.send_message(self.trackbar_hwnd, TBM_GETPOS, 0, 0)
        try:
            pos_int = int(pos)
        except (TypeError, ValueError):
            return
        self.current_threshold = max(0.3, min(2.0, pos_int / 100.0))
        if self.value_label_hwnd:
            user32.SetWindowTextW(self.value_label_hwnd, f"{self.current_threshold:.2f} s")

    def _prepare_window_icon(self) -> Optional[str]:
        png_path: Optional[str] = None
        try:
            candidate = get_asset_path("icon.png")
            if candidate.exists():
                png_path = str(candidate)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"[TraySettings] Failed to resolve icon.png: {exc}")

        if png_path and Image is not None:
            try:
                tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ico")
                tmp_path = tmp_file.name
                tmp_file.close()
                with Image.open(png_path) as img:
                    img.save(
                        tmp_path,
                        format="ICO",
                        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
                    )
                self._icon_temp_path = tmp_path
                return tmp_path
            except Exception as exc:  # noqa: BLE001
                log.warning(f"[TraySettings] Failed to convert icon.png to .ico: {exc}")

        try:
            ico_candidate = get_asset_path("icon.ico")
            if ico_candidate.exists():
                return str(ico_candidate)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"[TraySettings] Failed to resolve icon.ico: {exc}")

        return None

    def _load_license_status_text(self) -> str:
        try:
            license_client = LicenseClient(
                server_url=self.LICENSE_SERVER_URL,
                public_key_pem=PUBLIC_KEY,
            )
            info = license_client.get_license_info()
            if not info:
                return "License: status unavailable"

            if info.get("is_expired"):
                return "License: expired"

            days_remaining = info.get("days_remaining")
            if days_remaining is None:
                return "License: status unavailable"
            if days_remaining <= 0:
                return "License: expires today"
            if days_remaining == 1:
                return "License: 1 day remaining"
            return f"License: {days_remaining} days remaining"
        except Exception as exc:  # noqa: BLE001
            log.debug(f"[TraySettings] Failed to load license info: {exc}")
            return "License: status unavailable"

    def on_create(self) -> Optional[int]:
        margin_x = 20
        margin_y = 18
        content_width = self.width - (margin_x * 2)

        self.create_control(
            "STATIC",
            "Adjust the injection threshold (seconds):",
            WS_CHILD | WS_VISIBLE,
            0,
            margin_x,
            margin_y,
            content_width,
            20,
            200,
        )

        value_label = self.create_control(
            "STATIC",
            f"{self.initial_threshold:.2f} s",
            WS_CHILD | WS_VISIBLE,
            0,
            margin_x,
            margin_y + 24,
            content_width,
            20,
            self.VALUE_LABEL_ID,
        )
        self.value_label_hwnd = value_label

        trackbar = self.create_control(
            "msctls_trackbar32",
            "",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP,
            0,
            margin_x,
            margin_y + 54,
            content_width,
            30,
            self.TRACKBAR_ID,
        )
        self.trackbar_hwnd = trackbar

        min_pos = 30
        max_pos = 200
        initial_pos = max(min_pos, min(max_pos, int(round(self.initial_threshold * 100))))

        self.send_message(trackbar, TBM_SETRANGE, 1, MAKELPARAM(min_pos, max_pos))
        self.send_message(trackbar, TBM_SETPOS, 1, initial_pos)

        license_label = self.create_control(
            "STATIC",
            self._license_status_text,
            WS_CHILD | WS_VISIBLE,
            0,
            margin_x,
            margin_y + 94,
            content_width,
            20,
            self.LICENSE_LABEL_ID,
        )
        self.license_label_hwnd = license_label

        if self.hwnd:
            self.set_window_ex_styles(self.hwnd, add=WS_EX_TOOLWINDOW, remove=WS_EX_APPWINDOW)
            if self._icon_source_path:
                self.set_window_icon(self._icon_source_path)

        button_y = margin_y + 130
        self.create_control(
            "BUTTON",
            "Save",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON,
            0,
            margin_x + content_width - 180,
            button_y,
            80,
            26,
            self.SAVE_ID,
        )
        self.create_control(
            "BUTTON",
            "Cancel",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
            0,
            margin_x + content_width - 90,
            button_y,
            80,
            26,
            self.CANCEL_ID,
        )
        return 0

    def on_command(self, command_id: int, notification_code: int, control_hwnd) -> Optional[int]:
        if command_id == self.SAVE_ID and notification_code == 0:
            self._update_threshold_from_trackbar()
            self.result = self.current_threshold
            self._done.set()
            user32.DestroyWindow(self.hwnd)
            return 0
        if command_id == self.CANCEL_ID and notification_code == 0:
            self.result = None
            self._done.set()
            user32.DestroyWindow(self.hwnd)
            return 0
        if command_id == self.TRACKBAR_ID:
            self._update_threshold_from_trackbar()
        return None

    def on_hscroll(self, request_code: int, position: int, trackbar_hwnd) -> Optional[int]:
        if not self._handles_equal(trackbar_hwnd, self.trackbar_hwnd):
            return None
        thumb_codes = {4, 5}  # TB_THUMBPOSITION, TB_THUMBTRACK
        direct_position = position if request_code in thumb_codes else None
        self._update_threshold_from_trackbar(direct_position)
        return 0

    def on_close(self) -> Optional[int]:
        self.result = None
        self._done.set()
        return super().on_close()

    def on_destroy(self) -> Optional[int]:
        if self._icon_temp_path:
            try:
                os.remove(self._icon_temp_path)
            except OSError:
                pass
            self._icon_temp_path = None
        user32.PostQuitMessage(0)
        return 0

    def wait(self) -> None:
        self._done.wait()


def show_injection_settings_dialog() -> None:
    """
    Show the injection threshold settings dialog and persist changes.
    """
    current_threshold = get_config_float("General", "injection_threshold", 0.5)
    result_holder: dict[str, Optional[float]] = {"value": None}
    done_event = threading.Event()

    def dialog_thread() -> None:
        window: Optional[InjectionSettingsWindow] = None
        try:
            window = InjectionSettingsWindow(current_threshold)
            window.show_window(SW_SHOWNORMAL)

            msg = wintypes.MSG()
            while True:
                res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if res <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            if window and window.result is not None:
                result_holder["value"] = window.result
        finally:
            done_event.set()

    thread = threading.Thread(target=dialog_thread, daemon=True)
    thread.start()
    done_event.wait()

    new_value = result_holder["value"]
    if new_value is None:
        return

    try:
        set_config_option("General", "injection_threshold", f"{new_value:.2f}")
        log.info(f"[TraySettings] Injection threshold updated to {new_value:.2f}s")
    except Exception as exc:  # noqa: BLE001
        log.error(f"[TraySettings] Failed to save injection threshold: {exc}")
        user32.MessageBoxW(
            None,
            f"Failed to save settings:\n\n{exc}",
            "LeagueUnlocked Settings",
            MB_OK | MB_ICONERROR | MB_TOPMOST,
        )

