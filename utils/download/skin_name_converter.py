#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Name Converter
Converts name-based skin paths (ChampName/SkinName/...) to ID-based paths
({champ_id}/{skin_id}/{skin_id}.zip) using skin_ids.json from the repo ZIP.
"""

import json
import zipfile
from pathlib import Path
from typing import Optional


class SkinNameConverter:
    """Converts skin paths from human-readable names to ID-based paths."""

    SKIN_IDS_PATH = "LeagueSkins-main/resources/default/skin_ids.json"

    # Characters that are invalid in Windows file paths and get stripped from
    # repository folder/file names.
    _FS_INVALID_CHARS = str.maketrans("", "", '/\\:*?"<>|')

    @staticmethod
    def _normalize(name: str) -> str:
        """Normalize a skin name for filesystem-safe comparison.

        Lowercases, removes filesystem-invalid characters (/ \\ : * ? \" < > |),
        and strips trailing periods/spaces (Windows strips these from folder names).
        """
        return name.lower().translate(SkinNameConverter._FS_INVALID_CHARS).rstrip(". ")

    def __init__(self, mapping_data: dict[str, str]) -> None:
        """Build reverse lookups from raw skin_ids.json mapping.

        Args:
            mapping_data: Raw JSON mapping {skin_id_str: skin_name}.
        """
        self._name_to_id: dict[str, int] = {}
        self._champion_name_to_id: dict[str, int] = {}

        for skin_id_str, name in mapping_data.items():
            try:
                skin_id = int(skin_id_str)
            except (TypeError, ValueError):
                continue
            original = (name or "").strip()
            normalized = self._normalize(original)
            if not normalized:
                continue
            if normalized not in self._name_to_id:
                self._name_to_id[normalized] = skin_id
            if skin_id % 1000 == 0 and normalized not in self._champion_name_to_id:
                self._champion_name_to_id[normalized] = skin_id // 1000

    @classmethod
    def from_zip(cls, zip_ref: zipfile.ZipFile) -> Optional["SkinNameConverter"]:
        """Load skin_ids.json from the repository ZIP and return a converter.

        Args:
            zip_ref: Open ZipFile for the LeagueSkins repository.

        Returns:
            SkinNameConverter instance, or None if file missing/invalid/empty.
        """
        if cls.SKIN_IDS_PATH not in zip_ref.namelist():
            return None
        try:
            data = json.loads(zip_ref.read(cls.SKIN_IDS_PATH).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
            return None
        if not isinstance(data, dict) or not data:
            return None
        return cls(data)

    def convert_path(self, name_path: str) -> Optional[str]:
        """Convert a name-based relative path to an ID-based path.

        Supports:
        - 3 parts: ChampName/SkinName/SkinName.zip -> {champ_id}/{skin_id}/{skin_id}.zip
        - 4 parts: ChampName/SkinName/ChromaName/ChromaName.zip -> {champ_id}/{skin_id}/{chroma_id}/{chroma_id}.zip

        Args:
            name_path: Path after stripping 'skins/' (e.g. Aatrox/Blood Moon Aatrox/Blood Moon Aatrox.zip).

        Returns:
            ID-based path with forward slashes, or None if any lookup fails or path has wrong number of parts.
        """
        path_str = name_path.replace("\\", "/")
        parts = [p for p in path_str.split("/") if p]
        if len(parts) < 3 or len(parts) > 4:
            return None

        champ_key = self._normalize(parts[0])
        skin_key = self._normalize(parts[1])
        champ_id = self._champion_name_to_id.get(champ_key)
        skin_id = self._name_to_id.get(skin_key)
        if champ_id is None or skin_id is None:
            return None

        suffix = Path(parts[-1]).suffix or ""

        if len(parts) == 3:
            return f"{champ_id}/{skin_id}/{skin_id}{suffix}"
        chroma_key = self._normalize(parts[2])
        chroma_id = self._name_to_id.get(chroma_key)
        if chroma_id is None:
            return None
        return f"{champ_id}/{skin_id}/{chroma_id}/{chroma_id}{suffix}"
