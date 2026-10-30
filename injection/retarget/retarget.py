#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin retargeting
Moves an injected skin from the skin slot it was built for to a slot the player owns.

The game loads the skin the server says the player picked: for skin n it reads data/characters/<c>/skins/skin<n>.bin
from the champion's wad and starts from the entry "Characters/<C>/Skins/Skin<n>" in it. Rose's skins are built for
skin 0, so the player has to be on the champion's default skin, and everyone else in the game sees the default too.

Retargeting rebuilds the injected skin for another slot B, one the player owns, so Rose can pick B in champ select:
the others see the skin the player owns, the player sees the injected one. Only names change, never content:

- the skin's bin moves from skins/skinA.bin to skins/skinB.bin, and the mod's animations/skinA.bin, when it ships
  one, to animations/skinB.bin (a wad names its entries by xxh64 of their lowercase path)
- inside them, the entries "Characters/C/Skins/SkinA" and ".../SkinA/Resources", and "Characters/C/Animations/SkinA"
  with the animations, are renamed to B, and so is every field that refers to them (a bin names its entries by
  fnv1a of their lowercase name)
- the bin's header link to data/characters/c/animations/skinA.bin follows, with the animations

Asset paths (assets/.../skin14/...) and the links to the game's own bins stay as they are: the skin keeps reading the
original skin's content. Companions that carry the owner's skin (Annie's Tibbers, in Annie's wad as
data/characters/annietibbers/skins/skinA.bin) are moved along when the mod ships them.

The renamed bins go into a mod of their own: the source mod may be a junction into a shared cache and is never
written, and mod-tools merges the two into the champion's wad.

A slot the skin is built on can't be used: Rose's skins link the game's own bin of the skin they port
(DATA/Characters/Ahri/Skins/Skin14.bin), and a chroma's bin links its skin's, so writing over one of those would cut
the skin off its own content. The links are followed through the mod and the game's champion wad, and such a slot is
refused.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import shutil
import struct
import zipfile
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from typing import BinaryIO, Callable, Dict, Iterable, List, Optional, Set, Tuple

import xxhash
import zstandard

from utils.core.logging import get_logger

log = get_logger()

MOD_FOLDER = "ROSE-Retarget"
WAD_SUFFIXES = (".wad.client", ".wad")
ARCHIVE_SUFFIXES = (".zip", ".fantome")
# A skin id is the champion's id * 1000 + the skin's number
SKIN_NUMBERS = range(1000)
# Only bins are read to find companions, and a bin above this is no skin's
_MAX_SCANNED_BIN = 8 * 1024 * 1024

_HEX_NAME = re.compile(r"^([0-9a-f]{16})(\.[^/]*)?$", re.IGNORECASE)
_CHARACTER = re.compile(rb"characters/([a-z0-9_]+)/", re.IGNORECASE)
_WAD_HEADER_SIZE = 272
_WAD_ENTRY = struct.Struct("<QIIIBBHQ")  # path hash, offset, stored size, size, type, duplicate, subchunk, checksum


class RetargetError(Exception):
    """A skin that can't be moved to the slot asked for; the message says why, for the log."""


def _path_hash(path: str) -> int:
    return xxhash.xxh64_intdigest(path.lower().encode("utf-8"))


def _name_hash(name: str) -> int:
    """fnv1a-32 of the lowercase name: how a bin names its entries."""
    value = 0x811C9DC5
    for byte in name.lower().encode("utf-8"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def _skin_bin(character: str, number: int) -> str:
    return f"data/characters/{character}/skins/skin{number}.bin".lower()


def _animations_bin(character: str, number: int) -> str:
    return f"data/characters/{character}/animations/skin{number}.bin".lower()


# --------------------------------------------------------------------------------------
# wads: packed (.wad.client) or a folder of loose files named by path or by path hash
# --------------------------------------------------------------------------------------

def _decompress(stored: bytes, kind: int, size: int) -> Optional[bytes]:
    if kind == 0:
        return stored
    if kind == 1:
        return gzip.decompress(stored)
    if kind == 3:
        return zstandard.ZstdDecompressor().decompress(stored, max_output_size=size)
    if kind == 4:
        # the same stream cut into frames, read one after the other
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(stored), read_across_frames=True) as reader:
            return reader.read(size)
    return None  # 2 points into another wad


