"""
Update Dialog
Win32 dialog window for showing update progress
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
except ImportError:
    Image = None

from config import APP_VERSION
from utils.core.logging import get_named_logger
from utils.core.paths import get_asset_path
from utils.system.win32_base import (
    PBS_MARQUEE,
    PBM_SETRANGE,
    PBM_SETMARQUEE,
    WS_CAPTION,
    WS_CHILD,
    WS_MINIMIZEBOX,
    WS_SYSMENU,
    WS_VISIBLE,
    Win32Window,
    init_common_controls,
    MAKELPARAM,
    user32,
)

updater_log = get_named_logger("updater", prefix="log_updater")


class UpdateDialog(Win32Window):
    """Win32 dialog window for showing update progress"""
    
    STATUS_ID = 1001
    DETAIL_ID = 1002
    PROGRESS_ID = 1003

    def __init__(self) -> None:
        super().__init__(
            class_name="RoseUpdateDialog",
            window_title=f"Rose {APP_VERSION}",
            width=420,
            height=120,
            style=WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        )
        init_common_controls()
        updater_log.info("Update dialog initialized (Win32 window class registered).")
        self.detail_hwnd: Optional[int] = None
        self.progress_hwnd: Optional[int] = None
        self._allow_close = False
        self._marquee_enabled = False
        self._current_status = ""
        self._status_text = ""
        self._transfer_text = ""
        self._icon_temp_path: Optional[str] = None
        self._icon_source_path: Optional[str] = self._prepare_window_icon()
        self._transfer_bytes: Optional[int] = None
        self._transfer_total: Optional[int] = None
        self._transfer_managed = False

    def on_create(self) -> Optional[int]:
        client_width, client_height = self.get_client_size()
        margin = 20
        content_width = min(client_width - 2 * margin, 360)
        content_width = max(content_width, 240)
        x_pos = (client_width - content_width) // 2
        top = 4
        updater_log.debug("Creating update dialog controls.")

        detail_hwnd = self.create_control(
            "STATIC",
            "Preparing Rose…",
            WS_CHILD | WS_VISIBLE,
            0,
            x_pos,
            top,
            content_width,
            20,
            self.DETAIL_ID,
        )
        self.detail_hwnd = detail_hwnd

        progress_top = top + 24
        progress_hwnd = self.create_control(
            "msctls_progress32",
            "",
            WS_CHILD | WS_VISIBLE | PBS_MARQUEE,
            0,
            x_pos,
            progress_top,
            content_width,
            16,
            self.PROGRESS_ID,
        )
        self.progress_hwnd = progress_hwnd
        self.send_message(progress_hwnd, PBM_SETRANGE, 0, MAKELPARAM(0, 100))
        self.set_marquee(True)

        status_hwnd = self.create_control(
            "STATIC",
            "",
            WS_CHILD | WS_VISIBLE,
            0,
            x_pos,
            progress_top + 20,
            content_width,
            18,
            self.STATUS_ID,
        )
        self.status_hwnd = status_hwnd

        updater_log.info("Update dialog controls created successfully.")
        if self._icon_source_path:
            updater_log.debug(f"Applying window icon from {self._icon_source_path}")
            self.set_window_icon(self._icon_source_path)
        return 0

    def on_close(self) -> Optional[int]:
        if not self._allow_close:
            updater_log.debug("Close requested before completion; ignoring.")
            return 0
        updater_log.info("Update dialog closing.")
        return super().on_close()

    def allow_close(self) -> None:
        def _apply() -> None:
            self._allow_close = True
        self.invoke(_apply)
        updater_log.debug("Update dialog marked as closable.")

    def set_detail(self, text: str) -> None:
        updater_log.info(f"Detail: {text}")
        def _apply() -> None:
            self._current_status = text
            self._status_text = ""
            if self.detail_hwnd:
                user32.SetWindowTextW(self.detail_hwnd, text)
                user32.InvalidateRect(self.detail_hwnd, None, True)
            self._render_status_text()
        self.invoke(_apply)

    def set_status(self, text: str) -> None:
        updater_log.info(f"Status: {text}")
        def _apply() -> None:
            clean_text = re.sub(r"\s*/\s*\?\s*$", "", text).strip()
            title_text = re.sub(
                r"\s*(\d+(?:\.\d+)?\s*(?:B|KB|MB|GB|TB))(?:\s*/\s*\d+(?:\.\d+)?\s*(?:B|KB|MB|GB|TB))?\s*$",
                "",
                clean_text,
                flags=re.IGNORECASE,
            ).strip()
            self._status_text = title_text or clean_text
            self._render_status_text()
            self._update_transfer_from_message(clean_text)
        self.invoke(_apply)

    def set_progress(self, value: int) -> None:
        updater_log.debug(f"Progress update ignored (visual only): {value}")

        def _apply() -> None:
            if self.progress_hwnd:
                self.set_marquee(True)
        self.invoke(_apply)

    def reset_progress(self) -> None:
        updater_log.debug("Progress reset ignored (visual only).")

        def _apply() -> None:
            if self.progress_hwnd:
                self.set_marquee(True)
        self.invoke(_apply)

    def set_transfer_text(self, text: str) -> None:
        def _apply_change() -> None:
            self._transfer_text = text
            self._render_status_text()
        self.invoke(_apply_change)

    def clear_transfer_text(self) -> None:
        self._transfer_bytes = None
        self._transfer_total = None
        self._transfer_managed = False
        self.set_transfer_text("")

    def set_marquee(self, enabled: bool) -> None:
        updater_log.debug("Marquee animation enabled." if enabled else "Marquee animation disabled.")

        def _apply() -> None:
            self._set_marquee_ui(enabled)

        self.invoke(_apply)

    def _set_marquee_ui(self, enabled: bool) -> None:
        if not self.progress_hwnd:
            return
        if enabled and not self._marquee_enabled:
            self.send_message(self.progress_hwnd, PBM_SETMARQUEE, 1, 40)
            self._marquee_enabled = True
        elif not enabled and self._marquee_enabled:
            self.send_message(self.progress_hwnd, PBM_SETMARQUEE, 0, 0)
            self._marquee_enabled = False

    def destroy_window(self) -> None:
        try:
            super().destroy_window()
        finally:
            self._transfer_bytes = None
            self._transfer_total = None
            self._transfer_managed = False
            self._status_text = ""
            self._transfer_text = ""
            if self._icon_temp_path:
                try:
                    os.remove(self._icon_temp_path)
                except OSError:
                    pass

    def _prepare_window_icon(self) -> Optional[str]:
        png_path: Optional[Path] = None
        try:
            png_candidate = get_asset_path("tray_ready.png")
            if png_candidate.exists():
                png_path = png_candidate
        except Exception as exc:  # noqa: BLE001
            updater_log.warning(f"Failed to resolve tray_ready.png icon: {exc}")

        if png_path is not None and Image is not None:
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
                updater_log.warning(f"Failed to convert tray_ready.png to .ico: {exc}")

        try:
            ico_candidate = get_asset_path("icon.ico")
            if ico_candidate.exists():
                return str(ico_candidate)
        except Exception as exc:  # noqa: BLE001
            updater_log.warning(f"Failed to resolve icon.ico asset: {exc}")

        return None

    @staticmethod
    def _format_bytes(value: int) -> str:
        if value <= 0:
            return "0 MB"
        if value < 1024 * 1024:
            return f"{value / 1024:.1f} KB"
        return f"{value / (1024 * 1024):.1f} MB"

    def update_transfer_progress(self, downloaded: int, total: Optional[int]) -> None:
        self._transfer_bytes = max(0, downloaded)
        self._transfer_total = total if (total is not None and total > 0) else None
        self._transfer_managed = True
        if self._transfer_total:
            text = f"{self._format_bytes(self._transfer_bytes)} / {self._format_bytes(self._transfer_total)}"
        else:
            text = self._format_bytes(self._transfer_bytes)
        self.set_transfer_text(text)

    def _update_transfer_from_message(self, message: str) -> None:
        matches = re.findall(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)", message, flags=re.IGNORECASE)
        if not matches:
            if not self._transfer_managed:
                self.clear_transfer_text()
            return
        units = {
            "B": 1,
            "KB": 1024,
            "MB": 1024 * 1024,
            "GB": 1024 * 1024 * 1024,
            "TB": 1024 * 1024 * 1024 * 1024,
        }
        try:
            first_value, first_unit = matches[0]
            downloaded = int(float(first_value) * units[first_unit.upper()])
            if len(matches) > 1:
                second_value, second_unit = matches[1]
                total = int(float(second_value) * units[second_unit.upper()])
                if total <= 0:
                    total = None
            else:
                total = None
            self._transfer_bytes = max(0, downloaded)
            self._transfer_total = total if (total is not None and total > 0) else None
            self._transfer_managed = False
            if self._transfer_total:
                text = f"{self._format_bytes(self._transfer_bytes)} / {self._format_bytes(self._transfer_total)}"
            else:
                text = self._format_bytes(self._transfer_bytes)
            self.set_transfer_text(text)
        except Exception:
            pass

    def _render_status_text(self) -> None:
        if not self.detail_hwnd or not self.status_hwnd:
            return
        header = self._status_text or self._current_status or "Preparing Rose…"
        user32.SetWindowTextW(self.detail_hwnd, header)
        user32.InvalidateRect(self.detail_hwnd, None, True)
        user32.SetWindowTextW(self.status_hwnd, self._transfer_text or "")
        user32.InvalidateRect(self.status_hwnd, None, True)

