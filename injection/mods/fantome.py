#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a .fantome archive from a mod folder.

Rose hands mods to LTK Manager's library as ``.fantome`` archives (see
injection/tools/bridge.py). Most are archives already and go as they are
(injection.mods.mod_files); a folder (``META/info.json`` + ``WAD/...`` +
``RAW/...``) is packed into one: the mods Rose writes itself, and the mods
stored before Rose kept archives, packed once when Rose starts
(injection.mods.storage).

The archive is the folder itself: ``WAD/`` and ``RAW/`` paths carry over
untouched, ``META/info.json`` keeps the name/author/version, and a
``metadata.json`` is added for consumers that read the LeagueToolkit header
instead. Both carry the same values, so it does not matter which one LTK
Manager prefers.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Optional

from utils.core.logging import get_logger

from .mod_files import ModFiles

log = get_logger()

_INFO_PATH = Path("META") / "info.json"
_METADATA_PATH = Path("metadata.json")
# Compression used by the .fantome files Rose ships and reads
_COMPRESSION = zipfile.ZIP_DEFLATED
# The archive only travels to LTK Manager's library on this PC, while the
# loading screen name's 24 MB text table took 0.46s to pack at the default
# level (0.20s at 1, for 4.1 MB instead of 3.3 MB): packing is on the way
# from a skin pick to the patcher's scan
_COMPRESS_LEVEL = 1
# A packed WAD (a .wad.client directly under WAD/ or WAD_<layer>/) is stored,
# not deflated: LTK Manager's own fantome writer does the same, since a reader
# seeks into a stored entry and has to inflate a deflated one whole. Its chunks
# are already compressed, so deflating saved 4% for 12x the time (a 3 GB
# voiceover pack took minutes to pack, every game: #425)
_PACKED_WAD = re.compile(r"^(?:WAD|WAD_[A-Za-z0-9_-]+)/[^/]+\.wad(?:\.client|\.mobile)?$", re.IGNORECASE)


def is_packed_wad(relative: str) -> bool:
    """Whether the archive entry *relative* is a packed WAD (a .wad.client
    directly under WAD/ or WAD_<layer>/), which a .fantome holds stored."""
    return bool(_PACKED_WAD.match(relative.replace("\\", "/")))


def _compression_for(relative: str) -> int:
    """How an entry is compressed: stored for a packed WAD, deflated otherwise."""
    return zipfile.ZIP_STORED if _PACKED_WAD.match(relative) else _COMPRESSION


def read_info(mod: Path) -> dict:
    """The META/info.json of a mod folder or archive ({} when missing or unreadable)."""
    try:
        with ModFiles(mod) as files:
            document = json.loads(files.read(_INFO_PATH.as_posix()).decode("utf-8-sig"))
        return document if isinstance(document, dict) else {}
    except (OSError, ValueError, zipfile.BadZipFile):
        return {}


def fantome_metadata(mod_folder: Path, name: Optional[str] = None) -> dict:
    """The LeagueToolkit metadata.json for *mod_folder*.

    Prefers an existing one (the folder came from a .fantome that had it),
    otherwise derives it from META/info.json, otherwise from *name* (the
    folder name by default).
    """
    existing = mod_folder / _METADATA_PATH
    try:
        document = json.loads(existing.read_text(encoding="utf-8"))
        if isinstance(document, dict) and document.get("name"):
            return document
    except (OSError, ValueError):
        pass

    info = read_info(mod_folder)
    name = str(info.get("Name") or "").strip() or name or mod_folder.name
    metadata = {"name": name}
    author = str(info.get("Author") or "").strip()
    if author:
        metadata["author"] = author
    version = str(info.get("Version") or "").strip()
    if version:
        metadata["version"] = version
    description = str(info.get("Description") or "").strip()
    if description:
        metadata["description"] = description
    return metadata


def write_fantome_zip(mod_folder: Path, dest: Path, metadata: bool = True, name: Optional[str] = None) -> Path:
    """Pack *mod_folder* into the .fantome archive *dest* and return it.

    metadata=False packs the folder's files and nothing else: the archive
    then holds what the folder did, the same content hash for a friend's
    copy (party.discovery.custom_mods). *name* is the mod's name when its
    META/info.json has none (the folder name by default).
    """
    if not mod_folder.is_dir():
        raise FileNotFoundError(f"mod folder not found: {mod_folder}")

    with zipfile.ZipFile(dest, "w", _COMPRESSION, compresslevel=_COMPRESS_LEVEL) as archive:
        for path in sorted(mod_folder.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(mod_folder).as_posix()
            if metadata and relative == _METADATA_PATH.as_posix():
                continue  # replaced by the normalized copy below
            archive.write(path, relative, compress_type=_compression_for(relative))
        if metadata:
            archive.writestr(
                _METADATA_PATH.as_posix(),
                json.dumps(fantome_metadata(mod_folder, name), ensure_ascii=False, indent=2),
            )
    log.debug(f"[FANTOME] Packed {mod_folder.name} -> {dest.name}")
    return dest


def fantome_display_name(mod: Path) -> Optional[str]:
    """The name a mod folder or archive shows up under in LTK Manager's library."""
    return str(read_info(mod).get("Name") or "").strip() or mod.name