class _Wad:
    """A wad's entries by path hash, each read when asked for."""

    def __init__(self, name: str, readers: Dict[int, Callable[[], Optional[bytes]]], sizes: Dict[int, int]):
        self.name = name
        self._readers = readers
        self._sizes = sizes

    def __contains__(self, path_hash: int) -> bool:
        return path_hash in self._readers

    def hashes(self) -> Iterable[int]:
        return self._readers.keys()

    def size(self, path_hash: int) -> Optional[int]:
        return self._sizes.get(path_hash)

    def read(self, path_hash: int) -> Optional[bytes]:
        reader = self._readers.get(path_hash)
        if reader is None:
            return None
        try:
            return reader()
        except (OSError, zstandard.ZstdError, EOFError, zipfile.BadZipFile) as e:
            log.debug(f"[RETARGET] {self.name}: entry {path_hash:016x} unreadable: {e}")
            return None


def _read_packed(opener: Callable[[], BinaryIO], offset: int, stored: int, size: int, kind: int) -> Optional[bytes]:
    with opener() as f:
        f.seek(offset)
        return _decompress(f.read(stored), kind, size)


def _packed_wad(name: str, opener: Callable[[], BinaryIO]) -> _Wad:
    with opener() as f:
        header = f.read(_WAD_HEADER_SIZE)
        if len(header) < _WAD_HEADER_SIZE or header[:2] != b"RW" or header[2] != 3:
            raise RetargetError(f"{name} is not a wad v3")
        count = struct.unpack_from("<I", header, 268)[0]
        table = f.read(count * _WAD_ENTRY.size)
    if len(table) < count * _WAD_ENTRY.size:
        raise RetargetError(f"{name} is cut short")
    readers, sizes = {}, {}
    for i in range(count):
        path_hash, offset, stored, size, kind, _, _, _ = _WAD_ENTRY.unpack_from(table, i * _WAD_ENTRY.size)
        readers[path_hash] = partial(_read_packed, opener, offset, stored, size, kind & 0xF)
        sizes[path_hash] = size
    return _Wad(name, readers, sizes)


def _loose_wad(name: str, files: Dict[str, Tuple[Callable[[], bytes], int]]) -> _Wad:
    readers, sizes = {}, {}
    for relative, (read, size) in files.items():
        relative = relative.replace("\\", "/")
        match = _HEX_NAME.match(relative)
        path_hash = int(match.group(1), 16) if match else _path_hash(relative)
        readers[path_hash] = read
        sizes[path_hash] = size
    return _Wad(name, readers, sizes)


def _is_wad_name(name: str) -> bool:
    return name.lower().endswith(WAD_SUFFIXES)


def _mod_wads(source: Path, stack: ExitStack) -> List[_Wad]:
    """The wads of a mod: an extracted mod folder, or a .zip/.fantome archive read in place."""
    wads: List[_Wad] = []
    if source.is_dir():
        wad_dir = source / "WAD"
        if not wad_dir.is_dir():
            return wads
        for item in sorted(wad_dir.iterdir()):
            if not _is_wad_name(item.name):
                continue
            if item.is_file():
                wads.append(_packed_wad(item.name, partial(open, item, "rb")))
            elif item.is_dir():
                files = {
                    p.relative_to(item).as_posix(): (p.read_bytes, p.stat().st_size)
                    for p in item.rglob("*") if p.is_file()
                }
                wads.append(_loose_wad(item.name, files))
        return wads

    if source.suffix.lower() not in ARCHIVE_SUFFIXES:
        raise RetargetError(f"{source.name} is no mod Rose can read")
    archive = stack.enter_context(zipfile.ZipFile(source))
    loose: Dict[str, Dict[str, Tuple[Callable[[], bytes], int]]] = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        parts = info.filename.replace("\\", "/").split("/")
        if len(parts) < 2 or parts[0].lower() != "wad" or not _is_wad_name(parts[1]):
            continue
        if len(parts) == 2:
            wads.append(_packed_wad(parts[1], partial(archive.open, info)))
        else:
            loose.setdefault(parts[1], {})["/".join(parts[2:])] = (partial(archive.read, info), info.file_size)
    wads.extend(_loose_wad(name, files) for name, files in loose.items())
    return wads


