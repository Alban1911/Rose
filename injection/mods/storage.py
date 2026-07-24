#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mod storage service
Handles mods organized by category: skins, maps, fonts, announcers, others
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable, List, Optional

from .wad_extractor import (
    extract_wad_to_directory,
    get_hash_file_signature,
    resolve_wad_skin_targets,
)
from .wad_parser import find_matching_wad_paths, read_wad_path_hashes
from utils.core.junction import safe_remove_entry
from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir
from utils.core.safe_extract import safe_extractall
from utils.core.utilities import get_champion_id_from_skin_id

log = get_logger()
_STORAGE_LOCK = threading.RLock()


def _is_wad_entry(path: Path) -> bool:
    """Return whether *path* is a packed or extracted WAD container."""
    name = path.name.casefold()
    if path.is_file():
        return name.endswith(".wad.client")
    return path.is_dir() and name.endswith((".wad", ".wad.client"))


@dataclass(frozen=True)
class SkinModEntry:
    """Metadata for a mod inside mods/skins/{champion_id}000."""

    champion_id: Optional[int]
    skin_id: int
    mod_name: str
    path: Path
    updated_at: float
    description: Optional[str] = None
    affected_skin_ids: tuple[int, ...] = ()


class ModStorageService:
    """Service exposing the on-disk mods hierarchy."""

    LEGACY_TARGET_METADATA = "rose_legacy_targets.json"
    WAD_TARGET_METADATA = "rose_wad_targets.json"
    WAD_TARGET_CACHE_VERSION = 3
    ARCHIVE_MANIFEST_NAME = ".rose_archive_manifest.json"
    ARCHIVE_SCAN_INTERVAL_SECONDS = 1.0
    ARCHIVE_SUFFIXES = frozenset({".zip", ".fantome"})
    MAX_WAD_SKIN_NUMBER = 200

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

    def __init__(
        self,
        mods_root: Optional[Path] = None,
        watch_archives: bool = False,
        champion_name_resolver: Optional[Callable[[int], Optional[str]]] = None,
        wad_hash_file: Optional[Path] = None,
    ):
        self.mods_root = mods_root or (get_user_data_dir() / "mods")
        self._storage_lock = _STORAGE_LOCK
        self._champion_name_resolver = champion_name_resolver
        self._wad_hash_file = Path(wad_hash_file) if wad_hash_file is not None else None
        self._champion_name_cache: dict[int, str] = {}
        self._pending_extracted_mod_targets: set[Path] = set()
        self._wad_target_caches: dict[int, dict[str, dict]] = {}
        self._wad_target_cache_loaded: set[int] = set()
        self._wad_target_cache_dirty: set[int] = set()
        self._wad_hash_file_signatures: dict[int, Optional[dict[str, int]]] = {}
        self._failed_archive_signatures: dict[Path, tuple[int, int]] = {}
        self._affected_skin_cache: dict[Path, tuple[int, int, Optional[str], tuple[int, ...]]] = {}
        self._archive_manifest_path = self.mods_root / self.ARCHIVE_MANIFEST_NAME
        self._archive_manifest: Optional[dict[str, dict[str, int]]] = None
        self._archive_watch_stop = threading.Event()
        self._archive_watcher: Optional[threading.Thread] = None
        self.mods_root.mkdir(parents=True, exist_ok=True)
        self._ensure_mods_root_layout()
        self._migrate_legacy_skin_layout()
        self._queue_existing_extracted_mod_targets()

        # Reconcile archives after migrations so offline additions are prepared
        # before they are needed by injection. Existing archives are baselined
        # on first startup to avoid unpacking a large library unexpectedly.
        self._archive_manifest = self._load_archive_manifest()
        self._reconcile_archive_changes()
        if watch_archives:
            self._start_archive_watcher()

    def stop(self) -> None:
        """Stop archive monitoring and persist the latest archive manifest."""
        self._archive_watch_stop.set()
        watcher = self._archive_watcher
        if watcher is not None and watcher.is_alive():
            watcher.join(timeout=2.0)
        self._archive_watcher = None
        with self._storage_lock:
            self._flush_wad_target_caches()
            self._save_archive_manifest()

    def _load_archive_manifest(self) -> Optional[dict[str, dict[str, int]]]:
        try:
            if not self._archive_manifest_path.is_file():
                return None
            payload = json.loads(
                self._archive_manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            return None

        if not isinstance(payload, dict):
            return None
        archives = payload.get("archives")
        if not isinstance(archives, dict):
            return None

        manifest: dict[str, dict[str, int]] = {}
        for relative_path, signature in archives.items():
            if not isinstance(relative_path, str) or not isinstance(signature, dict):
                continue
            try:
                manifest[relative_path] = {
                    "size": int(signature["size"]),
                    "mtime_ns": int(signature["mtime_ns"]),
                }
            except (KeyError, TypeError, ValueError):
                continue
        return manifest

    def _save_archive_manifest(self) -> None:
        if self._archive_manifest is None:
            return

        temporary = self._archive_manifest_path.with_name(
            f".{self._archive_manifest_path.name}.tmp"
        )
        payload = {
            "version": 1,
            "archives": self._archive_manifest,
        }
        try:
            self._archive_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self._archive_manifest_path)
        except (OSError, TypeError, ValueError) as exc:
            log.warning(
                "[ModStorage] Could not save archive manifest: %s",
                exc,
            )
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _archive_directories(self) -> list[Path]:
        """Return directories where users can directly add mod archives."""
        directories: list[Path] = []
        for category in self.ROOT_CATEGORIES:
            category_dir = self.mods_root / category
            if category == self.CATEGORY_SKINS:
                try:
                    directories.extend(
                        child
                        for child in category_dir.iterdir()
                        if child.is_dir()
                    )
                except OSError:
                    continue
            else:
                directories.append(category_dir)
        return directories

    def _collect_archive_signatures(self) -> dict[str, dict[str, int]]:
        signatures: dict[str, dict[str, int]] = {}
        for directory in self._archive_directories():
            try:
                candidates = directory.iterdir()
            except OSError:
                continue
            for candidate in candidates:
                if not candidate.is_file() or candidate.suffix.casefold() not in self.ARCHIVE_SUFFIXES:
                    continue
                try:
                    stat = candidate.stat()
                except OSError:
                    continue
                signatures[self._relative_mod_path(candidate)] = {
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
        return signatures

    def _archive_path_from_relative(self, relative_path: str) -> Optional[Path]:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            return None
        candidate = self.mods_root.joinpath(*relative.parts)
        try:
            candidate.relative_to(self.mods_root)
        except ValueError:
            return None
        return candidate

    def _reconcile_archive_changes(self) -> None:
        with self._storage_lock:
            self._retry_pending_extracted_mod_targets()
            current = self._collect_archive_signatures()
            if self._archive_manifest is None:
                self._archive_manifest = current
                self._flush_wad_target_caches()
                self._save_archive_manifest()
                log.debug(
                    "[ModStorage] Baselined %d existing archives",
                    len(current),
                )
                return

            previous = self._archive_manifest
            next_manifest: dict[str, dict[str, int]] = {}
            for relative_path, signature in current.items():
                previous_signature = previous.get(relative_path)
                if previous_signature == signature:
                    next_manifest[relative_path] = signature
                    continue

                archive = self._archive_path_from_relative(relative_path)
                if archive is not None and self._extract_archive(archive):
                    self._prepare_extracted_mod_targets(
                        archive.parent / archive.stem
                    )
                    continue

                # Keep an old signature so a changed archive is retried. New
                # failed archives stay absent and are retried on the next poll.
                if previous_signature is not None:
                    next_manifest[relative_path] = previous_signature

            self._archive_manifest = next_manifest
            self._flush_wad_target_caches()
            self._save_archive_manifest()

    def _start_archive_watcher(self) -> None:
        if self._archive_watcher is not None and self._archive_watcher.is_alive():
            return
        self._archive_watch_stop.clear()
        self._archive_watcher = threading.Thread(
            target=self._archive_watch_loop,
            name="ModArchiveWatcher",
            daemon=True,
        )
        self._archive_watcher.start()

    def _archive_watch_loop(self) -> None:
        while not self._archive_watch_stop.wait(self.ARCHIVE_SCAN_INTERVAL_SECONDS):
            try:
                self._reconcile_archive_changes()
            except Exception as exc:  # noqa: BLE001
                log.warning("[ModStorage] Archive watcher failed: %s", exc)
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

    def _migrate_legacy_skin_layout(self) -> None:
        """Move old per-skin mod folders into the champion-level layout.

        Older Rose versions stored mods as skins/<skin_id>/<mod>. The current
        layout stores all mods for a champion under skins/<champion>000/<mod>
        and discovers affected skins from the mod contents. Keep the old
        target ID in migration metadata so a skin-specific legacy mod does not
        become a base-skin mod after it is moved.
        """
        moved_paths: dict[str, str] = {}
        try:
            with self._storage_lock:
                for legacy_dir in sorted(
                    self.skins_dir.iterdir(),
                    key=lambda path: path.name.casefold(),
                ):
                    if not legacy_dir.is_dir():
                        continue

                    legacy_id = self._to_int(legacy_dir.name)
                    if legacy_id is None or legacy_id <= 0:
                        continue

                    # Base folders are already in the new layout. Numeric
                    # folders below 1000 are handled as the intermediate
                    # champion/skin layout used by older builds.
                    if legacy_id >= 1000 and legacy_id % 1000 == 0:
                        continue

                    if legacy_id < 1000:
                        destination_root = self.get_skin_dir(legacy_id * 1000)
                        nested_skin_dirs = [
                            child
                            for child in sorted(
                                legacy_dir.iterdir(),
                                key=lambda path: path.name.casefold(),
                            )
                            if child.is_dir() and self._to_int(child.name) is not None
                        ]

                        for nested_dir in nested_skin_dirs:
                            nested_id = int(nested_dir.name)
                            target_skin_id = (
                                nested_id
                                if nested_id >= 1000
                                else legacy_id * 1000 + nested_id
                            )
                            moved_paths.update(
                                self._migrate_legacy_mod_directory(
                                    nested_dir,
                                    destination_root,
                                    target_skin_id,
                                )
                            )

                        moved_paths.update(
                            self._migrate_legacy_mod_directory(
                                legacy_dir,
                                destination_root,
                                None,
                            )
                        )
                    else:
                        destination_root = self.get_skin_dir(
                            (legacy_id // 1000) * 1000
                        )
                        moved_paths.update(
                            self._migrate_legacy_mod_directory(
                                legacy_dir,
                                destination_root,
                                legacy_id,
                            )
                        )

                self._rewrite_migrated_historic_paths(moved_paths)
        except (OSError, ValueError, TypeError) as exc:
            log.warning("[ModStorage] Legacy mod migration failed: %s", exc)

    def _migrate_legacy_mod_directory(
        self,
        source_dir: Path,
        destination_root: Path,
        legacy_skin_id: Optional[int],
    ) -> dict[str, str]:
        """Move mod entries from one legacy directory into a new root."""
        if not source_dir.exists() or not source_dir.is_dir():
            return {}

        self._extract_archives_in_directory(source_dir)
        destination_root.mkdir(parents=True, exist_ok=True)
        moved_paths: dict[str, str] = {}
        archive_suffixes = {".zip", ".fantome"}

        for candidate in sorted(
            source_dir.iterdir(),
            key=lambda path: path.name.casefold(),
        ):
            if not (
                candidate.is_dir()
                or (candidate.is_file() and candidate.suffix.casefold() in archive_suffixes)
            ):
                continue

            destination = self._unique_migration_destination(
                destination_root,
                candidate,
                legacy_skin_id,
            )
            old_relative_path = self._relative_mod_path(candidate)
            try:
                candidate.replace(destination)
            except OSError as exc:
                log.warning(
                    "[ModStorage] Could not migrate legacy mod %s: %s",
                    candidate,
                    exc,
                )
                continue

            if legacy_skin_id is not None and destination.is_dir():
                self._write_legacy_target_metadata(destination, legacy_skin_id)

            moved_paths[old_relative_path] = self._relative_mod_path(destination)
            log.info(
                "[ModStorage] Migrated legacy mod %s -> %s",
                old_relative_path,
                moved_paths[old_relative_path],
            )

        try:
            if not any(source_dir.iterdir()):
                source_dir.rmdir()
        except OSError:
            pass

        return moved_paths

    def _unique_migration_destination(
        self,
        destination_root: Path,
        source: Path,
        legacy_skin_id: Optional[int],
    ) -> Path:
        """Return a collision-free destination for a migrated mod."""
        destination = destination_root / source.name
        if not destination.exists() and not destination.is_symlink():
            return destination

        suffix = (
            f" (legacy {legacy_skin_id})"
            if legacy_skin_id is not None
            else " (legacy)"
        )
        if source.is_file():
            candidate = destination_root / (
                f"{source.stem}{suffix}{source.suffix}"
            )
        else:
            candidate = destination_root / f"{source.name}{suffix}"

        index = 2
        while candidate.exists() or candidate.is_symlink():
            if source.is_file():
                candidate = destination_root / (
                    f"{source.stem}{suffix} {index}{source.suffix}"
                )
            else:
                candidate = destination_root / f"{source.name}{suffix} {index}"
            index += 1
        return candidate

    def _write_legacy_target_metadata(
        self,
        mod_directory: Path,
        legacy_skin_id: int,
    ) -> None:
        """Record the old storage skin as an affected target."""
        metadata_path = (
            mod_directory / "META" / self.LEGACY_TARGET_METADATA
        )
        try:
            metadata = {}
            if metadata_path.is_file():
                loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    metadata = loaded

            existing = metadata.get("affectedSkinIds", [])
            if isinstance(existing, dict):
                existing = existing.keys()
            if isinstance(existing, (str, bytes)):
                existing = []
            try:
                affected = {int(value) for value in existing}
            except (TypeError, ValueError):
                affected = set()
            affected.add(int(legacy_skin_id))

            metadata["affectedSkinIds"] = sorted(affected)
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError) as exc:
            log.warning(
                "[ModStorage] Could not preserve legacy target %s for %s: %s",
                legacy_skin_id,
                mod_directory,
                exc,
            )

    def _relative_mod_path(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.mods_root)
        except ValueError:
            relative = path
        return str(relative).replace(chr(92), "/")

    def _rewrite_migrated_historic_paths(
        self,
        moved_paths: dict[str, str],
    ) -> None:
        """Update custom-mod history entries after moving their folders."""
        if not moved_paths:
            return

        try:
            from utils.core.historic import (
                get_custom_mod_path,
                is_custom_mod_path,
                load_historic_map,
                write_historic_entry,
            )

            def normalize_path(value: str) -> str:
                return str(value).replace(chr(92), "/").casefold()

            normalized_paths = {
                normalize_path(old): new for old, new in moved_paths.items()
            }
            for champion_id, historic_value in load_historic_map().items():
                if not is_custom_mod_path(historic_value):
                    continue
                old_path = get_custom_mod_path(historic_value)
                if not old_path:
                    continue
                new_path = normalized_paths.get(normalize_path(old_path))
                if not new_path:
                    continue
                write_historic_entry(
                    int(champion_id),
                    f"path:{new_path}",
                )
                log.info(
                    "[ModStorage] Updated historic mod path %s -> %s",
                    old_path,
                    new_path,
                )
        except (OSError, TypeError, ValueError, ImportError) as exc:
            log.warning(
                "[ModStorage] Could not update historic mod paths: %s",
                exc,
            )

    @property
    def skins_dir(self) -> Path:
        return self.mods_root / self.CATEGORY_SKINS

    def get_skin_dir(self, skin_id: int | str) -> Path:
        return self.skins_dir / str(skin_id)

    def _extract_archives_in_directory(self, directory: Path) -> None:
        """Convert dropped ZIP/fantome mods into extracted mod folders."""
        if not directory.exists() or not directory.is_dir():
            return

        try:
            archives = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for archive in archives:
            if archive.is_file() and archive.suffix.casefold() in self.ARCHIVE_SUFFIXES:
                self._extract_archive(archive)

    def _extract_archive(self, archive: Path) -> bool:
        """Extract one outer mod archive, leaving any WAD files packed."""
        try:
            stat = archive.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            return False
        if self._failed_archive_signatures.get(archive) == signature:
            return False

        target = archive.parent / archive.stem
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{archive.stem}.extracting-",
                dir=str(archive.parent),
            )
        )
        try:
            safe_extractall(archive, temporary)
            if not any(temporary.iterdir()):
                raise ValueError("archive contains no files")

            if target.exists() or target.is_symlink():
                safe_remove_entry(target)
            temporary.replace(target)
            archive.unlink()
            self._failed_archive_signatures.pop(archive, None)
            log.info("[ModStorage] Extracted and removed archive: %s", archive)
            return True
        except Exception as exc:  # noqa: BLE001
            safe_remove_entry(temporary)
            self._failed_archive_signatures[archive] = signature
            log.warning("[ModStorage] Failed to extract %s: %s", archive, exc)
            return False

    def _resolve_champion_name(self, champion_id: int) -> Optional[str]:
        if champion_id in self._champion_name_cache:
            return self._champion_name_cache[champion_id]

        resolver = self._champion_name_resolver
        if resolver is None:
            return None
        try:
            champion_name = resolver(champion_id)
        except Exception as exc:  # noqa: BLE001
            log.debug(
                "[ModStorage] Champion name lookup failed for %s: %s",
                champion_id,
                exc,
            )
            return None
        if not champion_name:
            return None
        champion_name = str(champion_name)
        self._champion_name_cache[champion_id] = champion_name
        return champion_name

    def _queue_existing_extracted_mod_targets(self) -> None:
        """Queue existing extracted WAD mods missing from the champion cache."""
        try:
            champion_directories = tuple(self.skins_dir.iterdir())
        except OSError:
            return

        for champion_directory in champion_directories:
            if not champion_directory.is_dir():
                continue
            storage_skin_id = self._to_int(champion_directory.name)
            if storage_skin_id is None:
                continue
            champion_id = get_champion_id_from_skin_id(storage_skin_id)
            if champion_id is None:
                continue

            try:
                mod_directories = tuple(
                    child for child in champion_directory.iterdir() if child.is_dir()
                )
            except OSError:
                continue

            cache = self._load_wad_target_cache(champion_id)
            active_mod_keys = {
                self._wad_target_cache_key(mod_directory, champion_id)
                for mod_directory in mod_directories
            }
            for mod_key in tuple(cache):
                if mod_key not in active_mod_keys:
                    cache.pop(mod_key, None)
                    self._wad_target_cache_dirty.add(champion_id)

            for mod_directory in mod_directories:
                if not (mod_directory / "WAD").is_dir():
                    continue
                mod_key = self._wad_target_cache_key(mod_directory, champion_id)
                if mod_key not in cache:
                    self._pending_extracted_mod_targets.add(mod_directory)

    def _retry_pending_extracted_mod_targets(self) -> None:
        for mod_directory in tuple(self._pending_extracted_mod_targets):
            if self._prepare_extracted_mod_targets(mod_directory):
                self._pending_extracted_mod_targets.discard(mod_directory)

    def _prepare_extracted_mod_targets(self, mod_directory: Path) -> bool:
        """Scan WAD targets as soon as an archive becomes an extracted mod."""
        if not mod_directory.is_dir() or mod_directory.parent.parent != self.skins_dir:
            return True

        storage_skin_id = self._to_int(mod_directory.parent.name)
        if storage_skin_id is None:
            return True
        champion_id = get_champion_id_from_skin_id(storage_skin_id)
        if champion_id is None:
            return True
        champion_name = self._resolve_champion_name(champion_id)
        if not champion_name:
            self._pending_extracted_mod_targets.add(mod_directory)
            log.debug(
                "[ModStorage] Delaying WAD target scan until champion %s is available: %s",
                champion_id,
                mod_directory,
            )
            return False

        affected_skin_ids = self._get_affected_skin_ids(
            mod_directory,
            storage_skin_id,
            champion_id,
            champion_name,
        )
        self._pending_extracted_mod_targets.discard(mod_directory)
        log.debug(
            "[ModStorage] Prepared extracted mod targets for %s: %s",
            mod_directory.name,
            affected_skin_ids,
        )
        return True

    def list_mods_for_skin(
        self,
        skin_id: int | str,
        champion_name: Optional[str] = None,
    ) -> List[SkinModEntry]:
        with self._storage_lock:
            entries = self._list_mods_for_skin(skin_id, champion_name)
            self._flush_wad_target_caches()
            return entries

    def _list_mods_for_skin(
        self,
        skin_id: int | str,
        champion_name: Optional[str] = None,
    ) -> List[SkinModEntry]:
        skin_dir = self.get_skin_dir(skin_id)
        if not skin_dir.exists() or not skin_dir.is_dir():
            return []

        skin_id_int = self._to_int(skin_id)
        if skin_id_int is None:
            return []

        self._extract_archives_in_directory(skin_dir)

        champion_id = get_champion_id_from_skin_id(skin_id_int)
        entries: List[SkinModEntry] = []
        for candidate in sorted(skin_dir.iterdir(), key=lambda p: p.name.lower()):
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

            affected_skin_ids = self._get_affected_skin_ids(
                candidate,
                skin_id_int,
                champion_id,
                champion_name,
            )

            entries.append(
                SkinModEntry(
                    champion_id=champion_id,
                    skin_id=skin_id_int,
                    mod_name=mod_name,
                    path=candidate,
                    updated_at=updated_at,
                    description=self._read_mod_description(candidate),
                    affected_skin_ids=affected_skin_ids,
                )
            )

        return entries

    def list_mods_for_champion(
        self,
        champion_id: int | str,
        champion_name: Optional[str] = None,
    ) -> List[SkinModEntry]:
        """Return every SkinModEntry whose champion matches *champion_id*.

        Scans all numeric subdirectories under ``skins/`` and aggregates the
        entries from each skin that belongs to the given champion.
        """
        champion_id_int = self._to_int(champion_id)
        if champion_id_int is None:
            return []

        entries: List[SkinModEntry] = []
        skins_dir = self.skins_dir
        if not skins_dir.exists() or not skins_dir.is_dir():
            return entries

        for child in sorted(skins_dir.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            child_int = self._to_int(child.name)
            if child_int is None:
                continue
            if get_champion_id_from_skin_id(child_int) != champion_id_int:
                continue
            entries.extend(self.list_mods_for_skin(child_int, champion_name))

        return entries

    def has_mods_for_skin(self, skin_id: int | str) -> bool:
        return bool(self.list_mods_for_skin(skin_id))

    def _get_affected_skin_ids(
        self,
        candidate: Path,
        storage_skin_id: int,
        champion_id: Optional[int],
        champion_name: Optional[str] = None,
    ) -> tuple[int, ...]:
        """Discover the skin IDs touched by a custom mod.

        Mods are stored under one skin directory, but a WAD can contain
        assets for several skins/chromas. Most CSLOL exports expose those
        targets as folders such as skins/skin04 and skins/skin05.
        Optional affected-skin metadata is also supported for mods that do
        not encode their targets in paths.
        """
        wad_container_present = False
        if candidate.is_dir():
            try:
                wad_container_present = (candidate / "WAD").is_dir()
                if not wad_container_present:
                    wad_container_present = any(
                        _is_wad_entry(path)
                        for path in candidate.iterdir()
                    )
            except OSError:
                wad_container_present = True

        try:
            stat = candidate.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            cached = self._affected_skin_cache.get(candidate)
            if (
                cached
                and cached[:2] == signature
                and cached[2] == champion_name
                and not wad_container_present
            ):
                return cached[3]
        except OSError:
            signature = (0, 0)

        # Prefer targets discovered from the mod itself. This matters for
        # champion-level imports stored under the base folder: a mod that only
        # contains skin04 assets must not also appear on the base skin just
        # because the user selected the champion when importing it.
        affected: set[int] = set()
        chroma_only = False

        def add_metadata_ids(value) -> None:
            values = value.keys() if isinstance(value, dict) else value
            if values is None or isinstance(values, (str, bytes)):
                return
            try:
                values = iter(values)
            except TypeError:
                return
            for raw_value in values:
                try:
                    affected.add(int(raw_value))
                except (TypeError, ValueError):
                    continue

        if candidate.is_dir():
            metadata_paths = (
                candidate / "META" / self.LEGACY_TARGET_METADATA,
                candidate / "META" / "affected_skins.json",
                candidate / "META" / "info.json",
                candidate / "META" / "details.json",
            )
            for metadata_path in metadata_paths:
                if not metadata_path.is_file():
                    continue
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    continue
                if not isinstance(metadata, dict):
                    continue
                metadata_text = " ".join(
                    str(metadata.get(key, ""))
                    for key in ("Name", "name", "Description", "description")
                )
                if re.search(
                    r"\ball\s+chromas?\b|\bchromas?\s+only\b",
                    metadata_text,
                    re.IGNORECASE,
                ):
                    chroma_only = True
                for key in (
                    "affectedSkinIds",
                    "affectedSkins",
                    "affected_skin_ids",
                    "affected_skins",
                    "skinIds",
                ):
                    if key in metadata:
                        add_metadata_ids(metadata[key])

            if champion_id is not None and champion_name:
                asset_targets = self._skin_ids_from_asset_paths(
                    candidate,
                    champion_id,
                    champion_name,
                )
                if asset_targets:
                    log.info(
                        "[ModStorage] Extracted asset path target found for %s: %s",
                        candidate.name,
                        sorted(asset_targets),
                    )
                affected.update(asset_targets)
        wad_targets = self._get_wad_targets(candidate, champion_id, champion_name)
        if wad_targets is not None:
            affected.update(wad_targets)

        # Some chroma-only exports include a small base-skin carrier folder
        # (for example skin04) even though their actual VFX are in skin05+.
        # Their metadata commonly calls this out as "All chromas". In that
        # case, do not expose the lowest skin in the detected family as a
        # selectable target.
        if chroma_only and champion_id is not None:
            champion_skin_ids = sorted(
                skin_id
                for skin_id in affected
                if skin_id // 1000 == int(champion_id)
            )
            if len(champion_skin_ids) > 1:
                affected.discard(champion_skin_ids[0])

        if not affected:
            log.info(
                "[ModStorage] No target found in mod; using storage skin fallback %s: %s",
                storage_skin_id,
                candidate,
            )
            affected.add(int(storage_skin_id))

        result = tuple(sorted(affected))
        self._affected_skin_cache[candidate] = (signature[0], signature[1], champion_name, result)
        return result

    @staticmethod
    def _skin_ids_from_asset_paths(
        root: Path,
        champion_id: int,
        champion_name: str,
    ) -> set[int]:
        """Find skin IDs below DATA/ASSETS character skin paths."""
        champion_path_names = set(
            ModStorageService._normalized_champion_path_names(champion_name)
        )
        if not champion_path_names:
            return set()

        affected: set[int] = set()
        try:
            paths = root.rglob("*")
            for asset_path in paths:
                try:
                    parts = asset_path.relative_to(root).parts
                except ValueError:
                    continue
                normalized_parts = tuple(part.casefold() for part in parts)
                for index in range(len(parts) - 4):
                    if normalized_parts[index] not in {"data", "assets"}:
                        continue
                    if normalized_parts[index + 1] != "characters":
                        continue
                    if normalized_parts[index + 2] not in champion_path_names:
                        continue
                    if normalized_parts[index + 3] != "skins":
                        continue
                    match = re.fullmatch(
                        r"skin[_-]?0*(\d+)(?:\.[^.]+)?",
                        parts[index + 4],
                        re.IGNORECASE,
                    )
                    if not match:
                        continue
                    suffix = int(match.group(1))
                    affected.add(
                        suffix
                        if suffix >= 1000
                        else int(champion_id) * 1000 + suffix
                    )
        except OSError:
            pass
        return affected

    def _scan_packed_wad_toc(
        self,
        wad_file: Path,
        champion_id: int,
        champion_name: str,
    ) -> tuple[set[int], bool]:
        """Run the cheap hash-only scan for one packed WAD."""
        try:
            path_hashes = read_wad_path_hashes(wad_file)
        except (OSError, ValueError) as exc:
            log.debug(
                "[ModStorage] WAD TOC scan failed for %s: %s",
                wad_file,
                exc,
            )
            return set(), False

        targets = find_matching_wad_paths(
            path_hashes,
            self._candidate_wad_skin_paths(champion_id, champion_name),
        )
        if targets:
            log.info(
                "[ModStorage] WAD TOC target scan found skins for %s: %s",
                wad_file.name,
                sorted(targets),
            )
        return targets, True

    def _scan_packed_wad_by_path_resolution(
        self,
        wad_file: Path,
        champion_id: int,
        champion_name: str,
    ) -> tuple[set[int], bool]:
        """Resolve known WAD paths and scan targets without materializing files."""
        try:
            targets = resolve_wad_skin_targets(
                wad_file,
                champion_id,
                champion_name,
                self._wad_hash_file,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[ModStorage] WAD path resolution failed for %s: %s",
                wad_file,
                exc,
            )
            return set(), False

        if targets:
            log.info(
                "[ModStorage] WAD path resolution found skins for %s: %s",
                wad_file.name,
                sorted(targets),
            )
        return targets, True

    def _scan_packed_wad_by_extraction(
        self,
        wad_file: Path,
        champion_id: int,
        champion_name: str,
    ) -> tuple[set[int], bool]:
        """Extract one packed WAD temporarily and scan its asset paths."""
        try:
            with tempfile.TemporaryDirectory(prefix="rose-wad-targets-") as temp_dir:
                extracted_root = extract_wad_to_directory(
                    wad_file,
                    Path(temp_dir),
                )
                targets = self._skin_ids_from_asset_paths(
                    extracted_root,
                    champion_id,
                    champion_name,
                )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[ModStorage] WAD extraction failed for %s: %s",
                wad_file,
                exc,
            )
            return set(), False

        if targets:
            log.info(
                "[ModStorage] WAD extraction target scan found skins for %s: %s",
                wad_file.name,
                sorted(targets),
            )
        return targets, True

    def _get_wad_targets(
        self,
        candidate: Path,
        champion_id: Optional[int],
        champion_name: Optional[str],
    ) -> Optional[set[int]]:
        """Discover targets from packed or already-extracted WAD containers."""
        if champion_id is None or not candidate.is_dir():
            return None

        wad_entries = sorted(
            (
                path
                for path in candidate.rglob("*")
                if _is_wad_entry(path)
            ),
            key=lambda path: path.as_posix().casefold(),
        )
        if not wad_entries:
            return None


        current_signatures: dict[str, dict[str, int]] = {}
        packed_wads: list[Path] = []
        extracted_wads: list[Path] = []
        for path in wad_entries:
            try:
                stat = path.stat()
            except OSError:
                continue
            current_signatures[self._relative_candidate_path(candidate, path)] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
            if path.is_file():
                packed_wads.append(path)
            else:
                extracted_wads.append(path)
        if not current_signatures:
            return None

        hash_file_signature = get_hash_file_signature(self._wad_hash_file)
        cached_targets = self._read_wad_target_cache(
            int(champion_id),
            candidate,
            current_signatures,
            hash_file_signature,
        )
        if cached_targets is not None:
            return cached_targets
        if not champion_name:
            log.debug(
                "[ModStorage] Cannot resolve WAD skin paths without champion name: %s",
                candidate,
            )
            return None

        discovered: set[int] = set()
        scan_complete = True
        for wad_file in packed_wads:
            fast_targets, fast_scan_complete = self._scan_packed_wad_toc(
                wad_file,
                int(champion_id),
                champion_name,
            )
            discovered.update(fast_targets)
            if fast_targets:
                continue

            if fast_scan_complete:
                log.info(
                    "[ModStorage] WAD TOC scan found no targets; resolving known paths in %s",
                    wad_file,
                )
            else:
                log.info(
                    "[ModStorage] WAD TOC scan failed; trying known-path resolution for %s",
                    wad_file,
                )
            resolved_targets, resolution_complete = self._scan_packed_wad_by_path_resolution(
                wad_file,
                int(champion_id),
                champion_name,
            )
            discovered.update(resolved_targets)
            if resolved_targets:
                continue

            if resolution_complete:
                log.info(
                    "[ModStorage] Known-path resolution found no targets; extracting %s",
                    wad_file,
                )
            else:
                log.info(
                    "[ModStorage] Known-path resolution unavailable; extracting %s",
                    wad_file,
                )

            extracted_targets, extraction_complete = self._scan_packed_wad_by_extraction(
                wad_file,
                int(champion_id),
                champion_name,
            )
            discovered.update(extracted_targets)
            if not extraction_complete:
                scan_complete = False

        for wad_directory in extracted_wads:
            discovered.update(
                self._skin_ids_from_asset_paths(
                    wad_directory,
                    champion_id,
                    champion_name,
                )
            )

        if not scan_complete:
            log.debug(
                "[ModStorage] WAD target scan incomplete; metadata not cached: %s",
                candidate,
            )
            return discovered or None

        self._record_wad_target_cache(
            int(champion_id),
            candidate,
            current_signatures,
            hash_file_signature,
            discovered,
        )
        if discovered:
            log.info(
                "[ModStorage] WAD target scan found skins for %s: %s",
                candidate.name,
                sorted(discovered),
            )
        else:
            log.debug("[ModStorage] WAD target scan found no skin IDs: %s", candidate)
        return discovered

    @staticmethod
    def _normalized_champion_path_names(champion_name: str) -> tuple[str, ...]:
        compact_name = re.sub(r"[^a-z0-9]", "", str(champion_name).casefold())
        if not compact_name:
            return ()

        names = [compact_name]
        aliases = {
            "wukong": "monkeyking",
            "nunuandwillump": "nunu",
            "renataglasc": "renata",
        }
        for source, alias in aliases.items():
            if compact_name == source and alias not in names:
                names.append(alias)
            elif compact_name == alias and source not in names:
                names.append(source)
        return tuple(names)
    @staticmethod
    def _candidate_wad_skin_paths(
        champion_id: int,
        champion_name: str,
    ) -> list[tuple[str, int]]:
        """Build finite DATA/ASSETS candidates for skin BINs."""
        names = ModStorageService._normalized_champion_path_names(champion_name)
        if not names:
            return []

        candidates: list[tuple[str, int]] = []
        for skin_number in range(ModStorageService.MAX_WAD_SKIN_NUMBER):
            target_skin_id = int(champion_id) * 1000 + skin_number
            skin_segments = [f"skin{skin_number}"]
            if skin_number < 100:
                skin_segments.append(f"skin{skin_number:02d}")
            for name in names:
                for root in ("data", "assets"):
                    for skin_segment in skin_segments:
                        candidates.append(
                            (
                                f"{root}/characters/{name}/skins/{skin_segment}.bin",
                                target_skin_id,
                            )
                        )
        return candidates

    def _wad_target_cache_path(self, champion_id: int) -> Path:
        return self.get_skin_dir(int(champion_id) * 1000) / self.WAD_TARGET_METADATA

    def _wad_target_cache_key(self, candidate: Path, champion_id: int) -> str:
        champion_root = self.get_skin_dir(int(champion_id) * 1000)
        try:
            return candidate.relative_to(champion_root).as_posix()
        except ValueError:
            return candidate.name

    def _load_wad_target_cache(self, champion_id: int) -> dict[str, dict]:
        if champion_id in self._wad_target_cache_loaded:
            return self._wad_target_caches.setdefault(champion_id, {})

        self._wad_target_cache_loaded.add(champion_id)
        cache: dict[str, dict] = {}
        cache_path = self._wad_target_cache_path(champion_id)
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("invalid WAD target cache")

            raw_hash_file_signature = payload["hashFile"]
            if raw_hash_file_signature is None:
                hash_file_signature = None
            elif isinstance(raw_hash_file_signature, dict):
                hash_file_signature = {
                    "size": int(raw_hash_file_signature["size"]),
                    "mtime_ns": int(raw_hash_file_signature["mtime_ns"]),
                }
            else:
                raise ValueError("invalid WAD hash-file signature")

            if (
                int(payload.get("version", 0)) == self.WAD_TARGET_CACHE_VERSION
                and int(payload.get("championId", -1)) == int(champion_id)
                and isinstance(payload.get("mods"), dict)
            ):
                self._wad_hash_file_signatures[champion_id] = hash_file_signature
                for mod_key, entry in payload["mods"].items():
                    if not isinstance(mod_key, str) or not isinstance(entry, dict):
                        continue
                    if not isinstance(entry.get("wadFiles"), dict):
                        continue
                    if not isinstance(entry.get("affectedSkinIds"), list):
                        continue
                    cache[mod_key] = entry
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            pass

        self._wad_target_caches[champion_id] = cache
        return cache

    def _read_wad_target_cache(
        self,
        champion_id: int,
        candidate: Path,
        signatures: dict[str, dict[str, int]],
        hash_file_signature: Optional[dict[str, int]],
    ) -> Optional[set[int]]:
        cache = self._load_wad_target_cache(champion_id)
        if self._wad_hash_file_signatures.get(champion_id) != hash_file_signature:
            had_cached_entries = bool(cache)
            cache.clear()
            self._wad_hash_file_signatures[champion_id] = hash_file_signature
            if had_cached_entries:
                self._wad_target_cache_dirty.add(champion_id)
            return None
        entry = cache.get(self._wad_target_cache_key(candidate, champion_id))
        if not isinstance(entry, dict) or entry.get("wadFiles") != signatures:
            return None
        try:
            return {int(value) for value in entry["affectedSkinIds"]}
        except (TypeError, ValueError):
            return None

    def _record_wad_target_cache(
        self,
        champion_id: int,
        candidate: Path,
        signatures: dict[str, dict[str, int]],
        hash_file_signature: Optional[dict[str, int]],
        affected_skin_ids: set[int],
    ) -> None:
        cache = self._load_wad_target_cache(champion_id)
        self._wad_hash_file_signatures[champion_id] = hash_file_signature
        cache[self._wad_target_cache_key(candidate, champion_id)] = {
            "wadFiles": signatures,
            "affectedSkinIds": sorted(affected_skin_ids),
        }
        self._wad_target_cache_dirty.add(champion_id)

    def _flush_wad_target_caches(self) -> None:
        for champion_id in tuple(self._wad_target_cache_dirty):
            cache_path = self._wad_target_cache_path(champion_id)
            temporary = cache_path.with_name(f".{cache_path.name}.tmp")
            payload = {
                "version": self.WAD_TARGET_CACHE_VERSION,
                "championId": int(champion_id),
                "hashFile": self._wad_hash_file_signatures.get(champion_id),
                "mods": self._wad_target_caches.get(champion_id, {}),
            }
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temporary.replace(cache_path)
                self._wad_target_cache_dirty.discard(champion_id)
            except (OSError, TypeError, ValueError) as exc:
                log.debug(
                    "[ModStorage] Could not cache WAD targets for champion %s: %s",
                    champion_id,
                    exc,
                )
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _relative_candidate_path(candidate: Path, path: Path) -> str:
        try:
            return str(path.relative_to(candidate)).replace(chr(92), "/")
        except ValueError:
            return path.name

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
        if category not in {
            self.CATEGORY_MAPS,
            self.CATEGORY_FONTS,
            self.CATEGORY_ANNOUNCERS,
            self.CATEGORY_UI,
            self.CATEGORY_VOICEOVER,
            self.CATEGORY_LOADING_SCREEN,
            self.CATEGORY_VFX,
            self.CATEGORY_SFX,
            self.CATEGORY_OTHERS,
        }:
            return []
        
        category_dir = self.mods_root / category
        if not category_dir.exists() or not category_dir.is_dir():
            return []

        self._extract_archives_in_directory(category_dir)
        
        entries = []
        for candidate in sorted(category_dir.iterdir(), key=lambda p: p.name.lower()):
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


