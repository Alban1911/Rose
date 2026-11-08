#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The user's saved mods, as their manifests list them.

A mod the user adds moves into LTK Manager's library, and Rose keeps only
what it knows about it: its manifest entry (rose_mod_targets.json in a
champion's folder, rose_category_mods.json in a category's), and its preview
image and description beside the manifest, under the mod's name. So a saved
mod is a manifest entry, not a file:

- an entry with an ltkId is held by LTK Manager (missing once a sync no
  longer finds it there);
- an entry without one whose archive (or folder) is still in Rose's mods
  folder is pending: it is injected as before and moved at the next start;
- an entry with neither is gone, and not listed, as before.

Files nobody registered are still listed where they were before (a champion's
or a legacy per-skin folder with default targets), so a mod dropped into the
folder by hand keeps working.

Reading here has no side effects: nothing is created or cleaned up. Every
writer of a mods manifest holds _STORAGE_LOCK and merges its fields into the
entry as the file holds it now, so two writers never undo each other.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, List, Mapping, Optional

from utils.core.atomic_file import atomic_write
from utils.core.logging import get_logger
from utils.core.modpkg import MODPKG_SUFFIX
from utils.core.safe_extract import MOD_ARCHIVE_SUFFIXES

from .ltk_ref import is_ltk_id, ltk_ref
from .mod_facts import ModFacts, compute_mod_facts

log = get_logger()

# Held by every writer of a mods manifest (ModStorageService and the writers
# here): each reads the file, changes it and writes it back
_STORAGE_LOCK = threading.RLock()
# Unreadable manifests already reported, so repeated listings do not flood the log
_reported_manifests: set[str] = set()

# As ModStorageService names them (it imports this module, not the reverse)
SKINS = "skins"
MOD_CATEGORIES = ("maps", "fonts", "announcers", "ui", "voiceover", "loading_screen", "vfx", "sfx", "others")
TARGET_METADATA = "rose_mod_targets.json"
LEGACY_TARGET_METADATA = "rose_wad_targets.json"
CATEGORY_METADATA = "rose_category_mods.json"
ARCHIVE_SUFFIX = ".fantome"
# The LTK Manager entries of saved mods deleted in Rose, removed from LTK
# Manager at the next session start: {"ids": [...]}
LTK_REMOVALS = "ltk_removals.json"

_METADATA_NAMES = {TARGET_METADATA, LEGACY_TARGET_METADATA, CATEGORY_METADATA}


@dataclass(frozen=True)
class SavedMod:
    """One mod the user saved in Rose."""

    kind: str  # "skins" or one of MOD_CATEGORIES
    directory: Path  # holds the manifest and the sidecars
    key: str  # its key in the manifest's "mods" ("" for a file nobody registered)
    name: str
    # Its identity, relative to the mods root (POSIX): the path historic.json
    # and mod_historic.json hold. <dir>/<name>.fantome, or the stored folder's
    # (or non-.fantome archive's) own path while it exists
    relative_path: str
    ltk_id: Optional[str]
    missing: bool
    stored: Optional[Path]  # Rose's copy (archive or folder), if there is one
    facts: Optional[ModFacts]
    display_name: Optional[str]
    target_skin_ids: tuple[int, ...]  # skins only
    updated_at: float
    metadata: Mapping[str, object] = field(compare=False)

    @property
    def pending(self) -> bool:
        """Still Rose's to move into LTK Manager."""
        return self.ltk_id is None and self.stored is not None

    @property
    def available(self) -> bool:
        """Whether it can be injected: in LTK Manager's library, or pending."""
        return bool(self.ltk_id and not self.missing) or self.pending

    @property
    def injection_name(self) -> str:
        """Its name in the injection's mods folder: the LTK reference for a
        mod LTK Manager holds, else the stored folder's name or the archive's
        without its extension, as it is linked there."""
        if self.ltk_id:
            return ltk_ref(self.ltk_id)
        if self.stored is None:
            return self.name
        return self.stored.name if self.stored.is_dir() else self.stored.stem

    @property
    def storage_id(self) -> Optional[int]:
        """The number of the skins folder holding it: its champion's id
        times 1000, or the skin a per-skin folder of an older Rose is named
        after. None for a category's mod."""
        return int(self.directory.name) if self.kind == SKINS else None

    def sidecar(self, suffix: str) -> Path:
        """Its file beside the manifest (".png", ".webp", ".txt")."""
        return self.directory / f"{self.name}{suffix}"

    def path(self, mods_root: Path) -> Path:
        """Where its identity points (the file may not exist)."""
        return Path(mods_root) / self.relative_path


