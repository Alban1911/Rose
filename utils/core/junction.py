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
from pathlib import Path
from typing import Union

from utils.core.logging import get_logger
from utils.core.safe_extract import MOD_ARCHIVE_SUFFIXES

log = get_logger()

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
# High-level entry point
# ---------------------------------------------------------------------------

def link_or_extract(source: Path, dest: Path) -> None:
    """Place mod content at *dest* using the fastest available method.

    * **Directory source**: create a junction from *dest* -> *source* (zero
      copy).  Falls back to ``shutil.copytree``.
    * **ZIP / fantome / modpkg source**: *dest* becomes a hard link to the
      archive, which LTK Manager installs as it is (see
      injection.mods.mod_files).
    * **Other file**: plain ``shutil.copy2`` into *dest*.
    """
    source = Path(source)
    dest = Path(dest)

    if source.is_dir():
        create_junction(source, dest)

    elif source.is_file() and source.suffix.lower() in MOD_ARCHIVE_SUFFIXES:
        link_file(source, dest)

    elif source.is_file():
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest / source.name)
        log.info(f"[JUNCTION] Copied file: {source.name} -> {dest}")

    else:
        log.warning(f"[JUNCTION] Source does not exist: {source}")
