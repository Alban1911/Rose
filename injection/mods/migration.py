#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import ctypes
import itertools
import os
import shutil
import sys
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, List, Mapping, NamedTuple, Optional, Protocol, Tuple

from config import MOD_MIGRATION_MUTEX_NAME, SINGLE_INSTANCE_MUTEX_NAME
from utils.core.junction import is_junction, safe_remove_entry
from utils.core.logging import get_logger
from utils.core.paths import get_desktop_user_desktop_dir

from ..overlay.ltf_session import LIBRARY_IMPORT_HEADROOM_BYTES
from ..overlay.ltk_data import entry_archive, mod_storage_root
from ..overlay.ltk_library import (
    BridgeCommandError,
    BridgeUnavailable,
    LibrarySession,
    LtkBusy,
    LtkLibrary,
    LtkUnavailable,
    MissingComponent,
)
from .conversion import convert_folder_mods, rename_saved_paths
from .manifest import ARCHIVE_SUFFIX, SavedMod, ltk_library_mods, update_listed_mod
from .mod_facts import read_mod_facts, stamp_of
from .storage import ModStorageService

log = get_logger()

BACKUP_FOLDER = "Rose mods backup {date:%Y-%m-%d}"
BACKUP_ASKED = "backupAsked"
INJECTION_LINK_FOLDERS = ("mods", "stage", "ltf_staging")
REASONS_THE_DLL_CHECK_REPORTS = tuple(MissingComponent)
COPY_CHUNK_BYTES = 8 * 1024 * 1024

_SYNCHRONIZE = 0x00100000
_ERROR_ALREADY_EXISTS = 183


class Step(Enum):
    """What the migration is doing: packing the mods an older Rose stored as
    folders, opening LTK Manager, copying the mods to the desktop, moving a
    mod into LTK Manager."""

    CONVERT = "convert"
    CONNECT = "connect"
    BACKUP = "backup"
    MOVE = "move"


class MigrationUi(Protocol):
    """What the migration shows and asks: the launcher's dialog."""

    def progress(self, step: Step, index: int = 0, total: int = 0, name: str = "",
                 done_bytes: int = 0, total_bytes: int = 0) -> None:
        """The *index*th of *total* (a mod, a file of the backup) is *name*;
        *done_bytes* of *total_bytes* are done (0 of 0: none to count)."""

    def ask_backup(self, size: int, free: int) -> bool:
        """Whether to copy the mods (*size* bytes) to the desktop (*free*
        bytes free on its drive) before moving them."""

    def notify(self, message: str) -> None:
        """Tell the user why mods stay in Rose for now."""


class FailedMove(NamedTuple):
    mod: str
    reason: str


@dataclass
class MigrationReport:

    moved: List[str] = field(default_factory=list)
    failed: List[FailedMove] = field(default_factory=list)
    skipped_reason: Optional[str] = None


class MigrationStopped(Exception):
    """Nothing more is moved this start; str() is why. *notice* is what the
    user is told (None: someone else tells them)."""

    def __init__(self, reason: str, notice: Optional[str] = None) -> None:
        super().__init__(reason)
        self.notice = notice


class _MoveFailed(Exception):
    """A mod could not be moved; it stays in Rose."""


@dataclass(frozen=True)
class _Move:
    """A saved mod to move into LTK Manager."""

    mod: SavedMod
    display_name: str
    size: int
    ltk_id_left_by_game: Optional[str]


@dataclass(frozen=True)
class _File:
    """A file the backup copies."""

    path: Path
    relative: Path
    size: int


def needs_migration(mods_root: Path) -> bool:
    """Whether a saved mod that lives in LTK Manager's library still has its
    copy in Rose: one to move there (pending), or a moved one whose copy a
    stopped run left. Reads the manifests and lists the mods folders (a
    custom skin's not: it stays Rose's), and starts no LTK Manager."""
    return any(mod.rose_copy is not None for mod in ltk_library_mods(mods_root))