def _pack_wad(entries: Dict[int, bytes]) -> bytes:
    """A wad v3.4: the index sorted by path hash, each entry zstd-compressed with the xxh3 of what is stored."""
    compressor = zstandard.ZstdCompressor(level=3)
    stored = [(path_hash, compressor.compress(entries[path_hash]), len(entries[path_hash]))
              for path_hash in sorted(entries)]
    header = bytearray(b"RW\x03\x04" + bytes(256) + bytes(8))
    header += struct.pack("<I", len(stored))
    offset = len(header) + len(stored) * _WAD_ENTRY.size
    table, blobs = bytearray(), bytearray()
    for path_hash, blob, size in stored:
        table += _WAD_ENTRY.pack(path_hash, offset, len(blob), size, 3, 0, 0, xxhash.xxh3_64_intdigest(blob))
        blobs += blob
        offset += len(blob)
    return bytes(header + table + blobs)


# --------------------------------------------------------------------------------------
# PROP bins: "PROP", u32 version, [u32 count, count x (u16 length, path)] linked bins, u32 count, count x u32 class,
# then count x (u32 size, u32 name, u16 count, fields); a field is u32 name, u8 type, value
# --------------------------------------------------------------------------------------

_FIXED_SIZES = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 4, 7: 4, 8: 8, 9: 8, 10: 4, 11: 8, 12: 12, 13: 16, 14: 64, 15: 4,
                18: 8, 0x87: 1}
_STRING, _HASH, _LINK = 16, 17, 0x84
_LIST, _LIST2, _POINTER, _EMBED, _OPTION, _MAP = 0x80, 0x81, 0x82, 0x83, 0x85, 0x86


def bin_links(data: bytes) -> List[str]:
    """The bins a bin links in its header, or none when it is no PROP bin."""
    try:
        return _Bin(data).links
    except RetargetError:
        return []


class _Bin:
    """A PROP bin, read far enough to rename its entries: the links in its header, and where the name of every
    entry and every reference to one (hash and link fields) is stored."""

    def __init__(self, data: bytes):
        if data[:4] != b"PROP":
            raise RetargetError(f"not a PROP bin ({data[:4]!r})")
        self.data = data
        self._at = 4
        try:
            self.version = self._read("I")
            self.links: List[str] = []
            if self.version >= 2:
                for _ in range(self._read("I")):
                    self.links.append(self._string())
            self.body_start = self._at
            self.names: List[int] = []
            count = self._read("I")
            self._at += 4 * count  # each entry's class
            for _ in range(count):
                size = self._read("I")
                end = self._at + size
                if end > len(data):
                    raise RetargetError("an entry runs past the end of the bin")
                self.names.append(self._at)
                self._at += 4
                found = len(self.names)
                try:
                    for _ in range(self._read("H")):
                        self._at += 4
                        self._value(self._read("B"))
                    if self._at != end:
                        raise RetargetError("an entry is not the size it says")
                except (RetargetError, struct.error, IndexError) as e:
                    # A field type this reader doesn't know (some skins' materials have one): the entry is skipped
                    # by its size, keeping its name, and only the references found in it before are renamed
                    log.debug(f"[RETARGET] an entry of the bin is skipped: {e}")
                    del self.names[found:]
                    self._at = end
        except (struct.error, IndexError, UnicodeDecodeError) as e:
            raise RetargetError(f"unreadable bin: {e}") from e

    def _read(self, fmt: str) -> int:
        value = struct.unpack_from("<" + fmt, self.data, self._at)[0]
        self._at += struct.calcsize("<" + fmt)
        return value

    def _string(self) -> str:
        length = self._read("H")
        text = self.data[self._at:self._at + length].decode("utf-8")
        self._at += length
        return text

    def _value(self, kind: int) -> None:
        if kind in (_HASH, _LINK):
            self.names.append(self._at)
            self._at += 4
        elif kind in _FIXED_SIZES:
            self._at += _FIXED_SIZES[kind]
        elif kind == _STRING:
            self._at += 2 + struct.unpack_from("<H", self.data, self._at)[0]
        elif kind in (_LIST, _LIST2):
            item = self._read("B")
            self._at += 4  # size
            for _ in range(self._read("I")):
                self._value(item)
        elif kind in (_POINTER, _EMBED):
            if self._read("I"):  # class, 0 for none
                self._at += 4  # size
                for _ in range(self._read("H")):
                    self._at += 4
                    self._value(self._read("B"))
        elif kind == _OPTION:
            item = self._read("B")
            for _ in range(self._read("B")):
                self._value(item)
        elif kind == _MAP:
            key, value = self._read("B"), self._read("B")
            self._at += 4  # size
            for _ in range(self._read("I")):
                self._value(key)
                self._value(value)
        else:
            raise RetargetError(f"unknown field type {kind:#x}")

    def renamed(self, names: Dict[int, int], link: Callable[[str], str]) -> bytes:
        """The bin again with these entry names changed wherever they are stored, and its links passed through link."""
        out = bytearray(self.data[:8])
        if self.version >= 2:
            out += struct.pack("<I", len(self.links))
            for path in self.links:
                encoded = link(path).encode("utf-8")
                out += struct.pack("<H", len(encoded)) + encoded
        body = bytearray(self.data[self.body_start:])
        for at in self.names:
            at -= self.body_start
            value = struct.unpack_from("<I", body, at)[0]
            if value in names:
                struct.pack_into("<I", body, at, names[value])
        return bytes(out + body)


