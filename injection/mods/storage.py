#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mod storage service
Handles mods organized by category: skins, maps, fonts, announcers, others
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional

from utils.core.junction import safe_remove_entry
from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir
from utils.core.safe_extract import safe_extractall
from utils.core.utilities import get_champion_id_from_skin_id

log = get_logger()
_STORAGE_LOCK = threading.RLock()


@dataclass(frozen=True)
class SkinModEntry:
    """Metadata for a mod inside a champion-level skin directory."""

    champion_id: Optional[int]
    skin_id: int
    mod_name: str
    path: Path
    updated_at: float
    description: Optional[str] = None
    target_skin_ids: tuple[int, ...] = ()


class ModStorageService:
    """Service exposing the on-disk mods hierarchy."""

    CHAMPION_LIST_CACHE_SECONDS = 0.75
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

    def _load_target_manifest(
        self,
        champion_id: int,
    ) -> tuple[tuple[int, ...], dict[str, dict]]:
        champion_dir = self.get_champion_dir(champion_id)
        payload = None
        for metadata_name in (self.TARGET_METADATA, self.LEGACY_TARGET_METADATA):
            manifest_path = champion_dir / metadata_name
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
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
        """Return a rename-stable folder hash and hashes for contained WADs."""
        folder_hash = hashlib.sha256()
        wad_hashes: dict[str, str] = {}
        try:
            files = sorted(
                (path for path in mod_path.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(mod_path).as_posix().casefold(),
            )
        except OSError:
            files = []

        for file_path in files:
            try:
                relative_path = file_path.relative_to(mod_path).as_posix()
                file_hash = hashlib.sha256()
                with file_path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        file_hash.update(chunk)
                file_digest = file_hash.digest()
                folder_hash.update(relative_path.encode("utf-8"))
                folder_hash.update(b"\0")
                folder_hash.update(file_digest)
                folder_hash.update(b"\0")
                if relative_path.casefold().endswith((".wad", ".wad.client")):
                    wad_hashes[relative_path] = file_hash.hexdigest()
            except (OSError, ValueError):
                continue
        return folder_hash.hexdigest(), wad_hashes

    def _get_manifest_targets_for_mod(
        self,
        candidate: Path,
        mod_name: str,
        mod_targets: dict[str, dict],
    ) -> tuple[int, ...]:
        named_metadata = mod_targets.get(mod_name)

        # Imported mods store their stable metadata under a content hash, but
        # also retain the original folder name.  Use that cheap lookup first;
        # hashing every WAD on every hover made the champ-select button wait
        # for the entire mod tree to be read.
        if named_metadata is not None:
            return self._normalize_target_ids(named_metadata)
        for metadata in mod_targets.values():
            if (
                isinstance(metadata, dict)
                and str(metadata.get("name") or "") == str(mod_name)
            ):
                return self._normalize_target_ids(metadata)

        # Legacy manifests may not have a per-mod mapping at all.  There is
        # nothing to match in that case, so avoid an unnecessary full hash.
        if not mod_targets:
            return ()

        # Only renamed/unmatched folders need the content-based fallback.
        folder_hash, wad_hashes = self._hash_mod_folder(candidate)
        for key, metadata in mod_targets.items():
            if not isinstance(metadata, dict):
                continue
            stored_folder_hash = str(metadata.get("folderHash") or "")
            stored_wad_hashes = metadata.get("wadHashes")
            if (
                key == folder_hash
                or stored_folder_hash == folder_hash
                or (
                    wad_hashes
                    and isinstance(stored_wad_hashes, dict)
                    and stored_wad_hashes == wad_hashes
                )
            ):
                return self._normalize_target_ids(metadata)
        if named_metadata is not None:
            return self._normalize_target_ids(named_metadata)
        return ()

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
        default_targets, mod_targets = self._load_target_manifest(champion_id_int)
        if mod_name:
            if mod_path is not None:
                folder_hash, wad_hashes = self._hash_mod_folder(Path(mod_path))
                for key, metadata in list(mod_targets.items()):
                    if key == folder_hash or (
                        isinstance(metadata, dict)
                        and metadata.get("folderHash") == folder_hash
                    ):
                        mod_targets.pop(key, None)
                mod_targets[folder_hash] = {
                    "name": str(mod_name),
                    "folderHash": folder_hash,
                    "wadHashes": wad_hashes,
                    "targets": list(targets),
                }
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

    def import_mod_file(
        self,
        champion_id: int | str,
        source_path: str | Path,
        skin_ids: object,
    ) -> tuple[Path, Path, str]:
        """Extract one user-selected mod archive into its champion folder."""
        source = Path(source_path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"Mod file not found: {source}")
        if source.suffix.lower() not in {".zip", ".fantome"}:
            raise ValueError("Only .zip and .fantome mod files are supported")

        champion_id_int = self._to_int(champion_id)
        if champion_id_int is None or champion_id_int <= 0:
            raise ValueError(f"Invalid champion ID: {champion_id}")

        champion_dir = self.get_champion_dir(champion_id_int)
        champion_dir.mkdir(parents=True, exist_ok=True)
        base_name = source.stem.strip()
        if not base_name or base_name in {".", ".."}:
            raise ValueError("The selected mod file has no usable name")

        mod_name = base_name
        target_dir = champion_dir / mod_name
        suffix = 2
        while target_dir.exists() or target_dir.is_symlink():
            mod_name = f"{base_name} ({suffix})"
            target_dir = champion_dir / mod_name
            suffix += 1

        temporary_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{mod_name}.importing-",
                dir=str(champion_dir),
            )
        )
        try:
            safe_extractall(source, temporary_dir)
            if not any(temporary_dir.iterdir()):
                raise ValueError("The selected mod archive contains no files")
            temporary_dir.replace(target_dir)
            manifest_path = self.set_champion_target_ids(
                champion_id_int,
                skin_ids,
                mod_name=mod_name,
                mod_path=target_dir,
            )
            return target_dir, manifest_path, mod_name
        except Exception:
            safe_remove_entry(temporary_dir)
            raise

    def _load_category_manifest(self, category: str) -> set[str]:
        manifest_path = self.mods_root / category / self.CATEGORY_METADATA
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return set()
        if not isinstance(payload, dict):
            return set()

        raw_mods = payload.get("mods") or {}
        if not isinstance(raw_mods, dict):
            return set()

        registered = set()
        for mod_key, raw_metadata in raw_mods.items():
            metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
            mod_path = str(metadata.get("path") or mod_key).replace("\\", "/").strip("/")
            if mod_path and "/" not in mod_path:
                registered.add(mod_path.casefold())
        return registered

    def import_category_mod_file(
        self,
        category: str,
        source_path: str | Path,
    ) -> tuple[Path, str]:
        """Extract one user-selected archive into a registered category folder."""
        if category not in self.MOD_CATEGORIES:
            raise ValueError(f"Unsupported mod category: {category}")

        source = Path(source_path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"Mod file not found: {source}")
        if source.suffix.lower() not in {".zip", ".fantome"}:
            raise ValueError("Only .zip and .fantome mod files are supported")

        category_dir = self.mods_root / category
        category_dir.mkdir(parents=True, exist_ok=True)
        base_name = source.stem.strip()
        if not base_name or base_name in {".", ".."}:
            raise ValueError("The selected mod archive has no usable name")

        mod_name = base_name
        target_dir = category_dir / mod_name
        suffix = 2
        while target_dir.exists() or target_dir.is_symlink():
            mod_name = f"{base_name} ({suffix})"
            target_dir = category_dir / mod_name
            suffix += 1

        temporary_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{mod_name}.importing-",
                dir=str(category_dir),
            )
        )
        target_created = False
        try:
            safe_extractall(source, temporary_dir)
            if not any(temporary_dir.iterdir()):
                raise ValueError("The selected mod archive contains no files")
            temporary_dir.replace(target_dir)
            target_created = True

            manifest_path = category_dir / self.CATEGORY_METADATA
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
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
            return target_dir, mod_name
        except Exception:
            safe_remove_entry(temporary_dir)
            if target_created:
                safe_remove_entry(target_dir)
            raise

    def _list_mods_in_directory(
        self,
        mod_directory: Path,
        champion_id: int,
        storage_skin_id: int,
        default_targets: tuple[int, ...] = (),
        mod_targets: Optional[dict[str, tuple[int, ...]]] = None,
        require_manifest: bool = False,
    ) -> List[SkinModEntry]:
        if not mod_directory.exists() or not mod_directory.is_dir():
            return []

        entries: List[SkinModEntry] = []
        mod_targets = mod_targets or {}
        for candidate in sorted(mod_directory.iterdir(), key=lambda p: p.name.lower()):
            if candidate.name in {self.TARGET_METADATA, self.LEGACY_TARGET_METADATA}:
                continue
            if candidate.is_dir():
                mod_name = candidate.name
            elif candidate.is_file() and candidate.suffix.lower() in {".zip", ".fantome"}:
                mod_name = candidate.stem
            else:
                continue

            try:
                updated_at = candidate.stat().st_mtime
            except OSError:
                updated_at = 0.0

            target_skin_ids = self._get_manifest_targets_for_mod(
                candidate,
                mod_name,
                mod_targets,
            )
            if not target_skin_ids:
                target_skin_ids = default_targets
            if not target_skin_ids:
                if require_manifest:
                    continue
                target_skin_ids = (storage_skin_id,)
            entries.append(
                SkinModEntry(
                    champion_id=champion_id,
                    skin_id=storage_skin_id,
                    mod_name=mod_name,
                    path=candidate,
                    updated_at=updated_at,
                    description=self._read_mod_description(candidate),
                    target_skin_ids=tuple(target_skin_ids),
                )
            )
        return entries

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
        """Return mods stored once under the champion's directory."""
        champion_id_int = self._to_int(champion_id)
        if champion_id_int is None or champion_id_int <= 0:
            return []

        cached = self._champion_listing_cache.get(champion_id_int)
        if cached is not None:
            cached_at, cached_entries = cached
            if time.monotonic() - cached_at < self.CHAMPION_LIST_CACHE_SECONDS:
                return list(cached_entries)

        champion_storage_id = champion_id_int * 1000
        champion_directory = self.get_champion_dir(champion_id_int)
        default_targets, mod_targets = self._load_target_manifest(champion_id_int)
        entries = self._list_mods_in_directory(
            champion_directory,
            champion_id_int,
            champion_storage_id,
            default_targets,
            mod_targets,
            require_manifest=True,
        )

        # Keep older per-skin imports readable without creating new per-skin
        # directories for the restored manual import flow.
        try:
            legacy_directories = sorted(self.skins_dir.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            legacy_directories = []
        for child in legacy_directories:
            if not child.is_dir() or child == champion_directory:
                continue
            legacy_skin_id = self._to_int(child.name)
            if legacy_skin_id is None or get_champion_id_from_skin_id(legacy_skin_id) != champion_id_int:
                continue
            entries.extend(
                self._list_mods_in_directory(
                    child,
                    champion_id_int,
                    legacy_skin_id,
                    (legacy_skin_id,),
                    require_manifest=True,
                )
            )
        self._champion_listing_cache[champion_id_int] = (
            time.monotonic(),
            tuple(entries),
        )
        return list(entries)

    def has_mods_for_skin(self, skin_id: int | str) -> bool:
        return bool(self.list_mods_for_skin(skin_id))

    def list_mods_for_category(self, category: str) -> List[dict]:
        with self._storage_lock:
            return self._list_mods_for_category(category)

    def _list_mods_for_category(self, category: str) -> List[dict]:
        """List all mods in a category (maps, fonts, announcers, others)
        
        Args:
            category: One of CATEGORY_MAPS, CATEGORY_FONTS, CATEGORY_ANNOUNCERS, CATEGORY_OTHERS
            
        Returns:
            List of mod dictionaries with name, path, updated_at, description
        """
        if category not in self.MOD_CATEGORIES:
            return []
        
        category_dir = self.mods_root / category
        if not category_dir.exists() or not category_dir.is_dir():
            return []

        registered_mods = self._load_category_manifest(category)
        entries = []
        for candidate in sorted(category_dir.iterdir(), key=lambda p: p.name.lower()):
            if not candidate.is_dir() or candidate.name == self.CATEGORY_METADATA:
                continue
            mod_name = candidate.name
            if mod_name.casefold() not in registered_mods:
                continue
            
            try:
                updated_at = candidate.stat().st_mtime
            except OSError:
                updated_at = 0.0
            
            try:
                relative_path = candidate.relative_to(self.mods_root)
            except Exception:
                relative_path = candidate
            
            entries.append({
                "id": str(relative_path).replace("\\", "/"),
                "name": mod_name,
                "path": str(relative_path).replace("\\", "/"),
                "updatedAt": updated_at,
                "description": self._read_mod_description(candidate),
            })
        
        return entries

    @staticmethod
    def _to_int(value: int | str) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _read_mod_description(candidate: Path) -> Optional[str]:
        description_file = candidate / "description.txt" if candidate.is_dir() else candidate.with_suffix(".txt")
        if not description_file.exists():
            return None
        try:
            return description_file.read_text(encoding="utf-8").strip()
        except Exception as exc:
            log.debug(f"[ModStorage] Unable to read descriptor {description_file}: {exc}")
            return None


