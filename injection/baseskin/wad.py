#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WAD v3 archives: the game's, read file by file, and a mod's, edited and written again.

A WAD is never read whole: its table is read, and a file's bytes when it is
asked for, so a champion WAD of a few hundred MB, or a voice-over WAD, costs
the few files the steps look at. Writing one streams the files nobody edited
from where they came.
"""

from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path
from typing import BinaryIO, Dict, Iterator, List, Optional, Tuple

import xxhash
import zstandard

HEADER_SIZE = 272
TOC_ENTRY_SIZE = 32
KIND_RAW, KIND_GZIP, KIND_ZSTD, KIND_ZSTD_CHUNKED = 0, 1, 3, 4
_KINDS = (KIND_RAW, KIND_GZIP, KIND_ZSTD, KIND_ZSTD_CHUNKED)
_NO_CHUNKING = bytes(3)
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_COPY_CHUNK = 1024 * 1024


class WadError(ValueError):
    """The bytes are not a WAD this module can read."""


def path_hash(path: str) -> int:
    """The id a WAD stores a path under: xxh64 of the lowercased path with forward slashes."""
    return xxhash.xxh64_intdigest(path.replace("\\", "/").encode("utf-8", "surrogateescape").lower())


def _decompress_chunked(payload: bytes) -> bytes:
    """A type 4 file: sub-chunks one after the other, each a zstd frame or, where
    compressing did not pay, the sub-chunk's raw bytes (a texture often starts
    with one: League's tools copy it through)."""
    view = memoryview(payload)
    out = bytearray()
    at = 0
    while at < len(payload):
        if payload.startswith(_ZSTD_MAGIC, at):
            frame = zstandard.ZstdDecompressor().decompressobj()
            out += frame.decompress(view[at:])
            if not frame.eof:
                raise WadError("a compressed sub-chunk is cut short")
            at = len(payload) - len(frame.unused_data)
        else:
            following = payload.find(_ZSTD_MAGIC, at)
            end = len(payload) if following < 0 else following
            out += view[at:end]
            at = end
    return bytes(out)


def _decompress(kind: int, payload: bytes, size: Optional[int] = None) -> bytes:
    """A file's content. Raises WadError (a ValueError) for bytes that do not
    decompress, whatever the codec's own error."""
    try:
        if kind == KIND_RAW:
            data = bytes(payload)
        elif kind == KIND_ZSTD:
            data = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(payload), read_across_frames=True).read()
        elif kind == KIND_ZSTD_CHUNKED:
            data = _decompress_chunked(bytes(payload))
        elif kind == KIND_GZIP:
            data = zlib.decompress(payload, 31)
        else:
            raise WadError(f"unsupported WAD compression type {kind}")
    except (zstandard.ZstdError, zlib.error) as e:
        raise WadError(f"a file does not decompress: {e}") from e
    if size is not None and len(data) != size:
        raise WadError(f"a file decompresses to {len(data)} bytes, its table says {size}")
    return data


def compress(data: bytes) -> Tuple[bytes, int]:
    """(payload, kind) as a WAD stores *data*: zstd when that is smaller."""
    packed = zstandard.ZstdCompressor(level=3).compress(data)
    if len(packed) < len(data):
        return packed, KIND_ZSTD
    return data, KIND_RAW


# --------------------------------------------------------------------------------------
# where a WAD's bytes are
# --------------------------------------------------------------------------------------

class WadSource:
    """Random access to the bytes of one WAD."""

    size = 0

    def read_at(self, offset: int, count: int) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        pass


class BytesSource(WadSource):
    def __init__(self, data) -> None:
        self._view = memoryview(data)
        self.size = len(self._view)

    def read_at(self, offset: int, count: int) -> bytes:
        return bytes(self._view[offset:offset + count])


