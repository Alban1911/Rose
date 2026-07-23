"""Fast, payload-free inspection of League of Legends WAD archives.

WAD files keep an xxHash64 for each original asset path in their table of
contents.  The path payloads themselves are compressed and are not needed to
identify which champion skins a custom mod affects, so this module only reads
the header and TOC.
"""

from __future__ import annotations

from pathlib import Path
import struct
from typing import BinaryIO, Iterable


WAD_MAGIC = b"RW"
WAD_V3_TOC_OFFSET = 0x110
WAD_V3_TOC_ENTRY_COUNT_OFFSET = 0x10C
WAD_V3_LEGACY_ENTRY_SIZE = 0x21
WAD_V3_ENTRY_SIZE = 0x20
WAD_TOC_BATCH_ENTRIES = 8192

_XXH64_MASK = 0xFFFFFFFFFFFFFFFF
_XXH64_PRIME1 = 11400714785074694791
_XXH64_PRIME2 = 14029467366897019727
_XXH64_PRIME3 = 1609587929392839161
_XXH64_PRIME4 = 9650029242287828579
_XXH64_PRIME5 = 2870177450012600261


def _rotl64(value: int, count: int) -> int:
    return ((value << count) | (value >> (64 - count))) & _XXH64_MASK


def _xxh64_round(accumulator: int, value: int) -> int:
    accumulator = (accumulator + value * _XXH64_PRIME2) & _XXH64_MASK
    accumulator = _rotl64(accumulator, 31)
    return (accumulator * _XXH64_PRIME1) & _XXH64_MASK


def xxhash64(data: bytes, seed: int = 0) -> int:
    """Return xxHash64(data), implemented without an external dependency."""

    length = len(data)
    offset = 0

    if length >= 32:
        v1 = (seed + _XXH64_PRIME1 + _XXH64_PRIME2) & _XXH64_MASK
        v2 = (seed + _XXH64_PRIME2) & _XXH64_MASK
        v3 = seed & _XXH64_MASK
        v4 = (seed - _XXH64_PRIME1) & _XXH64_MASK

        limit = length - 32
        while offset <= limit:
            v1 = _xxh64_round(v1, struct.unpack_from("<Q", data, offset)[0])
            v2 = _xxh64_round(v2, struct.unpack_from("<Q", data, offset + 8)[0])
            v3 = _xxh64_round(v3, struct.unpack_from("<Q", data, offset + 16)[0])
            v4 = _xxh64_round(v4, struct.unpack_from("<Q", data, offset + 24)[0])
            offset += 32

        result = (
            _rotl64(v1, 1)
            + _rotl64(v2, 7)
            + _rotl64(v3, 12)
            + _rotl64(v4, 18)
        ) & _XXH64_MASK

        for value in (v1, v2, v3, v4):
            result ^= _xxh64_round(0, value)
            result = (result * _XXH64_PRIME1 + _XXH64_PRIME4) & _XXH64_MASK
    else:
        result = (seed + _XXH64_PRIME5) & _XXH64_MASK

    result = (result + length) & _XXH64_MASK

    while offset + 8 <= length:
        lane = _xxh64_round(0, struct.unpack_from("<Q", data, offset)[0])
        result ^= lane
        result = (_rotl64(result, 27) * _XXH64_PRIME1 + _XXH64_PRIME4) & _XXH64_MASK
        offset += 8

    if offset + 4 <= length:
        result ^= (struct.unpack_from("<I", data, offset)[0] * _XXH64_PRIME1) & _XXH64_MASK
        result = (_rotl64(result, 23) * _XXH64_PRIME2 + _XXH64_PRIME3) & _XXH64_MASK
        offset += 4

    while offset < length:
        result ^= (data[offset] * _XXH64_PRIME5) & _XXH64_MASK
        result = (_rotl64(result, 11) * _XXH64_PRIME1) & _XXH64_MASK
        offset += 1

    result ^= result >> 33
    result = (result * _XXH64_PRIME2) & _XXH64_MASK
    result ^= result >> 29
    result = (result * _XXH64_PRIME3) & _XXH64_MASK
    result ^= result >> 32
    return result & _XXH64_MASK


def hash_wad_path(path: str) -> int:
    """Hash a normalized WAD asset path."""

    normalized = str(path).replace(chr(92), "/").strip("/").casefold()
    return xxhash64(normalized.encode("utf-8"))


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("truncated WAD archive")
    return data


def read_wad_path_hashes(path: Path) -> set[int]:
    """Read all path hashes from a supported WAD without extracting it.

    Current League archives use WAD v3.  The v3 header includes the TOC count,
    and v3.0-v3.3 use a 0x21-byte entry while v3.4+ use a 0x20-byte entry.
    """

    with path.open("rb") as stream:
        header = _read_exact(stream, WAD_V3_TOC_OFFSET)
        if header[:2] != WAD_MAGIC:
            raise ValueError(f"not a WAD archive: {path}")

        major_version = header[2]
        minor_version = header[3]
        if major_version != 3:
            raise ValueError(f"unsupported WAD version: {major_version}.{minor_version}")

        entry_count = struct.unpack_from("<I", header, WAD_V3_TOC_ENTRY_COUNT_OFFSET)[0]
        entry_size = (
            WAD_V3_LEGACY_ENTRY_SIZE
            if minor_version <= 3
            else WAD_V3_ENTRY_SIZE
        )

        file_size = path.stat().st_size
        toc_size = entry_count * entry_size
        if entry_count <= 0 or WAD_V3_TOC_OFFSET + toc_size > file_size:
            raise ValueError(f"invalid WAD TOC: {path}")

        stream.seek(WAD_V3_TOC_OFFSET)
        hashes: set[int] = set()
        remaining = entry_count
        while remaining:
            batch_count = min(remaining, WAD_TOC_BATCH_ENTRIES)
            batch = _read_exact(stream, batch_count * entry_size)
            for index in range(batch_count):
                offset = index * entry_size
                hashes.add(struct.unpack_from("<Q", batch, offset)[0])
            remaining -= batch_count

        return hashes


def find_matching_wad_paths(
    path_hashes: Iterable[int],
    candidate_paths: Iterable[tuple[str, int]],
) -> set[int]:
    """Return target IDs whose candidate path hash exists in a WAD TOC."""

    available = set(path_hashes)
    return {
        target_id
        for candidate_path, target_id in candidate_paths
        if hash_wad_path(candidate_path) in available
    }
