#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mod storage service
Handles mods organized by category: skins, maps, fonts, announcers, others

A mod is stored as the .fantome LTK Manager installs, as it is: a .fantome or
.zip is kept as it came, a .modpkg is converted once. Its preview image and
description sit beside it under its name (<name>.png / <name>.webp,
<name>.txt). Mods stored as folders by an earlier Rose are packed into
archives once, when Rose starts (convert_folder_mod).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional

from utils.core.junction import is_junction, safe_remove_entry
from utils.core.atomic_file import atomic_write
from utils.core.logging import get_logger
from utils.core.modpkg import MODPKG_SUFFIX
from utils.core.paths import get_user_data_dir
from utils.core.safe_extract import (
    MOD_ARCHIVE_SUFFIXES,
    check_mod_archive,
    extract_mod_archive,
)
from utils.core.utilities import get_champion_id_from_skin_id

from . import manifest as saved_manifest
from .fantome import is_packed_wad, write_fantome_zip
from .ltk_ref import is_ltk_id
# Shared with the manifest writers: one lock, one report per unreadable manifest
from .manifest import _STORAGE_LOCK, _reported_manifests
from .manifest import SavedMod
from .mod_facts import ModFacts
from .mod_files import ModFiles

log = get_logger()

_INFO_KEY = "meta/info.json"
_PREVIEW_IMAGES = (("META/image.png", ".png"), ("META/image.webp", ".webp"))

def _folder_file_sizes(folder: Path) -> dict[str, int]:
    """{relative path: size} of every file under *folder*.

    Raises OSError for anything it cannot read: Path.rglob skips a folder it
    may not list, and a mod folder an earlier Rose created can be readable
    by its own account only (tempfile.mkdtemp's owner-only access).
    """
    def fail(error: OSError) -> None:
        raise error

    sizes = {}
    for root, _dirs, names in os.walk(folder, onerror=fail):
        for name in names:
            path = Path(root) / name
            sizes[path.relative_to(folder).as_posix()] = path.stat().st_size
    return sizes


def _check_packed(archive: Path, expected: dict[str, int], added_metadata: bool) -> None:
    """Raise unless *archive* holds exactly the files *expected* lists, at
    their sizes: the folder is removed once its archive replaces it."""
    with zipfile.ZipFile(archive) as packed:
        held = {info.filename: info.file_size for info in packed.infolist() if not info.is_dir()}
    if added_metadata:
        held.pop("metadata.json", None)
        expected = {name: size for name, size in expected.items() if name != "metadata.json"}
    if held != expected:
        missing = sorted(set(expected) - set(held))[:3]
        raise OSError(f"the archive does not hold the folder's files as they are (missing: {missing or 'none'})")


@dataclass(frozen=True)
class SkinModEntry:
    """A saved skin mod as a champion's listing shows it."""

    champion_id: Optional[int]
    skin_id: int  # the skins folder holding it
    mod_name: str
    path: Path  # its identity (SavedMod.path): no file once LTK Manager holds the mod
    updated_at: float
    description: Optional[str] = None
    target_skin_ids: tuple[int, ...] = ()
    display_name: Optional[str] = None
    ltk_id: Optional[str] = None
    missing: bool = False  # the last sync found LTK Manager's entry gone
    stored: Optional[Path] = None  # Rose's copy, if there is one
    facts: Optional[ModFacts] = None

    @property
    def pending(self) -> bool:
        """Still Rose's to move into LTK Manager (SavedMod.pending)."""
        return self.ltk_id is None and self.stored is not None