class FileSource(WadSource):
    """*size* bytes of a file from *start*: a WAD file, or a WAD stored
    uncompressed in a ZIP archive."""

    def __init__(self, path: Path, start: int = 0, size: Optional[int] = None) -> None:
        self._handle: Optional[BinaryIO] = open(path, "rb")
        self._start = start
        if size is None:
            self._handle.seek(0, io.SEEK_END)
            size = self._handle.tell() - start
        self.size = size

    def read_at(self, offset: int, count: int) -> bytes:
        if self._handle is None:
            raise WadError("the WAD was closed")
        count = max(0, min(count, self.size - offset))
        self._handle.seek(self._start + offset)
        return self._handle.read(count)

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def _read_table(source: WadSource, name: str) -> Tuple[bytes, bytes]:
    """(header, table of contents) of the WAD in *source*."""
    head = source.read_at(0, HEADER_SIZE)
    if len(head) < HEADER_SIZE or head[:2] != b"RW":
        raise WadError(f"{name}not a WAD")
    if head[2] != 3:
        raise WadError(f"{name}unsupported WAD version {head[2]}.{head[3]}")
    count = struct.unpack_from("<I", head, 268)[0]
    table = source.read_at(HEADER_SIZE, TOC_ENTRY_SIZE * count)
    if len(table) != TOC_ENTRY_SIZE * count:
        raise WadError(f"{name}table of contents is truncated")
    return head, table


