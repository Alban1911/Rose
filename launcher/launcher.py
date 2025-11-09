"""
Native Win32 startup dialog used to prepare LeagueUnlocked before launching.

This replaces the former PyQt-based launcher with a lightweight Steam-style
progress window that:
    1. Checks for application updates and applies them if needed.
    2. Verifies local skin data and downloads missing content.
    3. Validates the license and prompts for activation when required.

Once all checks succeed, the dialog closes automatically and the main
application continues bootstrapping.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import threading
from pathlib import Path
from typing import Callable, Optional

try:
    from PIL import Image
except ImportError:
    Image = None

from config import APP_VERSION
from launcher.updater import auto_update
from state.app_status import AppStatus
from utils.license_flow import check_license
from utils.logging import get_logger, get_named_logger
from utils.paths import get_asset_path
from utils.skin_downloader import download_skins_on_startup
from utils.win32_base import (
    PBS_MARQUEE,
    PBM_SETRANGE,
    PBM_SETPOS,
    PBM_SETMARQUEE,
    WM_CLOSE,
    SW_SHOWNORMAL,
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

log = get_logger()
updater_log = get_named_logger("updater", prefix="log_updater")

MB_ICONERROR = 0x00000010
MB_OK = 0x00000000
MB_TOPMOST = 0x00040000


class UpdateDialog(Win32Window):
    STATUS_ID = 1001
    DETAIL_ID = 1002
    PROGRESS_ID = 1003

    def __init__(self) -> None:
        super().__init__(
            class_name="LeagueUnlockedUpdateDialog",
            window_title=f"LeagueUnlocked {APP_VERSION}",
            width=420,
            height=190,
            style=WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        )
        init_common_controls()
        updater_log.info("Update dialog initialized (Win32 window class registered).")
        self.status_hwnd: Optional[int] = None
        self.detail_hwnd: Optional[int] = None
        self.progress_hwnd: Optional[int] = None
        self._allow_close = False
        self._marquee_enabled = False
        self._current_status = ""
        self._icon_temp_path: Optional[str] = None
        self._icon_source_path: Optional[str] = self._prepare_window_icon()

    def on_create(self) -> Optional[int]:
        margin = 20
        content_width = self.width - (margin * 2)
        updater_log.debug("Creating update dialog controls.")

        title_hwnd = self.create_control(
            "STATIC",
            "Preparing LeagueUnlocked…",
            WS_CHILD | WS_VISIBLE,
            0,
            margin,
            margin - 6,
            content_width,
            22,
            self.DETAIL_ID,
        )
        self.detail_hwnd = title_hwnd

        status_hwnd = self.create_control(
            "STATIC",
            "Initializing…",
            WS_CHILD | WS_VISIBLE,
            0,
            margin,
            margin + 20,
            content_width,
            36,
            self.STATUS_ID,
        )
        self.status_hwnd = status_hwnd

        progress_hwnd = self.create_control(
            "msctls_progress32",
            "",
            WS_CHILD | WS_VISIBLE | PBS_MARQUEE,
            0,
            margin,
            margin + 64,
            content_width,
            22,
            self.PROGRESS_ID,
        )
        self.progress_hwnd = progress_hwnd
        self.send_message(progress_hwnd, PBM_SETRANGE, 0, MAKELPARAM(0, 100))
        self.set_marquee(True)
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
            if self.detail_hwnd:
                user32.SetWindowTextW(self.detail_hwnd, text)
        self.invoke(_apply)

    def set_status(self, text: str) -> None:
        updater_log.info(f"Status: {text}")
        def _apply() -> None:
            if self.status_hwnd:
                user32.SetWindowTextW(self.status_hwnd, text)
        self.invoke(_apply)

    def set_progress(self, value: int) -> None:
        clamped = max(0, min(100, int(value)))
        updater_log.debug(f"Progress set to {clamped}%")

        def _apply() -> None:
            if not self.progress_hwnd:
                return
            self._set_marquee_ui(False)
            self.send_message(self.progress_hwnd, PBM_SETPOS, clamped, 0)

        self.invoke(_apply)

    def reset_progress(self) -> None:
        updater_log.debug("Progress reset to 0%.")

        def _apply() -> None:
            if self.progress_hwnd:
                self._set_marquee_ui(False)
                self.send_message(self.progress_hwnd, PBM_SETPOS, 0, 0)

        self.invoke(_apply)

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
            if self._icon_temp_path:
                try:
                    os.remove(self._icon_temp_path)
                except OSError:
                    pass

    def _prepare_window_icon(self) -> Optional[str]:
        png_path: Optional[Path] = None
        try:
            png_candidate = get_asset_path("icon.png")
            if png_candidate.exists():
                png_path = png_candidate
        except Exception as exc:  # noqa: BLE001
            updater_log.warning(f"Failed to resolve icon.png asset: {exc}")

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
                updater_log.warning(f"Failed to convert icon.png to .ico: {exc}")

        try:
            ico_candidate = get_asset_path("icon.ico")
            if ico_candidate.exists():
                return str(ico_candidate)
        except Exception as exc:  # noqa: BLE001
            updater_log.warning(f"Failed to resolve icon.ico asset: {exc}")

        return None


def _show_error(message: str) -> None:
    try:
        user32.MessageBoxW(
            None,
            message,
            "LeagueUnlocked - Launcher",
            MB_OK | MB_ICONERROR | MB_TOPMOST,
        )
        updater_log.error(f"Error dialog shown to user: {message}")
    except Exception:
        print(f"[Launcher] ERROR: {message}")
        updater_log.exception("Failed to show error dialog", exc_info=True)


def _with_ui_updates(dialog: UpdateDialog) -> tuple[Callable[[str], None], Callable[[int], None]]:
    def update_status(message: str) -> None:
        dialog.set_status(message)
        dialog.pump_messages()
        updater_log.info(f"UI status update: {message}")

    def update_progress(value: int) -> None:
        dialog.set_progress(value)
        dialog.pump_messages()
        updater_log.debug(f"UI progress update: {value}%")

    return update_status, update_progress


def _perform_update(dialog: UpdateDialog) -> bool:
    updater_log.info("Starting update check sequence.")
    dialog.set_detail("Checking for updates…")
    dialog.set_status("Contacting update server…")
    dialog.set_marquee(True)
    dialog.pump_messages()

    status_cb, progress_cb = _with_ui_updates(dialog)
    try:
        updated = auto_update(status_cb, progress_cb)
        updater_log.info(f"Auto-update completed. Update installed: {updated}")
    except Exception as exc:  # noqa: BLE001
        log.error(f"Auto-update failed: {exc}")
        dialog.set_status(f"Update failed: {exc}")
        dialog.set_marquee(False)
        dialog.reset_progress()
        dialog.pump_messages()
        updater_log.exception("Auto-update raised an exception", exc_info=True)
        return False

    if updated:
        dialog.set_status("Update installed. Restarting…")
        dialog.set_progress(100)
        dialog.pump_messages()
        time.sleep(1.0)
        # auto_update already launched the new process via batch file; exit current one
        import os

        updater_log.info("Update applied successfully; exiting for restart.")
        os._exit(0)

    dialog.set_marquee(False)
    dialog.reset_progress()
    dialog.pump_messages()
    updater_log.info("No update applied; continuing startup.")
    return False


def _perform_skin_sync(dialog: UpdateDialog) -> None:
    updater_log.info("Starting skin verification sequence.")
    dialog.set_detail("Verifying skin library…")
    dialog.set_status("Checking installed skins…")
    dialog.set_marquee(True)
    dialog.pump_messages()

    status_checker = AppStatus()
    have_skins = status_checker.check_skins_downloaded()
    have_previews = status_checker.check_previews_downloaded()
    updater_log.info(f"Skin status - skins: {have_skins}, previews: {have_previews}")

    if have_skins and have_previews:
        status_checker.mark_download_process_complete()
        dialog.set_status("Skins already up to date.")
        dialog.set_marquee(False)
        dialog.set_progress(100)
        dialog.pump_messages()
        time.sleep(0.4)
        updater_log.info("Skins already up to date; skipping download.")
        return

    dialog.set_status("Downloading latest skins…")
    dialog.set_marquee(False)
    dialog.reset_progress()
    dialog.pump_messages()
    updater_log.info("Downloading skins and previews.")

    def skin_progress(percent: int, message: Optional[str] = None) -> None:
        if message:
            dialog.set_status(message)
            updater_log.info(f"Skin download status: {message}")
        dialog.set_progress(percent)
        dialog.pump_messages()
        updater_log.debug(f"Skin download progress: {percent}%")

    success = False
    try:
        success = download_skins_on_startup(progress_callback=skin_progress)
        updater_log.info(f"Skin download completed with success={success}")
    except Exception as exc:  # noqa: BLE001
        log.error(f"Skin download failed: {exc}")
        dialog.set_status(f"Skin download failed: {exc}")
        dialog.set_progress(0)
        dialog.pump_messages()
        updater_log.exception("Skin download raised an exception", exc_info=True)

    status_checker.update_status(force=True)

    if success:
        status_checker.mark_download_process_complete()
        dialog.set_status("Skins ready.")
        dialog.set_progress(100)
        dialog.pump_messages()
        time.sleep(0.4)
        updater_log.info("Skin library synchronized successfully.")
    else:
        dialog.set_status("Continuing without updating skins.")
        dialog.set_progress(0)
        dialog.pump_messages()
        updater_log.warning("Skin download failed; continuing without new skins.")


def _perform_license_check(dialog: UpdateDialog) -> None:
    updater_log.info("Starting license validation sequence.")
    dialog.set_detail("Validating license…")
    dialog.set_status("Checking license status…")
    dialog.set_marquee(True)
    dialog.pump_messages()

    def status_callback(message: str) -> None:
        dialog.set_status(message)
        dialog.pump_messages()
        updater_log.info(f"License status: {message}")

    check_license(status_callback=status_callback)
    dialog.set_marquee(False)
    dialog.set_progress(100)
    dialog.set_status("License valid.")
    dialog.pump_messages()
    time.sleep(0.3)
    updater_log.info("License validation completed successfully.")


def run_launcher() -> None:
    """Display the Win32 update dialog and perform startup checks."""
    if sys.platform != "win32":
        log.debug("Win32 launcher skipped on non-Windows platform.")
        return

    updater_log.info("Launcher sequence starting.")
    dialog = UpdateDialog()
    try:
        dialog.show_window(SW_SHOWNORMAL)
        dialog.pump_messages()
        updater_log.info("Update dialog displayed.")

        result: dict[str, Exception] = {}
        done_event = threading.Event()

        def worker():
            try:
                _perform_update(dialog)
                _perform_skin_sync(dialog)
                _perform_license_check(dialog)

                dialog.set_detail("All checks complete.")
                dialog.set_status("Launching LeagueUnlocked…")
                dialog.set_progress(100)
                dialog.pump_messages()
                time.sleep(0.4)
                updater_log.info("Launcher sequence completed successfully.")
            except SystemExit:
                updater_log.info("Launcher sequence exiting due to SystemExit (expected for update restart).")
                raise
            except Exception as exc:  # noqa: BLE001
                result["error"] = exc
                log.error(f"Launcher error: {exc}", exc_info=True)
                _show_error(f"Failed to prepare LeagueUnlocked:\n\n{exc}")
                updater_log.exception("Launcher sequence crashed", exc_info=True)
            finally:
                dialog.allow_close()
                if dialog.hwnd:
                    user32.PostMessageW(dialog.hwnd, WM_CLOSE, 0, 0)
                done_event.set()

        worker_thread = threading.Thread(target=worker, name="LauncherWorker", daemon=True)
        worker_thread.start()

        while not done_event.is_set():
            if not dialog.pump_messages(block=True):
                break

        worker_thread.join()

        if "error" in result:
            raise result["error"]
    finally:
        dialog.destroy_window()
        updater_log.info("Update dialog resources released.")

