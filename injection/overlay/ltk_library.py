#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LTK Manager's library, where the user's saved mods live.

A mod the user adds is imported into LTK Manager once and stays there; each
game only switches it on and off. Rose then needs LTK Manager's library in two
ways:

- offline, with no LTK Manager running: which entries exist and where LTK
  Manager keeps their archives, read from its own index (library.json in its
  data folder). A sync marks a saved mod missing from it, and the loading
  screen name reads a skin's champion record from LTK Manager's copy;
- online, through Rose's bridge, outside any game: importing a saved mod,
  checking and repairing it, keeping it (turned off) after the session that
  imported it, removing it. LtkLibrary.session() gives such a session, on the
  rules OverlayManager.check_mod always followed: never while an injection's
  session holds LTK Manager, and LTK Manager closed again if Rose started it.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Optional

from utils.core.logging import get_logger
from utils.core.modpkg import MODPKG_SUFFIX

from ..tools.bridge import BridgeCommandError, BridgeUnavailable
from .overlay_manager import (
    ALREADY_OPEN_REASON,
    LTF_MISSING_REASON,
    LTK_MANAGER_MISSING_REASON,
    REPAIR_PASSES,
    _answer_value,
    _archive_for_ltk,
    _rejected_by_game,
    _verdict_summary,
)

log = get_logger()

__all__ = [
    "ALREADY_OPEN_REASON",
    "BridgeCommandError",
    "BridgeUnavailable",
    "IndexEntry",
    "LTF_MISSING_REASON",
    "LTK_MANAGER_MISSING_REASON",
    "LibrarySession",
    "LtkBusy",
    "LtkLibrary",
    "LtkUnavailable",
    "entry_archive",
    "library_index_mtime",
    "library_index_path",
    "ltk_data_candidates",
    "ltk_data_dir",
    "read_library_index",
    "stored_archive",
]

LTK_DATA_FOLDER = "dev.leaguetoolkit.manager"
LIBRARY_INDEX = "library.json"
LTK_SETTINGS = "settings.json"
# The index layout this reads (LTK Manager 1.33): {"version": 2, "mods": [{id,
# format, storage, slug...}], "profiles": [{id, enabledMods...}], "activeProfileId"}.
# Another layout is not guessed at: a misread index would mark mods missing
LIBRARY_INDEX_VERSION = 2


# --------------------------------------------------------------------------------------
# offline: LTK Manager's own files
# --------------------------------------------------------------------------------------

def ltk_data_candidates() -> List[Path]:
    """Where LTK Manager may keep its data: the roaming app data of the
    desktop user it runs as first (an elevated Rose may run as another
    account), then this account's."""
    candidates = []
    try:
        from utils.core.paths import get_user_data_dir

        candidates.append(get_user_data_dir().parent.parent / "Roaming" / LTK_DATA_FOLDER)
    except Exception:  # noqa: BLE001 - the next candidate still answers
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


def library_index_mtime() -> Optional[float]:
    """When LTK Manager last changed its library (None: no index)."""
    path = library_index_path()
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


@dataclass(frozen=True)
class IndexEntry:
    """One mod of LTK Manager's library, as its index lists it."""

    ltk_id: str
    slug: Optional[str]
    format: Optional[str]
    storage: Optional[str]
    enabled: bool  # in the active profile's enabledMods (entries carry no flag)
    archive: Optional[Path]  # where LTK Manager keeps it as an archive (may not exist)


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


def _archive_suffix(fmt: object) -> str:
    return MODPKG_SUFFIX if fmt == "modpkg" else ".fantome"


def _plain_name(value: str) -> bool:
    """Whether *value* names a file in a folder, and nothing more."""
    return bool(value) and value not in {".", ".."} and not any(c in value for c in "/\\:")


def read_library_index() -> Optional[Dict[str, IndexEntry]]:
    """LTK Manager's library by entry id, read from its index without it
    running. None when the index is absent or cannot be read (LTK Manager
    writing it, another layout): never read that as "every mod is gone"."""
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


def stored_archive(ltk_id: str) -> Optional[Path]:
    """LTK Manager's archive of the entry *ltk_id*, if it is there."""
    index = read_library_index()
    entry = index.get(ltk_id) if index else None
    archive = entry.archive if entry is not None else None
    return archive if archive is not None and archive.is_file() else None


# --------------------------------------------------------------------------------------
# online: a session through Rose's bridge, outside any game
# --------------------------------------------------------------------------------------

class LtkBusy(RuntimeError):
    """LTK Manager is in use: an injection's session holds it (champion
    select, a game), or another session is connecting."""


class LtkUnavailable(RuntimeError):
    """LTK Manager could not be reached; str() is why (not installed, open
    without Rose's bridge, could not start, bridge gone)."""


