#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from utils.core.logging import get_logger
from utils.core.modpkg import MODPKG_SUFFIX

log = get_logger()

LTK_DATA_FOLDER = "dev.leaguetoolkit.manager"
LIBRARY_INDEX = "library.json"
LTK_SETTINGS = "settings.json"
WAD_REPORTS = "wad-reports.json"
# The index layout this reads (LTK Manager 1.33): {"version": 2, "mods": [{id,
# format, storage, slug...}], "profiles": [{id, enabledMods...}], "activeProfileId"}.
# Another layout is not guessed at: a misread index would mark mods missing
LIBRARY_INDEX_VERSION = 2


def ltk_data_candidates() -> List[Path]:
    """Where LTK Manager may keep its data: the roaming app data of the
    desktop user it runs as first (an elevated Rose may run as another
    account), then this account's."""
    candidates = []
    try:
        from utils.core.paths import get_user_data_dir

        candidates.append(get_user_data_dir().parent.parent / "Roaming" / LTK_DATA_FOLDER)
    except Exception:
        pass
    roaming = os.environ.get("APPDATA")
    if roaming:
        candidates.append(Path(roaming) / LTK_DATA_FOLDER)
    return candidates


def ltk_data_dir() -> Optional[Path]:
    """LTK Manager's data folder (%APPDATA%\\dev.leaguetoolkit.manager of the
    desktop user), None when LTK Manager never ran there."""
    for candidate in ltk_data_candidates():
        if candidate.is_dir():
            return candidate
    return None


def library_index_path() -> Optional[Path]:
    """LTK Manager's library index: it changes whenever its library does."""
    data_dir = ltk_data_dir()
    return data_dir / LIBRARY_INDEX if data_dir is not None else None


def _mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def library_version() -> Optional[tuple]:
    """When LTK Manager last changed its library, and its analysis of the
    mods (wad-reports.json, written apart from the index as it analyses
    one): (the index's mtime, the analysis's or None). None without an
    index."""
    path = library_index_path()
    index = _mtime(path) if path is not None else None
    return None if index is None else (index, _mtime(path.with_name(WAD_REPORTS)))


@dataclass(frozen=True)
class IndexEntry:
    """One mod of LTK Manager's library, as its index lists it."""

    ltk_id: str
    slug: Optional[str]
    format: Optional[str]
    storage: Optional[str]
    enabled: bool  # in the active profile's enabledMods (entries carry no flag)
    archive: Optional[Path]


