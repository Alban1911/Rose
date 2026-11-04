import ctypes
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main as rose_main
from injection.tools.tools_manager import ToolsManager


@unittest.skipUnless(sys.platform == "win32", "the startup dialog is a Windows dialog")
class LtkManagerDialogTests(unittest.TestCase):
    """Without LTK Manager, the startup dialog lets the user point Rose at it
    instead of opening the tools folder, which no longer helps"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.tools = self.root / "tools"
        self.manager = self.root / "LTK Manager" / "ltk-manager.exe"
        self.manager.parent.mkdir()
        self.manager.write_bytes(b"exe")
        for patcher in (
            # Never this PC's own config.ini
            patch("config.set_config_option"),
            patch.object(ctypes.windll.user32, "MessageBoxW", return_value=1),
            patch("subprocess.run"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        import config
        import subprocess
        self.set_config_option = config.set_config_option
        self.message_box = ctypes.windll.user32.MessageBoxW
        self.explorer = subprocess.run

    def show(self, choices, picked=None, reason="no_manager", found=None):
        with (
            patch.object(rose_main, "_show_native_dll_dialog", side_effect=choices) as dialog,
            patch.object(rose_main, "_pick_ltk_manager", return_value=picked),
            patch.object(ToolsManager, "detect_ltk_manager", return_value=found),
        ):
            result = rose_main._show_dll_dialog(self.tools, reason=reason)
        return result, dialog.call_count

    def test_the_text_explains_the_setup_and_offers_to_set_the_path(self):
        _, status_title, body, steps, action = rose_main._dll_dialog_text("no_manager")

        self.assertEqual(action, "Set up path")
        self.assertIn("never have to open it yourself", body)
        self.assertIn(rose_main.LTK_MANAGER_DOWNLOAD_URL, steps)
        self.assertNotIn("config.ini", steps)

    def test_web_addresses_become_links_without_the_closing_parenthesis(self):
        linked = rose_main._with_links("Install it (https://example.com/releases), then restart.")

        self.assertIn('<a href="https://example.com/releases">https://example.com/releases</a>)', linked)

    def test_a_picked_ltk_manager_is_saved_and_rose_starts(self):
        result, shown = self.show(["fix"], picked=self.manager, found=self.manager)

        self.assertTrue(result)
        self.assertEqual(shown, 1)
        self.set_config_option.assert_called_once_with("General", "ltkManagerPath", str(self.manager))

    def test_a_cancelled_picker_shows_the_dialog_again(self):
        result, shown = self.show(["fix", "close"], picked=None)

        self.assertFalse(result)
        self.assertEqual(shown, 2)
        self.set_config_option.assert_not_called()

    def test_another_program_is_refused(self):
        other = self.manager.parent / "Uninstall LTK Manager.exe"
        other.write_bytes(b"exe")

        result, shown = self.show(["fix", "close"], picked=other)

        self.assertFalse(result)
        self.assertEqual(shown, 2)
        self.set_config_option.assert_not_called()
        self.assertIn("is not LTK Manager", self.message_box.call_args[0][1])

    def test_a_path_rose_cannot_save_is_reported(self):
        result, shown = self.show(["fix", "close"], picked=self.manager, found=None)

        self.assertFalse(result)
        self.assertEqual(shown, 2)
        self.assertIn("could not save the path", self.message_box.call_args[0][1])

    def test_closing_the_dialog_closes_rose(self):
        result, shown = self.show(["close"])

        self.assertFalse(result)
        self.set_config_option.assert_not_called()

    def test_missing_bridge_files_still_open_the_tools_folder(self):
        result, _ = self.show(["fix"], reason="missing")

        self.assertFalse(result)
        self.assertEqual(self.explorer.call_args[0][0], ["explorer", str(self.tools)])


if __name__ == "__main__":
    unittest.main()
