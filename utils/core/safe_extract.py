#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safe Archive Extraction Utilities
Provides secure extraction of ZIP files with path traversal protection
"""

import io
import os
import zipfile
from pathlib import Path
from typing import List, Optional, Union

from utils.core.logging import get_logger
from utils.core.modpkg import MODPKG_SUFFIX, ModPackage, extract_modpkg

log = get_logger()

# Archives a custom mod can come in (.zip and .fantome are ZIP files)
MOD_ARCHIVE_SUFFIXES = (".zip", ".fantome", MODPKG_SUFFIX)


# Far above any real skin or map mod; an archive past these is a zip bomb or broken
MAX_ARCHIVE_ENTRIES = 200_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 16 * 1024 ** 3


class UnsafePathError(Exception):
    """Raised when a zip file contains paths that would escape the target directory"""
    pass


class ArchiveTooLargeError(UnsafePathError):
    """Raised when a zip file would unpack to more entries or bytes than any real mod"""


def _validate_members(zf: zipfile.ZipFile, dest_resolved: Path) -> None:
    """Refuse an archive with a path escaping dest_resolved or an absurd unpacked size.

    Sizes are the ones the archive declares; zipfile stops reading an entry at
    its declared size, so they bound what extraction can write.
    """
    members = zf.infolist()
    if len(members) > MAX_ARCHIVE_ENTRIES:
        log.error(f"[SECURITY] Blocked archive with {len(members)} entries")
        raise ArchiveTooLargeError(f"archive has {len(members)} entries (limit {MAX_ARCHIVE_ENTRIES})")
    total = sum(member.file_size for member in members)
    if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        log.error(f"[SECURITY] Blocked archive that unpacks to {total} bytes")
        raise ArchiveTooLargeError(
            f"archive unpacks to {total / 1024 ** 3:.1f} GiB (limit {MAX_ARCHIVE_UNCOMPRESSED_BYTES / 1024 ** 3:.0f} GiB)"
        )
    for member in members:
        target_path = dest_resolved / member.filename
        # Validate the path is safe (no path traversal)
        if not is_safe_path(dest_resolved, target_path):
            log.error(f"[SECURITY] Blocked unsafe path in archive: {member.filename}")
            raise UnsafePathError(
                f"Attempted path traversal detected: '{member.filename}' would extract outside target directory"
            )


def join_within(resolved_base: Path, relative_path: str) -> Optional[Path]:
    """Join *relative_path* to an already resolved base, or return None if it escapes the base.

    Purely lexical (no filesystem calls), for bulk extraction where resolving every entry is costly.
    """
    candidate = Path(os.path.normpath(resolved_base / relative_path))
    return candidate if candidate.is_relative_to(resolved_base) else None


def is_safe_path(base_dir: Path, target_path: Path) -> bool:
    """
    Check if target_path is safely contained within base_dir.
    Prevents path traversal attacks (e.g., ../../etc/passwd).

    Args:
        base_dir: The base directory that should contain the target
        target_path: The path to validate

    Returns:
        True if target_path is safely within base_dir, False otherwise
    """
    try:
        # Resolve both paths to absolute paths
        base_resolved = base_dir.resolve()
        target_resolved = target_path.resolve()

        # Compare path components: a string prefix check would accept sibling folders such as "skins-evil"
        return target_resolved.is_relative_to(base_resolved)
    except (OSError, ValueError):
        return False


def safe_extractall(zip_path: Union[str, Path], dest_dir: Union[str, Path]) -> None:
    """
    Safely extract all contents of a ZIP file to a destination directory.
    Validates each file path to prevent path traversal attacks (zip slip).

    Args:
        zip_path: Path to the ZIP file
        dest_dir: Destination directory for extraction

    Raises:
        UnsafePathError: If any file in the archive would be extracted outside dest_dir
            (ArchiveTooLargeError if it would unpack to an absurd size)
        zipfile.BadZipFile: If the file is not a valid ZIP
    """
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)

    # Ensure destination exists
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest_dir.resolve()

    with zipfile.ZipFile(zip_path, 'r') as zf:
        _validate_members(zf, dest_resolved)
        zf.extractall(dest_dir)
        log.debug(f"[EXTRACT] Safely extracted {len(zf.namelist())} files to {dest_dir}")


def safe_extractall_from_bytes(data: bytes, dest_dir: Union[str, Path]) -> None:
    """
    Safely extract all contents of in-memory ZIP data to a destination directory.
    Validates each file path to prevent path traversal attacks (zip slip).

    Args:
        data: Raw ZIP file contents as bytes
        dest_dir: Destination directory for extraction

    Raises:
        UnsafePathError: If any file in the archive would be extracted outside dest_dir
        zipfile.BadZipFile: If the data is not a valid ZIP
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest_dir.resolve()

    with zipfile.ZipFile(io.BytesIO(data), 'r') as zf:
        _validate_members(zf, dest_resolved)
        zf.extractall(dest_dir)
        log.debug(f"[EXTRACT] Safely extracted {len(zf.namelist())} files from memory to {dest_dir}")


def safe_extract(zip_path: Union[str, Path], member: str, dest_dir: Union[str, Path]) -> Path:
    """
    Safely extract a single member from a ZIP file.
    Validates the path to prevent path traversal attacks.

    Args:
        zip_path: Path to the ZIP file
        member: Name of the member to extract
        dest_dir: Destination directory for extraction

    Returns:
        Path to the extracted file

    Raises:
        UnsafePathError: If the member would be extracted outside dest_dir
        KeyError: If member is not in the archive
    """
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest_dir.resolve()

    # Construct and validate target path
    target_path = dest_resolved / member

    if not is_safe_path(dest_resolved, target_path):
        log.error(f"[SECURITY] Blocked unsafe path extraction: {member}")
        raise UnsafePathError(
            f"Attempted path traversal detected: '{member}' would extract outside target directory"
        )

    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extract(member, dest_dir)
        log.debug(f"[EXTRACT] Safely extracted {member} to {dest_dir}")

    return target_path


def list_mod_archive(archive_path: Union[str, Path]) -> List[str]:
    """Relative paths of the files extracting a mod archive creates."""
    archive_path = Path(archive_path)
    if archive_path.suffix.lower() == MODPKG_SUFFIX:
        with ModPackage.open(archive_path) as package:
            return package.file_paths()
    with zipfile.ZipFile(archive_path, 'r') as zf:
        return [info.filename for info in zf.infolist() if not info.is_dir()]


def extract_mod_archive(archive_path: Union[str, Path], dest_dir: Union[str, Path]) -> None:
    """Extract a .zip/.fantome mod archive, or unpack a .modpkg, into dest_dir."""
    if Path(archive_path).suffix.lower() == MODPKG_SUFFIX:
        extract_modpkg(archive_path, dest_dir)
    else:
        safe_extractall(archive_path, dest_dir)
