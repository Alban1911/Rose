import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from utils.download.repo_downloader import RepoDownloader


class ClassicLibraryTests(unittest.TestCase):
    """LeagueSkins' classic/ folder is kept in %LOCALAPPDATA%/Rose/classic"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.downloader = RepoDownloader(target_dir=self.root / 'skins')
        self.classic_dir = self.root / 'classic'

    def _repository_zip(self):
        path = self.root / 'repo.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('LeagueSkins-main/skins/1/1001/1001.fantome', b'skin')
            archive.writestr('LeagueSkins-main/classic/1/1001/1001.fantome', b'classic skin')
            archive.writestr('LeagueSkins-main/classic/103/103001/103052/103052.fantome', b'classic chroma')
        return path

    def test_classic_folder_sits_next_to_the_skins(self):
        self.assertEqual(self.downloader.classic_dir, self.classic_dir)
        self.assertEqual(
            self.downloader._resolve_local_path('classic/1/1001/1001.fantome'),
            self.classic_dir / '1' / '1001' / '1001.fantome',
        )
        self.assertIsNone(self.downloader._resolve_local_path('classic/../outside.fantome'))

    def test_repository_zip_brings_the_classic_skins(self):
        removed_upstream = self.classic_dir / '2' / '2001' / '2001.fantome'
        removed_upstream.parent.mkdir(parents=True)
        removed_upstream.write_bytes(b'old')

        self.assertTrue(self.downloader.extract_skins_from_zip(
            self._repository_zip(), overwrite_existing=True, extract_resources=False,
        ))

        self.assertEqual((self.root / 'skins' / '1' / '1001' / '1001.fantome').read_bytes(), b'skin')
        self.assertEqual((self.classic_dir / '1' / '1001' / '1001.fantome').read_bytes(), b'classic skin')
        self.assertTrue((self.classic_dir / '103' / '103001' / '103052' / '103052.fantome').exists())
        self.assertFalse(removed_upstream.exists())
        self.assertTrue(self.downloader._classic_library_synced())

    def test_incomplete_extraction_is_retried(self):
        # A folder in the way makes one Classic skin fail to extract
        (self.classic_dir / '1' / '1001' / '1001.fantome').mkdir(parents=True)
        self.downloader.extract_skins_from_zip(self._repository_zip(), overwrite_existing=True, extract_resources=False)
        self.assertEqual(self.downloader.last_extraction_failures, 1)
        self.assertFalse(self.downloader._classic_library_synced())

    def test_installs_synced_before_classic_existed_download_everything_once(self):
        with patch.object(self.downloader, 'fetch_remote_sha', return_value='abc123'), \
                patch.object(self.downloader, 'get_local_sha', return_value='abc123'), \
                patch.object(self.downloader, 'download_and_extract_skins', return_value=True) as full:
            self.assertTrue(self.downloader.download_incremental_updates())
            full.assert_called_once_with(force_update=True, remote_sha='abc123')

            self.downloader._mark_classic_library_synced()
            full.reset_mock()
            self.assertTrue(self.downloader.download_incremental_updates())
            full.assert_not_called()


if __name__ == '__main__':
    unittest.main()