def migrate_saved_mods(storage: ModStorageService, library: LtkLibrary, ui: MigrationUi, *,
                       holds_instance_lock: bool = False) -> MigrationReport:
    """Move every saved mod Rose still holds of those that live in LTK
    Manager's library (manifest.lives_in_ltk) into it.

    Nothing happens when none is left. Otherwise, with no other Rose running
    or moving them: the mods stored as folders are packed, the injection's
    folders emptied, LTK Manager opened (it must be there before anything is
    asked or copied), the user asked whether to back the mods up to the
    desktop first (once LTK Manager's drive is known to take them, and once
    for each mod an older Rose saved: one added while LTK Manager was busy
    moves silently), and each mod moved. LTK Manager
    missing or failing, a backup asked for that fails, a drive too full:
    nothing is moved or deleted, and the next start tries again. A mod that
    fails stays in Rose, pending; the user is told which.
    """
    report = MigrationReport()
    if not needs_migration(storage.mods_root):
        return report
    try:
        with _launcher_migration_mutex(holds_instance_lock):
            convert_folder_mods(storage, progress=lambda index, total, name: ui.progress(
                Step.CONVERT, index, total, name))
            _empty_injection_folders(library.host.injection_dir)
            ui.progress(Step.CONNECT)
            try:
                with library.session() as session:
                    _Migration(storage, session, ui, report).run()
            except (LtkBusy, LtkUnavailable) as e:
                reason = str(e)
                raise MigrationStopped(
                    reason, None if reason in REASONS_THE_DLL_CHECK_REPORTS else _unavailable_notice(reason)) from e
    except MigrationStopped as e:
        log.info(f"[MIGRATE] The saved mods stay in Rose for now: {e}")
        report.skipped_reason = str(e)
        if e.notice:
            ui.notify(e.notice)
        return report
    if report.failed:
        ui.notify(_failures_notice(report))
    return report


def delete_copy(storage: ModStorageService, mod: SavedMod) -> bool:
    """Point the saved selections still naming Rose's copy of a saved mod LTK
    Manager holds (the path of a .zip, a .modpkg or a folder, which names
    nothing once the copy is gone) at the mod's identity,
    <dir>/<name>.fantome, then delete the copy
    (ModStorageService.drop_stored_copy). False when the copy stays: a
    selection not renamed, or the copy in use. It is then a leftover copy,
    and the next start does both again."""
    if mod.rose_copy is None:
        return False
    parent = PurePosixPath(mod.identity).parent
    copy_path, identity = f"{parent}/{mod.rose_copy.name}", f"{parent}/{mod.name}{ARCHIVE_SUFFIX}"
    if copy_path.casefold() != identity.casefold() and not rename_saved_paths({copy_path: identity}):
        log.warning(f"[MIGRATE] Kept Rose's copy of {mod.name}: its saved selections could not be renamed")
        return False
    return storage.drop_stored_copy(identity)


