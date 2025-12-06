"""
Hash Check Sequence
Handles game hash file verification sequence
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from utils.download.hash_updater import update_hash_files
from utils.core.logging import get_logger, get_named_logger

log = get_logger()
updater_log = get_named_logger("updater", prefix="log_updater")


class HashCheckSequence:
    """Handles game hash file verification sequence"""
    
    def perform_hash_check(self, dialog, dev_mode: bool = False) -> None:
        """Perform hash file check and update
        
        Args:
            dialog: UpdateDialog instance for UI updates
            dev_mode: If True, skip hash check (for development)
        """
        # Skip hash check in dev mode
        if dev_mode:
            updater_log.info("Hash check skipped (dev mode)")
            dialog.set_status("Hash check skipped (dev mode)")
            dialog.pump_messages()
            return
        
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
            # This will block until hashes are downloaded and merged
            updated = update_hash_files(status_callback=status_callback, dev_mode=dev_mode)
            
            # Verify hashes.game.txt exists before continuing
            # Get the tools directory path (same logic as hash_updater)
            if getattr(sys, 'frozen', False):
                # Running as compiled executable
                if hasattr(sys, '_MEIPASS'):
                    # One-file mode
                    base_path = Path(sys._MEIPASS)
                    tools_dir = base_path / "injection" / "tools"
                else:
                    # One-dir mode
                    base_dir = Path(sys.executable).parent
                    possible_tools_dirs = [
                        base_dir / "injection" / "tools",
                        base_dir / "_internal" / "injection" / "tools",
                    ]
                    tools_dir = None
                    for dir_path in possible_tools_dirs:
                        if dir_path.exists():
                            tools_dir = dir_path
                            break
                    if not tools_dir:
                        tools_dir = possible_tools_dirs[0]
            else:
                # Running as Python script
                tools_dir = Path(__file__).parent.parent.parent / "injection" / "tools"
            
            hashes_file = tools_dir / "hashes.game.txt"
            
            if not hashes_file.exists():
                error_msg = "hashes.game.txt not found after download attempt"
                log.error(error_msg)
                dialog.set_status(error_msg)
                dialog.pump_messages()
                updater_log.error(error_msg)
                # Don't raise - allow app to continue, but log the error
            else:
                if updated:
                    updater_log.info("Game hashes updated successfully")
                    dialog.set_status("Game hashes updated successfully")
                else:
                    updater_log.info("Game hashes are up to date")
                    dialog.set_status("Game hashes are valid")
                dialog.pump_messages()
        except Exception as exc:  # noqa: BLE001
            log.error(f"Hash check failed: {exc}")
            dialog.set_status(f"Hash check failed: {exc}")
            dialog.pump_messages()
            updater_log.exception("Hash check raised an exception", exc_info=True)
            # Don't raise - allow app to continue even if hash check fails
            # The injection system will handle missing hashes gracefully
        
        dialog.set_marquee(False)
        dialog.reset_progress()
        dialog.clear_transfer_text()
        dialog.pump_messages()

