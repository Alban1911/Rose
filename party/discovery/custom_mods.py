#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Custom Mod Matching
Identifies custom skin mods by content so party members can use their own
copy of a friend's mod. Mod files never leave the PC; only hashes are shared.
"""

import hashlib
import threading
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple

from utils.core.logging import get_logger
from utils.core.modpkg import MODPKG_SUFFIX, ModPackage
from utils.core.paths import get_user_data_dir
from utils.core.safe_extract import MOD_ARCHIVE_SUFFIXES

log = get_logger()

# Rose metadata stored next to mods, never part of a mod
_METADATA_FILES = {"rose_mod_targets.json"}

# path -> ((mtime_ns, size), content_hash, legacy_hash)
_hash_cache: Dict[str, Tuple[Tuple[int, int], Optional[str], Optional[str]]] = {}
_cache_lock = threading.Lock()


def get_mods_root() -> Path:
    return get_user_data_dir() / "mods"


def _content_digest(entries) -> str:
    """Hash (relative path, file digest) pairs the same way for folders and archives."""
    digest = hashlib.sha256()
    for relative_path, file_digest in sorted(entries, key=lambda e: e[0].casefold()):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest)
        digest.update(b"\0")
    return digest.hexdigest()[:32]


def _hash_stream(stream) -> bytes:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.digest()


def _folder_content_hash(folder: Path) -> Optional[str]:
    entries = []
    for file_path in folder.rglob("*"):
        if not file_path.is_file():
            continue
        with file_path.open("rb") as stream:
            entries.append((file_path.relative_to(folder).as_posix(), _hash_stream(stream)))
    return _content_digest(entries) if entries else None


def _archive_content_hash(archive_path: Path) -> Optional[str]:
    entries = []
    if archive_path.suffix.lower() == MODPKG_SUFFIX:
        # Hash the files the package unpacks to, as the imported folder holds them
        with ModPackage.open(archive_path) as package:
            for relative_path, content in package.iter_files():
                entries.append((relative_path, hashlib.sha256(content).digest()))
        return _content_digest(entries) if entries else None
    with zipfile.ZipFile(archive_path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            with archive.open(info) as stream:
                entries.append((info.filename.replace("\\", "/").lstrip("/"), _hash_stream(stream)))
    return _content_digest(entries) if entries else None


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
    """Find our copy of a friend's custom mod.

    Returns:
        Path relative to the mods root, or None if we don't have it.
    """
    if not champion_id or not (content_hash or legacy_hash):
        return None

    mods_root = get_mods_root()
    try:
        for entry in _champion_mod_entries(int(champion_id)):
            entry_content, entry_legacy = mod_hashes(entry)
            if (content_hash and entry_content == content_hash) or (
                legacy_hash and entry_legacy == legacy_hash
            ):
                return entry.relative_to(mods_root).as_posix()
    except OSError as e:
        log.debug(f"[PARTY] Error searching local mods: {e}")
    return None