# --------------------------------------------------------------------------------------
# what the injection calls
# --------------------------------------------------------------------------------------

class RetargetPlan:
    """The renamed bins of one skin, ready to be written as a mod."""

    def __init__(self, source_number: int, target_number: int, wads: Dict[str, Dict[int, bytes]]):
        self.source_number = source_number
        self.target_number = target_number
        self.wads = wads

    def write(self, mods_dir: Path, folder: str = MOD_FOLDER) -> str:
        """Writes the mod into the mods directory and returns its folder name."""
        target = Path(mods_dir) / folder
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        (target / "META").mkdir(parents=True, exist_ok=True)
        (target / "WAD").mkdir(parents=True, exist_ok=True)
        (target / "META" / "info.json").write_text(json.dumps({
            "Author": "Rose",
            "Description": f"The injected skin, moved from skin {self.source_number} to skin {self.target_number}",
            "Name": "Skin slot",
            "Version": "1.0.0",
        }), encoding="utf-8")
        for wad_name, entries in self.wads.items():
            (target / "WAD" / wad_name).write_bytes(_pack_wad(entries))
        log.info(f"[RETARGET] skin {self.source_number} moved to skin {self.target_number} ({folder})")
        return folder


def _wad_alias(wad_name: str) -> str:
    """The character a champion wad is named after (Annie.wad.client -> annie)."""
    return wad_name.split(".")[0].lower()


def _characters(wad: _Wad) -> Set[str]:
    """The characters whose skins a wad may carry: the one it is named after, and those its bins name."""
    found = {_wad_alias(wad.name)}
    for path_hash in list(wad.hashes()):
        size = wad.size(path_hash)
        if size is None or size > _MAX_SCANNED_BIN:
            continue
        data = wad.read(path_hash)
        if data and data[:4] == b"PROP":
            found.update(m.decode("ascii").lower() for m in _CHARACTER.findall(data))
    return found


def _skins_in(wad: _Wad, characters: Iterable[str]) -> Dict[str, List[int]]:
    """The skin numbers each character has a bin for in a wad."""
    found = {}
    for character in characters:
        numbers = [n for n in SKIN_NUMBERS if _path_hash(_skin_bin(character, n)) in wad]
        if numbers:
            found[character] = numbers
    return found


def _game_wads(game_dir: Optional[Path], names: Iterable[str]) -> List[_Wad]:
    if not game_dir:
        return []
    champions = Path(game_dir) / "DATA" / "FINAL" / "Champions"
    if not champions.is_dir():
        return []
    by_name = {p.name.lower(): p for p in champions.iterdir() if p.is_file()}
    wads = []
    for name in names:
        path = by_name.get(name.lower())
        if path:
            wads.append(_packed_wad(path.name, partial(open, path, "rb")))
    return wads


