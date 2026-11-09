#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import shutil
import stat
import struct
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator, Mapping, Optional

import xxhash

from utils.core.modpkg import MODPKG_SUFFIX, ModPackage, extract_modpkg
from utils.core.paths import get_injection_dir

from .mod_files import ModFiles

PARTY_HASH_LENGTH = 32
_FACTS_SCRATCH = "mod_facts"
_UNPACKED_PREFIX = "facts-"
TABLE_HASH = xxhash.xxh64_intdigest(b"data/menu/en_us/lol.stringtable")



def _full_content_digest(entries) -> str:
    """Hash (relative path, file digest) pairs the same way for folders and
    archives: the whole hex digest is the manifest's folderHash."""
    digest = hashlib.sha256()
    for relative_path, file_digest in sorted(entries, key=lambda e: e[0].casefold()):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest)
        digest.update(b"\0")
    return digest.hexdigest()


def _content_digest(entries) -> str:
    """Hash (relative path, file digest) pairs the same way for folders and archives."""
    return _full_content_digest(entries)[:PARTY_HASH_LENGTH]


def _hash_stream(stream) -> bytes:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.digest()


def _is_preview_image(relative_path: str) -> bool:
    return relative_path.replace("\\", "/").casefold() == "meta/image.png"


def _folder_content_hash(folder: Path) -> Optional[str]:
    entries = []
    for file_path in folder.rglob("*"):
        if not file_path.is_file():
            continue
        relative_path = file_path.relative_to(folder).as_posix()
        if _is_preview_image(relative_path):
            continue
        with file_path.open("rb") as stream:
            entries.append((relative_path, _hash_stream(stream)))
    return _content_digest(entries) if entries else None


def _modpkg_unpacked_entries(package_path: Path) -> list:
    """(relative path, file digest) of the files a .modpkg unpacks to, as the
    folder it is imported as holds them."""
    entries = []
    with ModPackage.open(package_path) as package:
        for relative_path, content in package.iter_files():
            if _is_preview_image(relative_path):
                continue
            entries.append((relative_path, hashlib.sha256(content).digest()))
    return entries