class ModStorageService:
    """Service exposing the on-disk mods hierarchy."""

    CHAMPION_LIST_CACHE_SECONDS = 0.75
    # MAX_PATH is 260 including the terminating null character, so keep the
    # visible path at 259 characters or fewer for legacy Windows APIs.
    MAX_WINDOWS_PATH_LENGTH = 259
    # A stored mod's name is also its file name in the injection and LTK
    # Manager's staging folders, which sit about as deep as the mods storage
    MAX_MOD_NAME_LENGTH = 120
    # Keep temporary paths short on Windows: a .modpkg (or an archive without
    # META/info.json) is unpacked there before it is packed into a .fantome.
    IMPORT_TEMP_PREFIX = ".rose-import-"
    # A folder being packed into an archive (convert_folder_mod)
    CONVERT_TEMP_PREFIX = ".rose-convert-"
    # How Rose stores a mod: the archive LTK Manager installs
    ARCHIVE_SUFFIX = ".fantome"
    # Beside a stored archive, under its name
    IMAGE_SIDECAR_SUFFIXES = (".png", ".webp")
    DESCRIPTION_SIDECAR_SUFFIX = ".txt"
    MAX_MOD_IMAGE_BYTES = 5 * 1024 * 1024
    TARGET_METADATA = "rose_mod_targets.json"
    LEGACY_TARGET_METADATA = "rose_wad_targets.json"
    CATEGORY_METADATA = "rose_category_mods.json"

    CATEGORY_SKINS = "skins"
    CATEGORY_MAPS = "maps"
    CATEGORY_FONTS = "fonts"
    CATEGORY_ANNOUNCERS = "announcers"
    CATEGORY_UI = "ui"
    CATEGORY_VOICEOVER = "voiceover"
    CATEGORY_LOADING_SCREEN = "loading_screen"
    CATEGORY_VFX = "vfx"
    CATEGORY_SFX = "sfx"
    CATEGORY_OTHERS = "others"
    ROOT_CATEGORIES = (
        CATEGORY_SKINS,
        CATEGORY_MAPS,
        CATEGORY_FONTS,
        CATEGORY_ANNOUNCERS,
        CATEGORY_UI,
        CATEGORY_VOICEOVER,
        CATEGORY_LOADING_SCREEN,
        CATEGORY_VFX,
        CATEGORY_SFX,
        CATEGORY_OTHERS,
    )
    MOD_CATEGORIES = (
        CATEGORY_MAPS,
        CATEGORY_FONTS,
        CATEGORY_ANNOUNCERS,
        CATEGORY_UI,
        CATEGORY_VOICEOVER,
        CATEGORY_LOADING_SCREEN,
        CATEGORY_VFX,
        CATEGORY_SFX,
        CATEGORY_OTHERS,
    )

    def __init__(self, mods_root: Optional[Path] = None):
        self.mods_root = mods_root or (get_user_data_dir() / "mods")
        self._storage_lock = _STORAGE_LOCK
        self._champion_listing_cache: dict[
            int, tuple[float, tuple[SkinModEntry, ...]]
        ] = {}
        self.mods_root.mkdir(parents=True, exist_ok=True)
        self._ensure_mods_root_layout()

    @classmethod
    def _choose_archive_destination(
        cls,
        parent_dir: Path,
        base_name: str,
    ) -> tuple[str, Path]:
        """Choose a unique mod name for an archive stored in *parent_dir* and
        return it with the archive's path (<parent_dir>/<name>.fantome).

        A long name is truncated only as much as Windows' traditional
        260-character path limit needs, then the normal `` (2)`` collision
        suffixes are added. A mod stored as a folder takes its name too.
        """
        max_name_length = min(
            cls.MAX_MOD_NAME_LENGTH,
            cls.MAX_WINDOWS_PATH_LENGTH - len(str(parent_dir)) - 1 - len(cls.ARCHIVE_SUFFIX),
        )
        if max_name_length < 1:
            raise ValueError("The mods folder's path is too long for Windows")

        original_name = base_name
        suffix_number = 1
        while True:
            suffix = "" if suffix_number == 1 else f" ({suffix_number})"
            available_name_length = max_name_length - len(suffix)
            if available_name_length < 1:
                raise ValueError(
                    "Unable to create a unique Windows-safe name for "
                    "the selected mod"
                )

            candidate_base = base_name[:available_name_length].rstrip(" .")
            if not candidate_base:
                raise ValueError(
                    "The selected mod archive has no usable Windows-safe name"
                )
            mod_name = f"{candidate_base}{suffix}"
            archive = parent_dir / f"{mod_name}{cls.ARCHIVE_SUFFIX}"
            if not any(
                path.exists() or path.is_symlink()
                for path in (archive, parent_dir / mod_name)
            ):
                if mod_name != original_name:
                    log.warning(
                        "[MODS] Shortened mod name for Windows path limit: '%s' -> '%s'",
                        original_name,
                        mod_name,
                    )
                return mod_name, archive
            suffix_number += 1

    # -- stored archives -----------------------------------------------------
    def _store_archive(self, source: Path, parent_dir: Path, base_name: str) -> tuple[str, Path]:
        """Store the mod archive *source* in *parent_dir* as the .fantome LTK
        Manager installs; return its mod name and path."""
        mod_name, target = self._choose_archive_destination(parent_dir, base_name)
        temporary = parent_dir / f"{self.IMPORT_TEMP_PREFIX}{uuid.uuid4().hex}.tmp"
        try:
            self._write_stored_archive(source, temporary, mod_name)
            temporary.replace(target)
        except Exception:
            safe_remove_entry(temporary)
            raise
        self._write_image_sidecar(target)
        return mod_name, target

    def _write_stored_archive(self, source: Path, dest: Path, mod_name: str) -> None:
        """Write at *dest* the .fantome stored for the mod archive *source*.

        A .fantome or .zip that names its mod (META/info.json) is copied as
        it is, after the checks an extraction makes. A .modpkg, or an archive
        without META/info.json, is unpacked and packed into a .fantome, as an
        injection did before Rose kept archives. So is an archive holding a
        packed WAD deflated: LTK Manager stores its packed WADs, and rewrote
        a deflated one whole at every install (ltk_fantome's normalize), here
        once.
        """
        if source.suffix.lower() == MODPKG_SUFFIX:
            self._repack(source, dest, mod_name, metadata=False)
            return
        names = check_mod_archive(source)
        if not names:
            raise ValueError("The selected mod archive contains no files")
        has_info = any(name.replace("\\", "/").lstrip("/").casefold() == _INFO_KEY for name in names)
        with zipfile.ZipFile(source) as archive:
            deflated_wads = [
                info.filename for info in archive.infolist()
                if is_packed_wad(info.filename) and info.compress_type != zipfile.ZIP_STORED
            ]
        if has_info and not deflated_wads:
            shutil.copyfile(source, dest)
            return
        if deflated_wads:
            log.info(f"[MODS] Storing the {len(deflated_wads)} packed WAD(s) of {source.name} uncompressed, "
                     "as LTK Manager keeps them")
        self._repack(source, dest, mod_name, metadata=not has_info)

    def _repack(self, source: Path, dest: Path, mod_name: str, metadata: bool) -> None:
        with tempfile.TemporaryDirectory(
            prefix=self.IMPORT_TEMP_PREFIX, dir=str(dest.parent), ignore_cleanup_errors=True,
        ) as unpacked:
            unpacked_dir = Path(unpacked)
            extract_mod_archive(source, unpacked_dir)
            if not any(unpacked_dir.iterdir()):
                raise ValueError("The selected mod archive contains no files")
            write_fantome_zip(unpacked_dir, dest, metadata=metadata, name=mod_name)

    # Larger previews are not copied out of an archive (a broken or odd mod)
    MAX_SIDECAR_IMAGE_BYTES = 32 * 1024 * 1024

    def _write_image_sidecar(self, archive: Path) -> None:
        """Copy the archive's preview image beside it, for the mods UI."""
        try:
            with ModFiles(archive) as files:
                for member, suffix in _PREVIEW_IMAGES:
                    if not files.is_file(member):
                        continue
                    data = files.read(member)
                    if 0 < len(data) <= self.MAX_SIDECAR_IMAGE_BYTES:
                        with atomic_write(archive.with_suffix(suffix), "wb", durable=False) as handle:
                            handle.write(data)
                    return
        except (OSError, zipfile.BadZipFile) as exc:
            log.debug(f"[MODS] No preview image for {archive.name}: {exc}")

    @classmethod
    def sidecar_paths(cls, stored: Path) -> list[Path]:
        """The files beside a stored archive that belong to it (preview image,
        description); none for a folder, which holds its own."""
        if stored.is_dir():
            return []
        return [
            stored.with_suffix(suffix)
            for suffix in (*cls.IMAGE_SIDECAR_SUFFIXES, cls.DESCRIPTION_SIDECAR_SUFFIX)
        ]

    @classmethod
    def _remove_stored_mod(cls, stored: Path) -> None:
        """Delete a stored mod, folder or archive, with what sits beside it."""
        sidecars = cls.sidecar_paths(stored)
        safe_remove_entry(stored)
        for sidecar in sidecars:
            safe_remove_entry(sidecar)

    # -- saved mods, by their manifest entries (injection.mods.manifest) -------
    def saved_mods(self, kind: Optional[str] = None) -> List[SavedMod]:
        """Every saved mod (of *kind*: "skins" or a category), whether LTK
        Manager holds it or Rose still does."""
        return saved_manifest.iter_saved_mods(self.mods_root, kind)

    def saved_mod(self, relative_path: str) -> Optional[SavedMod]:
        """The saved mod known as *relative_path* (manifest.find_saved_mod)."""
        return saved_manifest.find_saved_mod(self.mods_root, relative_path)

    def pending_mods(self) -> List[SavedMod]:
        """The saved mods Rose still has to move into LTK Manager."""
        return saved_manifest.pending_mods(self.mods_root)

    def ltk_ids(self) -> set[str]:
        """Every LTK Manager entry Rose added for a saved mod (manifest.manifest_ltk_ids)."""
        return saved_manifest.manifest_ltk_ids(self.mods_root)

    def attach_ltk_entry(
        self,
        relative_path: str,
        ltk_id: str,
        facts: Optional[ModFacts] = None,
        stamp: Optional[list] = None,
    ) -> bool:
        """Record that LTK Manager holds a saved mod as its entry *ltk_id*.

        *facts* replace the entry's (None keeps those it has); *stamp* is LTK
        Manager's archive they were read from (None: the next sync reads them
        again from it). The mod's date is taken from Rose's copy now: once the
        copy is gone the listing has no file to read it from. False when the
        mod is not listed or its manifest cannot be read.
        """
        if not is_ltk_id(ltk_id):
            raise ValueError(f"Not an LTK Manager library id: {ltk_id!r}")
        fields: dict = {"ltkId": ltk_id, "missing": None, "ltkStamp": list(stamp) if stamp else None}
        if facts is not None:
            fields.update(facts.to_manifest())
        with self._storage_lock:
            mod = self.saved_mod(relative_path)
            if mod is not None and mod.stored is not None and "updatedAt" not in mod.metadata:
                try:
                    fields["updatedAt"] = mod.stored.stat().st_mtime
                except OSError:
                    pass
            attached = saved_manifest.update_saved_mod(self.mods_root, relative_path, **fields)
            self._champion_listing_cache.clear()
        return attached

    def drop_stored_copy(self, relative_path: str) -> bool:
        """Delete Rose's copy (archive or folder) of a saved mod LTK Manager
        holds now. Its preview image and description stay beside the manifest,
        under its name (a folder's own are copied out first). False when the
        mod has no ltkId or no copy, or the copy could not be deleted."""
        with self._storage_lock:
            mod = self.saved_mod(relative_path)
            if mod is None or not mod.ltk_id or mod.stored is None:
                return False
            stored = mod.stored
            if stored.is_dir() and not is_junction(stored):
                try:
                    self._keep_folder_sidecars(mod)
                except OSError as exc:
                    log.warning(f"[MODS] Kept {stored.name}: its image or description could not be copied ({exc})")
                    return False
            safe_remove_entry(stored)
            self._champion_listing_cache.clear()
            if stored.exists() or stored.is_symlink():
                log.warning(f"[MODS] Could not delete Rose's copy of {mod.name}: it is in use")
                return False
        log.info(f"[MODS] Deleted Rose's copy of {mod.name}: LTK Manager holds it")
        return True

    def _keep_folder_sidecars(self, mod: SavedMod) -> None:
        """Copy a mod folder's preview image and description beside it, as an
        archive keeps them: the folder is about to go."""
        folder = mod.stored
        if not any(mod.sidecar(suffix).exists() for suffix in self.IMAGE_SIDECAR_SUFFIXES):
            for member, suffix in _PREVIEW_IMAGES:
                image = folder.joinpath(*member.split("/"))
                if image.is_file():
                    shutil.copyfile(image, mod.sidecar(suffix))
                    break
        description = folder / "description.txt"
        sidecar = mod.sidecar(self.DESCRIPTION_SIDECAR_SUFFIX)
        if description.is_file() and not sidecar.exists():
            shutil.copyfile(description, sidecar)

    # -- mods stored as folders ------------------------------------------------
    def folder_mods(self) -> List[Path]:
        """The mods stored as folders, before Rose kept archives."""
        parents = []
        try:
            parents.extend(child for child in self.skins_dir.iterdir() if child.is_dir())
        except OSError:
            pass
        parents.extend(self.mods_root / category for category in self.MOD_CATEGORIES)
        folders = []
        for parent in parents:
            self._recover_conversions(parent)
            try:
                entries = sorted(parent.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                continue
            folders.extend(
                entry for entry in entries
                if not entry.name.startswith(".") and entry.is_dir() and not is_junction(entry)
            )
        return folders

    def _recover_conversions(self, parent: Path) -> None:
        """Finish or undo a conversion Rose was stopped in the middle of, and
        remove the archive an import stopped in the middle of was writing
        (Rose starts before any import)."""
        try:
            leftovers = [
                entry for entry in parent.iterdir()
                if entry.name.startswith((self.CONVERT_TEMP_PREFIX, self.IMPORT_TEMP_PREFIX))
            ]
        except OSError:
            return
        for entry in leftovers:
            if entry.name.endswith(".tmp") and entry.is_file():
                safe_remove_entry(entry)
            elif entry.name.startswith(self.IMPORT_TEMP_PREFIX):
                continue  # a folder repair's copy (OverlayManager._take_repaired_archive)
            elif entry.name.endswith(".old") and entry.is_dir():
                name = entry.name[len(self.CONVERT_TEMP_PREFIX):-len(".old")]
                original = parent / name
                if (parent / f"{name}{self.ARCHIVE_SUFFIX}").is_file():
                    safe_remove_entry(entry)  # the archive replaced it
                elif not original.exists():
                    try:
                        entry.rename(original)  # stopped before the archive was in place
                    except OSError as exc:
                        log.warning(f"[MODS] Could not restore the mod folder {name}: {exc}")

    def convert_folder_mod(self, folder: Path) -> Optional[Path]:
        """Pack a mod stored as a folder into the archive Rose stores now, and
        return it (None when an archive already has its name).

        The archive holds the folder's files as they are (the same content
        hash for a friend's copy, see party.discovery.custom_mods); its
        preview image and description are copied beside it. The folder is
        renamed out of the way before the archive takes its place, so a Rose
        stopped in the middle finds one or the other (_recover_conversions).
        """
        archive = folder.with_name(f"{folder.name}{self.ARCHIVE_SUFFIX}")
        if archive.exists():
            log.warning(f"[MODS] {folder.name} stays a folder: {archive.name} already exists")
            return None
        # Raises for a folder Rose cannot read: never taken for an empty one
        expected = _folder_file_sizes(folder)
        if not expected:
            log.info(f"[MODS] {folder.name} holds no files: left as it is")
            return None
        temporary = folder.with_name(f"{self.CONVERT_TEMP_PREFIX}{folder.name}.tmp")
        previous = folder.with_name(f"{self.CONVERT_TEMP_PREFIX}{folder.name}.old")
        has_info = "meta/info.json" in {relative.casefold() for relative in expected}
        try:
            write_fantome_zip(folder, temporary, metadata=not has_info)
            _check_packed(temporary, expected, added_metadata=not has_info)
        except Exception:
            safe_remove_entry(temporary)
            raise
        sidecars = []
        try:
            for member, suffix in _PREVIEW_IMAGES:
                image = folder.joinpath(*member.split("/"))
                if image.is_file():
                    sidecars.append(archive.with_suffix(suffix))
                    shutil.copyfile(image, sidecars[-1])
                    break
            description = folder / "description.txt"
            if description.is_file():
                sidecars.append(archive.with_suffix(self.DESCRIPTION_SIDECAR_SUFFIX))
                shutil.copyfile(description, sidecars[-1])
            folder.rename(previous)
        except OSError:
            for path in (temporary, *sidecars):
                safe_remove_entry(path)
            raise
        try:
            temporary.replace(archive)
        except OSError:
            previous.rename(folder)
            for path in (temporary, *sidecars):
                safe_remove_entry(path)
            raise
        safe_remove_entry(previous)
        return archive

    def _ensure_mods_root_layout(self) -> None:
        """
        Ensure `%LOCALAPPDATA%\\Rose\\mods` contains only the expected root category folders.

        - Creates missing category folders.
        - Removes *extra* root-level folders not in our category list.
          (Does not touch files and does not touch subfolders within valid categories.)
        """
        # Create expected root category folders
        for category in self.ROOT_CATEGORIES:
            (self.mods_root / category).mkdir(parents=True, exist_ok=True)

        # Remove unknown root-level directories
        try:
            for entry in self.mods_root.iterdir():
                if not entry.is_dir():
                    continue
                if entry.name in self.ROOT_CATEGORIES:
                    continue
                try:
                    shutil.rmtree(entry, ignore_errors=True)
                    log.info("[ModStorage] Removed unknown mods category folder: %s", entry)
                except Exception as exc:  # noqa: BLE001
                    log.warning("[ModStorage] Failed to remove unknown mods folder %s: %s", entry, exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("[ModStorage] Failed to scan mods root %s: %s", self.mods_root, exc)

    @property
    def skins_dir(self) -> Path:
        return self.mods_root / self.CATEGORY_SKINS

    def get_skin_dir(self, skin_id: int | str) -> Path:
        return self.skins_dir / str(skin_id)

    def get_champion_dir(self, champion_id: int | str) -> Path:
        """Return the single skin-mod directory for a champion."""
        champion_id_int = self._to_int(champion_id)
        if champion_id_int is None:
            raise ValueError(f"Invalid champion ID: {champion_id}")
        return self.get_skin_dir(champion_id_int * 1000)

    @staticmethod
    def _normalize_target_ids(value: object) -> tuple[int, ...]:
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

    @staticmethod
    def _load_manifest(manifest_path: Path) -> Optional[dict]:
        """Read a mod manifest: {} when there is none, None when it exists but cannot be read.

        An unreadable manifest used to look empty, so the mods it lists vanished
        from the UI with no trace, and importing a mod rewrote it with that mod alone.
        """
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, TypeError, ValueError) as e:
            if str(manifest_path) not in _reported_manifests:
                _reported_manifests.add(str(manifest_path))
                log.warning(f"[MODS] Could not read mod manifest {manifest_path}: {e}")
            return None
        return payload if isinstance(payload, dict) else {}

    def _load_target_manifest(
        self,
        champion_id: int,
        *,
        require_readable: bool = False,
    ) -> tuple[tuple[int, ...], dict[str, dict]]:
        champion_dir = self.get_champion_dir(champion_id)
        payload = None
        for metadata_name in (self.TARGET_METADATA, self.LEGACY_TARGET_METADATA):
            manifest_path = champion_dir / metadata_name
            payload = self._load_manifest(manifest_path)
            if payload is None and require_readable:
                raise ValueError("The saved skin mod targets could not be read, so they were left unchanged")
            if payload:
                break
        if not isinstance(payload, dict):
            return (), {}

        default_targets = self._normalize_target_ids(
            payload.get("targets") or payload.get("skinIds")
        )
        raw_mods = payload.get("mods") or {}
        mod_targets: dict[str, dict] = {}
        if isinstance(raw_mods, dict):
            for mod_name, raw_targets in raw_mods.items():
                targets = self._normalize_target_ids(raw_targets)
                if targets:
                    if isinstance(raw_targets, dict):
                        metadata = dict(raw_targets)
                    else:
                        metadata = {}
                    metadata["targets"] = list(targets)
                    mod_targets[str(mod_name)] = metadata
        return default_targets, mod_targets

    @staticmethod
    def _hash_mod_folder(mod_path: Path) -> tuple[str, dict[str, str]]:
        """Return a rename-stable hash of a mod (folder or archive: the same
        for an archive and the folder it unpacks to) and hashes for its WADs."""
        folder_hash = hashlib.sha256()
        wad_hashes: dict[str, str] = {}
        try:
            files = ModFiles(mod_path)
        except (OSError, zipfile.BadZipFile):
            return folder_hash.hexdigest(), wad_hashes

        with files:
            for relative_path in sorted(files.files_under(), key=str.casefold):
                if relative_path.casefold() == "meta/image.png":
                    continue
                try:
                    file_hash = hashlib.sha256()
                    with files.open(relative_path) as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            file_hash.update(chunk)
                    file_digest = file_hash.digest()
                    folder_hash.update(relative_path.encode("utf-8"))
                    folder_hash.update(b"\0")
                    folder_hash.update(file_digest)
                    folder_hash.update(b"\0")
                    if relative_path.casefold().endswith((".wad", ".wad.client")):
                        wad_hashes[relative_path] = file_hash.hexdigest()
                except (OSError, ValueError, zipfile.BadZipFile):
                    continue
        return folder_hash.hexdigest(), wad_hashes

    @staticmethod
    def _extract_display_name(metadata: Optional[dict]) -> Optional[str]:
        if not isinstance(metadata, dict):
            return None
        raw = metadata.get("displayName")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

    def set_champion_target_ids(
        self,
        champion_id: int | str,
        skin_ids: object,
        mod_name: Optional[str] = None,
        mod_path: Optional[Path] = None,
    ) -> Path:
        """Persist the user's manual targets for a champion or named mod."""
        champion_id_int = self._to_int(champion_id)
        if champion_id_int is None or champion_id_int <= 0:
            raise ValueError(f"Invalid champion ID: {champion_id}")

        targets = self._normalize_target_ids(skin_ids)
        if not targets:
            raise ValueError("At least one target skin ID is required")

        champion_dir = self.get_champion_dir(champion_id_int)
        champion_dir.mkdir(parents=True, exist_ok=True)
        default_targets, mod_targets = self._load_target_manifest(champion_id_int, require_readable=True)
        if mod_name:
            if mod_path is not None:
                folder_hash, wad_hashes = self._hash_mod_folder(Path(mod_path))
                existing_display_name = None
                for key, metadata in list(mod_targets.items()):
                    if key == folder_hash or (
                        isinstance(metadata, dict)
                        and metadata.get("folderHash") == folder_hash
                    ):
                        if isinstance(metadata, dict):
                            existing_display_name = self._extract_display_name(metadata)
                        mod_targets.pop(key, None)
                entry = {
                    "name": str(mod_name),
                    "folderHash": folder_hash,
                    "wadHashes": wad_hashes,
                    "targets": list(targets),
                }
                if existing_display_name:
                    entry["displayName"] = existing_display_name
                mod_targets[folder_hash] = entry
            else:
                mod_targets[str(mod_name)] = {
                    "name": str(mod_name),
                    "targets": list(targets),
                }
        else:
            default_targets = targets

        payload = {
            "version": 1,
            "championId": champion_id_int,
            "targets": list(default_targets),
            "mods": dict(sorted(mod_targets.items())),
        }
        manifest_path = champion_dir / self.TARGET_METADATA
        temporary_path = manifest_path.with_name(f".{manifest_path.name}.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(manifest_path)
        self._champion_listing_cache.pop(champion_id_int, None)
        return manifest_path

    MAX_DISPLAY_NAME_LENGTH = 100

    def set_champion_mod_display_name(
        self,
        champion_id: int | str,
        display_name: str,
        mod_name: Optional[str] = None,
        relative_path: Optional[str] = None,
    ) -> str:
        """Persist a user-facing display alias for an imported skin mod.

        The mod's on-disk folder is left untouched; only the manifest entry
        gains a ``displayName`` field, so target associations and any saved
        selections that reference the folder path stay intact.
        """
        champion_id_int = self._to_int(champion_id)
        if champion_id_int is None or champion_id_int <= 0:
            raise ValueError(f"Invalid champion ID: {champion_id}")

        clean_name = str(display_name or "").strip()[: self.MAX_DISPLAY_NAME_LENGTH]
        if not clean_name:
            raise ValueError("Display name cannot be empty")

        with self._storage_lock:
            champion_dir = self.get_champion_dir(champion_id_int)
            manifest_path = champion_dir / self.TARGET_METADATA
            payload = self._load_manifest(manifest_path)
            if not payload:
                raise ValueError("No mod manifest found for this champion")

            raw_mods = payload.get("mods")
            mods = dict(raw_mods) if isinstance(raw_mods, dict) else {}
            if not mods:
                raise ValueError("No mods registered for this champion")

            # Match by folder/manifest name only. Hashing WADs here ran on the
            # WebSocket event loop and could stall past ping_timeout, so the
            # UI never received champion-mod-renamed and stayed on "Saving...".
            name_candidates = []
            if mod_name:
                name_candidates.append(str(mod_name))
            target_path = self._resolve_mod_path(champion_dir, relative_path)
            if target_path is not None:
                name_candidates.append(target_path.name)
            name_candidates = list(dict.fromkeys(name_candidates))

            matched_key = None
            for candidate_name in name_candidates:
                for key, metadata in mods.items():
                    stored_name = metadata.get("name") if isinstance(metadata, dict) else None
                    if key == candidate_name or str(stored_name or "") == candidate_name:
                        matched_key = key
                        break
                if matched_key is not None:
                    break
            if matched_key is None:
                raise ValueError("Mod not found in manifest")

            entry = mods[matched_key]
            if not isinstance(entry, dict):
                entry = {"name": str(mod_name or matched_key)}
            entry["displayName"] = clean_name
            mods[matched_key] = entry

            payload["mods"] = dict(sorted(mods.items()))
            payload.setdefault("version", 1)
            payload.setdefault("championId", champion_id_int)

            temporary_path = manifest_path.with_name(f".{manifest_path.name}.tmp")
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(manifest_path)
            self._champion_listing_cache.pop(champion_id_int, None)
            return clean_name

    def set_category_mod_display_name(
        self,
        category: str,
        mod_name: str,
        display_name: str,
    ) -> str:
        """Persist a user-facing display alias for a category mod."""
        if category not in self.MOD_CATEGORIES:
            raise ValueError(f"Unsupported mod category: {category}")
        if not mod_name:
            raise ValueError("Mod name is required")

        clean_name = str(display_name or "").strip()[: self.MAX_DISPLAY_NAME_LENGTH]
        if not clean_name:
            raise ValueError("Display name cannot be empty")

        with self._storage_lock:
            category_dir = self.mods_root / category
            manifest_path = category_dir / self.CATEGORY_METADATA
            payload = self._load_manifest(manifest_path) or {}

            raw_mods = payload.get("mods")
            mods = dict(raw_mods) if isinstance(raw_mods, dict) else {}

            matched_key = None
            if mod_name in mods:
                matched_key = mod_name
            else:
                for key, metadata in mods.items():
                    stored = metadata.get("path") if isinstance(metadata, dict) else None
                    if str(stored or key) == str(mod_name):
                        matched_key = key
                        break
            if matched_key is None:
                raise ValueError("Mod not found in manifest")

            entry = mods[matched_key]
            if not isinstance(entry, dict):
                entry = {"name": matched_key, "path": matched_key}
            entry["displayName"] = clean_name
            mods[matched_key] = entry

            payload.update({
                "version": 1,
                "category": category,
                "mods": dict(sorted(mods.items())),
            })
            temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.tmp")
            temporary_manifest.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_manifest.replace(manifest_path)
            return clean_name

    def import_mod_file(
        self,
        champion_id: int | str,
        source_path: str | Path,
        skin_ids: object,
    ) -> tuple[Path, Path, str]:
        """Store one user-selected mod archive in its champion folder, as the
        .fantome LTK Manager installs (_store_archive)."""
        source = Path(source_path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"Mod file not found: {source}")
        if source.suffix.lower() not in MOD_ARCHIVE_SUFFIXES:
            raise ValueError("Only .zip, .fantome and .modpkg mod files are supported")

        champion_id_int = self._to_int(champion_id)
        if champion_id_int is None or champion_id_int <= 0:
            raise ValueError(f"Invalid champion ID: {champion_id}")

        champion_dir = self.get_champion_dir(champion_id_int)
        champion_dir.mkdir(parents=True, exist_ok=True)
        base_name = source.stem.strip()
        if not base_name or base_name in {".", ".."}:
            raise ValueError("The selected mod file has no usable name")

        mod_name, target = self._store_archive(source, champion_dir, base_name)
        try:
            manifest_path = self.set_champion_target_ids(
                champion_id_int,
                skin_ids,
                mod_name=mod_name,
                mod_path=target,
            )
            return target, manifest_path, mod_name
        except Exception:
            self._remove_stored_mod(target)
            raise

    def _resolve_mod_path(self, base_dir: Path, relative_path: object) -> Optional[Path]:
        """Resolve a user-supplied relative path, guarding against traversal."""
        if not relative_path:
            return None
        try:
            candidate = (self.mods_root / str(relative_path)).resolve()
            base_resolved = base_dir.resolve()
        except OSError:
            return None
        if base_resolved != candidate and base_resolved not in candidate.parents:
            return None
        return candidate

    @staticmethod
    def _is_unsafe_mod_identity(value: object) -> bool:
        name = str(value or "").strip().replace("\\", "/")
        if not name or name in {".", ".."}:
            return True
        return any(part in {".", ".."} for part in name.split("/"))

    def _delete_saved_mod(self, mod: SavedMod) -> bool:
        """Delete a saved mod: its manifest entry (LTK Manager's entry, when
        it holds the mod, goes at the next session start), Rose's copy, and
        the image and description beside the manifest."""
        if not saved_manifest.remove_saved_mod(self.mods_root, mod):
            return False
        if mod.stored is not None:
            safe_remove_entry(mod.stored)
        for suffix in (*self.IMAGE_SIDECAR_SUFFIXES, self.DESCRIPTION_SIDECAR_SUFFIX):
            sidecar = mod.sidecar(suffix)
            if sidecar.is_file():  # a folder of that name is another mod ("Example.txt")
                safe_remove_entry(sidecar)
        return True

    def delete_champion_mod(
        self,
        champion_id: int | str,
        mod_name: Optional[str] = None,
        relative_path: Optional[str] = None,
    ) -> bool:
        """Delete one saved mod of a champion, known by its identity
        (*relative_path*) or by its name in the champion's folder."""
        champion_id_int = self._to_int(champion_id)
        if champion_id_int is None or champion_id_int <= 0:
            raise ValueError(f"Invalid champion ID: {champion_id}")
        if not relative_path and not mod_name:
            return False
        identity = relative_path or f"{self.CATEGORY_SKINS}/{champion_id_int * 1000}/{mod_name}"
        with self._storage_lock:
            mod = self.saved_mod(identity)
            if mod is None or mod.storage_id is None or get_champion_id_from_skin_id(mod.storage_id) != champion_id_int:
                return False
            deleted = self._delete_saved_mod(mod)
            self._champion_listing_cache.pop(champion_id_int, None)
        return deleted

    def set_champion_mod_image(
        self,
        champion_id: int | str,
        relative_path: str,
        image_data: bytes | Path,
    ) -> Path:
        """Atomically add or replace a skin mod's preview image: a mod stored
        as a folder holds it (META/image.png), any other has it beside the
        manifest under its name, as its archive (LTK Manager's, or Rose's
        while it is pending) stays as LTK Manager installs it."""
        champion_id_int = self._to_int(champion_id)
        if champion_id_int is None or champion_id_int <= 0:
            raise ValueError(f"Invalid champion ID: {champion_id}")
        if not isinstance(relative_path, str) or self._is_unsafe_mod_identity(relative_path):
            raise ValueError("Invalid skin mod path")
        if isinstance(image_data, Path):
            try:
                image_size = image_data.stat().st_size
                if image_size <= 0 or image_size > self.MAX_MOD_IMAGE_BYTES:
                    raise ValueError("The image must be between 1 byte and 5 MB")
                with image_data.open("rb") as stream:
                    image_data = stream.read(self.MAX_MOD_IMAGE_BYTES + 1)
            except OSError as exc:
                raise ValueError(f"Could not read the selected image: {exc}") from exc
        if not isinstance(image_data, bytes) or not image_data:
            raise ValueError("A PNG image is required")
        if len(image_data) > self.MAX_MOD_IMAGE_BYTES:
            raise ValueError("The image must be 5 MB or smaller")
        if not image_data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("The selected file is not a PNG image")

        with self._storage_lock:
            mod = self.saved_mod(relative_path)
            if mod is None or mod.storage_id is None:
                raise ValueError("Skin mod folder was not found")
            if get_champion_id_from_skin_id(mod.storage_id) != champion_id_int:
                raise ValueError("Skin mod does not belong to the selected champion")

            target = mod.stored
            if target is None or not target.is_dir():
                image_path = mod.sidecar(".png")
                with atomic_write(image_path, "wb", durable=False) as handle:
                    handle.write(image_data)
                safe_remove_entry(mod.sidecar(".webp"))
                self._champion_listing_cache.pop(champion_id_int, None)
                return image_path

            meta_dir = target / "META"
            meta_dir.mkdir(exist_ok=True)
            resolved_meta = meta_dir.resolve()
            resolved_target = target.resolve()
            if resolved_meta.parent != resolved_target:
                raise ValueError("Skin mod META folder must stay inside the mod folder")

            image_path = meta_dir / "image.png"
            with atomic_write(image_path, "wb", durable=False) as handle:
                handle.write(image_data)

            self._champion_listing_cache.pop(champion_id_int, None)
            return image_path

    def delete_category_mod(self, category: str, mod_name: str) -> bool:
        """Delete one saved mod of a category, known by its name."""
        if category not in self.MOD_CATEGORIES:
            raise ValueError(f"Unsupported mod category: {category}")
        if not mod_name:
            return False
        with self._storage_lock:
            mod = self.saved_mod(f"{category}/{mod_name}")
            return mod is not None and self._delete_saved_mod(mod)

    def import_category_mod_file(
        self,
        category: str,
        source_path: str | Path,
    ) -> tuple[Path, str]:
        """Store one user-selected archive in a registered category folder, as
        the .fantome LTK Manager installs (_store_archive)."""
        if category not in self.MOD_CATEGORIES:
            raise ValueError(f"Unsupported mod category: {category}")

        source = Path(source_path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"Mod file not found: {source}")
        if source.suffix.lower() not in MOD_ARCHIVE_SUFFIXES:
            raise ValueError("Only .zip, .fantome and .modpkg mod files are supported")

        category_dir = self.mods_root / category
        category_dir.mkdir(parents=True, exist_ok=True)
        base_name = source.stem.strip()
        if not base_name or base_name in {".", ".."}:
            raise ValueError("The selected mod archive has no usable name")

        mod_name, target = self._store_archive(source, category_dir, base_name)
        try:
            manifest_path = category_dir / self.CATEGORY_METADATA
            payload = self._load_manifest(manifest_path)
            if payload is None:
                # Rewriting it would drop every other mod registered in this category
                raise ValueError("The list of mods in this category could not be read, so it was left unchanged")
            raw_mods = payload.get("mods")
            mods = dict(raw_mods) if isinstance(raw_mods, dict) else {}
            mods[mod_name] = {"name": mod_name, "path": mod_name}
            payload.update({
                "version": 1,
                "category": category,
                "mods": dict(sorted(mods.items())),
            })
            temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.tmp")
            temporary_manifest.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_manifest.replace(manifest_path)
            return target, mod_name
        except Exception:
            self._remove_stored_mod(target)
            raise

    def list_mods_for_skin(self, skin_id: int | str) -> List[SkinModEntry]:
        """Return mods for a skin, including champion-level target metadata."""
        skin_id_int = self._to_int(skin_id)
        if skin_id_int is None:
            return []
        champion_id = get_champion_id_from_skin_id(skin_id_int)
        if champion_id is None:
            return []
        return [
            entry
            for entry in self.list_mods_for_champion(champion_id)
            if skin_id_int in entry.target_skin_ids
        ]

    def list_mods_for_champion(self, champion_id: int | str) -> List[SkinModEntry]:
        """The skin mods saved for a champion (its folder, and the per-skin
        folders of older Roses), as their manifests list them: no mod file is
        opened, so a mod LTK Manager holds is listed like one Rose holds.
        Kept a moment: hovering skins lists them again and again."""
        champion_id_int = self._to_int(champion_id)
        if champion_id_int is None or champion_id_int <= 0:
            return []

        cached = self._champion_listing_cache.get(champion_id_int)
        if cached is not None:
            cached_at, cached_entries = cached
            if time.monotonic() - cached_at < self.CHAMPION_LIST_CACHE_SECONDS:
                return list(cached_entries)

        entries = tuple(
            SkinModEntry(
                champion_id=champion_id_int,
                skin_id=mod.storage_id,
                mod_name=mod.name,
                path=mod.path(self.mods_root),
                updated_at=mod.updated_at,
                description=self._read_mod_description(mod),
                target_skin_ids=mod.target_skin_ids,
                display_name=mod.display_name,
                ltk_id=mod.ltk_id,
                missing=mod.missing,
                stored=mod.stored,
                facts=mod.facts,
            )
            for mod in saved_manifest.iter_saved_mods(self.mods_root, self.CATEGORY_SKINS, champion_id=champion_id_int)
        )
        self._champion_listing_cache[champion_id_int] = (time.monotonic(), entries)
        return list(entries)

    def has_mods_for_skin(self, skin_id: int | str) -> bool:
        return bool(self.list_mods_for_skin(skin_id))

    def categories_with_mods(self) -> List[str]:
        """Root categories holding at least one saved mod, in menu order (a
        missing one counts: it is listed so it can be deleted)."""
        kinds = {mod.kind for mod in self.saved_mods()}
        return [category for category in self.ROOT_CATEGORIES if category in kinds]

    def list_mods_for_category(self, category: str) -> List[dict]:
        """The mods saved in a category, as its manifest lists them (no mod
        file is opened): id and path (the mod's identity), name, displayName,
        updatedAt, description, and where the mod is: ltkId, missing (LTK
        Manager lost it: listed so it can be deleted, never selected),
        pending (Rose still holds it) and facts (ModFacts.to_manifest(), None
        when unknown)."""
        if category not in self.MOD_CATEGORIES:
            return []
        with self._storage_lock:
            return [
                {
                    "id": mod.relative_path,
                    "name": mod.name,
                    "displayName": mod.display_name,
                    "path": mod.relative_path,
                    "updatedAt": mod.updated_at,
                    "description": self._read_mod_description(mod),
                    "ltkId": mod.ltk_id,
                    "missing": mod.missing,
                    "pending": mod.pending,
                    "facts": mod.facts.to_manifest() if mod.facts else None,
                }
                for mod in saved_manifest.iter_saved_mods(self.mods_root, category)
            ]

    @staticmethod
    def _to_int(value: int | str) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _read_mod_description(cls, mod: SavedMod) -> Optional[str]:
        """A saved mod's description: a mod stored as a folder holds it, any
        other has it beside the manifest, under its name."""
        if mod.stored is not None and mod.stored.is_dir():
            description_file = mod.stored / "description.txt"
        else:
            description_file = mod.sidecar(cls.DESCRIPTION_SIDECAR_SUFFIX)
        try:
            return description_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except Exception as exc:
            log.debug(f"[ModStorage] Unable to read descriptor {description_file}: {exc}")
            return None
