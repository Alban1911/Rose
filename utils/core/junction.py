#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Junction Utilities for Windows
Provides directory junctions and file hard links to avoid copying large mods
on every injection. Falls back to copying when neither is available.
"""

import os
import shutil
import stat
import threading
from pathlib import Path
from typing import Dict, Union

from utils.core.logging import get_logger
from utils.core.modpkg import MODPKG_SUFFIX
from utils.core.safe_extract import MOD_ARCHIVE_SUFFIXES, extract_mod_archive

log = get_logger()

# One extraction at a time per cached folder: the loadout countdown stages a
# mod while the injection may already link the same one, and a second
# extraction would remove the folder the first one is still writing
_cache_locks: Dict[str, threading.Lock] = {}
_cache_locks_guard = threading.Lock()


def _cache_lock(cached: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(cached))
    with _cache_locks_guard:
        return _cache_locks.setdefault(key, threading.Lock())


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def is_junction(path: Union[str, Path]) -> bool:
    """Detect whether *path* is a Windows junction (reparse point).

    Uses ``os.stat`` with ``follow_symlinks=False`` to read
    ``st_file_attributes`` which includes ``FILE_ATTRIBUTE_REPARSE_POINT``.
    Returns ``False`` on non-Windows platforms or if the path doesn't exist.
    """
    path = Path(path)
    try:
        # os.lstat does not follow symlinks/junctions
        st = os.lstat(path)
        attrs = getattr(st, "st_file_attributes", 0)
        # FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
        return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

def create_junction(source: Path, link: Path) -> bool:
    """Create a Windows directory junction at *link* pointing to *source*.

    Returns ``True`` on success.  Falls back to ``shutil.copytree`` and
    returns ``False`` if the junction cannot be created (non-Windows, missing
    API, etc.).
    """
    source = Path(source).resolve()
    link = Path(link)

    try:
        import _winapi  # type: ignore[import-not-found]
        _winapi.CreateJunction(str(source), str(link))
        log.info(f"[JUNCTION] Created junction: {link} -> {source}")
        return True
    except Exception as exc:
        log.warning(f"[JUNCTION] CreateJunction failed ({exc}), falling back to copytree")
        try:
            shutil.copytree(source, link, dirs_exist_ok=True)
            log.info(f"[JUNCTION] Fallback copytree: {source} -> {link}")
        except Exception as copy_exc:
            log.error(f"[JUNCTION] Fallback copytree also failed: {copy_exc}")
        return False


def link_file(source: Path, link: Path) -> bool:
    """Make *link* a hard link to the file *source*, or a copy of it.

    A hard link takes no time and no space, whatever the file's size: an
    archive goes to LTK Manager as it is stored. Rose's data folder is on one
    drive, so a copy only happens on a file system without hard links.
    Returns True for a link. Nothing may write into *link*: it is *source*.
    """
    source, link = Path(source), Path(link)
    try:
        os.link(source, link)
        return True
    except OSError as exc:
        log.debug(f"[JUNCTION] Could not hard link {source.name} ({exc}), copying it")
    shutil.copyfile(source, link)
    return False


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------

def safe_remove_entry(path: Union[str, Path]) -> None:
    """Remove *path* safely, handling junctions and regular dirs/files.

    * **Junction / symlink**: removed with ``os.rmdir`` which deletes the
      link itself without following it or touching the target.
    * **Directory**: removed with ``shutil.rmtree(ignore_errors=True)``.
    * **File**: removed with ``os.unlink``.
    """
    path = Path(path)

    if is_junction(path):
        try:
            os.rmdir(path)  # removes junction point only
            log.debug(f"[JUNCTION] Removed junction: {path}")
        except OSError as exc:
            log.warning(f"[JUNCTION] Failed to remove junction {path}: {exc}")
        return

    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return

    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Cache helpers for mod archives (ZIP / fantome / modpkg)
# ---------------------------------------------------------------------------

def _get_or_extract_to_cache(
    zip_path: Path,
    folder_name: str,
    cache_dir: Path,
) -> Path:
    """Return a cached extraction of *zip_path* inside *cache_dir*.

    The cache key is ``folder_name``.  The cached copy is invalidated when the
    source file's ``mtime`` changes (e.g. the user replaces the ZIP with an
    updated version).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / folder_name

    # Check mtime stamp file
    stamp = cache_dir / f"{folder_name}.mtime"
    try:
        source_mtime = str(zip_path.stat().st_mtime)
    except OSError:
        source_mtime = ""

    # A caller arriving while another extracts waits, then finds the cache
    with _cache_lock(cached):
        needs_extract = True
        if cached.is_dir() and stamp.exists():
            try:
                stored_mtime = stamp.read_text().strip()
                if stored_mtime == source_mtime:
                    needs_extract = False
                    log.debug(f"[JUNCTION] Cache hit for {folder_name}")
            except OSError:
                pass

        if needs_extract:
            # Remove stale cache
            if cached.exists() or is_junction(cached):
                safe_remove_entry(cached)
            cached.mkdir(parents=True, exist_ok=True)

            log.info(f"[JUNCTION] Extracting {zip_path.name} to cache: {cached}")
            extract_mod_archive(zip_path, cached)

            # Write mtime stamp
            try:
                stamp.write_text(source_mtime)
            except OSError:
                pass

    return cached


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def link_or_extract(
    source: Path,
    dest: Path,
    cache_dir: Path,
) -> None:
    """Place mod content at *dest* using the fastest available method.

    * **Directory source**: create a junction from *dest* -> *source* (zero
      copy).  Falls back to ``shutil.copytree``.
    * **ZIP / fantome source**: *dest* becomes a hard link to the archive,
      which LTK Manager installs as it is (see injection.mods.mod_files).
    * **modpkg source**: extract once into *cache_dir*, then junction
      *dest* -> cached directory.  Subsequent calls are instant.
    * **Other file**: plain ``shutil.copy2`` into *dest*.
    """
    source = Path(source)
    dest = Path(dest)

    if source.is_dir():
        create_junction(source, dest)

    elif source.is_file() and source.suffix.lower() in MOD_ARCHIVE_SUFFIXES and source.suffix.lower() != MODPKG_SUFFIX:
        link_file(source, dest)

    elif source.is_file() and source.suffix.lower() == MODPKG_SUFFIX:
        folder_name = source.stem
        cached = _get_or_extract_to_cache(source, folder_name, cache_dir)
        create_junction(cached, dest)

    elif source.is_file():
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest / source.name)
        log.info(f"[JUNCTION] Copied file: {source.name} -> {dest}")

    else:
        log.warning(f"[JUNCTION] Source does not exist: {source}")