class _Migration:
    """One start's moves, in one LTK Manager session."""

    def __init__(self, storage: ModStorageService, session: LibrarySession, ui: MigrationUi,
                 report: MigrationReport) -> None:
        self.storage = storage
        self.session = session
        self.ui = ui
        self.report = report

    def run(self) -> None:
        try:
            library = self.session.library()
        except (BridgeUnavailable, BridgeCommandError) as e:
            raise MigrationStopped(str(e), _unavailable_notice(str(e))) from e
        moves, leftovers = self._plan(library)
        unasked = [move.mod for move in moves if _backup_unasked(move.mod)]
        if unasked:
            self._check_space(moves)
            self._offer_backup(moves)
            _remember_backup_asked(unasked)
        for mod in leftovers:
            delete_copy(self.storage, mod)
        if moves:
            self._check_space(moves)
            log.info(f"[MIGRATE] Moving {len(moves)} saved mod(s) into LTK Manager's library")
            self._move_all(moves)

    def _plan(self, library: Mapping[str, dict]) -> Tuple[List[_Move], List[SavedMod]]:
        """(the mods to move, the leftover copies to delete). A copy whose
        entry LTK Manager no longer lists is moved again: it is the mod's
        only copy now."""
        moves, leftovers = [], []
        for mod in ltk_library_mods(self.storage.mods_root):
            if mod.rose_copy is None:
                continue
            if mod.ltk_id is not None and mod.ltk_id in library:
                leftovers.append(mod)
                continue
            try:
                kept_id = self.session.kept_copy(mod.rose_copy, library)
            except OSError as e:
                log.debug(f"[MIGRATE] Could not read {mod.name} to find the copy a game kept of it: {e}")
                kept_id = None
            moves.append(_Move(mod, mod.display_name or mod.name, _stored_size(mod.rose_copy), kept_id))
        return moves, leftovers

    def _offer_backup(self, moves: List[_Move]) -> None:
        """Ask whether to copy the mods folder (manifests, images and
        descriptions too) to the desktop first, and do it. Raises
        MigrationStopped when a backup the user wants cannot be made, or
        leaves no room for *moves* on a drive it shares with LTK Manager's
        library: nothing is deleted without it."""
        mods_root = self.storage.mods_root
        try:
            files = _files_under(mods_root)
            desktop = get_desktop_user_desktop_dir()
            free = free_space(desktop)
        except OSError as e:
            raise MigrationStopped(f"could not size the backup: {e}", _backup_notice(str(e))) from e
        size = sum(item.size for item in files)
        if not self.ui.ask_backup(size, free):
            log.info("[MIGRATE] Moving the saved mods without a backup, as the user chose")
            return
        if size > free:
            raise MigrationStopped(
                "not enough space for the backup",
                _backup_notice(f"there is not enough free space on its drive ({size_text(size)} needed, "
                               f"{size_text(free)} free)"),
            )
        self._check_space_beside_backup(moves, desktop, size)
        destination = None
        try:
            destination = _backup_folder(desktop)
            _copy_files(files, destination, lambda done, index, name: self.ui.progress(
                Step.BACKUP, index, len(files), name, done, size))
        except OSError as e:
            if destination is not None:
                shutil.rmtree(destination, ignore_errors=True)
            raise MigrationStopped(f"the backup failed: {e}", _backup_notice(str(e))) from e
        log.info(f"[MIGRATE] Backed up the saved mods ({size_text(size)}) to {destination}")

    def _import_space(self, moves: List[_Move]) -> Optional[Tuple[Path, int, int]]:
        """(LTK Manager's library folder, the bytes free on its drive, the
        bytes the imports of *moves* need there). Each import copies a mod
        there and Rose's copy goes after it: a drive Rose's mods share needs
        room for the largest, another drive for all of them. None when
        nothing is imported, or the folder or its space cannot be told."""
        imports = [move.size for move in moves if move.ltk_id_left_by_game is None]
        root = mod_storage_root()
        if not imports or root is None:
            return None
        try:
            free = free_space(root)
            shared = _volume(root) == _volume(self.storage.mods_root)
        except OSError as e:
            log.debug(f"[MIGRATE] Could not tell the free space on LTK Manager's drive: {e}")
            return None
        return root, free, (max(imports) if shared else sum(imports)) + LIBRARY_IMPORT_HEADROOM_BYTES

    def _check_space_beside_backup(self, moves: List[_Move], desktop: Path, size: int) -> None:
        """Raise MigrationStopped when a backup of *size* bytes on *desktop*
        would leave LTK Manager's drive, the same drive, without the room
        the imports need."""
        space = self._import_space(moves)
        if space is None:
            return
        root, free, need = space
        try:
            shared = _volume(desktop) == _volume(root)
        except OSError:
            return
        if shared and free < size + need:
            raise MigrationStopped(
                "not enough space for the backup and the mods",
                _backup_notice(f"your desktop is on the drive of LTK Manager's library, which does not have room "
                               f"for both the backup and your mods ({size_text(size + need)} needed, "
                               f"{size_text(free)} free)"),
            )

    def _check_space(self, moves: List[_Move]) -> None:
        """Raise MigrationStopped when LTK Manager's drive cannot take the
        mods (_import_space)."""
        space = self._import_space(moves)
        if space is None:
            return
        root, free, need = space
        if free < need:
            raise MigrationStopped(
                f"{size_text(free)} free on LTK Manager's drive, {size_text(need)} needed",
                f"Your mods need {size_text(need)} free on the drive of LTK Manager's library ({_existing(root)}), "
                f"and {size_text(free)} is free there.\n\nFree some space: your mods stay in Rose and work as "
                "before until then, and Rose moves them the next time it starts.",
            )

    def _move_all(self, moves: List[_Move]) -> None:
        total_bytes = sum(move.size for move in moves)
        done_bytes = 0
        for index, move in enumerate(moves, 1):
            self.ui.progress(Step.MOVE, index, len(moves), move.display_name, done_bytes, total_bytes)
            try:
                self._move(move)
            except BridgeUnavailable as e:
                log.warning(f"[MIGRATE] LTK Manager stopped answering: the remaining mods stay in Rose for now ({e})")
                self.report.failed.extend(
                    FailedMove(rest.display_name, f"LTK Manager stopped answering ({e})") for rest in moves[index - 1:])
                return
            except (_MoveFailed, BridgeCommandError, OSError, ValueError, zipfile.BadZipFile) as e:
                log.warning(f"[MIGRATE] Could not move {move.display_name} into LTK Manager, it stays in Rose for now: {e}")
                self.report.failed.append(FailedMove(move.display_name, str(e)))
            else:
                self.report.moved.append(move.display_name)
            done_bytes += move.size

    def _move(self, move: _Move) -> None:
        """Move one mod: its facts read from Rose's copy (unless its manifest
        holds them), its archive imported (or the copy a game kept taken as
        it is), the entry named by its manifest once LTK Manager lists it,
        kept there, and Rose's copy deleted. Raises with the mod still Rose's."""
        mod = move.mod
        facts = mod.facts or read_mod_facts(mod.rose_copy)
        ltk_id = move.ltk_id_left_by_game or str(self.session.import_archive(mod.rose_copy, move.display_name).get("id"))
        entry = self.session.confirm(ltk_id)
        if entry is None:
            raise _MoveFailed("LTK Manager does not list it after the import")
        archive = entry_archive(entry)
        stamp = stamp_of(archive) if archive is not None else None
        if not self.storage.attach_ltk_entry(mod.identity, ltk_id, facts=facts, stamp=stamp):
            raise _MoveFailed("its manifest could not be written")
        try:
            self.session.keep(ltk_id)
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.debug(f"[MIGRATE] Could not turn {move.display_name} off in LTK Manager, the next session start does: {e}")
        delete_copy(self.storage, mod)
        log.info(f"[MIGRATE] Moved {move.display_name} into LTK Manager's library"
                 f"{' (the copy a game kept there)' if move.ltk_id_left_by_game else ''}")


