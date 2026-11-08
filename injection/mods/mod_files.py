#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The files of a mod, whether Rose holds it as a folder or as an archive.

Rose keeps a mod as the .fantome it came in (a ZIP file) and LTK Manager
installs that archive as it is: unpacking it to pack it again took a minute
for a voiceover pack, every game. Only the mods Rose writes itself (the
loading screen name...) are folders, packed when they are installed.

In the injection's mods folder an archive is a hard link named as the mod's
folder would be, without an extension (utils.core.junction.link_or_extract),
so what reads a mod's files goes through ModFiles instead of walking a folder.
Paths compare as Windows compares a folder's: case-insensitively.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional

# A ZIP file starts with a local file header, or with the end of central
# directory record when it holds no file
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06")


def is_mod_archive(path: Path) -> bool:
    """Whether *path* is a mod archive (a ZIP file, whatever its name)."""
    try:
        with open(path, "rb") as handle:
            return handle.read(4) in _ZIP_SIGNATURES
    except OSError:  # missing, or a folder
        return False


def _key(relative: str) -> str:
    return str(relative).replace("\\", "/").strip("/").casefold()


def _prefix(folder: str) -> str:
    """What the paths under a folder start with ("" for the mod's root)."""
    key = _key(folder)
    return f"{key}/" if key else ""


def _stored_path(name: str) -> str:
    return name.replace("\\", "/").lstrip("/")


class ModFiles:
    """A mod's files by relative path ("WAD/Annie.wad.client").

    Opening an archive reads its central directory only; a file's bytes are
    read when asked for. Raises zipfile.BadZipFile for a file that is not a
    ZIP archive.
    """

    def __init__(self, mod: Path) -> None:
        self.mod = Path(mod)
        self._archive: Optional[zipfile.ZipFile] = None
        # casefolded path -> the archive's name for it
        self._entries: Dict[str, str] = {}
        if self.mod.is_file():
            self._archive = zipfile.ZipFile(self.mod)
            for info in self._archive.infolist():
                if not info.is_dir():
                    self._entries.setdefault(_key(info.filename), info.filename)

    def __enter__(self) -> "ModFiles":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        if self._archive is not None:
            self._archive.close()

    @property
    def is_archive(self) -> bool:
        return self._archive is not None

    def is_file(self, relative: str) -> bool:
        if self._archive is None:
            return (self.mod / relative).is_file()
        return _key(relative) in self._entries

    def is_dir(self, relative: str) -> bool:
        if self._archive is None:
            return (self.mod / relative).is_dir()
        prefix = _prefix(relative)
        return any(key.startswith(prefix) for key in self._entries)

    def children(self, relative: str = "") -> List[str]:
        """The names of the files and folders right under the folder *relative*."""
        if self._archive is None:
            try:
                return [path.name for path in (self.mod / relative).iterdir()]
            except OSError:
                return []
        prefix = _prefix(relative)
        names: Dict[str, str] = {}
        for key, name in self._entries.items():
            if key.startswith(prefix):
                child = _stored_path(name)[len(prefix):].split("/", 1)[0]
                names.setdefault(child.casefold(), child)
        return list(names.values())

    def files_under(self, relative: str = "") -> List[str]:
        """The relative paths of the files at any depth under the folder
        *relative* (the whole mod by default)."""
        if self._archive is None:
            folder = self.mod / relative
            try:
                return [path.relative_to(self.mod).as_posix() for path in folder.rglob("*") if path.is_file()]
            except OSError:
                return []
        prefix = _prefix(relative)
        return [_stored_path(name) for key, name in self._entries.items() if key.startswith(prefix)]

    def open(self, relative: str) -> BinaryIO:
        """A file's bytes as a stream (FileNotFoundError when there is none)."""
        if self._archive is None:
            return open(self.mod / relative, "rb")
        name = self._entries.get(_key(relative))
        if name is None:
            raise FileNotFoundError(f"{relative} is not in {self.mod.name}")
        return self._archive.open(name)

    def read(self, relative: str) -> bytes:
        with self.open(relative) as stream:
            return stream.read()
