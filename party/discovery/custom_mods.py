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

# The content hash is also a saved mod's partyHash, computed once when it is
# added (injection.mods.mod_facts): one algorithm for both
from injection.mods.mod_facts import (  # noqa: F401 - _content_digest, _is_preview_image re-exported
    _archive_content_hash,
    _content_digest,
    _folder_content_hash,
    _hash_stream,
    _is_preview_image,
)
from injection.mods.manifest import SKINS, TARGET_METADATA, find_saved_mod, iter_saved_mods
from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir
from utils.core.safe_extract import MOD_ARCHIVE_SUFFIXES

log = get_logger()

# Rose metadata stored next to mods, never part of a mod
_METADATA_FILES = {"rose_mod_targets.json"}

# path -> ((mtime_ns, size), content_hash, legacy_hash)
_hash_cache: Dict[str, Tuple[Tuple[int, ...], Optional[str], Optional[str]]] = {}
# saved mod's path -> ((its manifest's stamp, its file's stamp), content_hash, legacy_hash)
_saved_hash_cache: Dict[str, Tuple[tuple, Optional[str], Optional[str]]] = {}
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


def _file_stamp(path: Path) -> Tuple[int, ...]:
    try:
        stat = path.stat()
    except OSError:
        return ()
    return (stat.st_mtime_ns, stat.st_size)


def saved_mod_hashes(relative_path: str) -> Tuple[Optional[str], Optional[str]]:
    """(content hash, legacy hash) our pick of a saved mod shares with the
    party. A mod LTK Manager holds is injected from its library entry: its
    manifest's partyHash is the content hash, and there is no whole-file hash
    for older Roses. A pending mod's copy is hashed (mod_hashes). Nothing for
    a mod we cannot inject ourselves.

    Cached until its manifest or file changes: party mode asks every second,
    and finding the entry of a renamed pending mod reads the whole mod."""
    mods_root = get_mods_root()
    identity = mods_root / relative_path
    key = str(identity)
    stamp = (_file_stamp(identity.parent / TARGET_METADATA), _file_stamp(identity))
    with _cache_lock:
        cached = _saved_hash_cache.get(key)
    if cached and cached[0] == stamp:
        return cached[1], cached[2]

    saved = find_saved_mod(mods_root, relative_path)
    if saved is None:
        hashes = mod_hashes(identity)
    elif not saved.available:
        hashes = None, None
    elif saved.ltk_id:
        hashes = (saved.facts.party_hash if saved.facts else None), None
    else:
        hashes = mod_hashes(saved.stored)

    with _cache_lock:
        _saved_hash_cache[key] = (stamp, *hashes)
    return hashes


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
                    return saved.relative_path
        for entry in _champion_mod_entries(int(champion_id)):
            entry_content, entry_legacy = mod_hashes(entry)
            if (content_hash and entry_content == content_hash) or (
                legacy_hash and entry_legacy == legacy_hash
            ):
                return entry.relative_to(mods_root).as_posix()
    except OSError as e:
        log.debug(f"[PARTY] Error searching local mods: {e}")
    return None
