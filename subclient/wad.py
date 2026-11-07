import gzip
import struct
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

import xxhash
import zstandard

_HEADER = struct.Struct("<2sBB256sQI")  # magic, version, ECDSA signature, checksum, entry count
_ENTRY = struct.Struct("<QIIIBBHQ")  # path hash, offset, size, unpacked size, type, subchunk count, first subchunk, checksum

_RAW, _GZIP, _ZSTD = 0, 1, 3


class WadError(Exception):
    pass


def path_hash(path: str) -> int:
    """WADs index files by the xxh64 of their lowercased path."""
    return xxhash.xxh64(path.lower().encode("utf-8")).intdigest()


class WadArchive:
    """A version 3 WAD: the table of contents is read once, files on demand."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._entries: Optional[Dict[int, Tuple[int, int, int, int]]] = None
        self._lock = threading.Lock()

    def _toc(self) -> Dict[int, Tuple[int, int, int, int]]:
        with self._lock:
            if self._entries is None:
                with open(self.path, "rb") as f:
                    header = f.read(_HEADER.size)
                    if len(header) < _HEADER.size:
                        raise WadError(f"{self.path} is too short to be a WAD")
                    magic, major, _minor, _signature, _checksum, count = _HEADER.unpack(header)
                    if magic != b"RW" or major != 3:
                        raise WadError(f"{self.path} is not a version 3 WAD")
                    table = f.read(_ENTRY.size * count)
                    if len(table) < _ENTRY.size * count:
                        raise WadError(f"{self.path} has a truncated table of contents")
                entries = {}
                for i in range(count):
                    hashed, offset, size, unpacked, kind, _dup, _sub, _check = _ENTRY.unpack_from(table, i * _ENTRY.size)
                    entries[hashed] = (offset, size, unpacked, kind & 0x0F)
                self._entries = entries
            return self._entries

    def contains(self, path: str) -> bool:
        return path_hash(path) in self._toc()

    def read(self, path: str) -> Optional[bytes]:
        """The file's content, or None when the WAD has no such file."""
        entry = self._toc().get(path_hash(path))
        if entry is None:
            return None
        offset, size, unpacked, kind = entry
        with open(self.path, "rb") as f:
            f.seek(offset)
            data = f.read(size)
        if kind == _RAW:
            return data
        if kind == _GZIP:
            return gzip.decompress(data)
        if kind == _ZSTD:
            return zstandard.ZstdDecompressor().decompress(data, max_output_size=unpacked)
        raise WadError(f"{path} in {self.path} uses unsupported storage type {kind}")
