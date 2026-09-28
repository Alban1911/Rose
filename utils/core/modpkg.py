#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mod Package (.modpkg) Reader
Reads LeagueToolkit's .modpkg format (format version 1, specified in
docs/design/modpkg.md of LeagueToolkit/league-mod) and unpacks it into the mod
folder layout mod-tools builds overlays from:

    META/info.json                         written from the package metadata
    META/image.webp                        the package thumbnail, if any
    WAD/<name>.wad.client/<hash>.<ext>     one loose file per chunk

Files are named by their path hash, the key the game and mod-tools use inside
a WAD, so no path stored in a package ever becomes a file name. Only the base
layer is unpacked: other layers are optional content Rose cannot toggle.
"""

from __future__ import annotations

import json
import mmap
import os
import re
import struct
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator, NamedTuple, Optional, Union

import xxhash
import zstandard

from utils.core.logging import get_logger

log = get_logger()

MODPKG_SUFFIX = ".modpkg"

_MAGIC = b"_modpkg_"
_FORMAT_VERSION = 1
_NONE = 0xFFFFFFFF
_BASE_LAYER = b"base"
# The spec's name for the metadata chunk, then the one early packages used
_METADATA_PATHS = (b"_meta_/info.msgpack", b"_meta_/metadata.msgpack")
_THUMBNAIL_PATH = b"_meta_/thumbnail.webp"

_U32 = struct.Struct("<I")
_I32 = struct.Struct("<i")
_HEADER = struct.Struct("<III")  # format version, signature size, chunk count
_RECORD = struct.Struct("<QQBQQQQIII")  # one table of contents entry, 61 bytes

_RAW = 0
_ZSTD = 1
# Far above any file the game ships, low enough to refuse a decompression bomb
_MAX_CHUNK_SIZE = 512 * 1024 * 1024
_DECOMPRESS_STEP = 16 * 1024 * 1024

# mod-tools only reads WAD folders named like the game's WAD files
_WAD_FOLDER = re.compile(r"[a-z0-9_.-]+\.wad(\.client)?")
_EXTENSION = re.compile(r"\.[a-z0-9_-]{1,16}")
_HEX_NAME = re.compile(r"[0-9a-fA-F]{16}")


class ModpkgError(ValueError):
    """The file is not a .modpkg package Rose can read"""


class _Record(NamedTuple):
    path_hash: int
    data_offset: int
    compression: int
    compressed_size: int
    uncompressed_size: int
    compressed_checksum: int
    uncompressed_checksum: int
    path_index: int
    layer_index: int
    wad_index: int


class ModPackage:
    """A mounted package: header, tables and table of contents, checked as the
    spec's reader requirements ask before any file is read"""

    def __init__(self, data) -> None:
        """Mount a package held in a bytes-like object (bytes, mmap)"""
        self._data = data
        cursor = _Cursor(data)
        if cursor.take(len(_MAGIC)) != _MAGIC:
            raise ModpkgError("Not a .modpkg mod package")
        version, signature_size, chunk_count = cursor.unpack(_HEADER)
        if version != _FORMAT_VERSION:
            raise ModpkgError(f"Unsupported .modpkg format version {version}")
        cursor.take(signature_size)  # reserved, format version 1 defines no signature

        self.layers = [(cursor.counted_name(), cursor.unpack(_I32)[0]) for _ in cursor.count(8)]
        self.paths = [cursor.terminated_name() for _ in cursor.count(1)]
        self.wads = [cursor.terminated_name() for _ in cursor.count(1)]
        base_layer = next(
            (index for index, (name, _) in enumerate(self.layers) if _canonical(name) == _BASE_LAYER),
            None,
        )
        if base_layer is None:
            raise ModpkgError("The .modpkg has no base layer")

        cursor.take(-cursor.offset % 8)
        if chunk_count > cursor.remaining // _RECORD.size:
            raise ModpkgError("The .modpkg file is truncated")
        self.records: list[_Record] = []
        contents: dict[tuple[int, int], tuple[int, int]] = {}
        for index in range(chunk_count):
            record = _Record._make(_RECORD.unpack_from(data, cursor.offset + index * _RECORD.size))
            self._check_record(record)
            # One path holds one file per layer, whichever WADs list it
            content = (record.uncompressed_checksum, record.uncompressed_size)
            if contents.setdefault((record.path_hash, record.layer_index), content) != content:
                raise ModpkgError(f"The .modpkg holds two different files for {self.paths[record.path_index]}")
            self.records.append(record)

        self._wad_files: dict[str, _Record] = {}
        optional_layers = set()
        self.unplaced_file_count = 0
        placed = set()
        for record in self.records:
            if record.layer_index == _NONE:
                continue  # metadata
            if record.layer_index != base_layer:
                optional_layers.add(self.layers[record.layer_index][0])
                continue
            stored_path = self.paths[record.path_index]
            if record.wad_index != _NONE:
                folder, path_hash = self.wads[record.wad_index].lower(), record.path_hash
            else:
                folder, path_hash = _legacy_wad_path(stored_path)
            if folder is None or not _WAD_FOLDER.fullmatch(folder):
                self.unplaced_file_count += 1
                continue
            if (folder, path_hash) in placed:
                continue  # listed twice for one WAD
            placed.add((folder, path_hash))
            self._wad_files[f"WAD/{folder}/{path_hash:016x}{_extension(stored_path)}"] = record
        self.optional_layers = sorted(optional_layers)

    @classmethod
    @contextmanager
    def open(cls, path: Union[str, Path]) -> Iterator["ModPackage"]:
        """Mount the package at *path*; file data is only read on demand"""
        with open(path, "rb") as stream:
            if os.fstat(stream.fileno()).st_size == 0:
                raise ModpkgError("Not a .modpkg mod package")
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                yield cls(data)

    @property
    def wad_file_count(self) -> int:
        """Number of game files the unpacked mod holds"""
        return len(self._wad_files)

    def _check_record(self, record: _Record) -> None:
        if (
            record.compression not in (_RAW, _ZSTD)
            or record.path_index >= len(self.paths)
            or (record.layer_index != _NONE and record.layer_index >= len(self.layers))
            or (record.wad_index != _NONE and record.wad_index >= len(self.wads))
            or record.data_offset + record.compressed_size > len(self._data)
        ):
            # Packages from league-mod 0.2.0 and older also end up here: their
            # metadata sits where the table of contents is expected
            raise ModpkgError("The .modpkg is damaged or was packed by an early LeagueToolkit version")

    def read(self, record: _Record) -> bytes:
        """A file's bytes, decompressed and checked against its checksum"""
        name = self.paths[record.path_index]
        if record.uncompressed_size > _MAX_CHUNK_SIZE:
            raise ModpkgError(f"File too large in the .modpkg: {name}")
        stored = self._data[record.data_offset:record.data_offset + record.compressed_size]
        content = _decompress(stored, record.uncompressed_size) if record.compression == _ZSTD else stored
        if (
            content is None
            or len(content) != record.uncompressed_size
            or xxhash.xxh3_64_intdigest(content) != record.uncompressed_checksum
        ):
            raise ModpkgError(f"Corrupted file in the .modpkg: {name}")
        return content

    def _meta_file(self, path: bytes) -> Optional[_Record]:
        return next(
            (
                record for record in self.records
                if record.layer_index == _NONE
                and record.wad_index == _NONE
                and _canonical(self.paths[record.path_index]) == path
            ),
            None,
        )

    def metadata(self) -> dict:
        """The package's metadata document, or {} when it is missing or unreadable"""
        for path in _METADATA_PATHS:
            record = self._meta_file(path)
            if record is None:
                continue
            try:
                document = _unpack_msgpack(self.read(record))
            except ModpkgError as e:
                log.warning(f"[MODPKG] Ignoring the package metadata: {e}")
                return {}
            return document if isinstance(document, dict) else {}
        return {}

    def _info_json(self) -> bytes:
        """META/info.json as a .fantome carries it (mod-tools requires the file)"""
        metadata = self.metadata()
        authors = metadata.get("authors")
        author_names = [
            _text(author.get("name"))
            for author in (authors if isinstance(authors, list) else [])
            if isinstance(author, dict)
        ]
        info = {
            "Name": _text(metadata.get("display_name")) or _text(metadata.get("name")),
            "Author": ", ".join(name for name in author_names if name),
            "Version": _text(metadata.get("version")),
            "Description": _text(metadata.get("description")),
        }
        return json.dumps(info, ensure_ascii=False, indent=2).encode("utf-8")

    def _layout(self) -> dict[str, Union[bytes, _Record]]:
        """Relative path -> the bytes or package file it holds, for the unpacked mod"""
        layout: dict[str, Union[bytes, _Record]] = {"META/info.json": self._info_json()}
        thumbnail = self._meta_file(_THUMBNAIL_PATH)
        if thumbnail is not None:
            layout["META/image.webp"] = thumbnail
        layout.update(self._wad_files)
        return layout

    def file_paths(self) -> list[str]:
        """Relative paths of the files in the unpacked mod, without reading them"""
        return sorted(self._layout())

    def iter_files(self) -> Iterator[tuple[str, bytes]]:
        """(relative path, bytes) of every file in the unpacked mod, sorted by path"""
        layout = self._layout()
        for relative_path in sorted(layout):
            source = layout[relative_path]
            yield relative_path, source if isinstance(source, bytes) else self.read(source)