# --------------------------------------------------------------------------------------
# reading manifests
# --------------------------------------------------------------------------------------

def read_manifest(manifest_path: Path) -> Optional[dict]:
    """Read a mod manifest: {} when there is none, None when it exists but cannot be read.

    An unreadable manifest used to look empty, so the mods it lists vanished
    from the UI with no trace, and importing a mod rewrote it with that mod alone.
    """
    try:
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, TypeError, ValueError) as e:
        if str(manifest_path) not in _reported_manifests:
            _reported_manifests.add(str(manifest_path))
            log.warning(f"[MODS] Could not read mod manifest {manifest_path}: {e}")
        return None
    return payload if isinstance(payload, dict) else {}


def normalize_target_ids(value: object) -> tuple[int, ...]:
    """The skin ids a manifest value targets (an entry, or a bare list of ids)."""
    if isinstance(value, dict):
        value = (
            value.get("targets")
            or value.get("skinIds")
            or value.get("targetSkinIds")
            or value.get("affectedSkinIds")
            or []
        )
    if isinstance(value, (str, bytes)) or value is None:
        return ()
    try:
        values = iter(value)
    except TypeError:
        return ()
    normalized = set()
    for raw_value in values:
        try:
            skin_id = int(raw_value)
        except (TypeError, ValueError):
            continue
        if skin_id > 0:
            normalized.add(skin_id)
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class _Directory:
    kind: str
    path: Path
    relative: str  # POSIX, relative to the mods root
    storage_id: Optional[int] = None  # a skins folder's number
    legacy: bool = False  # a per-skin folder from before champion folders

    @property
    def manifest(self) -> Path:
        return self.path / (TARGET_METADATA if self.kind == SKINS else CATEGORY_METADATA)


@dataclass
class _Entry:
    key: str
    name: str
    metadata: dict
    targets: tuple[int, ...]
    ltk_id: Optional[str]


def _skins_directory(path: Path) -> Optional[_Directory]:
    """A numbered folder under skins: a champion's (<champion id>000) or a
    legacy per-skin one (<skin id>)."""
    try:
        storage_id = int(path.name)
    except ValueError:
        return None
    if storage_id <= 0:
        return None
    return _Directory(SKINS, path, f"{SKINS}/{path.name}", storage_id, storage_id % 1000 != 0)


def _directories(mods_root: Path, kind: Optional[str] = None,
                 champion_id: Optional[int] = None) -> List[_Directory]:
    """The folders that hold saved mods: champion and legacy per-skin folders
    (by number, so a champion's own folder comes before its per-skin ones),
    then the categories."""
    if kind is not None and kind != SKINS and kind not in MOD_CATEGORIES:
        return []
    directories: List[_Directory] = []
    if kind in (None, SKINS):
        try:
            children = list((mods_root / SKINS).iterdir())
        except OSError:
            children = []
        found = []
        for child in children:
            directory = _skins_directory(child)
            if directory is None:
                continue
            if champion_id is not None and directory.storage_id // 1000 != champion_id:
                continue
            if child.is_dir():
                found.append(directory)
        directories.extend(sorted(found, key=lambda d: d.storage_id))
    if kind is None:
        categories = MOD_CATEGORIES
    elif kind == SKINS:
        categories = ()
    else:
        categories = (kind,)
    for category in categories:
        path = mods_root / category
        if path.is_dir():
            directories.append(_Directory(category, path, category))
    return directories


def _read_directory_manifest(directory: _Directory) -> Optional[dict]:
    """A folder's manifest as the listing reads it: a champion folder falls
    back on the older rose_wad_targets.json when its own is empty or unreadable."""
    payload = read_manifest(directory.manifest)
    if directory.kind != SKINS or payload:
        return payload
    legacy = read_manifest(directory.path / LEGACY_TARGET_METADATA)
    return legacy if legacy or payload is not None else None


def _writable_manifest(directory: _Directory) -> Optional[dict]:
    """A folder's manifest as a writer must start from it, None when part of it
    cannot be read: rewriting it then would drop the mods it lists."""
    payload = read_manifest(directory.manifest)
    if payload is None or payload or directory.kind != SKINS:
        return payload
    return read_manifest(directory.path / LEGACY_TARGET_METADATA)


