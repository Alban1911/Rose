import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.core import historic


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


if __name__ == '__main__':
    unittest.main()
