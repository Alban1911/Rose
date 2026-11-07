import gzip
import struct
import tempfile
import unittest
from pathlib import Path

import zstandard

from subclient.wad import WadArchive, WadError, path_hash


def build_wad(path: Path, files: dict) -> Path:
    """A version 3.4 WAD holding {path: (storage type, content)}."""
    blobs, entries = b"", []
    data_start = 272 + 32 * len(files)
    for name, (kind, content) in files.items():
        stored = {0: content, 1: gzip.compress(content), 3: zstandard.ZstdCompressor().compress(content)}[kind]
        entries.append(struct.pack("<QIIIBBHQ", path_hash(name), data_start + len(blobs), len(stored),
                                   len(content), kind, 0, 0, 0))
        blobs += stored
    path.write_bytes(struct.pack("<2sBB256sQI", b"RW", 3, 4, b"", 0, len(files)) + b"".join(entries) + blobs)
    return path


class WadArchiveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_reads_stored_and_compressed_files(self):
        wad = WadArchive(build_wad(self.dir / "assets.wad", {
            "plugins/a/global/default/raw.svg": (0, b"<svg/>"),
            "plugins/a/global/default/old.css": (1, b"body{}"),
            "plugins/a/global/default/rcp-fe-a.js": (3, b"console.log(1)" * 100),
        }))
        self.assertEqual(wad.read("plugins/a/global/default/raw.svg"), b"<svg/>")
        self.assertEqual(wad.read("plugins/a/global/default/old.css"), b"body{}")
        self.assertEqual(wad.read("plugins/a/global/default/rcp-fe-a.js"), b"console.log(1)" * 100)

    def test_paths_are_case_insensitive_and_missing_files_are_none(self):
        wad = WadArchive(build_wad(self.dir / "assets.wad", {"plugins/a/global/default/x.js": (0, b"x")}))
        self.assertTrue(wad.contains("Plugins/A/global/default/X.js"))
        self.assertIsNone(wad.read("plugins/a/global/default/y.js"))

    def test_rejects_other_files(self):
        path = self.dir / "not.wad"
        path.write_bytes(b"MZ" + b"\0" * 300)
        with self.assertRaises(WadError):
            WadArchive(path).read("anything")


if __name__ == "__main__":
    unittest.main()
