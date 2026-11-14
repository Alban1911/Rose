import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.core import historic, mod_historic


class HistoricReadErrorTests(unittest.TestCase):
    """An unreadable history file made Historic mode forget every saved skin
    without a single log line"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.path = Path(temp_dir.name) / 'historic.json'
        patcher = patch.object(historic, '_historic_file_path', return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_corrupt_history_is_logged(self):
        self.path.write_text('{"21": 21001', encoding='utf-8')
        with self.assertLogs(level='WARNING') as logs:
            self.assertEqual(historic.load_historic_map(), {})
        self.assertIn('Could not read the saved skins', logs.output[0])

    def test_a_missing_history_is_quiet(self):
        with self.assertNoLogs(level='WARNING'):
            self.assertEqual(historic.load_historic_map(), {})


class UnreadableHistoryIsNotOverwrittenTests(unittest.TestCase):
    """A write that could not read the file first used to replace it with a
    single entry, dropping every other saved skin"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.path = Path(temp_dir.name) / 'historic.json'
        self.mod_path = Path(temp_dir.name) / 'mod_historic.json'
        for target, name in ((historic, '_historic_file_path'), (mod_historic, '_mod_historic_file_path')):
            patcher = patch.object(target, name, return_value=self.path if target is historic else self.mod_path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.original = '{"21": 21001, "103": 103002}'
        self.path.write_text(self.original, encoding='utf-8')

    def locked(self, path):
        real_open = Path.open

        def fake_open(self_, *args, **kwargs):
            if self_ == path:
                raise PermissionError('held by another process')
            return real_open(self_, *args, **kwargs)

        return patch.object(Path, 'open', fake_open)

    def test_write_keeps_the_file_when_it_cannot_be_read(self):
        with self.locked(self.path), self.assertLogs(level='WARNING'):
            historic.write_historic_entry(22, 22001)
        self.assertEqual(self.path.read_text(encoding='utf-8'), self.original)

    def test_write_replaces_a_corrupt_file(self):
        # Atomic writes never leave a corrupt file behind, so it is not a
        # transient state worth refusing to save over
        for content in ('{"21": 21001', '[1, 2]'):
            self.path.write_text(content, encoding='utf-8')
            historic.write_historic_entry(22, 22001)
            self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), {'22': 22001})

    def test_clear_keeps_the_file_when_it_cannot_be_read(self):
        with self.locked(self.path), self.assertLogs(level='WARNING'):
            historic.clear_historic_entry(21)
        self.assertEqual(self.path.read_text(encoding='utf-8'), self.original)

    def test_rename_raises_and_keeps_the_file_when_it_cannot_be_read(self):
        with self.locked(self.path), self.assertRaises(PermissionError):
            historic.rename_mod_paths({'a': 'b'})
        self.assertEqual(self.path.read_text(encoding='utf-8'), self.original)

    def test_writes_start_fresh_when_the_file_is_missing_or_empty(self):
        self.path.write_text('', encoding='utf-8')
        historic.write_historic_entry(22, 22001)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), {'22': 22001})
        self.path.unlink()
        historic.write_historic_entry(23, 23001)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), {'23': 23001})

    def test_mod_history_write_and_clear_keep_an_unreadable_file(self):
        original = '{"map": "maps/Map", "vfx": ["vfx/Old"]}'
        self.mod_path.write_text(original, encoding='utf-8')
        with self.locked(self.mod_path), self.assertLogs(level='WARNING'):
            mod_historic.write_historic_mod('ui', ['ui/Menu'])
            mod_historic.clear_historic_mod('map')
        self.assertEqual(self.mod_path.read_text(encoding='utf-8'), original)
        self.mod_path.write_text('{"map": ', encoding='utf-8')
        mod_historic.write_historic_mod('ui', ['ui/Menu'])
        self.assertEqual(json.loads(self.mod_path.read_text(encoding='utf-8')), {'ui': ['ui/Menu']})


if __name__ == '__main__':
    unittest.main()
