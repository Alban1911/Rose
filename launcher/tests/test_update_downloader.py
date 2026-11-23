import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

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
        self.sleep = self.enterContext(patch('time.sleep'))

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

    def test_temporary_network_errors_retry_the_download(self):
        for error in (
            requests.ConnectionError('reset'),
            requests.ReadTimeout('timed out'),
            requests.exceptions.ChunkedEncodingError('stream interrupted'),
        ):
            with self.subTest(error=type(error).__name__):
                self.sleep.reset_mock()
                response = FakeResponse([b'new copy'])
                with patch.object(update_downloader.requests, 'get', side_effect=[error, response]) as get:
                    ok = self.downloader.download_update(
                        'https://example.invalid/u.zip', self.target, lambda _: None,
                    )
                self.assertTrue(ok)
                self.assertEqual(get.call_count, 2)
                self.sleep.assert_called_once_with(1.0)
                self.assertEqual(self.target.read_bytes(), b'new copy')

    def test_a_retry_restarts_the_partial_file_and_progress(self):
        interrupted = FakeResponse([b'bad'], error=requests.ConnectionError('reset'))
        progress = []

        def get(url, **kwargs):
            if not progress:
                return interrupted
            self.assertEqual(self.target.read_bytes(), b'complete copy from the package')
            self.assertFalse(self.target.with_name(self.target.name + '.part').exists())
            return FakeResponse([b'new'])

        with patch.object(update_downloader.requests, 'get', side_effect=get) as request:
            ok = self.downloader.download_update(
                'https://example.invalid/u.zip', self.target, lambda _: None,
                bytes_callback=lambda current, total: progress.append((current, total)), total_size=3,
            )

        self.assertTrue(ok)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(progress, [(3, 3), (0, 3), (3, 3)])
        self.assertEqual(self.target.read_bytes(), b'new')

    def test_retries_are_bounded_and_keep_the_existing_file(self):
        statuses = []
        with patch.object(update_downloader.requests, 'get', side_effect=requests.ConnectionError('reset')) as get:
            ok = self.downloader.download_update(
                'https://example.invalid/u.zip', self.target, statuses.append,
            )

        self.assertFalse(ok)
        self.assertEqual(get.call_count, 3)
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [1.0, 2.0])
        self.assertTrue(statuses[-1].startswith('Download failed:'))
        self.assertEqual(self.target.read_bytes(), b'complete copy from the package')
        self.assertFalse(self.target.with_name(self.target.name + '.part').exists())

    def test_permanent_failures_do_not_retry(self):
        for error in (requests.HTTPError('404'), requests.exceptions.SSLError('invalid certificate')):
            with self.subTest(error=type(error).__name__):
                with patch.object(update_downloader.requests, 'get', side_effect=error) as get:
                    ok = self.downloader.download_update(
                        'https://example.invalid/u.zip', self.target, lambda _: None,
                    )
                self.assertFalse(ok)
                self.assertEqual(get.call_count, 1)
                self.sleep.assert_not_called()

    def test_a_local_file_error_does_not_retry(self):
        with (
            patch.object(update_downloader.requests, 'get', return_value=FakeResponse([b'new'])) as get,
            patch.object(update_downloader.os, 'replace', side_effect=PermissionError('file locked')),
        ):
            ok = self.downloader.download_update(
                'https://example.invalid/u.zip', self.target, lambda _: None,
            )

        self.assertFalse(ok)
        self.assertEqual(get.call_count, 1)
        self.sleep.assert_not_called()
        self.assertEqual(self.target.read_bytes(), b'complete copy from the package')

    def test_release_hash_downloads_retry_temporary_errors_too(self):
        with patch.object(update_downloader.requests, 'get', side_effect=[
            requests.ConnectionError('reset'), FakeResponse([b'new hashes']),
        ]) as get:
            ok = self.downloader.download_hash_file(
                'https://example.invalid/hashes', self.target, lambda _: None,
            )

        self.assertTrue(ok)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(self.target.read_bytes(), b'new hashes')


if __name__ == '__main__':
    unittest.main()
