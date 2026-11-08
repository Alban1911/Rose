#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mod Manager
Prepares the injection's mods directory: one entry per mod, a folder (or a
junction to one) or an archive linked under the mod's name
"""

from pathlib import Path

from utils.core.logging import get_logger, log_success
from utils.core.junction import link_file, safe_remove_entry

log = get_logger()


def empty_directory(path: Path) -> None:
    """Remove what a directory holds but keep the directory itself.

    The LTK patcher is started before the overlay is built and checks that its
    overlay directory exists when it is configured: deleting and recreating the
    directory made it fail, now and then, with "prefix not configured".
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    for entry in path.iterdir():
        safe_remove_entry(entry)


class ModManager:
    """Prepares the mods an injection installs"""

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
        try:
            empty_directory(overlay_dir)
            log.debug("[INJECT] Cleaned overlay directory")
        except Exception as e:
            log.warning(f"[INJECT] Failed to clean overlay directory: {e}")

    def link_archive(self, zp: Path) -> Path:
        """Put a skin archive (.fantome/.zip) into the mod directory as the mod
        named after it: a hard link LTK Manager installs as it is, so nothing
        is extracted (injection.mods.mod_files)."""
        target = self.mods_dir / zp.stem
        safe_remove_entry(target)
        link_file(zp, target)
        log_success(log, f"Linked skin archive: {zp.name}", "ðŸ“¦")
        return target
