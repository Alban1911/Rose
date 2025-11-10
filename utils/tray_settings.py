"""
System tray settings dialog for adjusting injection threshold.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Optional

from config import get_config_float, set_config_option
from utils.logging import get_logger
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


class InjectionSettingsWindow(Win32Window):
    TRACKBAR_ID = 3101
    VALUE_LABEL_ID = 3102
    SAVE_ID = 3103
    CANCEL_ID = 3104

    def __init__(self, initial_threshold: float) -> None:
        super().__init__(
            class_name="LeagueUnlockedSettingsDialog",
            window_title="Injection Threshold",
            width=360,
            height=200,
            style=WS_CAPTION | WS_SYSMENU,
        )
        self.initial_threshold = max(0.3, min(2.0, float(initial_threshold)))
        self.current_threshold = self.initial_threshold
        self.trackbar_hwnd: Optional[int] = None
        self.value_label_hwnd: Optional[int] = None
        self.result: Optional[float] = None
        self._done = threading.Event()
        init_common_controls()

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

        button_y = margin_y + 110
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
            self.result = self.current_threshold
            self._done.set()
            user32.DestroyWindow(self.hwnd)
            return 0
        if command_id == self.CANCEL_ID and notification_code == 0:
            self.result = None
            self._done.set()
            user32.DestroyWindow(self.hwnd)
            return 0
        return None

    def on_hscroll(self, request_code: int, position: int, trackbar_hwnd) -> Optional[int]:
        if trackbar_hwnd and trackbar_hwnd == self.trackbar_hwnd:
            pos = self.send_message(self.trackbar_hwnd, TBM_GETPOS, 0, 0)
            self.current_threshold = max(0.3, min(2.0, pos / 100.0))
            if self.value_label_hwnd:
                user32.SetWindowTextW(self.value_label_hwnd, f"{self.current_threshold:.2f} s")
        return 0

    def on_close(self) -> Optional[int]:
        self.result = None
        self._done.set()
        return super().on_close()

    def on_destroy(self) -> Optional[int]:
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
        user32.MessageBoxW(
            None,
            f"Injection threshold saved: {new_value:.2f} seconds.",
            "LeagueUnlocked Settings",
            MB_OK | MB_ICONINFORMATION | MB_TOPMOST,
        )
    except Exception as exc:  # noqa: BLE001
        log.error(f"[TraySettings] Failed to save injection threshold: {exc}")
        user32.MessageBoxW(
            None,
            f"Failed to save settings:\n\n{exc}",
            "LeagueUnlocked Settings",
            MB_OK | MB_ICONERROR | MB_TOPMOST,
        )

