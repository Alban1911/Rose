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

    ARCHIVE_SCAN_INTERVAL_SECONDS = 1.0
    LEGACY_TARGET_METADATA = "rose_legacy_targets.json"

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

    def __init__(self, mods_root: Optional[Path] = None, watch_archives: bool = False):
        self.mods_root = mods_root or (get_user_data_dir() / "mods")
        self._storage_lock = _STORAGE_LOCK
        self._watcher_stop = threading.Event()
        self._watcher_thread: Optional[threading.Thread] = None
        self._failed_archive_signatures: dict[Path, tuple[int, int]] = {}
        self._affected_skin_cache: dict[Path, tuple[int, int, tuple[int, ...]]] = {}
        self.mods_root.mkdir(parents=True, exist_ok=True)
        self._ensure_mods_root_layout()
        self._migrate_legacy_skin_layout()

        if watch_archives:
            self._watcher_thread = threading.Thread(
                target=self._watch_archives,
                name="RoseModArchiveWatcher",
                daemon=True,
            )
            self._watcher_thread.start()

    def _extract_archives_from_all_directories(self) -> None:
        """Extract archives from every supported mod directory."""
        skins_dir = self.skins_dir
        if skins_dir.exists() and skins_dir.is_dir():
            for skin_dir in skins_dir.iterdir():
                if skin_dir.is_dir():
                    self._extract_archives_in_directory(skin_dir)

        for category in self.ROOT_CATEGORIES:
            if category == self.CATEGORY_SKINS:
                continue
            self._extract_archives_in_directory(self.mods_root / category)

    def _watch_archives(self) -> None:
        """Watch the mod tree and extract newly added archives."""
        while not self._watcher_stop.is_set():
            try:
                with self._storage_lock:
                    self._extract_archives_from_all_directories()
            except Exception:  # noqa: BLE001
                log.exception("[ModStorage] Archive watcher scan failed")

            if self._watcher_stop.wait(self.ARCHIVE_SCAN_INTERVAL_SECONDS):
                break

    def stop(self) -> None:
        """Stop the background archive watcher, if it is running."""
        self._watcher_stop.set()
        watcher = self._watcher_thread
        if watcher and watcher.is_alive() and watcher is not threading.current_thread():
            watcher.join(timeout=2.0)
        self._watcher_thread = None

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
        """Convert dropped ZIP/fantome mods into extracted mod folders.

        Archives are extracted into a temporary sibling directory first. The
        source archive is removed only after extraction succeeds, so a broken
        or unsafe archive remains available for troubleshooting/retry.
        """
        if not directory.exists() or not directory.is_dir():
            return

        for archive in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if not archive.is_file() or archive.suffix.lower() not in {".zip", ".fantome"}:
                continue

            try:
                stat = archive.stat()
                signature = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue
            if self._failed_archive_signatures.get(archive) == signature:
                continue

            target = directory / archive.stem
            temporary = Path(
                tempfile.mkdtemp(
                    prefix=f".{archive.stem}.extracting-",
                    dir=str(directory),
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
            except Exception as exc:  # noqa: BLE001
                safe_remove_entry(temporary)
                self._failed_archive_signatures[archive] = signature
                log.warning("[ModStorage] Failed to extract %s: %s", archive, exc)

    def list_mods_for_skin(self, skin_id: int | str) -> List[SkinModEntry]:
        with self._storage_lock:
            return self._list_mods_for_skin(skin_id)

    def _list_mods_for_skin(self, skin_id: int | str) -> List[SkinModEntry]:
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

    def list_mods_for_champion(self, champion_id: int | str) -> List[SkinModEntry]:
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
            entries.extend(self.list_mods_for_skin(child_int))

        return entries

    def has_mods_for_skin(self, skin_id: int | str) -> bool:
        return bool(self.list_mods_for_skin(skin_id))

    def _get_affected_skin_ids(
        self,
        candidate: Path,
        storage_skin_id: int,
        champion_id: Optional[int],
    ) -> tuple[int, ...]:
        """Discover the skin IDs touched by a custom mod.

        Mods are stored under one skin directory, but a WAD can contain
        assets for several skins/chromas. Most CSLOL exports expose those
        targets as folders such as skins/skin04 and skins/skin05.
        Optional affected-skin metadata is also supported for mods that do
        not encode their targets in paths.
        """
        try:
            stat = candidate.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            cached = self._affected_skin_cache.get(candidate)
            if cached and cached[:2] == signature:
                return cached[2]
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

            if champion_id is not None:
                try:
                    for asset_path in candidate.rglob("*"):
                        try:
                            parts = asset_path.relative_to(candidate).parts
                        except ValueError:
                            continue
                        for index, part in enumerate(parts[:-1]):
                            if part.casefold() != "skins":
                                continue
                            match = re.fullmatch(
                                r"skin[_-]?(\d+)",
                                parts[index + 1],
                                re.IGNORECASE,
                            )
                            if not match:
                                continue
                            suffix = int(match.group(1))
                            affected.add(
                                suffix if suffix >= 1000 else int(champion_id) * 1000 + suffix
                            )
                except OSError:
                    pass

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
            affected.add(int(storage_skin_id))

        result = tuple(sorted(affected))
        self._affected_skin_cache[candidate] = (signature[0], signature[1], result)
        return result

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


