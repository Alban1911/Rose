#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import itertools
import json
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Callable, Dict, Iterable, List, Literal, Mapping, Optional, Union, get_args

from utils.core.atomic_file import atomic_write
from utils.core.logging import get_logger
from utils.core.modpkg import MODPKG_SUFFIX
from utils.core.safe_extract import MOD_ARCHIVE_SUFFIXES

from .ltk_ref import is_ltk_id
from .mod_facts import ModFacts, archive_index_hash, compute_mod_facts
from .mod_source import LtkEntry, ModSource, RoseFile

log = get_logger()

MANIFEST_WRITERS_LOCK = threading.RLock()
_unreadable_manifests_logged: set[str] = set()

ModCategory = Literal["maps", "fonts", "announcers", "ui", "voiceover", "loading_screen", "vfx", "sfx", "others"]
ModKind = Union[Literal["skins"], ModCategory]
SKINS: ModKind = "skins"
MOD_CATEGORIES: tuple[ModCategory, ...] = get_args(ModCategory)
TARGET_METADATA = "rose_mod_targets.json"
LEGACY_TARGET_METADATA = "rose_wad_targets.json"
CATEGORY_METADATA = "rose_category_mods.json"
ARCHIVE_SUFFIX = ".fantome"
PENDING_REMOVALS = "pendingRemovals"
MIRRORED = "mirrored"
HIDDEN = "hidden"
SOURCE_HASHES = "sourceHashes"
# A custom skin's: the sha256 of the file the user picked (party mode shares
# it, and matches a friend's copy by it), and its archive's index
# (mod_facts.archive_index_hash: a renamed skin is found by it)
SOURCE_HASH = "sourceHash"
INDEX_HASH = "indexHash"

_METADATA_NAMES = {TARGET_METADATA, LEGACY_TARGET_METADATA, CATEGORY_METADATA}


def lives_in_ltk(kind: str) -> bool:
    """Whether a saved mod of *kind* lives in LTK Manager's library once it is
    added: a category's mod (a map, a font, a voiceover pack...) does, and
    Rose keeps only its manifest entry. A custom skin never does: Rose keeps
    its file, which it rewrites to match the game's base skin
    (injection.baseskin), imports it for each game and removes it after, as
    it does its own skins. Everything else follows from SavedMod.source, a
    custom skin's always Rose's file."""
    return kind in MOD_CATEGORIES


class UnreadableManifest(ValueError):
    """A mods manifest exists but cannot be read: rewriting it would drop the
    mods it lists, so it is left as it is."""


