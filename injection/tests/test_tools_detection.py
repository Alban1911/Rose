import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from injection.tools.tools_manager import (
    LTF_BRIDGE_DLL,
    LTF_LAUNCHER,
    ToolsManager,
)


class LtfLauncherDetectionTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.tools = Path(temp_dir.name)

    def test_both_files_make_the_launcher_usable(self):
        (self.tools / LTF_LAUNCHER).write_bytes(b"launcher")
        (self.tools / LTF_BRIDGE_DLL).write_bytes(b"dll")

        self.assertEqual(ToolsManager(self.tools).detect_ltf_launcher(), self.tools / LTF_LAUNCHER)

    def test_a_missing_bridge_dll_makes_the_launcher_unusable(self):
        # The launcher refuses to start without its DLL next to it
        (self.tools / LTF_LAUNCHER).write_bytes(b"launcher")

        self.assertIsNone(ToolsManager(self.tools).detect_ltf_launcher())

    def test_check_tools_available_reports_the_missing_runtime(self):
        self.assertFalse(ToolsManager(self.tools).check_tools_available())

        (self.tools / LTF_LAUNCHER).write_bytes(b"launcher")
        (self.tools / LTF_BRIDGE_DLL).write_bytes(b"dll")

        self.assertTrue(ToolsManager(self.tools).check_tools_available())


class LtkManagerDetectionTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.manager = self.root / "ltk-manager.exe"
        self.manager.write_bytes(b"manager")

    def test_the_configured_path_wins(self):
        with patch("config.get_config_option", return_value=str(self.manager)):
            found = ToolsManager(self.root).detect_ltk_manager()

        self.assertEqual(found, self.manager)

    def test_a_configured_path_that_does_not_exist_falls_through(self):
        with patch("config.get_config_option", return_value=str(self.root / "gone.exe")), \
                patch.object(ToolsManager, "_running_ltk_manager", return_value=None), \
                patch("injection.tools.tools_manager.ltk_manager_install_dirs", return_value=[]):
            self.assertIsNone(ToolsManager(self.root).detect_ltk_manager())

    def test_a_running_manager_is_used_when_nothing_is_configured(self):
        with patch("config.get_config_option", return_value=None), \
                patch.object(ToolsManager, "_running_ltk_manager", return_value=self.manager):
            found = ToolsManager(self.root).detect_ltk_manager()

        self.assertEqual(found, self.manager)

    def test_the_known_install_locations_are_searched(self):
        with patch("config.get_config_option", return_value=None), \
                patch.object(ToolsManager, "_running_ltk_manager", return_value=None), \
                patch("injection.tools.tools_manager.ltk_manager_install_dirs", return_value=[self.root]):
            found = ToolsManager(self.root).detect_ltk_manager()

        self.assertEqual(found, self.manager)

    def test_no_install_reports_none(self):
        with patch("config.get_config_option", return_value=None), \
                patch.object(ToolsManager, "_running_ltk_manager", return_value=None), \
                patch("injection.tools.tools_manager.ltk_manager_install_dirs", return_value=[]):
            self.assertIsNone(ToolsManager(self.root).detect_ltk_manager())


if __name__ == "__main__":
    unittest.main()
