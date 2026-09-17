#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rift Classic (gameMode JADE) skin support.

Classic games spawn separate characters, ``Jade_<Name>``, whose default skin slots
are 0/301/302. Regular skin mods target ``<alias>/skins/skin0.bin`` and are never
loaded there. Instead of converting community mods, this module builds a mod from
the installed game's own ``jade_*/skins/skinN.bin`` for the champion and its
companion characters (e.g. Tibbers, Nidalee's cougar form): the two entry keys are
re-keyed to the loaded slot and the slot bin links the original skin bin, the same
shape community skin mods use. Data always matches the installed patch.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Iterable, Optional

import xxhash
import zstandard

from utils.core.logging import get_logger

log = get_logger()

JADE_GAME_MODE = "JADE"
CLASSIC_BASE_SKIN_SLOTS = (0, 301, 302)
CLASSIC_MOD_PREFIX = "classic_"
CLASSIC_CHAMPION_ID_OFFSET = 60_000
CLASSIC_SKIN_ID_OFFSET = CLASSIC_CHAMPION_ID_OFFSET * 1000

_WAD_TOC_OFFSET = 272
_WAD_ENTRY_SIZE = 32
_WAD_TYPE_RAW = 0
_WAD_TYPE_GZIP = 1
_WAD_TYPE_ZSTD = 3
_SKIN_ID_RE = re.compile(r"^(?:skin|chroma)_(\d+)$")
_WAD_NAME_RE = re.compile(r"^WAD/([^/]+)\.wad\.client(?:/|$)", re.IGNORECASE)
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_JADE_CHARACTER_RE = re.compile(rb"data/characters/(jade_[a-z0-9_]+)/")


class ClassicSkinError(Exception):
    """The selected skin cannot be prepared for a Rift Classic game."""


def is_classic_game_mode(game_mode: Optional[str]) -> bool:
    return isinstance(game_mode, str) and game_mode.upper() == JADE_GAME_MODE


def fnv1a_32(text: str) -> int:
    value = 0x811C9DC5
    for byte in text.lower().encode("utf-8"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def wad_path_hash(path: str) -> int:
    return xxhash.xxh64_intdigest(path.lower().encode("utf-8"))


def skin_number_from_name(skin_name: str) -> int:
    match = _SKIN_ID_RE.match(skin_name or "")
    if not match:
        raise ClassicSkinError(f"unsupported skin identifier '{skin_name}'")
    return int(match.group(1)) % 1000


def to_regular_champion_id(champion_id: Optional[int]) -> Optional[int]:
    """Map a Rift Classic champion ID"""
    if champion_id is not None and champion_id >= CLASSIC_CHAMPION_ID_OFFSET:
        return champion_id - CLASSIC_CHAMPION_ID_OFFSET
    return champion_id


def to_regular_skin_id(skin_id: Optional[int]) -> Optional[int]:
    """Map a Rift Classic skin or chroma ID """
    if skin_id is not None and skin_id >= CLASSIC_SKIN_ID_OFFSET:
        return skin_id - CLASSIC_SKIN_ID_OFFSET
    return skin_id


def to_regular_skin_name(skin_name: str) -> str:
    """Map a Rift Classic injection name"""
    match = re.match(r"^(skin|chroma)_(\d+)$", skin_name or "")
    if not match:
        return skin_name
    return f"{match.group(1)}_{to_regular_skin_id(int(match.group(2)))}"


def champion_alias_from_mod_archive(archive_path: Path) -> str:
    """Return the champion WAD alias (e.g. 'MissFortune') a skin archive targets."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            aliases = {m.group(1) for m in map(_WAD_NAME_RE.match, archive.namelist()) if m}
    except (OSError, zipfile.BadZipFile) as e:
        raise ClassicSkinError(f"cannot read skin archive {archive_path.name}: {e}") from e
    if len(aliases) != 1:
        raise ClassicSkinError(f"skin archive {archive_path.name} targets {len(aliases)} champion WADs")
    alias = aliases.pop()
    if not _SAFE_NAME_RE.match(alias):
        raise ClassicSkinError(f"skin archive {archive_path.name} has an invalid champion WAD name")
    return alias


@functools.lru_cache(maxsize=None)
def champion_alias_from_library(champion_dir: Path) -> str:
    """Return the champion WAD alias using any skin archive of the champion in the Rose library."""
    archives = sorted(p for pattern in ("*.fantome", "*.zip") for p in champion_dir.rglob(pattern)) if champion_dir.is_dir() else []
    errors = []
    for archive in archives:
        try:
            return champion_alias_from_mod_archive(archive)
        except ClassicSkinError as e:
            errors.append(str(e))
    detail = f" ({errors[0]})" if errors else ""
    raise ClassicSkinError(f"no usable skin archive for champion folder {champion_dir.name}{detail}")


def load_jade_characters(hashes_path: Path, cache_path: Path) -> frozenset[str]:
    """Return every ``jade_*`` character name known to the game hash table."""
    try:
        stat = hashes_path.stat()
    except OSError as e:
        log.warning("[CLASSIC] Game hash table unavailable, companion characters will be skipped: %s", e)
        return frozenset()

    fingerprint = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("source") == fingerprint:
            return frozenset(cached["characters"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass

    characters: set[str] = set()
    try:
        with open(hashes_path, "rb") as table:
            for line in table:
                if b"data/characters/jade_" in line:
                    match = _JADE_CHARACTER_RE.search(line)
                    if match:
                        characters.add(match.group(1).decode("ascii"))
    except OSError as e:
        log.warning("[CLASSIC] Could not read game hash table, companion characters will be skipped: %s", e)
        return frozenset()

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"source": fingerprint, "characters": sorted(characters)}), encoding="utf-8")
    except OSError as e:
        log.debug("[CLASSIC] Could not cache Rift Classic character index: %s", e)
    log.info("[CLASSIC] Indexed %d Rift Classic characters from game hash table", len(characters))
    return frozenset(characters)


class WadReader:
    """Random access to entries of a League WAD v3 file (table of contents read once)."""

    def __init__(self, path: Path):
        self.path = path
        try:
            with open(path, "rb") as wad:
                header = wad.read(_WAD_TOC_OFFSET)
                if len(header) < _WAD_TOC_OFFSET or header[:2] != b"RW" or header[2] != 3:
                    raise ClassicSkinError(f"{path.name} is not a supported WAD v3 file")
                (count,) = struct.unpack_from("<I", header, _WAD_TOC_OFFSET - 4)
                toc = wad.read(count * _WAD_ENTRY_SIZE)
            self._entries = {}
            for index in range(count):
                path_hash, offset, compressed, uncompressed, type_byte = struct.unpack_from(
                    "<QIIIB", toc, index * _WAD_ENTRY_SIZE
                )
                self._entries[path_hash] = (offset, compressed, uncompressed, type_byte & 0x0F)
        except struct.error as e:
            raise ClassicSkinError(f"{path.name} has a truncated table of contents") from e

    def has(self, entry_path: str) -> bool:
        return wad_path_hash(entry_path) in self._entries

    def read(self, entry_path: str) -> Optional[bytes]:
        entry = self._entries.get(wad_path_hash(entry_path))
        if entry is None:
            return None
        offset, compressed, uncompressed, entry_type = entry
        with open(self.path, "rb") as wad:
            wad.seek(offset)
            raw = wad.read(compressed)
        try:
            if entry_type == _WAD_TYPE_RAW:
                return raw
            if entry_type == _WAD_TYPE_GZIP:
                return zlib.decompress(raw, 16 + zlib.MAX_WBITS)
            if entry_type == _WAD_TYPE_ZSTD:
                return zstandard.ZstdDecompressor().decompress(raw, max_output_size=uncompressed)
        except (zlib.error, zstandard.ZstdError) as e:
            raise ClassicSkinError(f"corrupted WAD entry {entry_path} in {self.path.name}") from e
        raise ClassicSkinError(f"unsupported WAD entry type {entry_type} for {entry_path}")


def _parse_prop_entries(data: bytes) -> tuple[int, list[tuple[int, int, bytes]]]:
    """Return (version, [(entry_type, key_hash, body_without_key)]) of a PROP bin."""
    try:
        offset = 12 if data[:4] == b"PTCH" else 0
        if data[offset:offset + 4] != b"PROP":
            raise ClassicSkinError("skin bin is not a PROP file")
        offset += 4
        (version,) = struct.unpack_from("<I", data, offset)
        offset += 4
        if version < 2:
            raise ClassicSkinError(f"unsupported PROP version {version}")
        (link_count,) = struct.unpack_from("<I", data, offset)
        offset += 4
        for _ in range(link_count):
            (length,) = struct.unpack_from("<H", data, offset)
            offset += 2 + length
        (entry_count,) = struct.unpack_from("<I", data, offset)
        offset += 4
        entry_types = struct.unpack_from(f"<{entry_count}I", data, offset)
        offset += 4 * entry_count
        entries = []
        for entry_type in entry_types:
            length, key = struct.unpack_from("<II", data, offset)
            entries.append((entry_type, key, data[offset + 8:offset + 4 + length]))
            offset += 4 + length
    except struct.error as e:
        raise ClassicSkinError("skin bin is truncated") from e
    if offset != len(data):
        raise ClassicSkinError("skin bin has unexpected trailing data")
    return version, entries


def retarget_skin_bin(source: bytes, character: str, source_skin: int, target_skin: int) -> bytes:
    """Build the bin loaded for *target_skin* that renders *source_skin*."""
    source_prefix = f"Characters/{character}/Skins/Skin{source_skin}"
    target_prefix = f"Characters/{character}/Skins/Skin{target_skin}"
    renames = {
        fnv1a_32(source_prefix): fnv1a_32(target_prefix),
        fnv1a_32(f"{source_prefix}/Resources"): fnv1a_32(f"{target_prefix}/Resources"),
    }
    version, entries = _parse_prop_entries(source)
    selected = [(entry_type, renames[key], body) for entry_type, key, body in entries if key in renames]
    if not any(key == renames[fnv1a_32(source_prefix)] for _, key, _ in selected):
        raise ClassicSkinError(f"{source_prefix} entry not found in skin bin")

    link = f"DATA/Characters/{character}/Skins/Skin{source_skin}.bin".encode("utf-8")
    out = bytearray(b"PROP")
    out += struct.pack("<II", version, 1)
    out += struct.pack("<H", len(link)) + link
    out += struct.pack("<I", len(selected))
    out += b"".join(struct.pack("<I", entry_type) for entry_type, _, _ in selected)
    for _, key, body in selected:
        out += struct.pack("<II", len(body) + 4, key) + body
    return bytes(out)


def build_classic_mod(
    game_dir: Path,
    champion_alias: str,
    skin_number: int,
    mods_dir: Path,
    jade_characters: Iterable[str] = (),
    slots: Iterable[int] = CLASSIC_BASE_SKIN_SLOTS,
) -> str:
    """Write a folder mod for Rift Classic and return its folder name."""
    if not _SAFE_NAME_RE.match(champion_alias):
        raise ClassicSkinError(f"invalid champion alias '{champion_alias}'")
    wad_path = game_dir / "DATA" / "FINAL" / "Champions" / f"{champion_alias}.wad.client"
    if not wad_path.is_file():
        raise ClassicSkinError(f"champion WAD not found: {wad_path}")
    wad = WadReader(wad_path)

    main_character = f"jade_{champion_alias.lower()}"
    candidates = sorted(set(jade_characters) | {main_character})
    present = [c for c in candidates if wad.has(f"data/characters/{c}/{c}.bin")]
    if not present:
        raise ClassicSkinError(f"{champion_alias} has no Rift Classic version in this patch")
    targets = [c for c in present if wad.has(f"data/characters/{c}/skins/skin{skin_number}.bin")]
    if not targets:
        raise ClassicSkinError(f"skin {skin_number} is not available for {champion_alias} in Rift Classic")

    slots = tuple(slots)
    folder_name = f"{CLASSIC_MOD_PREFIX}{champion_alias.lower()}_{skin_number}"
    mod_root = mods_dir / folder_name
    if mod_root.exists():
        shutil.rmtree(mod_root)
    for character in targets:
        display = f"Jade_{champion_alias}" if character == main_character else character
        source = wad.read(f"data/characters/{character}/skins/skin{skin_number}.bin")
        bins_dir = mod_root / "WAD" / f"{champion_alias}.wad.client" / "data" / "characters" / character / "skins"
        bins_dir.mkdir(parents=True, exist_ok=True)
        for slot in slots:
            if slot != skin_number:
                (bins_dir / f"skin{slot}.bin").write_bytes(retarget_skin_bin(source, display, skin_number, slot))

    meta_dir = mod_root / "META"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "info.json").write_text(
        json.dumps({
            "Author": "Rose",
            "Name": f"{champion_alias} skin {skin_number} (Rift Classic)",
            "Version": "1.0",
            "Description": "Generated from installed game data",
        }),
        encoding="utf-8",
    )
    log.info("[CLASSIC] Prepared %s skin %d for %s, slots %s", champion_alias, skin_number, targets, list(slots))
    return folder_name