@dataclass(frozen=True)
class SavedMod:

    kind: ModKind
    manifest_dir: Path
    key: str
    name: str
    identity: str
    ltk_id: Optional[str]
    missing: bool
    rose_copy: Optional[Path]
    facts: Optional[ModFacts]
    display_name: Optional[str]
    target_skin_ids: tuple[int, ...]
    updated_at: float
    metadata: Mapping[str, object] = field(compare=False)

    @property
    def mirrored(self) -> bool:
        """Whether the user added it in LTK Manager, not in Rose: Rose lists
        it (ltk_mirror) and never removes it from LTK Manager."""
        return bool(self.ltk_id) and self.metadata.get(MIRRORED) is True

    @property
    def hidden(self) -> bool:
        """Whether the user hid it from Rose's lists of mods to pick."""
        return self.metadata.get(HIDDEN) is True

    def plugin_fields(self) -> dict:
        """What the plugins' listings say of it: where it is (its source's
        plugin_fields: ltkId, missing, pending), whether the user added it in
        LTK Manager, and whether they hid it."""
        return {**self.source.plugin_fields(), "mirrored": self.mirrored, "hidden": self.hidden}

    @property
    def registered(self) -> bool:
        """Whether its manifest has an entry for it (not a file nobody registered)."""
        return bool(self.key)

    @property
    def pending(self) -> bool:
        """Still Rose's to move into LTK Manager (lives_in_ltk)."""
        return lives_in_ltk(self.kind) and self.ltk_id is None and self.rose_copy is not None

    @property
    def available(self) -> bool:
        """Whether it can be injected: in LTK Manager's library, or its file in Rose."""
        return not self.missing if self.ltk_id else self.rose_copy is not None

    @property
    def own_folder(self) -> Optional[Path]:
        """Rose's copy when it is the folder of a mod LTK Manager does not
        hold, which holds the mod's preview image and description itself
        (META/image.png, description.txt). None for any other mod: those sit
        beside the manifest under its name, one LTK Manager holds included
        even while a folder copy of it is left, as that copy is about to go."""
        copy = self.rose_copy
        return copy if self.ltk_id is None and copy is not None and copy.is_dir() else None

    def image_paths(self) -> tuple[Path, Path]:
        """Where its preview image is, the PNG first (.fantome mods ship a
        PNG, .modpkg a WebP): in its own folder's META, else beside the
        manifest."""
        folder = self.own_folder
        if folder is not None:
            return folder / "META" / "image.png", folder / "META" / "image.webp"
        return self.sidecar(".png"), self.sidecar(".webp")

    @property
    def source(self) -> ModSource:
        """Where an injection takes it from: LTK Manager's entry, else Rose's
        copy, linked under its own name (a custom skin's always:
        lives_in_ltk). One with neither, which no listing yields, is taken
        from the file its identity names."""
        if self.ltk_id:
            return LtkEntry(self.ltk_id, self.facts, self.missing)
        return RoseFile.at(self.rose_copy or self.manifest_dir / PurePosixPath(self.identity).name)

    @property
    def storage_id(self) -> Optional[int]:
        """The number of the skins folder holding it: its champion's id
        times 1000, or the skin a per-skin folder of an older Rose is named
        after. None for a category's mod."""
        return int(self.manifest_dir.name) if self.kind == SKINS else None

    def sidecar(self, suffix: str) -> Path:
        """Its file beside the manifest (".png", ".webp", ".txt")."""
        return self.manifest_dir / f"{self.name}{suffix}"

    def path(self, mods_root: Path) -> Path:
        """Where its identity points (the file may not exist)."""
        return Path(mods_root) / self.identity



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
        if str(manifest_path) not in _unreadable_manifests_logged:
            _unreadable_manifests_logged.add(str(manifest_path))
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
    kind: ModKind
    path: Path
    relative: PurePosixPath
    skins_folder_number: Optional[int] = None
    per_skin_legacy: bool = False

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
    return _Directory(SKINS, path, PurePosixPath(SKINS, path.name), storage_id, storage_id % 1000 != 0)


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
            if champion_id is not None and directory.skins_folder_number // 1000 != champion_id:
                continue
            if child.is_dir():
                found.append(directory)
        directories.extend(sorted(found, key=lambda d: d.skins_folder_number))
    if kind is None:
        categories = MOD_CATEGORIES
    elif kind == SKINS:
        categories = ()
    else:
        categories = (kind,)
    for category in categories:
        path = mods_root / category
        if path.is_dir():
            directories.append(_Directory(category, path, PurePosixPath(category)))
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
    return _category_mod_name(metadata, key)


def _category_mod_name(metadata: Mapping, key: str) -> str:
    """A category's mod's name: its entry's path (the mod's name, without the
    extension), else its key."""
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
        ltk_id = metadata.get("ltkId") if lives_in_ltk(directory.kind) else None
        entries.append(_Entry(key, name, metadata, targets, ltk_id if is_ltk_id(ltk_id) else None))
    return _one_entry_per_name(entries)


def _one_entry_per_name(entries: List[_Entry]) -> List[_Entry]:
    """*entries*, one per name: the entry LTK Manager holds wins, else the first."""
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


def _unstored_modpkg(candidate: Path) -> bool:
    """Whether *candidate* is a .modpkg file: never what Rose stores a custom
    skin as (only a category's mod is kept as one), and hashing it would mean
    unpacking it."""
    return candidate.is_file() and candidate.suffix.lower() == MODPKG_SUFFIX


def _content_match(candidate: Path, entries: List[_Entry]) -> Optional[_Entry]:
    """The entry a renamed stored skin was registered as, by its archive's
    index (indexHash, read in a moment), or for an entry an older Rose wrote,
    by its content (the hashes it kept, which reads the whole mod): only files
    no entry names need it."""
    if _unstored_modpkg(candidate):
        return None
    try:
        index_hash = archive_index_hash(candidate)
    except (OSError, zipfile.BadZipFile) as e:
        log.debug(f"[MODS] Could not read {candidate.name}'s index to match it to its manifest entry: {e}")
        index_hash = None
    if index_hash is not None:
        match = next((entry for entry in entries if entry.metadata.get(INDEX_HASH) == index_hash), None)
        if match is not None:
            return match
    entries = [entry for entry in entries if INDEX_HASH not in entry.metadata]
    if not entries:
        return None
    try:
        _facts, full_hash, wad_hashes = compute_mod_facts(candidate)
    except Exception as e:
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


