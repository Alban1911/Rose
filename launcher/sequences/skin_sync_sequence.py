"""
Skin Sync Sequence
Handles skin download and verification sequence
"""

from __future__ import annotations

import time
from typing import Optional

from state import AppStatus
from utils.core.logging import get_logger, get_named_logger
from utils.download.skin_downloader import download_skins_on_startup

log = get_logger()
updater_log = get_named_logger("updater", prefix="log_updater")

MB_OK = 0x00000000
MB_ICONWARNING = 0x00000030
MB_TOPMOST = 0x00040000


class SkinSyncSequence:
    """Handles skin download and verification sequence"""

    def perform_skin_sync(self, dialog, test_fail: bool = False) -> None:
        """Perform skin download and verification

        Args:
            dialog: UpdateDialog instance for UI updates
            test_fail: If True, force download to fail (for testing error handling)
        """
        updater_log.info("Starting skin verification sequence.")
        dialog.clear_transfer_text()
        dialog.set_detail("Verifying skin library…")
        dialog.set_status("Checking installed skins…")
        dialog.set_marquee(True)
        dialog.pump_messages()

        status_checker = AppStatus()
        have_skins = status_checker.check_skins_downloaded()
        have_previews = status_checker.check_previews_downloaded()
        updater_log.info(f"Skin status - skins: {have_skins}, previews: {have_previews}")

        needs_full_download = not (have_skins and have_previews)

        if needs_full_download:
            dialog.set_status("Downloading latest skins…")
        else:
            dialog.set_status("Checking for skin updates…")

        dialog.set_marquee(False)
        dialog.reset_progress()
        dialog.clear_transfer_text()
        dialog.pump_messages()
        updater_log.info("Downloading skins and previews (incremental=%s).", not needs_full_download)

        def skin_progress(percent: int, message: Optional[str] = None) -> None:
            if message:
                dialog.set_status(message)
                updater_log.info(f"Skin download status: {message}")
            dialog.set_progress(percent)
            dialog.pump_messages()
            updater_log.debug(f"Skin download progress: {percent}%")

        success = False

        # Test mode: force download failure
        if test_fail:
            updater_log.warning("--test-download-fail flag set, forcing download failure")
            dialog.set_status("Testing download failure...")
            dialog.pump_messages()
            time.sleep(1)  # Brief pause so user sees the status
            success = False
        else:
            try:
                success = download_skins_on_startup(
                    force_update=needs_full_download,
                    progress_callback=skin_progress,
                )
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
            dialog.clear_transfer_text()
            dialog.pump_messages()
            time.sleep(0.4)
            updater_log.info("Skin library synchronized successfully.")
        else:
            dialog.set_status("Skin download failed. Continuing…")
            dialog.set_progress(0)
            dialog.clear_transfer_text()
            dialog.pump_messages()
            updater_log.warning("Skin download failed; continuing startup.")

