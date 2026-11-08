#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What Rose needs to know about a saved mod, read once from its files.

A mod the user adds ends up in LTK Manager's library, and Rose keeps no copy
of it: party mode, the loading screen name and the champion select listing
can no longer open the mod's files when they need an answer. So the answers
are computed once, when the mod is added or moved into LTK Manager (and again
when LTK Manager changes its copy), and kept in the mod's manifest entry.

The content hash lives here too: party mode matches a friend's mod by it
(party.discovery.custom_mods), and the manifest's partyHash must be that very
hash, read from the same files the same way.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import stat
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Optional

from utils.core.modpkg import MODPKG_SUFFIX, ModPackage, extract_modpkg
from utils.core.paths import get_injection_dir

from .mod_files import ModFiles

# A partyHash is the content hash cut to 32 hex characters
_PARTY_HASH = re.compile(r"[0-9a-f]{32}")
# Where a .modpkg is unpacked to be read, one folder per read: in Rose's
# injection folder (the desktop user's, on the drive of Rose's data), but not
# in its ltf_staging, which every LTK session clears as it starts
_FACTS_SCRATCH = "mod_facts"
_UNPACKED_PREFIX = "facts-"


# --------------------------------------------------------------------------------------
# the content hash (party mode's, and the manifest's folderHash)
# --------------------------------------------------------------------------------------

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
    return _full_content_digest(entries)[:32]


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


def _archive_content_hash(archive_path: Path) -> Optional[str]:
    entries = []
    if archive_path.suffix.lower() == MODPKG_SUFFIX:
        # Hash the files the package unpacks to, as the imported folder holds them
        with ModPackage.open(archive_path) as package:
            for relative_path, content in package.iter_files():
                if _is_preview_image(relative_path):
                    continue
                entries.append((relative_path, hashlib.sha256(content).digest()))
        return _content_digest(entries) if entries else None
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


# --------------------------------------------------------------------------------------
# the facts
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ModFacts:
    """The answers about a mod that used to need its files.

    Hashable: an injection plan (injection.core.stage_plan.ModStep) carries
    them, and plans are compared by equality.
    """

    # party mode's content hash; None when the mod holds only its preview image
    party_hash: Optional[str]
    # the champions it carries wads for (loading_name._champion_aliases order)
    champion_aliases: tuple[str, ...]
    # whether it carries the game's text table (loading_name._ships_language_table)
    ships_language_table: bool

    def to_manifest(self) -> dict:
        return {
            "partyHash": self.party_hash,
            "championAliases": list(self.champion_aliases),
            "shipsLanguageTable": self.ships_language_table,
        }

    @classmethod
    def from_manifest(cls, m: object) -> Optional["ModFacts"]:
        """The facts of a manifest entry, or None when it does not hold all of
        them, well typed: an entry written by an older Rose has none, and a
        reader must then fall back on the mod's files or safe defaults rather
        than trust half an answer."""
        if not isinstance(m, Mapping):
            return None
        if not all(key in m for key in ("partyHash", "championAliases", "shipsLanguageTable")):
            return None
        party_hash, aliases, ships = m["partyHash"], m["championAliases"], m["shipsLanguageTable"]
        if party_hash is not None and not (isinstance(party_hash, str) and _PARTY_HASH.fullmatch(party_hash)):
            return None
        if not isinstance(aliases, (list, tuple)) or not all(isinstance(alias, str) for alias in aliases):
            return None
        if not isinstance(ships, bool):
            return None
        return cls(party_hash, tuple(aliases), ships)


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
    if mod.is_file() and mod.suffix.lower() == MODPKG_SUFFIX:
        # ModFiles reads ZIP archives only
        with _unpacked_modpkg(mod) as folder:
            return _facts_of(folder)
    return _facts_of(mod)


@contextmanager
def _unpacked_modpkg(package: Path) -> Iterator[Path]:
    scratch = get_injection_dir() / _FACTS_SCRATCH / f"{_UNPACKED_PREFIX}{uuid.uuid4().hex}"
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
        leftovers = [entry for entry in (get_injection_dir() / _FACTS_SCRATCH).iterdir()
                     if entry.name.startswith(_UNPACKED_PREFIX)]
    except OSError:
        return
    for entry in leftovers:
        shutil.rmtree(entry, ignore_errors=True)


def _facts_of(mod: Path) -> tuple[ModFacts, str, dict[str, str]]:
    # Imported here: loading_name imports injection.mods.mod_files, which runs
    # injection.mods' __init__, which imports the storage that imports this
    from injection.loadingname import loading_name

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
        aliases = tuple(loading_name._champion_aliases(files))
        ships = bool(loading_name._ships_language_table(files))
    full_hash = _full_content_digest(entries)
    facts = ModFacts(full_hash[:32] if entries else None, aliases, ships)
    return facts, full_hash, wad_hashes


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