def _identity(directory: _Directory, name: str, stored: Optional[Path], is_dir: bool,
              ltk_id: Optional[str]) -> str:
    """A saved mod's identity: <dir>/<name>.fantome, or a pending mod's own
    folder or non-.fantome archive path. A mod LTK Manager holds keeps the
    first while a leftover copy remains: the saved selections are pointed at
    it before that copy goes (migration.delete_copy)."""
    if ltk_id is None and stored is not None and (is_dir or stored.suffix.lower() != ARCHIVE_SUFFIX):
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


def _directory_mods(directory: _Directory, match_content: bool = True) -> List[SavedMod]:
    payload = _read_directory_manifest(directory) or {}
    entries = _entries(directory, payload)
    default_targets: tuple[int, ...] = ()
    if directory.kind == SKINS:
        default_targets = normalize_target_ids(payload.get("targets") or payload.get("skinIds"))
        if directory.per_skin_legacy and not default_targets:
            default_targets = (directory.skins_folder_number,)

    by_key = {entry.key.casefold(): entry for entry in entries}
    by_name = {entry.name.casefold(): entry for entry in entries}
    copy_by_key: Dict[str, tuple[Path, bool]] = {}
    unmatched: List[tuple[Path, bool]] = []
    for candidate, is_dir in _stored_candidates(directory.path):
        stem = (candidate.name if is_dir else candidate.stem).casefold()
        entry = by_key.get(stem) or by_name.get(stem)
        if entry is not None and entry.key not in copy_by_key:
            copy_by_key[entry.key] = (candidate, is_dir)
        else:
            unmatched.append((candidate, is_dir))

    if directory.kind == SKINS and unmatched and match_content:
        _match_renamed(unmatched, entries, copy_by_key)

    mods: List[SavedMod] = []
    for entry in entries:
        copy, is_dir = copy_by_key.get(entry.key, (None, False))
        if copy is None and entry.ltk_id is None:
            continue
        name = (copy.name if is_dir else copy.stem) if copy is not None else entry.name
        targets = ()
        if directory.kind == SKINS:
            targets = entry.targets or default_targets or (directory.skins_folder_number,)
        updated_at = _mtime(copy) if copy is not None else None
        mods.append(SavedMod(
            kind=directory.kind,
            manifest_dir=directory.path,
            key=entry.key,
            name=name,
            identity=_identity(directory, name, copy, is_dir, entry.ltk_id),
            ltk_id=entry.ltk_id,
            missing=bool(entry.ltk_id) and entry.metadata.get("missing") is True,
            rose_copy=copy,
            facts=ModFacts.from_manifest(entry.metadata),
            display_name=_display_name(entry.metadata),
            target_skin_ids=tuple(targets),
            updated_at=updated_at if updated_at is not None else _updated_at(entry.metadata),
            metadata=MappingProxyType(entry.metadata),
        ))
    mods.extend(_unregistered_mods(directory, unmatched, default_targets))
    return sorted(mods, key=lambda mod: mod.name.lower())


def _match_renamed(unmatched: List[tuple[Path, bool]], entries: List[_Entry],
                   copy_by_key: Dict[str, tuple[Path, bool]]) -> None:
    """Match the renamed mods among *unmatched* to their entries by content,
    as the listing always matched them, moving each match into
    *copy_by_key*."""
    unclaimed = [entry for entry in entries if entry.key not in copy_by_key]
    for candidate, is_dir in list(unmatched):
        if not unclaimed:
            break
        entry = _content_match(candidate, unclaimed)
        if entry is not None:
            copy_by_key[entry.key] = (candidate, is_dir)
            unclaimed.remove(entry)
            unmatched.remove((candidate, is_dir))


