#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A digest of a mod folder's content.

The mods staged in LTK Manager during the loadout countdown are reused by the
injection when they are the same: two folders Rose prepared from the same
files give the same digest, whatever their location or extraction time.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Files up to this size are hashed whole; larger ones (a map's or a
# voiceover's WAD) by their size and both ends, which is enough to tell apart
# two archives Rose extracted
_WHOLE_FILE_LIMIT = 4 * 1024 * 1024
_EDGE_BYTES = 1024 * 1024


def mod_fingerprint(folder: Path) -> str:
    """The digest of *folder*'s files (relative paths, sizes and content)."""
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(folder).as_posix()
        size = path.stat().st_size
        digest.update(f"{relative}\0{size}\0".encode("utf-8"))
        with open(path, "rb") as handle:
            if size <= _WHOLE_FILE_LIMIT:
                digest.update(handle.read())
            else:
                digest.update(handle.read(_EDGE_BYTES))
                handle.seek(size - _EDGE_BYTES)
                digest.update(handle.read(_EDGE_BYTES))
    return digest.hexdigest()