def _blocked_by(links: Iterable[str], forbidden: Set[str], wads: List[_Wad]) -> Optional[str]:
    """The first bin in these links' chain that is one of the forbidden paths, following links through the wads."""
    queue = [link.lower() for link in links]
    seen: Set[str] = set()
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        if path in forbidden:
            return path
        path_hash = _path_hash(path)
        for wad in wads:
            if path_hash in wad:
                queue.extend(link.lower() for link in bin_links(wad.read(path_hash) or b""))
                break
    return None


def plan_retarget(
    source: Path,
    target_number: int,
    game_dir: Optional[Path],
    source_number: Optional[int] = None,
) -> RetargetPlan:
    """Renames a mod's skin to skin target_number, or raises RetargetError when it can't be.

    source is an extracted mod folder or a .zip/.fantome archive. source_number is the slot the mod is built for;
    without it, it is the only skin slot the mod has a bin for.
    """
    if not 0 <= int(target_number) < len(SKIN_NUMBERS):
        raise RetargetError(f"skin {target_number} is no skin number")
    with ExitStack() as stack:
        wads = _mod_wads(Path(source), stack)
        skins = {wad.name: _skins_in(wad, _characters(wad)) for wad in wads}
        numbers = {n for found in skins.values() for numbers in found.values() for n in numbers}
        if source_number is None:
            if len(numbers) != 1:
                raise RetargetError(
                    "the mod has no skin bin" if not numbers else f"the mod has bins for several skins {sorted(numbers)}")
            source_number = next(iter(numbers))
        elif source_number not in numbers:
            raise RetargetError(f"the mod has no bin for skin {source_number}")
        if source_number == target_number:
            raise RetargetError(f"the mod is already built for skin {target_number}")

        a, b = source_number, target_number
        out: Dict[str, Dict[int, bytes]] = {}
        forbidden: Set[str] = set()
        # The links the bins keep: the ones renamed with the animations lead to the bins written here
        kept_links: List[str] = []
        for wad in wads:
            for character, character_numbers in skins[wad.name].items():
                if a not in character_numbers:
                    continue
                skin = wad.read(_path_hash(_skin_bin(character, a)))
                if skin is None:
                    raise RetargetError(f"{wad.name}: {_skin_bin(character, a)} is unreadable")
                animations = wad.read(_path_hash(_animations_bin(character, a)))

                names = {
                    _name_hash(f"Characters/{character}/Skins/Skin{a}"): _name_hash(f"Characters/{character}/Skins/Skin{b}"),
                    _name_hash(f"Characters/{character}/Skins/Skin{a}/Resources"):
                        _name_hash(f"Characters/{character}/Skins/Skin{b}/Resources"),
                }
                old_animations = _animations_bin(character, a)
                if animations is not None:
                    names[_name_hash(f"Characters/{character}/Animations/Skin{a}")] = \
                        _name_hash(f"Characters/{character}/Animations/Skin{b}")

                def link(path: str, old=old_animations, moved=animations is not None) -> str:
                    if moved and path.lower() == old:
                        return re.sub(rf"(?i)skin{a}\.bin$", f"Skin{b}.bin", path)
                    kept_links.append(path)
                    return path

                entries = out.setdefault(wad.name, {})
                entries[_path_hash(_skin_bin(character, b))] = _Bin(skin).renamed(names, link)
                forbidden.add(_skin_bin(character, b))
                if animations is not None:
                    entries[_path_hash(_animations_bin(character, b))] = _Bin(animations).renamed(names, link)
                    forbidden.add(_animations_bin(character, b))
                log.debug(f"[RETARGET] {wad.name}: {character} skin {a} -> {b}"
                          + (" with its animations" if animations is not None else ""))

        game = _game_wads(game_dir, out.keys())
        if len(game) < len(out):
            raise RetargetError("the game's champion files were not found, the skin's links can't be checked")
        blocked = _blocked_by(kept_links, forbidden, wads + game)
        if blocked:
            raise RetargetError(f"the skin is built on {blocked}, which skin {b} would replace")
        return RetargetPlan(a, b, out)