class GameWad:
    """One of the game's WADs. Its table is read once; a file is read, and
    decompressed, when asked for."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        source = FileSource(self.path)
        try:
            _head, table = _read_table(source, f"{self.path.name}: ")
        finally:
            source.close()
        self._entries: Dict[int, tuple] = {}
        for index in range(len(table) // TOC_ENTRY_SIZE):
            name_hash, offset, packed, size = struct.unpack_from("<QIII", table, index * TOC_ENTRY_SIZE)
            kind = table[index * TOC_ENTRY_SIZE + 20] & 0x0F
            self._entries.setdefault(name_hash, (offset, packed, size, kind))

    def has_path(self, path: str) -> bool:
        return path_hash(path) in self._entries

    def read_path(self, path: str) -> Optional[bytes]:
        """The file at *path*, decompressed (None when the WAD has none)."""
        entry = self._entries.get(path_hash(path))
        if entry is None:
            return None
        offset, packed, size, kind = entry
        with open(self.path, "rb") as handle:
            handle.seek(offset)
            payload = handle.read(packed)
        if len(payload) != packed:
            raise WadError(f"{self.path.name}: a file runs past the end of the WAD")
        try:
            return _decompress(kind, payload, size)
        except WadError as e:
            raise WadError(f"{self.path.name}: {path}: {e}") from e


# --------------------------------------------------------------------------------------
# a mod's WAD
# --------------------------------------------------------------------------------------

class WadFile:
    """One file of a mod's WAD: where its stored bytes are and, read on demand,
    its content. A file given new content holds it in memory."""

    __slots__ = ("name_hash", "kind", "size", "packed", "chunking", "checksum",
                 "_source", "_offset", "_payload", "_data")

    def __init__(self, name_hash: int, kind: int, size: int, packed: int, source: Optional[WadSource] = None,
                 offset: int = 0, chunking: bytes = _NO_CHUNKING, checksum: Optional[bytes] = None) -> None:
        self.name_hash = name_hash
        self.kind = kind
        self.size = size
        self.packed = packed
        # What a sub-chunked file (type 4) keeps in its table besides the type:
        # the sub-chunk count (the type byte's high nibble) and the first sub-chunk's index
        self.chunking = chunking
        self.checksum = checksum   # the table's, for a file written back as it came
        self._source = source
        self._offset = offset
        self._payload: Optional[bytes] = None
        self._data: Optional[bytes] = None

    @property
    def payload(self) -> bytes:
        """The bytes as the WAD stores them."""
        if self._payload is not None:
            return self._payload
        if self._source is None:
            return b""
        payload = self._source.read_at(self._offset, self.packed)
        if len(payload) != self.packed:
            raise WadError("a WAD file runs past the end of the WAD")
        return payload

    @property
    def data(self) -> bytes:
        if self._data is None:
            self._data = _decompress(self.kind, self.payload, self.size)
        return self._data

    def set_data(self, data: bytes) -> None:
        self._payload, self.kind = compress(data)
        self.packed = len(self._payload)
        self.size = len(data)
        self.chunking = _NO_CHUNKING
        self.checksum = None
        self._data = data

    def write_payload(self, out: BinaryIO) -> None:
        if self._payload is not None or self._source is None:
            out.write(self.payload)
            return
        done = 0
        while done < self.packed:
            chunk = self._source.read_at(self._offset + done, min(_COPY_CHUNK, self.packed - done))
            if not chunk:
                raise WadError("a WAD file runs past the end of the WAD")
            out.write(chunk)
            done += len(chunk)


class ModWad:
    """A WAD file of a mod. Its table is read when it is opened, a file's bytes
    when they are asked for. Files keep their order; those nobody edits are
    written back as they came."""

    def __init__(self, data=None, source: Optional[WadSource] = None) -> None:
        if source is None:
            source = BytesSource(data if data is not None else b"")
        self._source = source
        head, table = _read_table(source, "")
        self.version = bytes(head[2:4])
        self.files: List[WadFile] = []
        self._index: Dict[int, WadFile] = {}
        for index in range(len(table) // TOC_ENTRY_SIZE):
            at = index * TOC_ENTRY_SIZE
            name_hash, offset, packed, size = struct.unpack_from("<QIII", table, at)
            kind = table[at + 20] & 0x0F
            if kind not in _KINDS:
                raise WadError(f"unsupported WAD compression type {kind}")
            if offset + packed > source.size:
                raise WadError("a WAD file runs past the end of the WAD")
            chunking = _NO_CHUNKING
            if kind == KIND_ZSTD_CHUNKED:
                chunking = bytes([table[at + 20] & 0xF0]) + table[at + 22:at + 24]
            entry = WadFile(name_hash, kind, size, packed, source, offset, chunking, table[at + 24:at + 32])
            self.files.append(entry)
            self._index.setdefault(name_hash, entry)
        self.modified = False

    def close(self) -> None:
        self._source.close()

    def get(self, name_hash: int) -> Optional[WadFile]:
        return self._index.get(name_hash)

    def __contains__(self, name_hash: int) -> bool:
        return name_hash in self._index

    def put(self, name_hash: int, data: bytes) -> None:
        """Set a file's content (a new file goes last)."""
        entry = self._index.get(name_hash)
        if entry is None:
            entry = WadFile(name_hash, KIND_RAW, 0, 0)
            self.files.append(entry)
            self._index[name_hash] = entry
        entry.set_data(data)
        self.modified = True

    def __iter__(self) -> Iterator[WadFile]:
        return iter(self.files)

    def byte_size(self) -> int:
        return HEADER_SIZE + TOC_ENTRY_SIZE * len(self.files) + sum(entry.packed for entry in self.files)

    def write_to(self, out: BinaryIO) -> None:
        """Write the WAD to *out*: the files nobody edited are copied from where they are."""
        count = len(self.files)
        out.write(b"RW" + self.version + bytes(256 + 8) + struct.pack("<I", count))
        table = bytearray()
        offset = HEADER_SIZE + TOC_ENTRY_SIZE * count
        for entry in self.files:
            chunked = entry.kind == KIND_ZSTD_CHUNKED
            table += struct.pack("<QIII", entry.name_hash, offset, entry.packed, entry.size)
            table.append(entry.kind | (entry.chunking[0] if chunked else 0))
            table.append(0)  # duplicate flag: every file carries its own bytes
            table += entry.chunking[1:3] if chunked else b"\x00\x00"
            checksum = entry.checksum
            if checksum is None or len(checksum) != 8:
                checksum = struct.pack("<Q", xxhash.xxh3_64_intdigest(entry.payload))
            table += checksum
            offset += entry.packed
        out.write(table)
        for entry in self.files:
            entry.write_payload(out)

    def to_bytes(self) -> bytes:
        out = io.BytesIO()
        self.write_to(out)
        return out.getvalue()