def _entry_name(directory: _Directory, key: str, metadata: Mapping) -> str:
    if directory.kind == SKINS:
        return str(metadata.get("name") or key)
    # A category knows a mod by its path (its name, without the extension)
    return str(metadata.get("path") or key).replace("\\", "/").strip("/")


def _entries(directory: _Directory, payload: Optional[dict]) -> List[_Entry]:
    raw = payload.get("mods") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return []
    entries = []
    for raw_key, value in raw.items():
        key = str(raw_key)
        metadata = dict(value) if isinstance(value, dict) else {}
        name = _entry_name(directory, key, metadata)
        targets = normalize_target_ids(value) if directory.kind == SKINS else ()
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            continue
        ltk_id = metadata.get("ltkId")
        entries.append(_Entry(key, name, metadata, targets, ltk_id if is_ltk_id(ltk_id) else None))
    # One mod per name: the entry LTK Manager holds wins, else the first
    chosen: dict[str, _Entry] = {}
    for entry in entries:
        current = chosen.get(entry.name.casefold())
        if current is None or (entry.ltk_id and not current.ltk_id):
            chosen[entry.name.casefold()] = entry
    return [entry for entry in entries if chosen[entry.name.casefold()] is entry]


def _stored_candidates(directory: Path) -> List[tuple[Path, bool]]:
    """The mods stored in *directory* (folders and archives) with whether
    each is a folder, by name. Rose's temporary entries (".rose-...") and the
    manifests are not mods."""
    try:
        children = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    candidates = []
    for child in children:
        if child.name.startswith(".") or child.name in _METADATA_NAMES:
            continue
        if child.is_dir():
            candidates.append((child, True))
        elif child.is_file() and child.suffix.lower() in MOD_ARCHIVE_SUFFIXES:
            candidates.append((child, False))
    return candidates


def _content_match(candidate: Path, entries: List[_Entry]) -> Optional[_Entry]:
    """The entry a renamed stored mod was registered as, by its content (the
    hash the manifest keeps): only files no entry names need it."""
    if candidate.is_file() and candidate.suffix.lower() == MODPKG_SUFFIX:
        return None  # never stored as one, and reading it would mean unpacking it
    try:
        _facts, full_hash, wad_hashes = compute_mod_facts(candidate)
    except Exception as e:  # noqa: BLE001 - an unreadable file just stays unmatched
        log.debug(f"[MODS] Could not hash {candidate.name} to match it to its manifest entry: {e}")
        return None
    for entry in entries:
        stored_wad_hashes = entry.metadata.get("wadHashes")
        if (
            entry.key == full_hash
            or entry.metadata.get("folderHash") == full_hash
            or (wad_hashes and isinstance(stored_wad_hashes, dict) and stored_wad_hashes == wad_hashes)
        ):
            return entry
    return None


def _mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _identity(directory: _Directory, name: str, stored: Optional[Path], is_dir: bool) -> str:
    if stored is not None and (is_dir or stored.suffix.lower() != ARCHIVE_SUFFIX):
        return f"{directory.relative}/{stored.name}"
    return f"{directory.relative}/{name}{ARCHIVE_SUFFIX}"


def _display_name(metadata: Mapping) -> Optional[str]:
    raw = metadata.get("displayName")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _updated_at(metadata: Mapping) -> float:
    raw = metadata.get("updatedAt")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    return 0.0