def extract_modpkg(source: Union[str, Path], dest_dir: Union[str, Path]) -> None:
    """Unpack a .modpkg into *dest_dir* as a mod folder mod-tools can use"""
    source = Path(source)
    dest_dir = Path(dest_dir)
    with ModPackage.open(source) as package:
        if not package.wad_file_count:
            raise ModpkgError("The .modpkg has no game files Rose can inject")
        if package.optional_layers:
            log.info(
                f"[MODPKG] {source.name}: skipping optional layers "
                f"{', '.join(package.optional_layers)} (Rose injects the base layer)"
            )
        if package.unplaced_file_count:
            log.warning(f"[MODPKG] {source.name}: skipping {package.unplaced_file_count} files that target no game WAD")
        file_count = 0
        for relative_path, content in package.iter_files():
            target = dest_dir.joinpath(*relative_path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            file_count += 1
    log.debug(f"[EXTRACT] Unpacked {file_count} files from {source.name} to {dest_dir}")


class _Cursor:
    """Reads the header and tables front to back, never past the end"""

    def __init__(self, data) -> None:
        self.data = data
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def take(self, size: int) -> bytes:
        if size > self.remaining:
            raise ModpkgError("The .modpkg file is truncated")
        value = self.data[self.offset:self.offset + size]
        self.offset += size
        return value

    def unpack(self, fmt: struct.Struct) -> tuple:
        return fmt.unpack(self.take(fmt.size))

    def count(self, min_entry_size: int) -> range:
        """A table's entry count, checked against the bytes left to hold it"""
        (count,) = self.unpack(_U32)
        if count * min_entry_size > self.remaining:
            raise ModpkgError("The .modpkg file is truncated")
        return range(count)

    def counted_name(self) -> str:
        (size,) = self.unpack(_U32)
        return _decode_name(self.take(size))

    def terminated_name(self) -> str:
        end = self.data.find(b"\x00", self.offset)
        if end < 0:
            raise ModpkgError("The .modpkg file is truncated")
        raw = self.take(end - self.offset)
        self.offset += 1  # the terminator
        return _decode_name(raw)


def _decode_name(raw: bytes) -> str:
    """A table name, refused if extracting under it could leave the output folder"""
    try:
        name = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ModpkgError("The .modpkg holds a name that is not valid UTF-8") from None
    if name.startswith(("/", "\\")) or ":" in name or ".." in re.split(r"[/\\]", name):
        raise ModpkgError(f"The .modpkg holds an unsafe path: {name}")
    return name


def _canonical(name: str) -> bytes:
    """A name as the format compares it: ASCII-lowercased"""
    return name.encode("utf-8").lower()


def _legacy_wad_path(stored_path: str) -> tuple[Optional[str], int]:
    """(WAD folder, path hash) of a file from a package written before the WAD table.

    league-mod 0.2 and older stored no WAD table: the WAD was the first folder of
    the path (aatrox.wad.client\\data\\...) and the path hash covered the whole
    path, so the hash the game knows the file by is recomputed from the rest.
    Today's packer turns every such folder into a WAD target, so a file without
    one under a folder named like a WAD can only come from those packages.
    """
    wad, _, inner_path = stored_path.replace("\\", "/").partition("/")
    if not inner_path:
        return None, 0
    stem = inner_path.split(".", 1)[0]
    if "/" not in inner_path and _HEX_NAME.fullmatch(stem):
        return wad.lower(), int(stem, 16)
    return wad.lower(), xxhash.xxh64_intdigest(inner_path.encode("utf-8").lower())


def _extension(stored_path: str) -> str:
    """The stored path's extension, kept on the unpacked file as a hint"""
    suffix = PurePosixPath(stored_path.replace("\\", "/")).suffix.lower()
    return suffix if _EXTENSION.fullmatch(suffix) else ""


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _decompress(stored: bytes, size: int) -> Optional[bytes]:
    """Decode a Zstandard frame, reading at most one byte past the expected size"""
    parts = []
    total = 0
    try:
        with zstandard.ZstdDecompressor().stream_reader(stored) as reader:
            while total <= size:
                part = reader.read(min(size + 1 - total, _DECOMPRESS_STEP))
                if not part:
                    break
                parts.append(part)
                total += len(part)
    except zstandard.ZstdError:
        return None
    return b"".join(parts)


# MessagePack, as much of it as the metadata document can use (big-endian)
_MSGPACK_NUMBERS = {
    0xCA: struct.Struct(">f"),
    0xCB: struct.Struct(">d"),
    0xCC: struct.Struct(">B"),
    0xCD: struct.Struct(">H"),
    0xCE: struct.Struct(">I"),
    0xCF: struct.Struct(">Q"),
    0xD0: struct.Struct(">b"),
    0xD1: struct.Struct(">h"),
    0xD2: struct.Struct(">i"),
    0xD3: struct.Struct(">q"),
}
# Head byte -> (value kind, length field)
_MSGPACK_SIZED = {
    0xC4: ("bin", struct.Struct(">B")),
    0xC5: ("bin", struct.Struct(">H")),
    0xC6: ("bin", struct.Struct(">I")),
    0xC7: ("ext", struct.Struct(">B")),
    0xC8: ("ext", struct.Struct(">H")),
    0xC9: ("ext", struct.Struct(">I")),
    0xD9: ("str", struct.Struct(">B")),
    0xDA: ("str", struct.Struct(">H")),
    0xDB: ("str", struct.Struct(">I")),
    0xDC: ("array", struct.Struct(">H")),
    0xDD: ("array", struct.Struct(">I")),
    0xDE: ("map", struct.Struct(">H")),
    0xDF: ("map", struct.Struct(">I")),
}
_MSGPACK_FIXEXT_SIZES = {0xD4: 1, 0xD5: 2, 0xD6: 4, 0xD7: 8, 0xD8: 16}
_MSGPACK_CONSTANTS = {0xC0: None, 0xC2: False, 0xC3: True}
_MSGPACK_MAX_DEPTH = 32


def _unpack_msgpack(data: bytes) -> object:
    """Decode one MessagePack value"""
    try:
        value, _ = _msgpack_value(data, 0, 0)
    except (IndexError, struct.error, TypeError, UnicodeDecodeError):
        raise ModpkgError("Unreadable .modpkg metadata") from None
    return value


def _msgpack_value(data: bytes, offset: int, depth: int) -> tuple[object, int]:
    if depth > _MSGPACK_MAX_DEPTH:
        raise ModpkgError("The .modpkg metadata is nested too deeply")
    head = data[offset]
    offset += 1
    if head <= 0x7F:
        return head, offset
    if head >= 0xE0:
        return head - 0x100, offset
    if head <= 0x8F:
        return _msgpack_map(data, offset, head & 0x0F, depth)
    if head <= 0x9F:
        return _msgpack_array(data, offset, head & 0x0F, depth)
    if head <= 0xBF:
        return _msgpack_bytes(data, offset, head & 0x1F, text=True)
    if head in _MSGPACK_CONSTANTS:
        return _MSGPACK_CONSTANTS[head], offset
    if head in _MSGPACK_NUMBERS:
        number = _MSGPACK_NUMBERS[head]
        return number.unpack_from(data, offset)[0], offset + number.size
    if head in _MSGPACK_FIXEXT_SIZES:
        # Extension values mean nothing to the metadata schema: skip type and data
        return _msgpack_skip(data, offset, 1 + _MSGPACK_FIXEXT_SIZES[head])
    if head not in _MSGPACK_SIZED:
        raise ModpkgError(f"Unreadable .modpkg metadata (byte 0x{head:02x})")
    kind, length_field = _MSGPACK_SIZED[head]
    (length,) = length_field.unpack_from(data, offset)
    offset += length_field.size
    if kind == "str":
        return _msgpack_bytes(data, offset, length, text=True)
    if kind == "bin":
        return _msgpack_bytes(data, offset, length, text=False)
    if kind == "ext":
        return _msgpack_skip(data, offset, 1 + length)
    if kind == "array":
        return _msgpack_array(data, offset, length, depth)
    return _msgpack_map(data, offset, length, depth)


def _msgpack_bytes(data: bytes, offset: int, length: int, text: bool) -> tuple[object, int]:
    end = offset + length
    if end > len(data):
        raise ModpkgError("Truncated .modpkg metadata")
    raw = bytes(data[offset:end])
    return (raw.decode("utf-8") if text else raw), end


def _msgpack_skip(data: bytes, offset: int, length: int) -> tuple[None, int]:
    if offset + length > len(data):
        raise ModpkgError("Truncated .modpkg metadata")
    return None, offset + length


def _msgpack_array(data: bytes, offset: int, count: int, depth: int) -> tuple[list, int]:
    if count > len(data) - offset:
        raise ModpkgError("Truncated .modpkg metadata")
    items = []
    for _ in range(count):
        item, offset = _msgpack_value(data, offset, depth + 1)
        items.append(item)
    return items, offset


def _msgpack_map(data: bytes, offset: int, count: int, depth: int) -> tuple[dict, int]:
    if count * 2 > len(data) - offset:
        raise ModpkgError("Truncated .modpkg metadata")
    result = {}
    for _ in range(count):
        key, offset = _msgpack_value(data, offset, depth + 1)
        value, offset = _msgpack_value(data, offset, depth + 1)
        result[key] = value
    return result, offset
