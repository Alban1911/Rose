import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher.update import update_downloader
from launcher.update.update_downloader import UpdateDownloader


class FakeResponse:
    def __init__(self, chunks, headers=None, error=None):
        self.chunks = chunks
        self.headers = headers or {}
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, _chunk_size):
        yield from self.chunks
        if self.error:
            raise self.error


class PartialDownloadTests(unittest.TestCase):
    """An interrupted download used to overwrite the update package's
    hashes.game.txt with a truncated copy, which was then installed"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.target = Path(temp_dir.name) / 'hashes.game.txt'
        self.target.write_bytes(b'complete copy from the package')
        self.downloader = UpdateDownloader()

    def download_hash_file(self, response):
        with patch.object(update_downloader.requests, 'get', return_value=response):
            return self.downloader.download_hash_file('https://example.invalid/h', self.target, lambda _: None)

    def test_a_dropped_connection_keeps_the_existing_file(self):
        ok = self.download_hash_file(FakeResponse([b'trunc'], error=ConnectionError('reset')))

        self.assertFalse(ok)
        self.assertEqual(self.target.read_bytes(), b'complete copy from the package')

    def test_a_short_body_is_rejected(self):
        ok = self.download_hash_file(FakeResponse([b'half'], headers={'Content-Length': '8'}))

        self.assertFalse(ok)
        self.assertEqual(self.target.read_bytes(), b'complete copy from the package')

    def test_a_complete_download_replaces_the_file(self):
        ok = self.download_hash_file(FakeResponse([b'new ', b'copy'], headers={'Content-Length': '8'}))

        self.assertTrue(ok)
        self.assertEqual(self.target.read_bytes(), b'new copy')
        self.assertFalse(self.target.with_name('hashes.game.txt.part').exists())

    def test_a_compressed_response_is_not_checked_against_its_length(self):
        headers = {'Content-Length': '3', 'Content-Encoding': 'gzip'}
        self.assertTrue(self.download_hash_file(FakeResponse([b'decoded body'], headers=headers)))

    def test_the_update_package_is_checked_against_the_release_asset_size(self):
        with patch.object(update_downloader.requests, 'get', return_value=FakeResponse([b'abc'])):
            ok = self.downloader.download_update(
                'https://example.invalid/u.zip', self.target, lambda _: None, total_size=10,
            )
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
