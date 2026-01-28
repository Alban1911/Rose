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
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except Exception:
                    pass
    
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
        """Extract ZIP or .fantome file to mod directory

        Note: Both .zip and .fantome files are ZIP-compatible archives.
        Uses safe_extractall to prevent path traversal (zip slip) attacks.
        """
        target = self.mods_dir / zp.stem
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        # Security: Use safe extraction to prevent path traversal attacks
        safe_extractall(zp, target)
        file_type = "ZIP" if zp.suffix == ".zip" else ".fantome"
        log_success(log, f"Extracted {file_type}: {zp.name}", "📦")
        return target
    