def _unregistered_mods(directory: _Directory, unmatched: List[tuple[Path, bool]],
                       default_targets: tuple[int, ...]) -> List[SavedMod]:
    """The files in *directory* nobody registered: a champion's folder lists
    them with its default targets; a category lists only what it registered."""
    if directory.kind != SKINS or not default_targets:
        return []
    mods = []
    for candidate, is_dir in unmatched:
        name = candidate.name if is_dir else candidate.stem
        mods.append(SavedMod(
            kind=SKINS,
            manifest_dir=directory.path,
            key="",
            name=name,
            identity=_identity(directory, name, candidate, is_dir, None),
            ltk_id=None,
            missing=False,
            rose_copy=candidate,
            facts=None,
            display_name=None,
            target_skin_ids=default_targets,
            updated_at=_mtime(candidate) or 0.0,
            metadata=MappingProxyType({}),
        ))
    return mods



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
    """The saved mods folder *parts* name, relative to the mods root."""
    if len(parts) == 2 and parts[0].casefold() == SKINS:
        directory = _skins_directory(mods_root / SKINS / parts[1])
        return directory if directory is not None and directory.path.is_dir() else None
    if len(parts) == 1:
        category = next((c for c in MOD_CATEGORIES if c.casefold() == parts[0].casefold()), None)
        if category is not None and (mods_root / category).is_dir():
            return _Directory(category, mods_root / category, PurePosixPath(category))
    return None


def _find(mods_root: Path, relative_path: object,
          match_content: bool = True) -> Optional[tuple[_Directory, SavedMod]]:
    wanted = _relative_identity(mods_root, relative_path)
    if wanted is None:
        return None
    directory = _directory_of(mods_root, wanted.split("/")[:-1])
    if directory is None:
        return None
    folded = wanted.casefold()
    mods = _directory_mods(directory, match_content)
    for mod in mods:
        if mod.identity.casefold() == folded:
            return directory, mod
    for mod in mods:
        aliases = {f"{directory.relative}/{mod.name}", f"{directory.relative}/{mod.name}{ARCHIVE_SUFFIX}"}
        if mod.rose_copy is not None:
            aliases.add(f"{directory.relative}/{mod.rose_copy.name}")
        if folded in {alias.casefold() for alias in aliases}:
            return directory, mod
    return None


def find_saved_mod(mods_root: Path, relative_path: object, *, match_content: bool = True) -> Optional[SavedMod]:
    """The saved mod known as *relative_path*, compared as Windows compares
    paths: its identity, or the other name it has had (the folder it was
    stored as before archives, <dir>/<name>; the archive it became,
    <dir>/<name>.fantome), as selections saved by older Roses hold them.

    *match_content* False never matches a renamed file to its entry by its
    content, which reads the whole mod: such a file is then a file nobody
    registered (listed only with its folder's default targets)."""
    found = _find(Path(mods_root), relative_path, match_content)
    return found[1] if found else None


def stored_skin(mod_path: Path) -> Optional[SavedMod]:
    """The registered custom skin stored at *mod_path* (in a skins/<id>
    folder), found by its file's name, never by its content; None when its
    manifest has no entry under that name."""
    path = Path(mod_path)
    directory = _skins_directory(path.parent)
    if directory is None:
        return None
    return next((
        mod for mod in _directory_mods(directory, match_content=False)
        if mod.registered and mod.rose_copy is not None and mod.rose_copy.name.casefold() == path.name.casefold()
    ), None)


def _ltk_directories(mods_root: Path) -> List[_Directory]:
    """The folders of the mods that live in LTK Manager's library
    (lives_in_ltk): a custom skin's are never read for LTK Manager."""
    return [directory for directory in _directories(Path(mods_root)) if lives_in_ltk(directory.kind)]


def ltk_library_mods(mods_root: Path) -> List[SavedMod]:
    """The saved mods that live in LTK Manager's library, whether it holds
    them or Rose still does."""
    return [mod for directory in _ltk_directories(mods_root) for mod in _directory_mods(directory)]


def pending_mods(mods_root: Path) -> List[SavedMod]:
    """The saved mods Rose still has to move into LTK Manager."""
    return [mod for mod in ltk_library_mods(mods_root) if mod.pending]


def leftover_copies(mods_root: Path) -> List[SavedMod]:
    """Saved mods LTK Manager holds whose copy is still in Rose (a move that
    stopped between the manifest write and the deletion)."""
    return [mod for mod in ltk_library_mods(mods_root) if mod.ltk_id and mod.rose_copy is not None]