def _directory_mods(directory: _Directory) -> List[SavedMod]:
    payload = _read_directory_manifest(directory) or {}
    entries = _entries(directory, payload)
    default_targets: tuple[int, ...] = ()
    if directory.kind == SKINS:
        default_targets = normalize_target_ids(payload.get("targets") or payload.get("skinIds"))
        if directory.legacy and not default_targets:
            default_targets = (directory.storage_id,)

    by_key = {entry.key.casefold(): entry for entry in entries}
    by_name = {entry.name.casefold(): entry for entry in entries}
    stored: dict[int, tuple[Path, bool]] = {}  # id(entry) -> its stored copy
    unmatched: List[tuple[Path, bool]] = []
    for candidate, is_dir in _stored_candidates(directory.path):
        stem = (candidate.name if is_dir else candidate.stem).casefold()
        entry = by_key.get(stem) or by_name.get(stem)
        if entry is not None and id(entry) not in stored:
            stored[id(entry)] = (candidate, is_dir)
        else:
            unmatched.append((candidate, is_dir))

    if directory.kind == SKINS and unmatched:
        # A renamed mod, as the listing always matched it: never an entry LTK
        # Manager holds, so a listing of moved mods hashes nothing
        unclaimed = [entry for entry in entries if id(entry) not in stored and entry.ltk_id is None]
        for candidate, is_dir in list(unmatched):
            if not unclaimed:
                break
            entry = _content_match(candidate, unclaimed)
            if entry is not None:
                stored[id(entry)] = (candidate, is_dir)
                unclaimed.remove(entry)
                unmatched.remove((candidate, is_dir))

    mods: List[SavedMod] = []
    for entry in entries:
        copy, is_dir = stored.get(id(entry), (None, False))
        if copy is None and entry.ltk_id is None:
            continue  # gone, as before
        name = (copy.name if is_dir else copy.stem) if copy is not None else entry.name
        targets = ()
        if directory.kind == SKINS:
            targets = entry.targets or default_targets or (directory.storage_id,)
        updated_at = _mtime(copy) if copy is not None else None
        mods.append(SavedMod(
            kind=directory.kind,
            directory=directory.path,
            key=entry.key,
            name=name,
            relative_path=_identity(directory, name, copy, is_dir),
            ltk_id=entry.ltk_id,
            missing=bool(entry.ltk_id) and entry.metadata.get("missing") is True,
            stored=copy,
            facts=ModFacts.from_manifest(entry.metadata),
            display_name=_display_name(entry.metadata),
            target_skin_ids=tuple(targets),
            updated_at=updated_at if updated_at is not None else _updated_at(entry.metadata),
            metadata=MappingProxyType(entry.metadata),
        ))
    # A file nobody registered: listed with the folder's default targets, as
    # before; a category lists only what it registered
    if directory.kind == SKINS and default_targets:
        for candidate, is_dir in unmatched:
            name = candidate.name if is_dir else candidate.stem
            mods.append(SavedMod(
                kind=SKINS,
                directory=directory.path,
                key="",
                name=name,
                relative_path=_identity(directory, name, candidate, is_dir),
                ltk_id=None,
                missing=False,
                stored=candidate,
                facts=None,
                display_name=None,
                target_skin_ids=default_targets,
                updated_at=_mtime(candidate) or 0.0,
                metadata=MappingProxyType({}),
            ))
    return sorted(mods, key=lambda mod: mod.name.lower())


# --------------------------------------------------------------------------------------
# saved mods
# --------------------------------------------------------------------------------------

def iter_saved_mods(mods_root: Path, kind: Optional[str] = None, *,
                    champion_id: Optional[int] = None) -> List[SavedMod]:
    """Every saved mod (of *kind*, "skins" or a category; of *champion_id*'s
    folders), whether LTK Manager holds it or it is pending."""
    mods: List[SavedMod] = []
    for directory in _directories(Path(mods_root), kind, champion_id):
        mods.extend(_directory_mods(directory))
    return mods


def _relative_identity(mods_root: Path, relative_path: object) -> Optional[str]:
    text = str(relative_path or "").strip()
    if not text:
        return None
    if Path(text).is_absolute():
        try:
            text = Path(text).relative_to(mods_root).as_posix()
        except ValueError:
            return None
    parts = text.replace("\\", "/").strip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return "/".join(parts)


def _directory_of(mods_root: Path, parts: List[str]) -> Optional[_Directory]:
    if len(parts) == 3 and parts[0].casefold() == SKINS:
        directory = _skins_directory(mods_root / SKINS / parts[1])
        return directory if directory is not None and directory.path.is_dir() else None
    if len(parts) == 2:
        category = next((c for c in MOD_CATEGORIES if c.casefold() == parts[0].casefold()), None)
        if category is not None and (mods_root / category).is_dir():
            return _Directory(category, mods_root / category, category)
    return None


