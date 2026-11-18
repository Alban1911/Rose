#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mod Manager
Prepares the injection's mods directory: one entry per mod, a folder (or a
junction to one) or an archive linked under the mod's name
"""

import shutil
from pathlib import Path
from typing import Optional

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

    def __init__(self, mods_dir: Path, game_dir: Optional[Path] = None):
        self.mods_dir = mods_dir
        # With the game's folder, a linked skin archive is first made to match
        # the game's base skin (injection.baseskin), so LTK Manager takes it for
        # the champion's own skin and not for a skinhack
        self.game_dir = game_dir
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
        is extracted (injection.mods.mod_files).

        With a game folder, the archive is copied and its base skin fixed
        first (injection.baseskin): the copy is kept only when the fix writes
        it, so the downloaded library's archive is never changed. An archive
        that already matches the base skin stays a hard link.
        """
        target = self.mods_dir / zp.stem
        safe_remove_entry(target)
        if self.game_dir is not None and self._fix_base_skin(zp, target):
            log_success(log, f"Linked skin archive: {zp.name}", "📦")
            return target
        safe_remove_entry(target)
        link_file(zp, target)
        log_success(log, f"Linked skin archive: {zp.name}", "📦")
        return target

    def _fix_base_skin(self, source: Path, target: Path) -> bool:
        """Copy *source* to *target* and fix its base skin there; True when the
        fix wrote it (so the fixed copy is kept). False for an archive that
        already matches, and for one that could not be checked: the original is
        linked as before."""
        from injection.baseskin import fix_mod
        from injection.baseskin.library import describe

        try:
            shutil.copyfile(source, target)
            result = fix_mod(target, self.game_dir)
        except Exception as e:  # noqa: BLE001 - a check that fails must not stop the injection
            log.warning(f"[BASESKIN] Could not check {source.name} against the game's base skin: {e}")
            return False
        if not result.changed:
            return False
        log.info(f"[BASESKIN] Fixed the base skin of the injected {source.name}: {describe(result)}")
        return True