def _ltk_ids_in(payload: Optional[dict]) -> set[str]:
    """The LTK Manager entries Rose added for a manifest's mods: not those of
    the user's own mods it lists (mirrored)."""
    raw = payload.get("mods") if isinstance(payload, dict) else None
    return {
        value["ltkId"] for value in (raw.values() if isinstance(raw, dict) else ())
        if isinstance(value, dict) and is_ltk_id(value.get("ltkId")) and value.get(MIRRORED) is not True
    }


def _pending_removals(payload: Optional[dict]) -> List[str]:
    """The LTK Manager entries of a manifest's mods deleted in Rose, still to
    remove from LTK Manager (its pendingRemovals)."""
    raw = payload.get(PENDING_REMOVALS) if isinstance(payload, dict) else None
    return list(dict.fromkeys(mod_id for mod_id in raw if is_ltk_id(mod_id))) if isinstance(raw, list) else []


def _manifest_ids(mods_root: Path) -> tuple[set[str], List[str]]:
    """(the LTK Manager entries the manifests' mods name, the missing ones
    too; those their pendingRemovals list, in order)."""
    named: set[str] = set()
    removals: List[str] = []
    for directory in _ltk_directories(mods_root):
        payload = _read_directory_manifest(directory)
        named |= _ltk_ids_in(payload)
        removals.extend(_pending_removals(payload))
    return named, list(dict.fromkeys(removals))


def manifest_ltk_ids(mods_root: Path) -> set[str]:
    """Every LTK Manager entry Rose added for a saved mod: each manifest's
    ltkIds, the missing ones too, and those still to remove, but not the
    user's own mods it lists (mirrored). Cleaning up after a game must never
    take one of them for a leftover."""
    named, removals = _manifest_ids(mods_root)
    return named | set(removals)


def ltk_removals(mods_root: Path) -> List[str]:
    """The LTK Manager entries of saved mods deleted in Rose, still to remove
    (the manifests' pendingRemovals), but none a manifest's mod still names:
    removing that one would take a saved mod's only copy."""
    named, removals = _manifest_ids(mods_root)
    return [mod_id for mod_id in removals if mod_id not in named]



def _write_json(path: Path, payload: dict) -> None:
    """Replace *path* with *payload* in one move: a reader never sees half a file."""
    with atomic_write(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2))


def _change_manifest(directory: _Directory, change: Callable[[dict, dict], bool]) -> bool:
    """Every manifest write goes through here: *change(payload, mods)* edits
    the manifest as the file holds it now (its root, and a copy of its
    "mods"), under MANIFEST_WRITERS_LOCK, and returns whether to write it back, which
    is done in one move. Raises UnreadableManifest rather than start from an
    empty one."""
    with MANIFEST_WRITERS_LOCK:
        payload = _writable_manifest(directory)
        if payload is None:
            raise UnreadableManifest("The list of mods in this folder could not be read, so it was left unchanged")
        payload = dict(payload)
        raw_mods = payload.get("mods")
        mods = dict(raw_mods) if isinstance(raw_mods, dict) else {}
        if not change(payload, mods):
            return False
        _write_manifest(directory, payload, mods)
        return True


def _named(directory: _Directory, mods: dict, name: str) -> List[str]:
    """The keys of the entries in *mods* that name the mod *name*."""
    return [
        key for key, value in mods.items()
        if _entry_name(directory, key, value if isinstance(value, dict) else {}).casefold() == name.casefold()
    ]


def _set_pending_removals(payload: dict, ids: Iterable[object]) -> None:
    removals = list(dict.fromkeys(mod_id for mod_id in ids if is_ltk_id(mod_id)))
    if removals:
        payload[PENDING_REMOVALS] = removals
    else:
        payload.pop(PENDING_REMOVALS, None)


def _drop_entries(payload: dict, mods: dict, keys: Iterable[str]) -> None:
    """Take these entries out of *mods*, the LTK Manager entries Rose added
    for them added to the manifest's pendingRemovals in the same write: one
    no manifest named any more would stay in LTK Manager for good, as Rose
    would never know it again. A mod the user added in LTK Manager stays
    there (mirrored)."""
    keys = list(keys)
    dropped = [mods[key].get("ltkId") for key in keys
               if isinstance(mods[key], dict) and mods[key].get(MIRRORED) is not True]
    _set_pending_removals(payload, [*_pending_removals(payload), *dropped])
    for key in keys:
        del mods[key]


