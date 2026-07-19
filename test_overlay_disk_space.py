import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from injection.overlay.overlay_manager import OverlayManager


class OverlayDiskSpaceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = OverlayManager(
            tools_dir=Path(self.temp_dir.name) / 'tools',
            mods_dir=Path(self.temp_dir.name) / 'mods',
            game_dir=Path(self.temp_dir.name) / 'game',
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch('injection.overlay.overlay_manager.report_issue')
    @patch('injection.overlay.overlay_manager.shutil.disk_usage')
    def test_reports_when_free_space_is_below_safe_minimum(self, disk_usage, report_issue):
        disk_usage.return_value = SimpleNamespace(free=512 * 1024 * 1024)

        result = self.manager._report_low_disk_space_failure(mod_names=['skin', 'map'])

        self.assertTrue(result)
        report_issue.assert_called_once()
        self.assertEqual(report_issue.call_args.args[0], 'LOW_DISK_SPACE')

    @patch('injection.overlay.overlay_manager.report_issue')
    @patch('injection.overlay.overlay_manager.shutil.disk_usage')
    def test_reports_explicit_disk_full_tool_error(self, disk_usage, report_issue):
        disk_usage.return_value = SimpleNamespace(free=100 * 1024 * 1024 * 1024)

        result = self.manager._report_low_disk_space_failure(
            output_lines=['mkoverlay failed: no space left on device'],
        )

        self.assertTrue(result)
        report_issue.assert_called_once()

    @patch('injection.overlay.overlay_manager.report_issue')
    @patch('injection.overlay.overlay_manager.shutil.disk_usage')
    def test_does_not_report_normal_injection_failure(self, disk_usage, report_issue):
        disk_usage.return_value = SimpleNamespace(free=100 * 1024 * 1024 * 1024)

        result = self.manager._report_low_disk_space_failure(
            output_lines=['mkoverlay failed: conflicting files'],
        )

        self.assertFalse(result)
        report_issue.assert_not_called()


if __name__ == '__main__':
    unittest.main()
