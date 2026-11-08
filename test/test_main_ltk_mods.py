
import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import main as rose_main
from config import REMOVE_LTK_MODS_TIMEOUT_S
from main.setup.arguments import setup_arguments


def parse(*argv):
    with patch.object(sys, "argv", ["Rose.exe", *argv]):
        return setup_arguments()


class ArgumentTests(unittest.TestCase):
    def test_the_flag_is_read_and_off_by_default(self):
        self.assertTrue(parse("--remove-ltk-mods").remove_ltk_mods)
        self.assertFalse(parse().remove_ltk_mods)

    def test_the_flag_is_not_in_the_help(self):
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown), self.assertRaises(SystemExit):
            parse("--help")

        self.assertIn("--dev", shown.getvalue())
        self.assertNotIn("--remove-ltk-mods", shown.getvalue())


class StartTests(unittest.TestCase):
    def test_rose_syncs_the_saved_mods_alone_and_after_converting_the_stored_folders(self):
        """The unpacked .modpkgs a closed Rose left go once no other Rose
        runs, before the sync can unpack one again"""
        class Started(Exception):
            """Stops the start once its mods steps are done"""

        steps = MagicMock()
        steps.core.side_effect = Started
        with patch.object(rose_main, "check_single_instance", steps.alone), \
                patch.object(rose_main, "_update_registry_version"), \
                patch.object(rose_main.pengu_loader, "cleanup_if_dirty"), \
                patch.object(rose_main, "setup_logging_and_cleanup"), \
                patch.object(rose_main, "initialize_tray_manager", return_value=None), \
                patch.object(rose_main, "AppStatus"), \
                patch.object(rose_main, "remove_unpacked_leftovers", steps.sweep), \
                patch.object(rose_main, "convert_stored_mods", steps.convert), \
                patch.object(rose_main, "start_saved_mods_sync", steps.sync), \
                patch.object(rose_main, "initialize_core_components", steps.core):
            with self.assertRaises(Started):
                rose_main.run_league_unlock(args=SimpleNamespace())

        self.assertEqual([call[0] for call in steps.mock_calls], ["alone", "sweep", "convert", "sync", "core"])
        steps.sync.assert_called_once_with(only_if_changed=False)


class RemoveLtkModsTests(unittest.TestCase):
    def test_the_flag_removes_the_mods_and_exits_before_anything_else(self):
        launcher = SimpleNamespace(run_launcher=MagicMock())
        with patch.object(sys, "argv", ["Rose.exe", "--remove-ltk-mods"]), \
                patch.dict(sys.modules, {"launcher": launcher}), \
                patch.object(rose_main, "_remove_ltk_mods", return_value=1) as remove, \
                patch.object(rose_main, "_check_dll_present") as dll_check, \
                patch.object(rose_main, "run_league_unlock") as start:
            with self.assertRaises(SystemExit) as exited:
                rose_main.main()

        self.assertEqual(exited.exception.code, 1)
        remove.assert_called_once_with()
        launcher.run_launcher.assert_not_called()
        dll_check.assert_not_called()
        start.assert_not_called()

    def removing(self, **remove):
        """_remove_ltk_mods with Rose's paths and logging patched out"""
        self.tools, self.injection = Path("C:/Rose/tools"), Path("C:/Rose data/injection")
        with patch("utils.core.logging.setup_logging") as self.logging, \
                patch("threading.Timer") as self.watchdog, \
                patch("utils.core.paths.get_tools_dir", return_value=self.tools), \
                patch("utils.core.paths.get_injection_dir", return_value=self.injection), \
                patch("injection.overlay.ltk_library.remove_rose_mods", **remove) as self.remove:
            return rose_main._remove_ltk_mods()

    def test_the_mods_are_removed_through_roses_own_tools_with_a_watchdog(self):
        self.assertEqual(self.removing(return_value=0), 0)

        host = self.remove.call_args.args[0]
        self.assertEqual((host.tools_dir, host.injection_dir), (self.tools, self.injection))
        self.logging.assert_called_once_with("customer")
        self.watchdog.assert_called_once_with(REMOVE_LTK_MODS_TIMEOUT_S, os._exit, args=(1,))
        self.assertTrue(self.watchdog.return_value.daemon)
        self.watchdog.return_value.start.assert_called_once_with()

    def test_a_failure_exits_with_an_error_and_no_dialog(self):
        self.assertEqual(self.removing(side_effect=RuntimeError("the mods folder is gone")), 1)


if __name__ == "__main__":
    unittest.main()