def update_saved_mod(mods_root: Path, relative_path: object, **fields: object) -> bool:
    """Merge *fields* (manifest keys: ltkId=..., missing=...) into a saved
    mod's manifest entry; a None value removes the key. A file nobody
    registered gets its entry, under its name, with its default targets
    written out. False when the mod is not listed, or its manifest cannot be
    read."""
    with MANIFEST_WRITERS_LOCK:
        found = _find(Path(mods_root), relative_path)
        if found is None:
            log.debug(f"[MODS] {relative_path} is not a saved mod: no manifest entry was changed")
            return False
        return _merge_into_entry(*found, fields)


def update_listed_mod(mod: SavedMod, *, keep_existing: bool = False, **fields: object) -> bool:
    """Merge *fields* into the manifest entry *mod* was listed from, by its
    key, whatever its file holds now: a renamed skin Rose rewrote no longer
    matches its entry by content. A file nobody registered gets its entry
    (update_saved_mod). *keep_existing* leaves a field the entry holds
    already as it is. False when the entry changed meanwhile, or its
    manifest cannot be read."""
    return _merge_into_entry(_mod_directory(mod), mod, fields, keep_existing)


def _merge_into_entry(directory: _Directory, mod: SavedMod, fields: Mapping[str, object],
                      keep_existing: bool = False) -> bool:
    def merge(_payload: dict, mods: dict) -> bool:
        key = mod.key
        if key:
            if key not in mods:
                log.debug(f"[MODS] {mod.name}'s manifest entry changed meanwhile: left unchanged")
                return False
            current = mods[key]
            entry = dict(current) if isinstance(current, dict) else {
                "name": mod.name, "targets": list(normalize_target_ids(current)),
            }
        else:
            key = mod.name
            if any(str(existing).casefold() == key.casefold() for existing in mods):
                return False
            entry = {"name": mod.name, "targets": list(mod.target_skin_ids)}
        for name, value in fields.items():
            if keep_existing and name in entry:
                continue
            if value is None:
                entry.pop(name, None)
            else:
                entry[name] = value
        mods[key] = entry
        return True

    try:
        return _change_manifest(directory, merge)
    except UnreadableManifest:
        log.warning(f"[MODS] The manifest of {mod.name} could not be read, so it was left unchanged")
        return False


def _mod_directory(mod: SavedMod) -> _Directory:
    if mod.kind == SKINS:
        return _skins_directory(mod.manifest_dir)
    return _Directory(mod.kind, mod.manifest_dir, PurePosixPath(mod.kind))


def remove_saved_mod(mods_root: Path, mod: SavedMod) -> bool:
    """Take a saved mod out of its manifest: its entry, and any other under
    its name, their LTK Manager entries left to remove at the next session
    start (_drop_entries). False when the manifest cannot be read. Rose's
    copy and the files beside the manifest are the caller's to delete."""
    if not mod.registered:
        return True
    directory = _mod_directory(mod)

    def drop(payload: dict, mods: dict) -> bool:
        removed = set(_named(directory, mods, mod.name))
        if mod.key in mods:
            removed.add(mod.key)
        _drop_entries(payload, mods, removed)
        return bool(removed)

    try:
        _change_manifest(directory, drop)
    except UnreadableManifest:
        log.warning(f"[MODS] The manifest of {mod.name} could not be read, so it was left unchanged")
        return False
    return True


def forget_ltk_removals(mods_root: Path, ids: Iterable[str]) -> None:
    """Take these entries (removed, or gone already) out of every manifest's
    pendingRemovals. A manifest that cannot be read keeps them: a later
    session start finds them gone."""
    done = set(ids)

    def forget(payload: dict, _mods: dict) -> bool:
        pending = _pending_removals(payload)
        if not done & set(pending):
            return False
        _set_pending_removals(payload, [mod_id for mod_id in pending if mod_id not in done])
        return True

    for directory in _ltk_directories(mods_root) if done else ():
        try:
            _change_manifest(directory, forget)
        except UnreadableManifest as e:
            log.debug(f"[MODS] {directory.manifest}: {e}")