@contextmanager
def _launcher_migration_mutex(holds_instance_lock: bool = False) -> Iterator[None]:
    """Keep other Rose versions and direct callers out during migration."""
    if sys.platform != "win32":
        yield
        return
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    if not holds_instance_lock:
        running = kernel32.OpenMutexW(_SYNCHRONIZE, False, SINGLE_INSTANCE_MUTEX_NAME)
        if running:
            kernel32.CloseHandle(running)
            raise MigrationStopped("Rose is running already")
    handle = kernel32.CreateMutexW(None, False, MOD_MIGRATION_MUTEX_NAME)
    if not handle:
        raise MigrationStopped("could not reserve the mod migration mutex")
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        raise MigrationStopped("another Rose is moving the mods")
    try:
        yield
    finally:
        kernel32.CloseHandle(handle)


def _backup_unasked(mod: SavedMod) -> bool:
    """Whether the user is still to be asked to back up the mods before *mod*
    moves: an older Rose saved it (its manifest has no facts), and no start
    asked yet."""
    return mod.facts is None and mod.metadata.get(BACKUP_ASKED) is not True


def _remember_backup_asked(mods: List[SavedMod]) -> None:
    """Note in each mod's manifest entry that the backup was made or turned
    down: a mod that stays in Rose (its import failed, LTK Manager stopped)
    does not have the user asked, and the mods copied, again at each start."""
    for mod in mods:
        if not update_listed_mod(mod, **{BACKUP_ASKED: True}):
            log.debug(f"[MIGRATE] Could not note that the backup was asked for {mod.name}: the next start asks again")


