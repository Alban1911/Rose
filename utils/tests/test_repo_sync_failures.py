import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from utils.download.repo_downloader import RepoDownloader


class FailedRemovalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.downloader = RepoDownloader(self.root / 'skins')
        self.downloader.save_local_sha('old-sha')
        self.downloader._mark_classic_library_synced()
        self.old = self.root / 'skins' / '1' / '1001.zip'
        self.old.parent.mkdir(parents=True)
        self.old.write_bytes(b'obsolete')

    def lock_old_file(self):
        unlink = Path.unlink

        def remove(path, *args, **kwargs):
            if path == self.old:
                raise PermissionError('file is temporarily locked')
            return unlink(path, *args, **kwargs)

        return patch.object(Path, 'unlink', remove)

    def test_incremental_removed_file_failure_does_not_record_the_commit(self):
        with self.lock_old_file(), \
                patch.object(self.downloader, 'fetch_remote_sha', return_value='new-sha'), \
                patch.object(self.downloader, 'get_changed_files', return_value=[
                    {'filename': 'skins/1/1001.zip', 'status': 'removed'},
                ]), \
                patch.object(self.downloader, 'download_and_extract_skins', return_value=False) as full:
            self.assertFalse(self.downloader.download_incremental_updates())
        self.assertEqual(self.downloader.get_local_sha(), 'old-sha')
        full.assert_called_once()

    def test_failed_rename_removal_is_not_success(self):
        with self.lock_old_file(), patch.object(self.downloader.session, 'get') as get:
            get.return_value.iter_content.return_value = [b'new skin']
            self.assertFalse(self.downloader.download_changed_files([{
                'filename': 'skins/1/1002.zip', 'status': 'renamed',
                'previous_filename': 'skins/1/1001.zip',
            }]))
        self.assertTrue(self.old.exists())

    def test_failed_rename_does_not_record_the_commit(self):
        with self.lock_old_file(), \
                patch.object(self.downloader, 'fetch_remote_sha', return_value='new-sha'), \
                patch.object(self.downloader, 'get_changed_files', return_value=[{
                    'filename': 'skins/1/1002.zip', 'status': 'renamed',
                    'previous_filename': 'skins/1/1001.zip',
                }]), \
                patch.object(self.downloader.session, 'get') as get, \
                patch.object(self.downloader, 'download_and_extract_skins', return_value=False):
            get.return_value.iter_content.return_value = [b'new skin']
            self.assertFalse(self.downloader.download_incremental_updates())
        self.assertEqual(self.downloader.get_local_sha(), 'old-sha')

    def test_full_sync_retains_version_until_obsolete_file_can_be_removed(self):
        archive = self.root / 'repository.zip'
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr('LeagueSkins-main/skins/1/1002.zip', b'replacement')
        with self.lock_old_file(), \
                patch.object(self.downloader, 'download_repo_zip', return_value=archive):
            self.downloader.download_and_extract_skins(True, remote_sha='new-sha')
        self.assertEqual(self.downloader.get_local_sha(), 'old-sha')
        self.assertEqual(self.downloader.last_extraction_failures, 1)
        self.assertTrue(self.old.exists())

    def test_successful_cleanup_counts_deleted_files(self):
        entries = [zipfile.ZipInfo('LeagueSkins-main/skins/1/1002.zip')]
        self.assertEqual(self.downloader._cleanup_removed_skin_files(entries, self.root / 'skins'), 1)
        self.assertFalse(self.old.exists())
        self.assertEqual(self.downloader.get_local_sha(), 'old-sha')

    def test_full_fallback_retries_locked_removal_before_recording_commit(self):
        def repository_zip(**kwargs):
            archive = self.root / 'repository.zip'
            with zipfile.ZipFile(archive, 'w') as zf:
                zf.writestr('LeagueSkins-main/skins/1/1002.zip', b'replacement')
            return archive

        with patch.object(self.downloader, 'fetch_remote_sha', return_value='new-sha'), \
                patch.object(self.downloader, 'get_changed_files', return_value=[
                    {'filename': 'skins/1/1001.zip', 'status': 'removed'},
                ]), \
                patch.object(self.downloader, 'download_repo_zip', side_effect=repository_zip):
            with self.lock_old_file():
                self.downloader.download_incremental_updates()
            self.assertEqual(self.downloader.get_local_sha(), 'old-sha')
            self.assertEqual(self.downloader.last_extraction_failures, 1)
            self.assertTrue(self.old.exists())

            with patch.object(self.downloader, 'get_changed_files', return_value=None):
                self.assertTrue(self.downloader.download_incremental_updates())
        self.assertEqual(self.downloader.get_local_sha(), 'new-sha')
        self.assertEqual(self.downloader.last_extraction_failures, 0)
        self.assertFalse(self.old.exists())


if __name__ == '__main__':
    unittest.main()
