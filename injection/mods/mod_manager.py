#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mod Manager
Handles mod extraction, installation, and management
"""

import shutil
from pathlib import Path
from typing import List

from utils.core.issue_reporter import report_issue, clear_issue
from utils.core.logging import get_logger, log_success
from utils.core.paths import get_user_data_dir
from utils.core.safe_extract import safe_extractall, safe_extractall_from_bytes
from utils.core.junction import is_junction, safe_remove_entry

log = get_logger()


class ModManager:
    """Manages mod extraction and installation"""
    
    def __init__(self, mods_dir: Path):
        self.mods_dir = mods_dir
        self.mods_dir.mkdir(parents=True, exist_ok=True)
    
    def clean_mods_dir(self):
        """Clean the mods directory"""
        if not self.mods_dir.exists():
            self.mods_dir.mkdir(parents=True, exist_ok=True)
            return
        for p in self.mods_dir.iterdir():
            safe_remove_entry(p)
    
    def clean_overlay_dir(self):
        """Clean the overlay directory to prevent file lock issues"""
        overlay_dir = self.mods_dir.parent / "overlay"
        if overlay_dir.exists():
            try:
                shutil.rmtree(overlay_dir, ignore_errors=True)
                log.debug("[INJECT] Cleaned overlay directory")
            except Exception as e:
                log.warning(f"[INJECT] Failed to clean overlay directory: {e}")
        overlay_dir.mkdir(parents=True, exist_ok=True)
    
    def extract_zip_to_mod(self, zp: Path) -> Path:
        """Extract ZIP, .fantome, or .rse file to mod directory

        Note: Both .zip and .fantome files are ZIP-compatible archives.
        .rse files are encrypted skins — decrypted in memory, never written to disk.
        Uses safe_extractall to prevent path traversal (zip slip) attacks.
        """
        target = self.mods_dir / zp.stem
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)

        if zp.suffix.lower() == ".rse":
            from utils.crypto.key_provider import get_skin_key
            from utils.crypto.skin_crypto import decrypt_bytes

            key = get_skin_key()
            if key is None:
                report_issue(
                    "SKIN_DECRYPT_KEY_FAILED",
                    "error",
                    "Cannot decrypt skin: failed to fetch decryption key from server.",
                    hint="Check your internet connection and firewall settings. In some countries, network restrictions may block access — try using a VPN.",
                )
                raise RuntimeError("Cannot decrypt skin: failed to fetch decryption key from server")

            clear_issue("SKIN_DECRYPT_KEY_FAILED")

            encrypted_data = zp.read_bytes()
            decrypted_data = decrypt_bytes(encrypted_data, key)
            if decrypted_data is None:
                raise RuntimeError(f"Failed to decrypt skin file: {zp.name}")

            safe_extractall_from_bytes(decrypted_data, target)
        else:
            # Security: Use safe extraction to prevent path traversal attacks
            safe_extractall(zp, target)

        # Hide extracted files so they can't be easily browsed
        self._hide_directory(target)

        file_type = {".zip": "ZIP", ".fantome": ".fantome", ".rse": "RSE"}.get(zp.suffix.lower(), zp.suffix)
        log_success(log, f"Extracted {file_type}: {zp.name}", "📦")
        return target

    @staticmethod
    def _hide_directory(path: Path):
        """Set hidden + system attributes on a directory and its contents (Windows only)"""
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes
            FILE_ATTRIBUTE_HIDDEN = 0x02
            FILE_ATTRIBUTE_SYSTEM = 0x04
            attrs = FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)
            for item in path.rglob('*'):
                ctypes.windll.kernel32.SetFileAttributesW(str(item), attrs)
        except Exception:
            pass
    
