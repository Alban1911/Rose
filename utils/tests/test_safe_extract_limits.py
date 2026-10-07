import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from utils.core import safe_extract
from utils.core.safe_extract import ArchiveTooLargeError, UnsafePathError, safe_extractall


def make_zip(path, files):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)


class ExtractionLimitTests(unittest.TestCase):
    """Custom mods come from anywhere: a zip bomb used to fill the disk while
    it was being unpacked for an injection"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.archive = self.root / 'mod.fantome'
        self.dest = self.root / 'out'

    def test_an_archive_that_unpacks_too_large_is_refused_before_writing(self):
        make_zip(self.archive, {'WAD/a.wad.client': b'\0' * 4096})
        with patch.object(safe_extract, 'MAX_ARCHIVE_UNCOMPRESSED_BYTES', 1024), self.assertLogs(level='ERROR'):
            with self.assertRaises(ArchiveTooLargeError):
                safe_extractall(self.archive, self.dest)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_an_archive_with_too_many_entries_is_refused(self):
        make_zip(self.archive, {f'f{i}.txt': b'x' for i in range(5)})
        with patch.object(safe_extract, 'MAX_ARCHIVE_ENTRIES', 4), self.assertLogs(level='ERROR'):
            with self.assertRaises(ArchiveTooLargeError):
                safe_extractall(self.archive, self.dest)

    def test_the_limit_error_is_handled_like_an_unsafe_path(self):
        self.assertTrue(issubclass(ArchiveTooLargeError, UnsafePathError))

    def test_a_regular_mod_still_extracts(self):
        make_zip(self.archive, {'META/info.json': b'{}', 'WAD/a.wad.client': b'data'})
        safe_extractall(self.archive, self.dest)
        self.assertEqual((self.dest / 'WAD' / 'a.wad.client').read_bytes(), b'data')

    def test_path_traversal_is_still_blocked_from_memory(self):
        buffer = io.BytesIO()
        make_zip(buffer, {'../escape.txt': b'x'})
        with self.assertLogs(level='ERROR'), self.assertRaises(UnsafePathError):
            safe_extract.safe_extractall_from_bytes(buffer.getvalue(), self.dest)
        self.assertFalse((self.root / 'escape.txt').exists())


if __name__ == '__main__':
    unittest.main()
