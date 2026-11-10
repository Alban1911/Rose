#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where a saved mod's files go in its folder: its archive under a name no
other mod of the folder holds, and its preview image and description beside
it under that name (<name>.png / <name>.webp, <name>.txt)."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Optional

from utils.core.atomic_file import atomic_write
from utils.core.logging import get_logger
from utils.core.safe_extract import MOD_ARCHIVE_SUFFIXES

from . import manifest as saved_manifest
from .mod_files import ModFiles

log = get_logger()

# MAX_PATH is 260 including the terminating null character, so keep the
# visible path at 259 characters or fewer for legacy Windows APIs.
MAX_WINDOWS_PATH_LENGTH = 259
# A stored mod's name is also its file name in the injection and LTK
# Manager's staging folders, which sit about as deep as the mods storage
MAX_MOD_NAME_LENGTH = 120
IMAGE_SIDECAR_SUFFIXES = (".png", ".webp")
DESCRIPTION_SIDECAR_SUFFIX = ".txt"
PREVIEW_IMAGES = (("META/image.png", ".png"), ("META/image.webp", ".webp"))
# Larger previews are not copied out of an archive (a broken or odd mod)
MAX_SIDECAR_IMAGE_BYTES = 32 * 1024 * 1024


def _occupied(path: Path) -> bool:
    """Whether something (a link included, even a broken one) is at *path*."""
    return path.exists() or path.is_symlink()


def sidecar_paths(stored: Path) -> list[Path]:
    """The files beside a stored archive that belong to it (preview image,
    description); none for a folder, which holds its own."""
    if stored.is_dir():
        return []
    return [stored.with_suffix(suffix) for suffix in (*IMAGE_SIDECAR_SUFFIXES, DESCRIPTION_SIDECAR_SUFFIX)]


def choose_archive_destination(mods_root: Path, parent_dir: Path, base_name: str) -> tuple[str, Path]:
    """Choose a unique mod name for an archive stored in *parent_dir* and
    return it with the archive's path (<parent_dir>/<name>.fantome).

    A name is taken by a stored mod (archive or folder), and by a saved
    mod's manifest entry or the image and description beside it under
    that name: once LTK Manager holds a mod, nothing else in the folder
    holds its name. One LTK Manager lost keeps it too, until the user
    deletes it: a mod added under its name is another mod.

    A long name is truncated only as much as Windows' traditional
    260-character path limit needs, then the normal `` (2)`` collision
    suffixes are added.
    """
    archive_suffix = saved_manifest.ARCHIVE_SUFFIX
    max_name_length = min(
        MAX_MOD_NAME_LENGTH,
        MAX_WINDOWS_PATH_LENGTH - len(str(parent_dir)) - 1 - len(archive_suffix),
    )
    if max_name_length < 1:
        raise ValueError("The mods folder's path is too long for Windows")

    original_name = base_name
    suffix_number = 1
    while True:
        suffix = "" if suffix_number == 1 else f" ({suffix_number})"
        available_name_length = max_name_length - len(suffix)
        if available_name_length < 1:
            raise ValueError(
                "Unable to create a unique Windows-safe name for "
                "the selected mod"
            )

        candidate_base = base_name[:available_name_length].rstrip(" .")
        if not candidate_base:
            raise ValueError(
                "The selected mod archive has no usable Windows-safe name"
            )
        mod_name = f"{candidate_base}{suffix}"
        archive = parent_dir / f"{mod_name}{archive_suffix}"
        taken = [parent_dir / mod_name, *(archive.with_suffix(s) for s in MOD_ARCHIVE_SUFFIXES),
                 *sidecar_paths(archive)]
        if (
            not any(_occupied(path) for path in taken)
            and saved_manifest.find_saved_mod(mods_root, archive, match_content=False) is None
        ):
            if mod_name != original_name:
                log.warning(
                    "[MODS] Shortened mod name for Windows path limit: '%s' -> '%s'",
                    original_name,
                    mod_name,
                )
            return mod_name, archive
        suffix_number += 1


def write_image_sidecar(archive: Path, beside: Optional[Path] = None) -> Optional[Path]:
    """Copy the archive's preview image beside it (beside *beside*, the
    path of a mod Rose does not store), for the mods UI, and return it: None
    when it has none to copy. Raises OSError when it cannot be written."""
    preview = _preview_image(archive)
    if preview is None:
        return None
    data, suffix = preview
    image = (beside or archive).with_suffix(suffix)
    with atomic_write(image, "wb", durable=False) as handle:
        handle.write(data)
    return image


def _preview_image(archive: Path) -> Optional[tuple[bytes, str]]:
    """The archive's preview image and its suffix; None when it has none,
    one too large, or cannot be read."""
    try:
        with ModFiles(archive) as files:
            for member, suffix in PREVIEW_IMAGES:
                if files.is_file(member):
                    data = files.read(member)
                    return (data, suffix) if 0 < len(data) <= MAX_SIDECAR_IMAGE_BYTES else None
    except (OSError, zipfile.BadZipFile) as exc:
        log.debug(f"[MODS] No preview image for {archive.name}: {exc}")
    return None
