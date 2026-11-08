#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import re
import shutil
import stat
import struct
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator, List, Mapping, Optional

import xxhash

from utils.core.modpkg import MODPKG_SUFFIX, ModPackage, extract_modpkg
from utils.core.paths import get_injection_dir

from .mod_files import ModFiles

_PARTY_HASH = re.compile(r"[0-9a-f]{32}")
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



@dataclass(frozen=True)
class ModFacts:
    """The answers about a mod that used to need its files.

    Hashable: an injection plan (injection.core.stage_plan.ModStep) carries
    them, and plans are compared by equality.
    """

    party_hash: Optional[str]
    champion_aliases: tuple[str, ...]
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


def champion_aliases_of(mod: ModFiles) -> List[str]:
    """The champions a mod carries wads for, in the order it lists them (Zed.wad.client -> Zed)."""
    aliases = []
    for name in mod.children("WAD"):
        if not name.lower().endswith(".wad.client"):
            continue
        alias = name[: -len(".wad.client")].split(".")[0]
        if alias.lower() != "global" and alias not in aliases:
            aliases.append(alias)
    return aliases


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
        aliases = tuple(champion_aliases_of(files))
        ships = ships_language_table_of(files)
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
