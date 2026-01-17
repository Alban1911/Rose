"""
System tray settings dialog for adjusting injection threshold.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional

try:
    from PIL import Image  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    Image = None  # type: ignore

from config import get_config_float, get_config_option, set_config_option
from utils.system.admin_utils import (
    is_admin,
    is_registered_for_autostart,
    register_autostart,
    unregister_autostart,
    show_autostart_removed_dialog,
    show_autostart_success_dialog,
    show_message_box_threaded,
)
from utils.core.logging import get_logger
from utils.core.paths import get_asset_path
from utils.system.win32_base import (
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
BS_AUTOCHECKBOX = 0x00000003
BM_GETCHECK = 0x00F0
BM_SETCHECK = 0x00F1
BST_UNCHECKED = 0x0000
BST_CHECKED = 0x0001

# Edit control constants
ES_LEFT = 0x0000
ES_MULTILINE = 0x0004
ES_AUTOVSCROLL = 0x0040
ES_AUTOHSCROLL = 0x0080
ES_NOHIDESEL = 0x0100
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_SETTEXT = 0x000C
EN_CHANGE = 0x0300
EN_UPDATE = 0x0400


class InjectionSettingsWindow(Win32Window):
    TRACKBAR_ID = 3101
    VALUE_LABEL_ID = 3102
    SAVE_ID = 3103
    CANCEL_ID = 3104
    AUTOSTART_ID = 3106
    GAME_PATH_EDIT_ID = 3107
    GAME_PATH_LABEL_ID = 3108
    GAME_PATH_STATUS_ID = 3109

    def __init__(self, initial_threshold: float) -> None:
        super().__init__(
            class_name="RoseSettingsDialog",
            window_title="Settings",
            width=360,
            height=380,
            style=WS_CAPTION | WS_SYSMENU,
        )
        self.initial_threshold = max(0.0, min(2.0, float(initial_threshold)))
        self.current_threshold = self.initial_threshold
        self.trackbar_hwnd: Optional[int] = None
        self.value_label_hwnd: Optional[int] = None
        self.autostart_checkbox_hwnd: Optional[int] = None
        self.game_path_edit_hwnd: Optional[int] = None
        self.game_path_status_hwnd: Optional[int] = None
        self.result: Optional[float] = None
        self.autostart_result: Optional[bool] = None
        self.game_path_result: Optional[str] = None
        self._done = threading.Event()
        self._icon_temp_path: Optional[str] = None
        self._icon_source_path: Optional[str] = self._prepare_window_icon()
        self._autostart_initial, self._autostart_enabled = self._load_autostart_status()
        self._initial_game_path = self._load_game_path()
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
        self.current_threshold = max(0.0, min(2.0, pos_int / 100.0))
        if self.value_label_hwnd:
            user32.SetWindowTextW(self.value_label_hwnd, f"{self.current_threshold:.2f} s")

    def _prepare_window_icon(self) -> Optional[str]:
        png_path: Optional[str] = None
        try:
            candidate = get_asset_path("tray_ready.png")
            if candidate.exists():
                png_path = str(candidate)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"[TraySettings] Failed to resolve tray_ready.png icon: {exc}")

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
                log.warning(f"[TraySettings] Failed to convert tray_ready.png to .ico: {exc}")

        try:
            ico_candidate = get_asset_path("icon.ico")
            if ico_candidate.exists():
                return str(ico_candidate)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"[TraySettings] Failed to resolve icon.ico: {exc}")

        return None

    def _load_autostart_status(self) -> tuple[bool, bool]:
        try:
            enabled = is_registered_for_autostart()
            return enabled, enabled
        except Exception as exc:  # noqa: BLE001
            log.debug(f"[TraySettings] Failed to load autostart status: {exc}")
            return False, False

    def _load_game_path(self) -> str:
        """Load league path from config"""
        try:
            path = get_config_option("General", "leaguePath")
            return path or ""
        except Exception as exc:  # noqa: BLE001
            log.debug(f"[TraySettings] Failed to load league path: {exc}")
            return ""

    def _validate_game_path(self, path: str) -> bool:
        """Validate that the game path exists and contains League of Legends.exe"""
        if not path or not path.strip():
            return False
        try:
            game_dir = Path(path.strip())
            if not game_dir.exists() or not game_dir.is_dir():
                return False
            league_exe = game_dir / "League of Legends.exe"
            return league_exe.exists() and league_exe.is_file()
        except Exception:
            return False

    def _update_path_status(self, path: str = None) -> None:
        """Update the status indicator based on path validation"""
        if path is None:
            # Get current text from edit control
            if not self.game_path_edit_hwnd:
                return
            length = self.send_message(self.game_path_edit_hwnd, WM_GETTEXTLENGTH, 0, 0)
            if length == 0:
                path = ""
            else:
                buffer = ctypes.create_unicode_buffer(length + 1)
                self.send_message(self.game_path_edit_hwnd, WM_GETTEXT, length + 1, ctypes.addressof(buffer))
                path = buffer.value
        
        if not self.game_path_status_hwnd:
            return
        
        is_valid = self._validate_game_path(path)
        status_text = "✅" if is_valid else "❌"
        user32.SetWindowTextW(self.game_path_status_hwnd, status_text)

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

        autostart_checkbox = self.create_control(
            "BUTTON",
            "Start automatically with Windows",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTOCHECKBOX,
            0,
            margin_x,
            margin_y + 122,
            content_width,
            20,
            self.AUTOSTART_ID,
        )
        self.autostart_checkbox_hwnd = autostart_checkbox
        if self._autostart_enabled:
            self.send_message(autostart_checkbox, BM_SETCHECK, BST_CHECKED, 0)

        # Game path section
        game_path_y = margin_y + 162
        self.create_control(
            "STATIC",
            "League of Legends Game Path:",
            WS_CHILD | WS_VISIBLE,
            0,
            margin_x,
            game_path_y,
            content_width,
            20,
            self.GAME_PATH_LABEL_ID,
        )

        # Edit control for game path
        game_path_edit = self.create_control(
            "EDIT",
            self._initial_game_path,
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_LEFT | ES_AUTOHSCROLL,
            WS_EX_CLIENTEDGE,
            margin_x,
            game_path_y + 24,
            content_width - 30,
            22,
            self.GAME_PATH_EDIT_ID,
        )
        self.game_path_edit_hwnd = game_path_edit

        # Status indicator (emoji)
        status_indicator = self.create_control(
            "STATIC",
            "",
            WS_CHILD | WS_VISIBLE,
            0,
            margin_x + content_width - 25,
            game_path_y + 24,
            20,
            22,
            self.GAME_PATH_STATUS_ID,
        )
        self.game_path_status_hwnd = status_indicator
        # Initial validation
        self._update_path_status(self._initial_game_path)

        if self.hwnd:
            self.set_window_ex_styles(self.hwnd, add=WS_EX_TOOLWINDOW, remove=WS_EX_APPWINDOW)
            if self._icon_source_path:
                self.set_window_icon(self._icon_source_path)

        button_y = margin_y + 218
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
            self.autostart_result = self._autostart_enabled
            # Get game path from edit control
            if self.game_path_edit_hwnd:
                length = self.send_message(self.game_path_edit_hwnd, WM_GETTEXTLENGTH, 0, 0)
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    self.send_message(self.game_path_edit_hwnd, WM_GETTEXT, length + 1, ctypes.addressof(buffer))
                    self.game_path_result = buffer.value.strip()
                else:
                    self.game_path_result = ""
            self._done.set()
            user32.DestroyWindow(self.hwnd)
            return 0
        if command_id == self.CANCEL_ID and notification_code == 0:
            self.result = None
            self.autostart_result = None
            self.game_path_result = None
            self._done.set()
            user32.DestroyWindow(self.hwnd)
            return 0
        if command_id == self.TRACKBAR_ID:
            self._update_threshold_from_trackbar()
            return 0
        if command_id == self.AUTOSTART_ID and notification_code == 0:
            self._handle_autostart_toggle()
            return 0
        if command_id == self.GAME_PATH_EDIT_ID and notification_code == EN_CHANGE:
            # Path changed, update validation status
            self._update_path_status()
            return 0
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

    def _handle_autostart_toggle(self) -> None:
        if not self.autostart_checkbox_hwnd:
            return
        state = self.send_message(self.autostart_checkbox_hwnd, BM_GETCHECK, 0, 0)
        self._autostart_enabled = state == BST_CHECKED

    @property
    def autostart_initial(self) -> bool:
        return self._autostart_initial


def show_injection_settings_dialog() -> None:
    """
    Show the injection threshold settings dialog and persist changes.
    """
    current_threshold = get_config_float("General", "injection_threshold", 0.5)
    result_holder: dict[str, Optional[float | bool | str]] = {
        "threshold": None,
        "autostart": None,
        "autostart_initial": None,
        "game_path": None,
    }
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
                result_holder["threshold"] = window.result
                result_holder["autostart"] = window.autostart_result
                result_holder["autostart_initial"] = window.autostart_initial
                result_holder["game_path"] = window.game_path_result
        finally:
            done_event.set()

    thread = threading.Thread(target=dialog_thread, daemon=True)
    thread.start()
    done_event.wait()

    new_value = result_holder["threshold"]
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
            "Rose Settings",
            MB_OK | MB_ICONERROR | MB_TOPMOST,
        )
        # Even if threshold save fails, fall through to process auto-start changes.

    # Save game path if provided
    game_path = result_holder["game_path"]
    if game_path is not None:
        try:
            if game_path.strip():
                set_config_option("General", "leaguePath", game_path.strip())
                # Try to infer and save client path
                from injection.config.config_manager import ConfigManager
                config_manager = ConfigManager()
                inferred_client_path = config_manager.infer_client_path_from_league_path(game_path.strip())
                if inferred_client_path:
                    set_config_option("General", "clientPath", inferred_client_path)
                    log.info(f"[TraySettings] League path updated to: {game_path.strip()}, client path: {inferred_client_path}")
                else:
                    log.info(f"[TraySettings] League path updated to: {game_path.strip()} (client path could not be inferred)")
            else:
                # Empty path means clear the manual path (will use auto-detection)
                set_config_option("General", "leaguePath", "")
                set_config_option("General", "clientPath", "")
                log.info("[TraySettings] League path cleared, will use auto-detection")
        except Exception as exc:  # noqa: BLE001
            log.error(f"[TraySettings] Failed to save game path: {exc}")

    autostart_new = result_holder["autostart"]
    autostart_initial = result_holder["autostart_initial"]
    if isinstance(autostart_new, bool) and isinstance(autostart_initial, bool):
        if autostart_new != autostart_initial:
            if autostart_new:
                if not is_admin():
                    msg = (
                        "Administrator privileges are required to enable auto-start.\n\n"
                        "Please restart Rose with Administrator rights and try again."
                    )
                    show_message_box_threaded(msg, "Auto-Start", MB_ICONERROR)
                    log.warning("[TraySettings] Auto-start enable blocked - not running as administrator")
                    return
                success, message = register_autostart()
                if success:
                    log.info("[TraySettings] Auto-start registered via settings dialog")
                    show_autostart_success_dialog()
                else:
                    log.error(f"[TraySettings] Failed to register auto-start: {message}")
                    show_message_box_threaded(
                        f"Failed to enable auto-start:\n\n{message}",
                        "Auto-Start",
                        MB_ICONERROR,
                    )
            else:
                if not is_admin():
                    msg = (
                        "Administrator privileges are required to disable auto-start.\n\n"
                        "Please restart Rose with Administrator rights and try again."
                    )
                    show_message_box_threaded(msg, "Auto-Start", MB_ICONERROR)
                    log.warning("[TraySettings] Auto-start disable blocked - not running as administrator")
                    return
                success, message = unregister_autostart()
                if success:
                    log.info("[TraySettings] Auto-start unregistered via settings dialog")
                    show_autostart_removed_dialog()
                else:
                    log.error(f"[TraySettings] Failed to unregister auto-start: {message}")
                    show_message_box_threaded(
                        f"Failed to disable auto-start:\n\n{message}",
                        "Auto-Start",
                        MB_ICONERROR,
                    )

