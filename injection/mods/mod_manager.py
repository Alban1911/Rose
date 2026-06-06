#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mod Manager
Handles mod extraction, installation, and management
"""

import shutil
from pathlib import Path
from typing import List

from utils.core.logging import get_logger, log_success
from utils.core.paths import get_user_data_dir
from utils.core.safe_extract import safe_extractall
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
        """Extract a ZIP-compatible skin archive to the mod directory."""
        target = self.mods_dir / zp.stem
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)

        # Security: Use safe extraction to prevent path traversal attacks.
        safe_extractall(zp, target)

        # Hide extracted files so they can't be easily browsed
        self._hide_directory(target)

        file_type = {".zip": "ZIP", ".fantome": ".fantome"}.get(zp.suffix.lower(), zp.suffix)
        log_success(log, f"Extracted {file_type}: {zp.name}", "ðŸ“¦")
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
