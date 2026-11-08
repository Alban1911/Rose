#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pack the mods an earlier Rose stored as folders into archives, once.

Rose used to unpack a mod when it was added, then pack the folder into a
.fantome again for LTK Manager at every injection: a minute for a voiceover
pack, every game. It now stores the archive LTK Manager installs as it is
(injection.mods.storage), and converts the folders an earlier Rose stored
when it starts, before anything else runs (main.run_league_unlock): an
injection never reads a folder in the middle of its conversion.

A folder that cannot be converted (a full disk...) stays a folder: the
injection still packs it, and the next start tries again.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, Optional

from utils.core.junction import safe_remove_entry
from utils.core.logging import get_logger
from utils.core.paths import get_injection_dir

from .storage import ModStorageService

log = get_logger()

# What utils.core.junction.link_or_extract extracted .zip/.fantome mods into:
# it links them now, so the extractions only take space
EXTRACT_CACHE = ".extract_cache"
EXTRACT_CACHE_CLEARED = ".archives-linked"


def convert_folder_mods(
    storage: Optional[ModStorageService] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> int:
    """Convert every mod stored as a folder; return how many were converted.

    *progress(index, total, name)* is told about each mod before its turn.
    The saved selections (historic.json, mod_historic.json) are pointed at
    the archives.
    """
    storage = storage or ModStorageService()
    folders = storage.folder_mods()
    renamed: Dict[str, str] = {}
    if folders:
        log.info(f"[MODS] Packing {len(folders)} mod(s) stored as folders into the archives LTK Manager installs")
    for index, folder in enumerate(folders, 1):
        if progress is not None:
            progress(index, len(folders), folder.name)
        started = time.monotonic()
        try:
            archive = storage.convert_folder_mod(folder)
        except Exception as e:  # noqa: BLE001 - the folder stays usable as it is
            log.warning(f"[MODS] Could not pack {folder.name} into an archive ({e}): it stays a folder for now")
            continue
        if archive is None:
            continue
        renamed[folder.relative_to(storage.mods_root).as_posix()] = archive.relative_to(storage.mods_root).as_posix()
        log.info(
            f"[MODS] Packed {folder.name} into {archive.name} ({archive.stat().st_size / 1024 ** 2:.0f} MB) "
            f"in {time.monotonic() - started:.1f}s"
        )
    if renamed:
        _rename_saved_paths(renamed)
    _clear_extract_cache()
    return len(renamed)


def _rename_saved_paths(renamed: Dict[str, str]) -> None:
    """Point the saved selections at the archives that replaced the folders."""
    from utils.core import historic, mod_historic

    for module in (historic, mod_historic):
        try:
            changed = module.rename_mod_paths(renamed)
        except Exception as e:  # noqa: BLE001 - a saved selection is a convenience
            log.warning(f"[MODS] Could not update the saved mods in {module.__name__}: {e}")
            continue
        if changed:
            log.info(f"[MODS] Pointed {changed} saved selection(s) at the packed mods")


def _clear_extract_cache() -> None:
    """Remove the extractions link_or_extract made of .zip/.fantome mods, once."""
    cache = get_injection_dir() / EXTRACT_CACHE
    marker = cache / EXTRACT_CACHE_CLEARED
    if not cache.is_dir() or marker.exists():
        return
    try:
        for entry in cache.iterdir():
            safe_remove_entry(entry)
        marker.write_text("Mod archives are linked, not extracted\n", encoding="utf-8")
        log.info("[MODS] Removed the extracted copies of mod archives (they are linked now)")
    except OSError as e:
        log.debug(f"[MODS] Could not clear {cache}: {e}")