def _archive_content_hash(archive_path: Path) -> Optional[str]:
    if archive_path.suffix.lower() == MODPKG_SUFFIX:
        entries = _modpkg_unpacked_entries(archive_path)
        return _content_digest(entries) if entries else None
    entries = []
    with zipfile.ZipFile(archive_path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative_path = info.filename.replace("\\", "/").lstrip("/")
            if _is_preview_image(relative_path):
                continue
            with archive.open(info) as stream:
                entries.append((relative_path, _hash_stream(stream)))
    return _content_digest(entries) if entries else None



@dataclass(frozen=True)
class ModFacts:
    """The answers about a mod that used to need its files: whether it
    carries its own language table (loading_name.ships_language_table), which
    a loading screen name built beside it would compete with.

    Hashable: an injection plan (injection.core.stage_plan.ModStep) carries
    them, and plans are compared by equality.
    """

    ships_language_table: bool

    @classmethod
    def unknown(cls) -> "ModFacts":
        """What the loading screen name takes a mod LTK Manager holds for when
        its manifest lacks the facts: one that may carry the text table the
        name's own would compete with."""
        return cls(ships_language_table=True)

    def to_manifest(self) -> dict:
        return {"shipsLanguageTable": self.ships_language_table}

    @classmethod
    def from_manifest(cls, m: object) -> Optional["ModFacts"]:
        """The facts of a manifest entry, or None when it does not hold them,
        well typed: an entry written by an older Rose has none, and a reader
        must then fall back on the mod's files or safe defaults."""
        ships = m.get("shipsLanguageTable") if isinstance(m, Mapping) else None
        return cls(ships) if isinstance(ships, bool) else None


def read_mod_facts(mod: Path) -> ModFacts:
    """The facts of the mod at *mod* (a folder, a ZIP archive whatever its
    name, or a .modpkg), without hashing its content: only the names of its
    files and the headers of its language WADs are read, a moment for a
    voiceover pack that compute_mod_facts takes seconds to hash. A .modpkg
    is read from its table of contents, never unpacked (ModFiles).

    Raises OSError, zipfile.BadZipFile or ValueError (a .modpkg it cannot
    read): a mod it cannot read has no facts rather than wrong ones.
    """
    mod = Path(mod)
    if not mod.exists():
        raise FileNotFoundError(f"Mod not found: {mod}")
    with ModFiles(mod) as files:
        return ModFacts(ships_language_table_of(files))


def compute_mod_facts(mod: Path) -> tuple[ModFacts, str, dict[str, str]]:
    """The facts of the mod at *mod* (a folder, a ZIP archive whatever its
    name, or a .modpkg), its full content hash (the manifest's folderHash) and
    its WADs' hashes, in one pass over its files: a voiceover pack is gigabytes.

    Raises OSError, zipfile.BadZipFile or ValueError (a .modpkg it cannot
    unpack): a mod it cannot read has no facts rather than wrong ones.
    """
    mod = Path(mod)
    if not mod.exists():
        raise FileNotFoundError(f"Mod not found: {mod}")
    with _readable(mod) as readable:
        return _facts_of(readable)


@contextmanager
def _readable(mod: Path) -> Iterator[Path]:
    """*mod* as ModFiles reads it, a folder or a ZIP archive: a .modpkg unpacked."""
    if mod.is_file() and mod.suffix.lower() == MODPKG_SUFFIX:
        with _unpacked_modpkg(mod) as folder:
            yield folder
    else:
        yield mod


def _facts_scratch_dir() -> Path:
    """Where a .modpkg is unpacked to be read, one folder per read: in Rose's
    injection folder (the desktop user's, on the drive of Rose's data), but
    not in its ltf_staging, which every LTK session clears as it starts."""
    return get_injection_dir() / _FACTS_SCRATCH


@contextmanager
def _unpacked_modpkg(package: Path) -> Iterator[Path]:
    scratch = _facts_scratch_dir() / f"{_UNPACKED_PREFIX}{uuid.uuid4().hex}"
    scratch.mkdir(parents=True)
    try:
        extract_modpkg(package, scratch)
        yield scratch
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def remove_unpacked_leftovers() -> None:
    """Remove the .modpkg copies reads left unpacked: Rose closed while a
    sync read one on its daemon thread leaves the whole mod there, gigabytes
    for a voiceover pack. Only for Rose's start, before anything reads a mod:
    no other Rose runs then and the launcher's migration has finished."""
    try:
        leftovers = [entry for entry in _facts_scratch_dir().iterdir()
                     if entry.name.startswith(_UNPACKED_PREFIX)]
    except OSError:
        return
    for entry in leftovers:
        shutil.rmtree(entry, ignore_errors=True)


def _table_hashes(wad_name: str) -> set:
    """The path hashes the language table can have in a wad: the en_US path every language uses, and the wad's own
    language's (Global.ko_KR.wad.client -> data/menu/ko_kr/lol.stringtable)."""
    hashes = {TABLE_HASH}
    parts = wad_name.lower().split(".")
    if len(parts) >= 4 and parts[0] == "global":
        hashes.add(xxhash.xxh64_intdigest(f"data/menu/{parts[1]}/lol.stringtable".encode("utf-8")))
    return hashes


def _wad_may_hold(mod: ModFiles, wad: str, hashes: set) -> bool:
    """Whether the mod's packed wad (its relative path) has an entry for one of these path hashes, or can't be
    read: a packed language wad that can't be read is most likely a whole copy."""
    try:
        with mod.open(wad) as handle:
            header = handle.read(272)
            if len(header) < 272 or header[:2] != b"RW" or header[2] != 3:
                return True
            count = struct.unpack_from("<I", header, 268)[0]
            toc = handle.read(count * 32)
    except (OSError, zipfile.BadZipFile):
        return True
    if len(toc) < count * 32:
        return True
    return any(struct.unpack_from("<Q", toc, i * 32)[0] in hashes for i in range(count))


def ships_language_table_of(mod: ModFiles) -> bool:
    """Whether a mod carries its own lol.stringtable, loose or in a language wad (as some font mods do)."""
    if any(PurePosixPath(path).name.lower() == "lol.stringtable" for path in mod.files_under("RAW")):
        return True
    for name in mod.children("WAD"):
        lowered = name.lower()
        if not (lowered.startswith("global") and lowered.endswith(".wad.client")):
            continue
        hashes = _table_hashes(name)
        wad = f"WAD/{name}"
        if mod.is_dir(wad):
            names = {f"{h:016x}" for h in hashes}
            for path in mod.files_under(wad):
                file_name = PurePosixPath(path).name.lower()
                if file_name == "lol.stringtable" or file_name.split(".")[0] in names:
                    return True
        elif _wad_may_hold(mod, wad, hashes):
            return True
    return False


def _facts_of(mod: Path) -> tuple[ModFacts, str, dict[str, str]]:
    entries = []
    wad_hashes: dict[str, str] = {}
    with ModFiles(mod) as files:
        for relative_path in files.files_under():
            if _is_preview_image(relative_path):
                continue
            with files.open(relative_path) as stream:
                file_digest = _hash_stream(stream)
            entries.append((relative_path, file_digest))
            if relative_path.casefold().endswith((".wad", ".wad.client")):
                wad_hashes[relative_path] = file_digest.hex()
        facts = ModFacts(ships_language_table_of(files))
    return facts, _full_content_digest(entries), wad_hashes


def stamp_of(archive: Path) -> Optional[list[int]]:
    """[size, mtime_ns] of LTK Manager's copy of a mod when its facts were
    read: a stamp that changed means LTK Manager changed the mod (a newer
    version, a repair) and its facts must be read again. None when there is
    no such file."""
    try:
        status = Path(archive).stat()
    except OSError:
        return None
    if not stat.S_ISREG(status.st_mode):
        return None
    return [status.st_size, status.st_mtime_ns]
