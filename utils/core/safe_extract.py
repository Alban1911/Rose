#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safe Archive Extraction Utilities
Provides secure extraction of ZIP files with path traversal protection
"""

import zipfile
from pathlib import Path
from typing import Union

from utils.core.logging import get_logger

log = get_logger()


class UnsafePathError(Exception):
    """Raised when a zip file contains paths that would escape the target directory"""
    pass


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

        # Check if target is within base directory
        return str(target_resolved).startswith(str(base_resolved))
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
        zipfile.BadZipFile: If the file is not a valid ZIP
    """
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)

    # Ensure destination exists
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest_dir.resolve()

    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.namelist():
            # Construct the target path
            target_path = dest_resolved / member

            # Validate the path is safe (no path traversal)
            if not is_safe_path(dest_resolved, target_path):
                log.error(f"[SECURITY] Blocked unsafe path in archive: {member}")
                raise UnsafePathError(
                    f"Attempted path traversal detected: '{member}' would extract outside target directory"
                )

        # All paths validated, safe to extract
        zf.extractall(dest_dir)
        log.debug(f"[EXTRACT] Safely extracted {len(zf.namelist())} files to {dest_dir}")


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
