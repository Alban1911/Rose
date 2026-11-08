#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Custom Mod Matching
Identifies custom skin mods by content so party members can use their own
copy of a friend's mod. Mod files never leave the PC; only hashes are shared.
"""

import threading
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple

from injection.mods.mod_facts import (
    _archive_content_hash,
    _content_digest,
    _folder_content_hash,
    _hash_stream,
    _is_preview_image,
)
from injection.mods.manifest import SKINS, find_saved_mod, iter_saved_mods
from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir
from utils.core.safe_extract import MOD_ARCHIVE_SUFFIXES

log = get_logger()

# Rose metadata stored next to mods, never part of a mod
_METADATA_FILES = {"rose_mod_targets.json"}

# path -> ((mtime_ns, size), content_hash, legacy_hash)
_hash_cache: Dict[str, Tuple[Tuple[int, ...], Optional[str], Optional[str]]] = {}
_cache_lock = threading.Lock()


def get_mods_root() -> Path:
    return get_user_data_dir() / "mods"


def _legacy_archive_hash(archive_path: Path) -> str:
    """Whole-file hash sent by older Rose versions for archive mods."""
    with archive_path.open("rb") as stream:
        return _hash_stream(stream).hex()[:16]


def mod_hashes(mod_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """Return (content hash, legacy archive hash) of a custom mod folder or archive.

    The content hash is the same for an archive and its extracted folder.
    The legacy hash only exists for archives. Results are cached per file.
    """
    try:
        stat = mod_path.stat()
    except OSError:
        return None, None

    key = str(mod_path)
    if mod_path.is_dir():
        image_path = mod_path / "META" / "image.png"
        try:
            image_stat = image_path.stat()
            image_stamp = (image_stat.st_mtime_ns, image_stat.st_size)
        except OSError:
            image_stamp = (0, 0)
        stamp = (stat.st_mtime_ns, stat.st_size, *image_stamp)
    else:
        stamp = (stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        cached = _hash_cache.get(key)
    if cached and cached[0] == stamp:
        return cached[1], cached[2]

    content_hash = legacy_hash = None
    try:
        if mod_path.is_dir():
            content_hash = _folder_content_hash(mod_path)
        elif mod_path.suffix.lower() in MOD_ARCHIVE_SUFFIXES:
            legacy_hash = _legacy_archive_hash(mod_path)
            content_hash = _archive_content_hash(mod_path)
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        log.debug(f"[PARTY] Failed to hash custom mod {mod_path}: {e}")

    with _cache_lock:
        _hash_cache[key] = (stamp, content_hash, legacy_hash)
    return content_hash, legacy_hash


def _stored_path(path: Path) -> Path:
    """*path*, or the .fantome a mod saved as a folder by an older Rose was
    packed into (the pick still names the folder)."""
    archive = path.with_name(path.name + ".fantome")
    return archive if not path.exists() and archive.is_file() else path


def saved_mod_hashes(relative_path: str) -> Tuple[Optional[str], Optional[str]]:
    """(content hash, legacy hash) our pick of a saved mod shares with the
    party. A mod LTK Manager holds is injected from its library entry: its
    manifest's partyHash is the content hash, and there is no whole-file hash
    for older Roses. A pending mod's copy is hashed (mod_hashes, cached by the
    file). Nothing for a mod we cannot inject ourselves.

    Party mode asks every second: the mod is found without matching a renamed
    file to its entry by content, which reads the whole mod (a renamed file
    is hashed as itself)."""
    mods_root = get_mods_root()
    saved = find_saved_mod(mods_root, relative_path, match_content=False)
    if saved is None:
        return mod_hashes(_stored_path(mods_root / relative_path))
    if not saved.available:
        return None, None
    if saved.ltk_id:
        return (saved.facts.party_hash if saved.facts else None), None
    return mod_hashes(saved.rose_copy)


def _champion_mod_entries(champion_id: int):
    """Custom mods stored for a champion (champion folder and legacy per-skin folders)."""
    skins_dir = get_mods_root() / "skins"
    if not skins_dir.is_dir():
        return
    for skin_dir in skins_dir.iterdir():
        try:
            storage_id = int(skin_dir.name)
        except ValueError:
            continue
        if storage_id // 1000 != champion_id or not skin_dir.is_dir():
            continue
        for entry in skin_dir.iterdir():
            if entry.name in _METADATA_FILES:
                continue
            if entry.is_dir() or entry.suffix.lower() in MOD_ARCHIVE_SUFFIXES:
                yield entry


def find_local_mod(
    champion_id: int,
    content_hash: Optional[str] = None,
    legacy_hash: Optional[str] = None,
) -> Optional[str]:
    """Find our copy of a friend's custom mod: first by the partyHash our
    saved mods' manifests keep (one LTK Manager holds has no file in Rose to
    hash), then by hashing the files Rose still holds, as friends on older
    Roses may send only an archive's whole-file hash.

    Returns:
        Path relative to the mods root, or None if we don't have it.
    """
    if not champion_id or not (content_hash or legacy_hash):
        return None

    mods_root = get_mods_root()
    try:
        if content_hash:
            for saved in iter_saved_mods(mods_root, SKINS, champion_id=int(champion_id)):
                if saved.available and saved.facts and saved.facts.party_hash == content_hash:
                    return saved.identity
        for entry in _champion_mod_entries(int(champion_id)):
            entry_content, entry_legacy = mod_hashes(entry)
            if (content_hash and entry_content == content_hash) or (
                legacy_hash and entry_legacy == legacy_hash
            ):
                return entry.relative_to(mods_root).as_posix()
    except OSError as e:
        log.debug(f"[PARTY] Error searching local mods: {e}")
    return None