def add_saved_mod(mods_root: Path, archive: Path, facts: Optional[ModFacts], targets: Iterable[int] = (), *,
                  source_hash: Optional[str] = None, index_hash: Optional[str] = None) -> None:
    """Register the archive of a mod just added to its folder, keyed by its
    name, with its date (the listing keeps it once the archive is in LTK
    Manager) and what Rose needs to know about it, read once: a category's
    mod its facts (read_mod_facts); a custom skin its targets, the sha256 of
    the file the user picked (*source_hash*: what party mode shares and
    matches a friend's copy by) and its archive's index (*index_hash*: what
    a renamed skin is found by, _content_match).

    An entry left under its name by a mod whose file is gone is dropped.
    Raises UnreadableManifest, or ValueError when *archive* is not in a saved
    mods folder."""
    mods_root = Path(mods_root)
    identity = _relative_identity(mods_root, archive)
    directory = _directory_of(mods_root, identity.split("/")[:-1]) if identity else None
    if directory is None:
        raise ValueError(f"{archive} is not in a saved mods folder")
    name = Path(identity).stem
    entry: dict = {"name": name, **(facts.to_manifest() if facts is not None else {})}
    updated_at = _mtime(mods_root / identity)
    if updated_at is not None:
        entry["updatedAt"] = updated_at
    if source_hash is not None:
        entry[SOURCE_HASH] = source_hash
    if index_hash is not None:
        entry[INDEX_HASH] = index_hash
    if directory.kind == SKINS:
        entry["targets"] = list(targets)
    else:
        entry["path"] = name

    def register(payload: dict, mods: dict) -> bool:
        _drop_entries(payload, mods, _named(directory, mods, name))
        mods[name] = entry
        return True

    _change_manifest(directory, register)


def add_mirrored_mod(mods_root: Path, category: str, ltk_id: str, name: str, fields: Mapping[str, object]) -> str:
    """List in *category* the mod the user added to LTK Manager as entry
    *ltk_id*, marked as the user's (mirrored), with *fields* (displayName,
    facts...), under *name* or the first free "<name>-<n>": no other entry
    nor stored mod of the category has that name. Returns the name it got.
    Raises UnreadableManifest."""
    directory = _Directory(category, Path(mods_root) / category, PurePosixPath(category))
    directory.path.mkdir(parents=True, exist_ok=True)
    stored = {(path.name if is_dir else path.stem).casefold() for path, is_dir in _stored_candidates(directory.path)}
    chosen: List[str] = []

    def register(_payload: dict, mods: dict) -> bool:
        taken = stored | {_entry_name(directory, k, v if isinstance(v, dict) else {}).casefold() for k, v in mods.items()}
        candidates = itertools.chain((name,), (f"{name}-{n}" for n in itertools.count(2)))
        unique = next(candidate for candidate in candidates if candidate.casefold() not in taken)
        mods[unique] = {**fields, "name": unique, "path": unique, "ltkId": ltk_id, MIRRORED: True}
        chosen.append(unique)
        return True

    _change_manifest(directory, register)
    return chosen[0]


def set_hidden(mods_root: Path, relative_path: object, hidden: bool) -> bool:
    """Hide the mod the user added in LTK Manager (mirrored) known as
    *relative_path* from the lists to pick a game's mods from, or show it
    again. False for any other mod, one not found, or a manifest that cannot
    be read."""
    with MANIFEST_WRITERS_LOCK:
        found = _find(Path(mods_root), relative_path, match_content=False)
        if found is None or not found[1].mirrored:
            return False
        return _merge_into_entry(*found, {HIDDEN: True if hidden else None})


def set_targets(directory: Path, targets: Iterable[int], name: Optional[str] = None) -> None:
    """Set the skins a champion's folder targets by default, or those its mod
    *name* targets (an entry under that name is created when none has it).
    Raises UnreadableManifest."""
    folder = _skins_directory(Path(directory))
    if folder is None:
        raise ValueError(f"{directory} is not a champion's mods folder")
    targets = list(targets)

    def retarget(payload: dict, mods: dict) -> bool:
        if name is None:
            payload["targets"] = targets
            return True
        key = next(iter(_named(folder, mods, name)), name)
        current = mods.get(key)
        mods[key] = {**(current if isinstance(current, dict) else {"name": name}), "targets": targets}
        return True

    _change_manifest(folder, retarget)


def _write_manifest(directory: _Directory, payload: dict, mods: dict) -> None:
    payload["version"] = 1
    if directory.kind == SKINS:
        payload.setdefault("championId", directory.skins_folder_number // 1000)
        payload.setdefault("targets", [directory.skins_folder_number] if directory.per_skin_legacy else [])
    else:
        payload["category"] = directory.kind
    payload["mods"] = dict(sorted(mods.items()))
    _write_json(directory.manifest, payload)