def _find(mods_root: Path, relative_path: object) -> Optional[tuple[_Directory, SavedMod]]:
    wanted = _relative_identity(mods_root, relative_path)
    if wanted is None:
        return None
    directory = _directory_of(mods_root, wanted.split("/"))
    if directory is None:
        return None
    folded = wanted.casefold()
    mods = _directory_mods(directory)
    for mod in mods:
        if mod.relative_path.casefold() == folded:
            return directory, mod
    for mod in mods:
        aliases = {f"{directory.relative}/{mod.name}", f"{directory.relative}/{mod.name}{ARCHIVE_SUFFIX}"}
        if mod.stored is not None:
            aliases.add(f"{directory.relative}/{mod.stored.name}")
        if folded in {alias.casefold() for alias in aliases}:
            return directory, mod
    return None


def find_saved_mod(mods_root: Path, relative_path: object) -> Optional[SavedMod]:
    """The saved mod known as *relative_path*, compared as Windows compares
    paths: its identity, or the other name it has had (the folder it was
    stored as before archives, <dir>/<name>; the archive it became,
    <dir>/<name>.fantome), as selections saved by older Roses hold them."""
    found = _find(Path(mods_root), relative_path)
    return found[1] if found else None


def pending_mods(mods_root: Path) -> List[SavedMod]:
    """The saved mods Rose still has to move into LTK Manager."""
    return [mod for mod in iter_saved_mods(mods_root) if mod.pending]


def leftover_copies(mods_root: Path) -> List[SavedMod]:
    """Saved mods LTK Manager holds whose copy is still in Rose (a move that
    stopped between the manifest write and the deletion)."""
    return [mod for mod in iter_saved_mods(mods_root) if mod.ltk_id and mod.stored is not None]


def manifest_ltk_ids(mods_root: Path) -> set[str]:
    """Every LTK Manager entry Rose added for a saved mod: each manifest's
    ltkIds, the missing ones too, and those queued for removal. Cleaning up
    after a game must never take one of them for a leftover."""
    ids: set[str] = set()
    for directory in _directories(Path(mods_root)):
        payload = _read_directory_manifest(directory)
        raw = payload.get("mods") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            continue
        for value in raw.values():
            if isinstance(value, dict) and is_ltk_id(value.get("ltkId")):
                ids.add(value["ltkId"])
    ids.update(ltk_removals(mods_root))
    return ids


# --------------------------------------------------------------------------------------
# writing manifests
# --------------------------------------------------------------------------------------

def _write_json(path: Path, payload: dict) -> None:
    """Replace *path* with *payload* in one move: a reader never sees half a file."""
    with atomic_write(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2))


def update_saved_mod(mods_root: Path, relative_path: object, **fields: object) -> bool:
    """Merge *fields* (manifest keys: ltkId=..., partyHash=...) into a saved
    mod's manifest entry; a None value removes the key. A file nobody
    registered gets its entry, under its name, with its default targets
    written out. False when the mod is not listed, or its manifest cannot be
    read (rewriting it would drop the mods it lists)."""
    with _STORAGE_LOCK:
        found = _find(Path(mods_root), relative_path)
        if found is None:
            log.debug(f"[MODS] {relative_path} is not a saved mod: no manifest entry was changed")
            return False
        directory, mod = found
        payload = _writable_manifest(directory)
        if payload is None:
            log.warning(f"[MODS] The manifest of {mod.name} could not be read, so it was left unchanged")
            return False
        payload = dict(payload)
        raw_mods = payload.get("mods")
        mods = dict(raw_mods) if isinstance(raw_mods, dict) else {}
        key = mod.key
        if key:
            if key not in mods:
                log.debug(f"[MODS] {mod.name}'s manifest entry changed meanwhile: left unchanged")
                return False
            current = mods[key]
            entry = dict(current) if isinstance(current, dict) else {
                "name": mod.name, "targets": list(normalize_target_ids(current)),
            }
            if directory.kind == SKINS and mod.stored is not None and fields.get("ltkId"):
                # A renamed file was matched by its content, which an entry LTK
                # Manager holds never is: its name must lead to the file now
                entry["name"] = mod.name
        else:
            key = mod.name
            if any(str(existing).casefold() == key.casefold() for existing in mods):
                return False
            entry = {"name": mod.name, "targets": list(mod.target_skin_ids)}
        for name, value in fields.items():
            if value is None:
                entry.pop(name, None)
            else:
                entry[name] = value
        mods[key] = entry
        _write_manifest(directory, payload, mods)
        return True