class LtkLibrary:
    """LTK Manager's library through Rose's bridge, for the saved mods."""

    def __init__(self, overlay) -> None:
        self.overlay = overlay

    @contextmanager
    def session(self, *, wait: bool = False) -> Iterator["LibrarySession"]:
        """A session with LTK Manager, started if it is not running and closed
        again after if Rose started it. Entries imported in it are removed at
        its end unless kept (LibrarySession.keep).

        Raises LtkBusy at once while an injection holds LTK Manager: nothing
        here ever waits on a game. *wait* waits for another session's connect
        instead (the uninstall cleanup, with Rose not running).

        The stage lock is held throughout, taken before the connect lock as
        the injection takes them: an injection installs under it before its
        session is registered (session_active), and a session starting then
        would remove the mods it just installed as an earlier session's.
        """
        overlay = self.overlay
        if not overlay._stage_lock.acquire(blocking=wait):
            raise LtkBusy("LTK Manager is in use for a game")
        try:
            if not overlay._connect_lock.acquire(blocking=wait):
                raise LtkBusy("LTK Manager is busy with another session")
            try:
                with overlay._session_lock:
                    busy = overlay._early_session is not None or overlay._staging_open
                process_manager = overlay.process_manager
                if busy or (process_manager is not None and process_manager.session_active()):
                    raise LtkBusy("LTK Manager is in use for a game")
                session = overlay._start_ltf_session(report=False)
                if session is None:
                    raise LtkUnavailable(overlay.last_failure_reason or "LTK Manager could not be started")
                try:
                    yield LibrarySession(overlay, session)
                finally:
                    # Removes what was imported and not kept, closes LTK Manager if Rose started it
                    overlay._end_session(session)
            finally:
                overlay._connect_lock.release()
        finally:
            overlay._stage_lock.release()


class LibrarySession:
    """What a saved mod needs from LTK Manager's library, in one session.

    Bridge failures raise BridgeUnavailable (the bridge is gone: stop) or
    BridgeCommandError (this command failed).
    """

    def __init__(self, overlay, session: dict) -> None:
        self._overlay = overlay
        self._session = session

    @property
    def bridge(self):
        return self._session["bridge"]

    def library(self) -> Dict[str, dict]:
        """LTK Manager's library by entry id."""
        return {str(entry.get("id")): entry for entry in self.bridge.library() if entry.get("id")}

    def import_archive(self, archive: Path, display_name: str) -> dict:
        """Import a saved mod (its archive, or a folder, packed) and return its
        entry. The entry is Rose's until kept: a session that ends, or a Rose
        that crashes, first removes it, as an injection's mods."""
        archive = Path(archive)
        staging = self._overlay._staging_root() / f"import-{uuid.uuid4().hex}"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            if archive.is_file():
                # A .modpkg keeps its suffix: LTK Manager tells the format by it
                suffix = MODPKG_SUFFIX if archive.suffix.lower() == MODPKG_SUFFIX else ".fantome"
                staged = _archive_for_ltk(archive, staging / f"{archive.stem}{suffix}")
            else:
                staged = _archive_for_ltk(archive, staging / f"{archive.name}.fantome")
            return self._overlay._import_archive(self._session, staged, archive, display_name)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def confirm(self, ltk_id: str) -> Optional[dict]:
        """The entry *ltk_id* as LTK Manager's library lists it now, if it does."""
        return self.library().get(str(ltk_id))

    def keep(self, ltk_id: str) -> None:
        """Leave the entry in LTK Manager after the session, turned off: it is
        a saved mod now. Write its ltkId into the manifest before: from here
        nothing removes the entry, and the session-start cleanup leaves alone
        the entries a manifest lists. Raises when it could not be turned off
        (it is still kept; the next session start turns it off)."""
        ltk_id = str(ltk_id)
        for tracked in ("installed", "fingerprints", "sources"):
            self._session[tracked].pop(ltk_id, None)
        self._overlay._untrack(removed=[ltk_id])
        self.bridge.toggle(ltk_id, False)

    def switch(self, ltk_id: str, enabled: bool) -> None:
        """Turn an entry on or off."""
        self.bridge.toggle(str(ltk_id), enabled)

    def uninstall(self, ltk_id: str) -> None:
        """Remove an entry from LTK Manager's library."""
        ltk_id = str(ltk_id)
        self.bridge.uninstall(ltk_id)
        if self._session["installed"].pop(ltk_id, None) is not None:
            self._session["fingerprints"].pop(ltk_id, None)
            self._session["sources"].pop(ltk_id, None)
            self._overlay._untrack(removed=[ltk_id])

    def check_and_repair(self, ltk_id: str, display_name: str) -> dict:
        """LTK Manager's verdict on an entry, after it repaired what it can.

        LTK Manager repairs its own copy; nothing is written back into Rose,
        which keeps none. Returns {"health": LTK's word before any repair,
        "repaired": fixes applied, "problems": [{"rule", "title",
        "description"}] that still make the game reject the mod}.
        """
        ltk_id = str(ltk_id)
        bridge = self.bridge
        verdict = _answer_value(bridge.check_mod_health(ltk_id))
        result = {"health": str(verdict.get("health") or ""), "repaired": 0, "problems": []}
        log.info(f"[MODCHECK] LTK Manager's verdict on {display_name}: {result['health'] or 'unknown'}"
                 f" ({_verdict_summary(verdict)})")
        # One pass can leave a fix for the next: a rule skips a file an
        # earlier rule of the same pass rewrote
        for _ in range(REPAIR_PASSES):
            if verdict.get("health") != "repairable" or int(verdict.get("fixable") or 0) <= 0:
                break
            report = _answer_value(bridge.repair_mod(ltk_id))
            applied = int(report.get("applied") or 0)
            if report.get("failed"):
                log.warning(f"[MODCHECK] LTK Manager could not repair all of {display_name}: {report.get('failed')}")
            if not applied:
                break
            result["repaired"] += applied
            verdict = _answer_value(bridge.check_mod_health(ltk_id))
        if result["repaired"]:
            log.info(f"[MODCHECK] LTK Manager repaired {result['repaired']} problem(s) in {display_name} "
                     f"({_verdict_summary(verdict)} left)")
        result["problems"] = _rejected_by_game(verdict)
        for problem in result["problems"]:
            log.warning(f"[MODCHECK] {display_name} will not work in game: {problem['title']} - "
                        f"{problem['description']}")
        return result
