"""
Native Win32 startup dialog used to prepare Rose before launching.

This replaces the former PyQt-based launcher with a lightweight Steam-style
progress window that:
    1. Checks for application updates and applies them if needed.
    2. Verifies local skin data and downloads missing content.

Once all checks succeed, the dialog closes automatically and the main
application continues bootstrapping.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable

from utils.logging import get_logger, get_named_logger
from utils.win32_base import (
    WM_CLOSE,
    SW_SHOWNORMAL,
    user32,
)

from .update_dialog import UpdateDialog
from .update_sequence import UpdateSequence
from .hash_check_sequence import HashCheckSequence
from .skin_sync_sequence import SkinSyncSequence

log = get_logger()
updater_log = get_named_logger("updater", prefix="log_updater")

MB_ICONERROR = 0x00000010
MB_OK = 0x00000000
MB_TOPMOST = 0x00040000


def _show_error(message: str) -> None:
    """Show error dialog to user"""
    try:
        user32.MessageBoxW(
            None,
            message,
            "Rose - Launcher",
            MB_OK | MB_ICONERROR | MB_TOPMOST,
        )
        updater_log.error(f"Error dialog shown to user: {message}")
    except Exception:
        print(f"[Launcher] ERROR: {message}")
        updater_log.exception("Failed to show error dialog", exc_info=True)


def _with_ui_updates(dialog: UpdateDialog) -> tuple[Callable[[str], None], Callable[[int], None]]:
    """Create UI update callbacks for dialog"""
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
    """Perform update check and installation"""
    updater_log.info("Starting update check sequence.")
    dialog.clear_transfer_text()
    dialog.set_detail("Checking for updates…")
    dialog.set_status("Contacting update server…")
    dialog.set_marquee(True)
    dialog.pump_messages()

    status_cb, progress_cb = _with_ui_updates(dialog)
    try:
        sequence = UpdateSequence()
        updated = sequence.perform_update(
            status_cb,
            lambda _: None,
            bytes_callback=lambda downloaded, total: dialog.update_transfer_progress(downloaded, total),
        )
        updater_log.info(f"Auto-update completed. Update installed: {updated}")
    except Exception as exc:  # noqa: BLE001
        log.error(f"Auto-update failed: {exc}")
        dialog.set_status(f"Update failed: {exc}")
        dialog.set_marquee(False)
        dialog.reset_progress()
        dialog.clear_transfer_text()
        dialog.pump_messages()
        updater_log.exception("Auto-update raised an exception", exc_info=True)
        return False

    if updated:
        dialog.set_status("Update installed. Restarting…")
        dialog.set_progress(100)
        dialog.pump_messages()
        time.sleep(1.0)
        # auto_update already launched the new process via batch file; exit current one
        updater_log.info("Update applied successfully; exiting for restart.")
        os._exit(0)

    dialog.set_marquee(False)
    dialog.reset_progress()
    dialog.clear_transfer_text()
    dialog.pump_messages()
    updater_log.info("No update applied; continuing startup.")
    return False


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
                
                hash_sequence = HashCheckSequence()
                hash_sequence.perform_hash_check(dialog)
                
                skin_sequence = SkinSyncSequence()
                skin_sequence.perform_skin_sync(dialog)

                dialog.set_detail("All checks complete.")
                dialog.set_status("Launching Rose…")
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
                _show_error(f"Failed to prepare Rose:\n\n{exc}")
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
