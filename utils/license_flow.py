"""
License validation helpers using native Win32 UI elements.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import threading
from typing import Callable, Optional

from utils.license_client import LicenseClient
from utils.logging import get_logger, get_log_mode, log_section, log_success
from utils.paths import get_user_data_dir
from utils.public_key import PUBLIC_KEY
from utils.win32_base import (
    BS_DEFPUSHBUTTON,
    BS_PUSHBUTTON,
    ES_AUTOHSCROLL,
    SW_SHOWNORMAL,
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
MB_ICONERROR = 0x00000010
MB_ICONINFORMATION = 0x00000040
MB_TOPMOST = 0x00040000


class LicenseActivationWindow(Win32Window):
    EDIT_ID = 2001
    OK_ID = 2002
    CANCEL_ID = 2003

    def __init__(self, error_message: str = "") -> None:
        super().__init__(
            class_name="LeagueUnlockedLicenseDialog",
            window_title="LeagueUnlocked - License Activation",
            width=420,
            height=200,
            style=WS_CAPTION | WS_SYSMENU,
        )
        self.error_message = error_message
        self.result: Optional[str] = None
        self._done = threading.Event()
        self.input_hwnd: Optional[int] = None
        self.error_hwnd: Optional[int] = None
        init_common_controls()

    def on_create(self) -> Optional[int]:
        margin_x = 20
        margin_y = 18
        content_width = self.width - (margin_x * 2)

        self.create_control(
            "STATIC",
            "Enter your license key to continue:",
            WS_CHILD | WS_VISIBLE,
            0,
            margin_x,
            margin_y,
            content_width,
            20,
            100,
        )

        if self.error_message:
            error_hwnd = self.create_control(
                "STATIC",
                self.error_message,
                WS_CHILD | WS_VISIBLE,
                0,
                margin_x,
                margin_y + 24,
                content_width,
                32,
                101,
            )
            self.error_hwnd = error_hwnd
            margin_y += 34

        input_hwnd = self.create_control(
            "EDIT",
            "",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
            WS_EX_CLIENTEDGE,
            margin_x,
            margin_y + 26,
            content_width,
            26,
            self.EDIT_ID,
        )
        self.input_hwnd = input_hwnd
        user32.SetFocus(input_hwnd)
        # Limit license key length
        EM_SETLIMITTEXT = 0x00C5
        user32.SendMessageW(input_hwnd, EM_SETLIMITTEXT, 128, 0)

        button_y = margin_y + 70
        ok_hwnd = self.create_control(
            "BUTTON",
            "Activate",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON,
            0,
            margin_x + content_width - 200,
            button_y,
            90,
            28,
            self.OK_ID,
        )
        self.create_control(
            "BUTTON",
            "Cancel",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
            0,
            margin_x + content_width - 100,
            button_y,
            90,
            28,
            self.CANCEL_ID,
        )
        user32.SetFocus(ok_hwnd)
        return 0

    def on_command(self, command_id: int, notification_code: int, control_hwnd) -> Optional[int]:
        if command_id == self.OK_ID and notification_code == 0:
            self._handle_ok()
            return 0
        if command_id == self.CANCEL_ID and notification_code == 0:
            self.result = None
            user32.DestroyWindow(self.hwnd)
            return 0
        return None

    def on_close(self) -> Optional[int]:
        self.result = None
        self._done.set()
        return super().on_close()

    def on_destroy(self) -> Optional[int]:
        self._done.set()
        user32.PostQuitMessage(0)
        return 0

    def _handle_ok(self) -> None:
        if not self.input_hwnd:
            return
        length = user32.GetWindowTextLengthW(self.input_hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(self.input_hwnd, buffer, len(buffer))
        license_key = buffer.value.strip()

        if not license_key:
            user32.MessageBoxW(
                self.hwnd,
                "Please enter a license key.",
                "License Activation",
                MB_OK | MB_ICONERROR | MB_TOPMOST,
            )
            return

        self.result = license_key
        self._done.set()
        user32.DestroyWindow(self.hwnd)

def show_license_activation_dialog(error_message: str = "") -> Optional[str]:
    """
    Display the native Win32 license activation dialog and return the entered key.
    """
    result_holder: dict[str, Optional[str]] = {"value": None}
    done_event = threading.Event()

    def dialog_thread() -> None:
        window: Optional[LicenseActivationWindow] = None
        try:
            window = LicenseActivationWindow(error_message)
            window.show_window(SW_SHOWNORMAL)

            msg = wintypes.MSG()
            while True:
                res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if res <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            result_holder["value"] = window.result if window else None
        finally:
            done_event.set()

    thread = threading.Thread(target=dialog_thread, daemon=True)
    thread.start()
    done_event.wait()
    return result_holder["value"]


def check_license(status_callback: Optional[Callable[[str], None]] = None) -> bool:
    """
    Validate the user's license, prompting for activation if required.
    """

    def update_status(message: str) -> None:
        if status_callback:
            status_callback(message)
        log.info(f"[LICENSE] {message}")

    update_status("Starting license check...")

    license_client = LicenseClient(
        server_url="https://api.leagueunlocked.net",
        license_file=str(get_user_data_dir() / "license.dat"),
        public_key_pem=PUBLIC_KEY,
    )

    update_status("Checking license validity (offline)…")
    valid, message = license_client.is_license_valid(check_online=False)
    log.info(f"[LICENSE] Validation result: valid={valid}, message={message}")

    if not valid:
        update_status(f"License validation failed: {message}")
        max_attempts = 3
        for attempt in range(max_attempts):
            prompt_message = message if message else "No license detected. Please enter your license key."
            license_key = show_license_activation_dialog(prompt_message)
            if not license_key:
                user32.MessageBoxW(
                    None,
                    "No license key entered. LeagueUnlocked will now exit.",
                    "LeagueUnlocked - License Required",
                    MB_OK | MB_ICONERROR | MB_TOPMOST,
                )
                sys.exit(1)

            update_status("Activating license...")
            success, activation_message = license_client.activate_license(license_key)

            if success:
                log_success(log, f"License activated successfully: {activation_message}", "✅")
                user32.MessageBoxW(
                    None,
                    f"License activated successfully.\n\n{activation_message}",
                    "License Activated",
                    MB_OK | MB_ICONINFORMATION | MB_TOPMOST,
                )
                valid = True
                break

            message = activation_message
            update_status(f"License activation failed: {activation_message}")
            if attempt == max_attempts - 1:
                user32.MessageBoxW(
                    None,
                    f"License activation failed after {max_attempts} attempts:\n\n{activation_message}",
                    "LeagueUnlocked - Activation Failed",
                    MB_OK | MB_ICONERROR | MB_TOPMOST,
                )
                sys.exit(1)

    info = license_client.get_license_info()
    if info:
        if get_log_mode() == "customer":
            log.info(f"✅ License Valid ({info['days_remaining']} days remaining)")
        else:
            log_section(
                log,
                "License Validated",
                "✅",
                {
                    "Status": "Active",
                    "Days Remaining": str(info["days_remaining"]),
                    "Expires": info["expires_at"],
                },
            )

    update_status("License check complete.")
    return True