def remove_saved_mod(mods_root: Path, mod: SavedMod) -> bool:
    """Take a saved mod out of its manifest: its entry, and any other under
    its name. The LTK Manager entries they name are queued for removal at the
    next session start first: one no manifest names any more would stay in
    LTK Manager for good, as Rose would never know it again. False when the
    manifest cannot be read (rewriting it would drop the mods it lists).
    Rose's copy and the files beside the manifest are the caller's to delete."""
    if not mod.key:
        return True  # a file nobody registered: no entry to take out
    if mod.kind == SKINS:
        directory = _skins_directory(mod.directory)
    else:
        directory = _Directory(mod.kind, mod.directory, mod.kind)
    with _STORAGE_LOCK:
        payload = _writable_manifest(directory)
        if payload is None:
            log.warning(f"[MODS] The manifest of {mod.name} could not be read, so it was left unchanged")
            return False
        raw_mods = payload.get("mods")
        mods = dict(raw_mods) if isinstance(raw_mods, dict) else {}
        removed = {
            key: value for key, value in mods.items()
            if key == mod.key
            or _entry_name(directory, key, value if isinstance(value, dict) else {}).casefold() == mod.name.casefold()
        }
        if not removed:
            return True
        queue_ltk_removal(mods_root, [value.get("ltkId") for value in removed.values() if isinstance(value, dict)])
        _write_manifest(directory, dict(payload), {key: value for key, value in mods.items() if key not in removed})
    return True


def _write_manifest(directory: _Directory, payload: dict, mods: dict) -> None:
    payload["version"] = 1
    if directory.kind == SKINS:
        payload.setdefault("championId", directory.storage_id // 1000)
        payload.setdefault("targets", [directory.storage_id] if directory.legacy else [])
    else:
        payload["category"] = directory.kind
    payload["mods"] = dict(sorted(mods.items()))
    _write_json(directory.manifest, payload)


# --------------------------------------------------------------------------------------
# LTK Manager entries to remove (saved mods deleted in Rose)
# --------------------------------------------------------------------------------------

def _removals_path(mods_root: Path) -> Path:
    return Path(mods_root) / LTK_REMOVALS


def ltk_removals(mods_root: Path) -> List[str]:
    """The LTK Manager entries of saved mods deleted in Rose, still to remove."""
    path = _removals_path(mods_root)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        if str(path) not in _reported_manifests:
            _reported_manifests.add(str(path))
            log.warning(f"[MODS] Could not read {path}: {e}")
        return []
    ids = document.get("ids") if isinstance(document, dict) else None
    if not isinstance(ids, list):
        return []
    return list(dict.fromkeys(mod_id for mod_id in ids if is_ltk_id(mod_id)))


def queue_ltk_removal(mods_root: Path, ids: Iterable[str]) -> None:
    """Have the next session start remove these LTK Manager entries. An
    unreadable queue is replaced: it is a to-do list, and the entries it held
    are only left behind in LTK Manager, as these would be otherwise."""
    wanted = [mod_id for mod_id in ids if is_ltk_id(mod_id)]
    if not wanted:
        return
    with _STORAGE_LOCK:
        queued = ltk_removals(mods_root)
        merged = list(dict.fromkeys([*queued, *wanted]))
        if merged != queued:
            _write_json(_removals_path(mods_root), {"ids": merged})


def forget_ltk_removals(mods_root: Path, ids: Iterable[str]) -> None:
    """Drop these entries from the removal queue (removed, or gone already)."""
    done = set(ids)
    with _STORAGE_LOCK:
        queued = ltk_removals(mods_root)
        remaining = [mod_id for mod_id in queued if mod_id not in done]
        if remaining == queued:
            return
        if remaining:
            _write_json(_removals_path(mods_root), {"ids": remaining})
        else:
            _removals_path(mods_root).unlink(missing_ok=True)


# --------------------------------------------------------------------------------------
# selections
# --------------------------------------------------------------------------------------

def selection_available(sel: Mapping) -> bool:
    """Whether a selected saved mod can still be injected: one LTK Manager
    holds unless a sync found it gone, a pending one while its file exists.
    Takes the selection dicts as they were before LTK Manager held mods too."""
    if not isinstance(sel, Mapping):
        return False
    if sel.get("ltk_id"):
        return not sel.get("missing")
    mod_path = sel.get("mod_path")
    if not mod_path:
        return False
    try:
        return Path(mod_path).exists()
    except (OSError, TypeError, ValueError):
        return False