def _empty_injection_folders(injection_dir: Path) -> None:
    """Empty the folders an injection links saved mods into: a hard link
    left there keeps a deleted archive's bytes on disk."""
    for name in INJECTION_LINK_FOLDERS:
        try:
            entries = list((injection_dir / name).iterdir())
        except OSError:
            continue
        for entry in entries:
            safe_remove_entry(entry)


def _files_under(folder: Path) -> List[_File]:
    """Every file under *folder*, links left out: what they point at is not
    Rose's, and nothing here deletes it. Raises OSError for a folder it
    cannot read: a backup must not miss a mod."""
    def fail(error: OSError) -> None:
        raise error

    files = []
    for root, dirs, names in os.walk(folder, onerror=fail):
        dirs[:] = [name for name in dirs if not is_junction(Path(root) / name)]
        for name in names:
            path = Path(root) / name
            if not path.is_symlink():
                files.append(_File(path, path.relative_to(folder), path.stat().st_size))
    return files


def _stored_size(stored: Path) -> int:
    """The bytes of Rose's copy of a mod (an archive, or a folder an older Rose stored)."""
    try:
        if stored.is_dir():
            return sum(item.size for item in _files_under(stored))
        return stored.stat().st_size
    except OSError:
        return 0


def _backup_folder(desktop: Path) -> Path:
    """Create today's backup folder on *desktop* ("Rose mods backup
    YYYY-MM-DD", " (2)"... when that one exists) and return it."""
    base = BACKUP_FOLDER.format(date=date.today())
    for number in itertools.count(1):
        folder = desktop / (base if number == 1 else f"{base} ({number})")
        try:
            folder.mkdir(parents=True)
        except FileExistsError:
            continue
        return folder


def _copy_files(files: List[_File], destination: Path, progress: Callable[[int, int, str], None]) -> None:
    """Copy *files* under *destination* as they are (their dates too),
    telling *progress(bytes done, index, name)* as it goes."""
    done = 0
    for index, item in enumerate(files, 1):
        progress(done, index, item.relative.as_posix())
        target = destination / item.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with item.path.open("rb") as source, target.open("wb") as copy:
            for chunk in iter(lambda: source.read(COPY_CHUNK_BYTES), b""):
                copy.write(chunk)
                done += len(chunk)
                progress(done, index, item.relative.as_posix())
        shutil.copystat(item.path, target)


def _existing(path: Path) -> Path:
    """*path*, or its nearest parent that exists: a folder not created yet
    will be on its parent's drive."""
    path = Path(path)
    return next((candidate for candidate in (path, *path.parents) if candidate.exists()), path)


def free_space(path: Path) -> int:
    """The free bytes on the drive of *path* (which may not exist yet)."""
    return shutil.disk_usage(_existing(path)).free


def _volume(path: Path) -> int:
    return os.stat(_existing(path)).st_dev


def size_text(size: int) -> str:
    """A size as people read it: "850 MB", "3.6 GB", "120 GB"."""
    units = ("B", "KB", "MB", "GB", "TB")
    value, unit = float(max(0, size)), 0
    while value >= 1024 and unit < len(units) - 1:
        value /= 1024
        unit += 1
    if unit == 0 or value >= 10:
        return f"{value:.0f} {units[unit]}"
    return f"{value:.1f} {units[unit]}"


def _unavailable_notice(reason: str) -> str:
    return (f"Rose could not move your mods into LTK Manager: {reason}.\n\n"
            "Your mods stay in Rose and work as before. Rose tries again the next time it starts "
            "(close LTK Manager first if it is open).")


def _backup_notice(why: str) -> str:
    return (f"Rose could not back up your mods to your desktop: {why}.\n\n"
            "Nothing was moved or deleted: your mods stay in Rose and work as before, "
            "and Rose asks again the next time it starts.")


def _failures_notice(report: MigrationReport) -> str:
    failures = "\n".join(f"- {name}: {why}" for name, why in report.failed)
    total = len(report.moved) + len(report.failed)
    return (f"Rose moved {len(report.moved)} of your {total} mods into LTK Manager. These stay in Rose and work "
            f"as before, and Rose tries to move them again the next time it starts:\n\n{failures}")