def _mod_storage_root(data_dir: Path) -> Path:
    """Where LTK Manager stores its mods: its settings' modStoragePath, else
    the mods folder of its data folder."""
    try:
        settings = json.loads((data_dir / LTK_SETTINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.debug(f"[MODS] Could not read LTK Manager's settings: {e}")
        settings = None
    custom = settings.get("modStoragePath") if isinstance(settings, dict) else None
    if isinstance(custom, str) and custom.strip():
        return Path(custom.strip())
    return data_dir / "mods"


def mod_storage_root() -> Optional[Path]:
    """Where LTK Manager stores the mods it imports (None: it never ran
    here). The folder may not exist yet."""
    data_dir = ltk_data_dir()
    return _mod_storage_root(data_dir) if data_dir is not None else None


def _archive_suffix(fmt: object) -> str:
    return MODPKG_SUFFIX if fmt == "modpkg" else ".fantome"


def _plain_name(value: str) -> bool:
    """Whether *value* names a file in a folder, and nothing more."""
    return bool(value) and value not in {".", ".."} and not any(c in value for c in "/\\:")


def _read_index_document() -> Optional[dict]:
    """LTK Manager's library index as it is on disk, None when it is absent
    or cannot be read (LTK Manager writing it, another layout)."""
    path = library_index_path()
    if path is None:
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.debug(f"[MODS] Could not read LTK Manager's library index: {e}")
        return None
    if not isinstance(document, dict) or document.get("version") != LIBRARY_INDEX_VERSION:
        return None
    return document


def lists_profile_or_folder(name: str) -> bool:
    """Whether LTK Manager's index lists a profile or a folder named *name*
    (True when it cannot be read: it may)."""
    document = _read_index_document()
    if document is None:
        return True
    listed = [*(document.get("profiles") or []), *(document.get("folders") or [])]
    return any(isinstance(item, dict) and item.get("name") == name for item in listed)


def read_library_index() -> Optional[Dict[str, IndexEntry]]:
    """LTK Manager's library by entry id, read from its index without it
    running. None when the index is absent or cannot be read (LTK Manager
    writing it, another layout): never read that as "every mod is gone"."""
    document = _read_index_document()
    if document is None:
        return None
    path = library_index_path()
    mods = document.get("mods")
    if not isinstance(mods, list):
        return None

    enabled: set = set()
    profiles = document.get("profiles")
    if isinstance(profiles, list):
        for profile in profiles:
            if isinstance(profile, dict) and profile.get("id") == document.get("activeProfileId"):
                listed = profile.get("enabledMods")
                if isinstance(listed, list):
                    enabled = {str(mod_id) for mod_id in listed}
                break

    root = _mod_storage_root(path.parent)
    index: Dict[str, IndexEntry] = {}
    for mod in mods:
        if not isinstance(mod, dict):
            continue
        ltk_id = mod.get("id")
        if not isinstance(ltk_id, str) or not ltk_id:
            continue
        slug = mod.get("slug") if isinstance(mod.get("slug"), str) else None
        fmt = mod.get("format") if isinstance(mod.get("format"), str) else None
        storage = mod.get("storage") if isinstance(mod.get("storage"), str) else None
        archive = None
        if slug and _plain_name(slug) and storage in (None, "archive"):
            archive = root / f"{slug}{_archive_suffix(fmt)}"
        index[ltk_id] = IndexEntry(ltk_id, slug, fmt, storage, ltk_id in enabled, archive)
    return index


def read_mod_analysis() -> Dict[str, dict]:
    """What LTK Manager's own analysis found in each mod of its library, by
    entry id: {"tags": ["champion-skin", "map-skin", "ui"...], "maps": [...],
    "champions": [...]} (its wad-reports.json, written as it installs a mod).
    A mod it has not analysed is left out; {} when it analysed none. Raises
    OSError or ValueError when it cannot be read (LTK Manager writing it,
    another layout): never read that as "no mod is analysed"."""
    data_dir = ltk_data_dir()
    if data_dir is None:
        return {}
    try:
        document = json.loads((data_dir / WAD_REPORTS).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    reports = document.get("reports") if isinstance(document, dict) else None
    if not isinstance(reports, dict):
        raise ValueError(f"{WAD_REPORTS} holds no reports")
    return {
        str(mod_id): report["derived"] for mod_id, report in reports.items()
        if isinstance(report, dict) and isinstance(report.get("derived"), dict)
    }


def entry_archive(entry: Mapping) -> Optional[Path]:
    """Where LTK Manager keeps the archive of a library entry its bridge
    listed: an archive-storage mod keeps it beside its folder (modDir), as
    <modDir>.fantome (.modpkg for that format). None for a folder-storage
    mod, or an entry without modDir. The file may not exist."""
    mod_dir = entry.get("modDir")
    if not mod_dir or entry.get("storage") not in (None, "archive"):
        return None
    mod_dir = Path(str(mod_dir))
    return mod_dir.with_name(mod_dir.name + _archive_suffix(entry.get("format")))


def entry_name(entry: Mapping) -> str:
    return str(entry.get("displayName") or entry.get("name") or entry.get("id"))


class LtkLogTail:
    """What LTK Manager writes to its own log from the moment this was made.

    The patcher's verdict on the game ("dll attached", "joined too late, not
    overlaying") only shows there: the status the bridge reads does not carry it.
    """

    LOG_PATTERN = "ltk-manager*.log"

    def __init__(self, directory: Optional[Path]):
        self.directory = directory
        self.path = self._newest()
        self.offset = self._size(self.path)

    @staticmethod
    def log_dir() -> Optional[Path]:
        """LTK Manager's log folder: in the roaming app data of the desktop
        user it runs as (an elevated Rose may run as another account)."""
        for data_dir in ltk_data_candidates():
            candidate = data_dir / "logs"
            if candidate.is_dir():
                return candidate
        return None

    @staticmethod
    def _size(path: Optional[Path]) -> int:
        try:
            return path.stat().st_size if path else 0
        except OSError:
            return 0

    def _newest(self) -> Optional[Path]:
        if self.directory is None:
            return None
        try:
            logs = list(self.directory.glob(self.LOG_PATTERN))
            return max(logs, key=lambda log_path: log_path.stat().st_mtime) if logs else None
        except OSError:
            return None

    def read(self) -> str:
        """The text written since the last read."""
        newest = self._newest()
        if newest is None:
            return ""
        rolled_over_to_new_file = newest != self.path
        if rolled_over_to_new_file:
            self.path, self.offset = newest, 0
        rewritten = self._size(self.path) < self.offset
        if rewritten:
            self.offset = 0
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.offset)
                data = handle.read()
        except OSError:
            return ""
        self.offset += len(data)
        return data.decode("utf-8", "replace")
