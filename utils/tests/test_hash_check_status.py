import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from launcher.sequences import hash_check_sequence
from utils.download import hash_updater


class HashCheckStatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.target = self.root / 'injection' / 'tools' / 'hashes.game.txt'
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'existing hashes\n')
        self.enterContext(patch.object(sys, 'frozen', True, create=True))
        self.enterContext(patch.object(sys, '_MEIPASS', str(self.root), create=True))
        self.remote = self.enterContext(patch.object(hash_updater, 'remote_etags', return_value=None))
        self.enterContext(patch.object(hash_updater, 'load_state', return_value={}))
        self.save = self.enterContext(patch.object(hash_updater, 'save_state'))
        self.download = self.enterContext(patch.object(hash_updater, 'download_file', return_value=b'new hashes\n'))
        self.statuses = []

    def test_unavailable_check_uses_the_cache_without_claiming_it_is_valid(self):
        result = hash_updater.update_hash_files(status_callback=self.statuses.append)

        self.assertIsNone(result)
        self.assertNotIn('Game hashes are valid', self.statuses)
        self.assertIn('using existing file', self.statuses[-1])
        self.assertEqual(self.target.read_bytes(), b'existing hashes\n')
        self.download.assert_not_called()
        self.save.assert_not_called()

    def test_an_unchanged_remote_is_still_reported_as_current(self):
        etags = {name: 'same' for name in hash_updater.HASH_FILES}
        self.remote.return_value = etags
        with patch.object(hash_updater, 'load_state', return_value={'etags': etags}):
            result = hash_updater.update_hash_files(status_callback=self.statuses.append)

        self.assertIs(result, False)
        self.assertEqual(self.statuses[-1], 'Game hashes are valid')
        self.download.assert_not_called()

    def test_a_failed_download_is_not_reported_as_an_unchanged_file(self):
        self.remote.return_value = {name: 'new' for name in hash_updater.HASH_FILES}
        self.download.return_value = None

        result = hash_updater.update_hash_files(status_callback=self.statuses.append)

        self.assertIsNone(result)
        self.assertEqual(self.target.read_bytes(), b'existing hashes\n')
        self.assertNotIn('Game hashes are valid', self.statuses)
        self.save.assert_not_called()

    def test_a_missing_cache_is_downloaded_even_when_the_check_is_unavailable(self):
        self.target.unlink()

        result = hash_updater.update_hash_files(status_callback=self.statuses.append)

        self.assertIs(result, True)
        self.assertEqual(self.download.call_count, len(hash_updater.HASH_FILES))
        self.assertIn(b'new hashes', self.target.read_bytes())

    def test_a_failed_write_is_not_reported_as_an_unchanged_file(self):
        self.remote.return_value = {name: 'new' for name in hash_updater.HASH_FILES}
        with patch('builtins.open', side_effect=PermissionError('read only')):
            result = hash_updater.update_hash_files(status_callback=self.statuses.append)

        self.assertIsNone(result)
        self.assertEqual(self.target.read_bytes(), b'existing hashes\n')
        self.save.assert_not_called()

    def test_the_launcher_preserves_the_failed_check_status(self):
        dialog = Mock()

        hash_check_sequence.HashCheckSequence().perform_hash_check(dialog)

        statuses = [call.args[0] for call in dialog.set_status.call_args_list]
        self.assertNotIn('Game hashes are valid', statuses)
        self.assertIn('using existing file', statuses[-1])

    def test_a_missing_file_after_a_failed_download_still_reports_an_error(self):
        self.target.unlink()
        self.download.return_value = None
        dialog = Mock()

        hash_check_sequence.HashCheckSequence().perform_hash_check(dialog)

        self.assertEqual(dialog.set_status.call_args.args[0], 'hashes.game.txt not found after download attempt')
