#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mod storage service
Handles the structured mods hierarchy described by /mods/{skins,maps,fonts,announcers}
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir

log = get_logger()


@dataclass(frozen=True)
class SkinModEntry:
    """Metadata for a single custom mod placed under skins/{champ}/{skin}"""

    champion_id: int
    skin_id: int
    mod_name: str
    path: Path
    updated_at: float
    description: Optional[str] = None


class ModStorageService:
    """Service that exposes the on-disk mods hierarchy to the rest of the app."""

    CATEGORY_ANNOUNCERS = "announcers"
    CATEGORY_FONTS = "fonts"
    CATEGORY_MAPS = "maps"
    CATEGORY_SKINS = "skins"

    def __init__(self, mods_root: Optional[Path] = None):
        self.mods_root = mods_root or (get_user_data_dir() / "mods")
        self.mods_root.mkdir(parents=True, exist_ok=True)
        for category in self._category_names():
            (self.mods_root / category).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _category_names() -> List[str]:
        return [
            ModStorageService.CATEGORY_ANNOUNCERS,
            ModStorageService.CATEGORY_FONTS,
            ModStorageService.CATEGORY_MAPS,
            ModStorageService.CATEGORY_SKINS,
        ]

    def list_categories(self) -> List[str]:
        return self._category_names()

    def get_category_path(self, category: str) -> Path:
        return self.mods_root / category

    @property
    def skins_dir(self) -> Path:
        return self.get_category_path(self.CATEGORY_SKINS)

    def list_champion_ids(self) -> List[int]:
        return self._list_numeric_dirs(self.skins_dir)

    def list_skin_ids(self, champion_id: int | str) -> List[int]:
        champion_dir = self.skins_dir / str(champion_id)
        return self._list_numeric_dirs(champion_dir)

    def list_mod_names(self, champion_id: int | str, skin_id: int | str) -> List[str]:
        skin_dir = self._get_skin_dir(champion_id, skin_id)
        if not skin_dir.exists():
            return []
        mod_dirs = sorted(
            [p for p in skin_dir.iterdir() if p.is_dir()],
            key=lambda p: p.name.lower(),
        )
        return [p.name for p in mod_dirs]

    def list_mods_for_skin(self, champion_id: int | str, skin_id: int | str) -> List[SkinModEntry]:
        skin_dir = self._get_skin_dir(champion_id, skin_id)
        if not skin_dir.exists():
            return []

        entries: List[SkinModEntry] = []
        champion_id_int = self._to_int(champion_id)
        skin_id_int = self._to_int(skin_id)
        if champion_id_int is None or skin_id_int is None:
            return []

        for mod_dir in sorted(
            [p for p in skin_dir.iterdir() if p.is_dir()],
            key=lambda p: p.name.lower(),
        ):
            try:
                updated_at = mod_dir.stat().st_mtime
            except OSError:
                updated_at = 0.0

            entry = SkinModEntry(
                champion_id=champion_id_int,
                skin_id=skin_id_int,
                mod_name=mod_dir.name,
                path=mod_dir,
                updated_at=updated_at,
                description=self._read_mod_description(mod_dir),
            )
            entries.append(entry)

        return entries

    def scan_skin_catalog(self) -> dict[int, dict[int, List[SkinModEntry]]]:
        """
        Scan the entire skins hierarchy and return a nested catalog.
        Useful for UI components that need to enumerate everything.
        """
        catalog: dict[int, dict[int, List[SkinModEntry]]] = {}
        for champ_id in self.list_champion_ids():
            champion_map: dict[int, List[SkinModEntry]] = {}
            for skin_id in self.list_skin_ids(champ_id):
                mods = self.list_mods_for_skin(champ_id, skin_id)
                if mods:
                    champion_map[skin_id] = mods
            if champion_map:
                catalog[champ_id] = champion_map
        return catalog

    def _get_skin_dir(self, champion_id: int | str, skin_id: int | str) -> Path:
        return self.skins_dir / str(champion_id) / str(skin_id)

    @staticmethod
    def _list_numeric_dirs(base: Path) -> List[int]:
        if not base.exists():
            return []

        ids: List[int] = []
        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            entry_id = ModStorageService._to_int(entry.name)
            if entry_id is None:
                continue
            ids.append(entry_id)

        return sorted(ids)

    @staticmethod
    def _to_int(value: int | str) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _read_mod_description(mod_dir: Path) -> Optional[str]:
        description_file = mod_dir / "description.txt"
        if not description_file.exists():
            return None
        try:
            return description_file.read_text(encoding="utf-8").strip()
        except Exception as exc:
            log.debug(f"[ModStorage] Unable to read descriptor {description_file}: {exc}")
            return None


