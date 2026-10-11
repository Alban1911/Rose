import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from utils.core.startup_diagnostics import DiagnosticsResult
from utils.integration import tray_manager


class TrayDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tray = tray_manager.TrayManager()
        self.tray.icon = Mock()
        self.result = DiagnosticsResult(Path("diagnostic reports"), True, "Collection complete")
        logger = patch.object(tray_manager, "log")
        logger.start()
        self.addCleanup(logger.stop)

    def test_collector_runs_off_tray_thread_and_duplicate_clicks_are_ignored(self):
        entered = threading.Event()
        release = threading.Event()
        thread_ids = []

        def collect(stop_event):
            thread_ids.append(threading.get_ident())
            entered.set()
            release.wait(5)
            return self.result

        with (
            patch.object(tray_manager, "run_startup_diagnostics", side_effect=collect) as run,
            patch.object(tray_manager, "open_folder_in_explorer") as open_folder,
        ):
            try:
                self.tray._on_diagnose_startup(None, None)
                self.assertTrue(entered.wait(2))
                menu = self.tray._create_menu()
                item = next(item for item in menu.items if item.text == "Diagnosing Rose startup...")
                self.assertFalse(item.enabled)
                self.tray._on_diagnose_startup(None, None)
                self.assertEqual(run.call_count, 1)
                self.assertNotEqual(thread_ids, [threading.get_ident()])
            finally:
                release.set()
                self.tray._diagnostics_thread.join(5)
            open_folder.assert_called_once_with(self.result.directory)
        self.assertFalse(self.tray._diagnostics_lock.locked())
        self.assertEqual(item.text, "Diagnose Rose startup")
        self.assertTrue(item.enabled)

    def test_worker_failure_releases_lock_and_notifies(self):
        self.tray._diagnostics_lock.acquire()
        with patch.object(tray_manager, "run_startup_diagnostics", side_effect=OSError("cannot write")):
            self.tray._collect_startup_diagnostics()
        self.assertFalse(self.tray._diagnostics_lock.locked())
        self.assertIn("Could not save", self.tray.icon.notify.call_args.args[0])

    def test_thread_launch_failure_allows_retry(self):
        with patch.object(tray_manager.threading, "Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("cannot start thread")
            self.tray._on_diagnose_startup(None, None)
        self.assertFalse(self.tray._diagnostics_lock.locked())

    def test_shutdown_does_not_open_report_or_launch_another_collector(self):
        self.tray._stop_event.set()
        with (
            patch.object(tray_manager, "run_startup_diagnostics", return_value=self.result) as run,
            patch.object(tray_manager, "open_folder_in_explorer") as open_folder,
        ):
            self.tray._on_diagnose_startup(None, None)
            run.assert_not_called()
            self.tray._diagnostics_lock.acquire()
            self.tray._collect_startup_diagnostics()
            open_folder.assert_not_called()
        self.tray.icon.notify.assert_not_called()

    def test_explorer_failure_does_not_discard_success(self):
        self.tray._diagnostics_lock.acquire()
        with (
            patch.object(tray_manager, "run_startup_diagnostics", return_value=self.result),
            patch.object(tray_manager, "open_folder_in_explorer", side_effect=OSError("no explorer")),
        ):
            self.tray._collect_startup_diagnostics()
        self.assertIn("Reports saved", self.tray.icon.notify.call_args.args[0])
        self.assertFalse(self.tray._diagnostics_lock.locked())


if __name__ == "__main__":
    unittest.main()
