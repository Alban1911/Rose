#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from utils.core.logging import get_logger
from utils.threading.thread_manager import create_daemon_thread

from ..overlay.ltk_data import IndexEntry, library_index_mtime, read_library_index
from .manifest import _STORAGE_LOCK, SavedMod, find_saved_mod, update_saved_mod
from .migration import delete_copy
from .mod_facts import compute_mod_facts, stamp_of
from .storage import ModStorageService

log = get_logger()

_SYNC_LOCK = threading.Lock()
_synced_mtime: Optional[float] = None


@dataclass
class SyncReport:
    """What a sync changed, by the mods' names."""

    missing: List[str] = field(default_factory=list)
    found: List[str] = field(default_factory=list)
    refreshed: List[str] = field(default_factory=list)
    copies_deleted: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Whether the sync changed anything."""
        return bool(self.missing or self.found or self.refreshed or self.copies_deleted)


def sync_saved_mods(storage: Optional[ModStorageService] = None, *,
                    only_if_changed: bool) -> Optional[SyncReport]:
    """Bring every saved mod's manifest in line with LTK Manager's index.
    *only_if_changed* skips it while the index is the one this Rose's last
    sync read.

    The manifests are read before the index: a mod added meanwhile is in LTK
    Manager's index before its manifest names it, so it is never taken for
    one LTK Manager lost. None when the sync did not run: another one is
    running, the index did not change, or it cannot be read.
    """
    global _synced_mtime
    if not _SYNC_LOCK.acquire(blocking=False):
        log.debug("[MODS] A sync with LTK Manager's library is running already")
        return None
    try:
        mtime = library_index_mtime()
        if only_if_changed and mtime is not None and mtime == _synced_mtime:
            log.debug("[MODS] LTK Manager's library did not change since the last sync")
            return None
        storage = storage or ModStorageService()
        held = [mod for mod in storage.saved_mods() if mod.ltk_id]
        index = read_library_index()
        if index is None:
            log.debug("[MODS] LTK Manager's library index cannot be read now: the saved mods are left as they are")
            return None
        report = SyncReport()
        for mod in held:
            _sync_mod(storage, mod, index.get(mod.ltk_id), report)
        if mtime is not None:
            _synced_mtime = mtime
        if report:
            log.info(f"[MODS] Synced the saved mods with LTK Manager's library: {len(report.missing)} missing, "
                     f"{len(report.found)} found again, {len(report.refreshed)} changed by LTK Manager, "
                     f"{len(report.copies_deleted)} copies deleted")
        return report
    finally:
        _SYNC_LOCK.release()


def start_saved_mods_sync(*, only_if_changed: bool) -> threading.Thread:
    """Run sync_saved_mods on a daemon thread: neither Rose's start nor a
    champion select waits for it (the facts of a voiceover pack LTK Manager
    repaired take seconds to read again)."""
    def run() -> None:
        try:
            sync_saved_mods(only_if_changed=only_if_changed)
        except Exception as e:
            log.warning(f"[MODS] Could not sync the saved mods with LTK Manager's library: {e}", exc_info=True)

    thread = create_daemon_thread(run, "LtkLibrarySync")
    thread.start()
    return thread


def _sync_mod(storage: ModStorageService, mod: SavedMod, entry: Optional[IndexEntry], report: SyncReport) -> None:
    """Bring one saved mod LTK Manager holds in line with its index *entry*
    (None: gone), in one manifest write, then delete Rose's leftover copy of
    a listed one: under the manifests' lock, and only while its manifest
    entry is still the one the sync read."""
    fields: dict = {}
    if (entry is None) != mod.missing:
        fields["missing"] = True if entry is None else None
    if entry is not None:
        fields.update(_changed_facts(mod, entry))
    with _STORAGE_LOCK:
        if not _unchanged(storage.mods_root, mod):
            log.debug(f"[MODS] {mod.name} was deleted or added again during the sync: left to the next one")
            return
        if fields and not update_saved_mod(storage.mods_root, mod.relative_path, **fields):
            return
        if "missing" in fields:
            if entry is None:
                report.missing.append(mod.name)
                log.info(f"[MODS] {mod.name} is no longer in LTK Manager's library: shown as missing until it "
                         "is added again")
            else:
                report.found.append(mod.name)
                log.info(f"[MODS] {mod.name} is in LTK Manager's library again")
        if "ltkStamp" in fields:
            report.refreshed.append(mod.name)
            log.info(f"[MODS] LTK Manager changed {mod.name}: read what Rose needs to know about it again")
        if entry is not None and mod.stored is not None and delete_copy(storage, mod):
            report.copies_deleted.append(mod.name)


def _unchanged(mods_root: Path, mod: SavedMod) -> bool:
    """Whether the manifest entry *mod* came from is still under its name,
    with the same LTK Manager entry: one deleted and added again under that
    name is another mod, whatever the sync read of the first."""
    current = find_saved_mod(mods_root, mod.relative_path, match_content=False)
    return current is not None and (current.key, current.ltk_id) == (mod.key, mod.ltk_id)


def _changed_facts(mod: SavedMod, entry: IndexEntry) -> dict:
    """The facts of *mod* read again from LTK Manager's archive, with its
    stamp, as manifest fields: {} while the archive is the one they were read
    from (or there is no archive to read). One that cannot be read now is
    left for the next sync, its stamp not recorded."""
    stamp = stamp_of(entry.archive) if entry.archive is not None else None
    if stamp is None or (mod.facts is not None and stamp == mod.metadata.get("ltkStamp")):
        return {}
    try:
        facts = compute_mod_facts(entry.archive)[0]
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        log.warning(f"[MODS] Could not read {mod.name} in LTK Manager's library ({entry.archive}): {e}")
        return {}
    return {**facts.to_manifest(), "ltkStamp": stamp}
