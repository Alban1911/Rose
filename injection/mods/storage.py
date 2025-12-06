#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mod storage service
Handles mods organized by category: skins, maps, fonts, announcers, others
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir
from utils.core.utilities import get_champion_id_from_skin_id

log = get_logger()


@dataclass(frozen=True)
class SkinModEntry:
    """Metadata for a mod inside mods/skins/{skin_id}"""

    champion_id: Optional[int]
    skin_id: int
    mod_name: str
    path: Path
    updated_at: float
    description: Optional[str] = None


class ModStorageService:
    """Service exposing the on-disk mods hierarchy."""

    CATEGORY_SKINS = "skins"
    CATEGORY_MAPS = "maps"
    CATEGORY_FONTS = "fonts"
    CATEGORY_ANNOUNCERS = "announcers"
    CATEGORY_OTHERS = "others"

    def __init__(self, mods_root: Optional[Path] = None):
        self.mods_root = mods_root or (get_user_data_dir() / "mods")
        self.mods_root.mkdir(parents=True, exist_ok=True)
        # Create all mod category folders
        (self.mods_root / self.CATEGORY_SKINS).mkdir(parents=True, exist_ok=True)
        (self.mods_root / self.CATEGORY_MAPS).mkdir(parents=True, exist_ok=True)
        (self.mods_root / self.CATEGORY_FONTS).mkdir(parents=True, exist_ok=True)
        (self.mods_root / self.CATEGORY_ANNOUNCERS).mkdir(parents=True, exist_ok=True)
        (self.mods_root / self.CATEGORY_OTHERS).mkdir(parents=True, exist_ok=True)

    @property
    def skins_dir(self) -> Path:
        return self.mods_root / self.CATEGORY_SKINS

    def get_skin_dir(self, skin_id: int | str) -> Path:
        return self.skins_dir / str(skin_id)

    def list_mods_for_skin(self, skin_id: int | str) -> List[SkinModEntry]:
        skin_dir = self.get_skin_dir(skin_id)
        if not skin_dir.exists() or not skin_dir.is_dir():
            return []

        skin_id_int = self._to_int(skin_id)
        if skin_id_int is None:
            return []

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

            entries.append(
                SkinModEntry(
                    champion_id=champion_id,
                    skin_id=skin_id_int,
                    mod_name=mod_name,
                    path=candidate,
                    updated_at=updated_at,
                    description=self._read_mod_description(candidate),
                )
            )

        return entries

    def has_mods_for_skin(self, skin_id: int | str) -> bool:
        return bool(self.list_mods_for_skin(skin_id))

    def list_mods_for_category(self, category: str) -> List[dict]:
        """List all mods in a category (maps, fonts, announcers, others)
        
        Args:
            category: One of CATEGORY_MAPS, CATEGORY_FONTS, CATEGORY_ANNOUNCERS, CATEGORY_OTHERS
            
        Returns:
            List of mod dictionaries with name, path, updated_at, description
        """
        if category not in {self.CATEGORY_MAPS, self.CATEGORY_FONTS, self.CATEGORY_ANNOUNCERS, self.CATEGORY_OTHERS}:
            return []
        
        category_dir = self.mods_root / category
        if not category_dir.exists() or not category_dir.is_dir():
            return []
        
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


