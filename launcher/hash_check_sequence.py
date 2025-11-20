"""
Hash Check Sequence
Handles game hash file verification sequence
"""

from __future__ import annotations

from typing import Callable

from utils.hash_updater import update_hash_files
from utils.logging import get_logger, get_named_logger

log = get_logger()
updater_log = get_named_logger("updater", prefix="log_updater")


class HashCheckSequence:
    """Handles game hash file verification sequence"""
    
    def perform_hash_check(self, dialog) -> None:
        """Perform hash file check and update
        
        Args:
            dialog: UpdateDialog instance for UI updates
        """
        updater_log.info("Starting game hash verification sequence.")
        dialog.clear_transfer_text()
        dialog.set_detail("Verifying game hashes…")
        dialog.set_status("Checking game hashes…")
        dialog.set_marquee(True)
        dialog.pump_messages()
        
        def status_callback(message: str) -> None:
            dialog.set_status(message)
            dialog.pump_messages()
            updater_log.info(f"Hash check status: {message}")
        
        try:
            updated = update_hash_files(status_callback=status_callback)
            if updated:
                updater_log.info("Game hashes updated successfully")
            else:
                updater_log.info("Game hashes are up to date")
        except Exception as exc:  # noqa: BLE001
            log.error(f"Hash check failed: {exc}")
            dialog.set_status(f"Hash check failed: {exc}")
            dialog.pump_messages()
            updater_log.exception("Hash check raised an exception", exc_info=True)
        
        dialog.set_marquee(False)
        dialog.reset_progress()
        dialog.clear_transfer_text()
        dialog.pump_messages()

