import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from utils.core import startup_diagnostics as diagnostics


class StartupDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="Rose diagnostics ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.script = self.root / "Diagnose-Rose.ps1"
        self.script.touch()
        self.shell = self.root / "powershell.exe"
        self.shell.touch()
        self.stop = threading.Event()
        for name, value in (
            ("get_user_data_dir", self.root / "user data"),
            ("get_app_dir", self.root / "Rose app"),
            ("get_asset_path", self.script),
            ("_powershell_path", self.shell),
        ):
            patcher = patch.object(diagnostics, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def process(self, command, **kwargs):
        self.command = command
        self.options = kwargs
        directory = Path(command[command.index("-ReportDirectory") + 1])
        (directory / "report.txt").write_text("Diagnostic fixture", encoding="utf-8")
        (directory / "report.json").write_text(json.dumps({
            "complete": True, "findings": [{"status": "FAIL"}, {"status": "UNKNOWN"}],
        }), encoding="utf-8-sig")
        process = Mock()
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        process.poll.return_value = 0
        process.returncode = 0
        self.child = process
        return process

    def test_success_uses_explicit_paths_and_keeps_runs_separate(self):
        with patch.object(diagnostics.subprocess, "Popen", side_effect=self.process):
            first = diagnostics.run_startup_diagnostics(self.stop)
            second = diagnostics.run_startup_diagnostics(self.stop)
        self.assertTrue(first.completed)
        self.assertNotEqual(first.directory, second.directory)
        self.assertEqual(first.directory.parent, self.root / "user data" / "logs" / "diagnostics")
        self.assertIn("1 FAIL", first.message)
        self.assertEqual(self.command[self.command.index("-DataPath") + 1], str(self.root / "user data"))
        self.assertEqual(self.command[self.command.index("-RosePath") + 1], str(self.root / "Rose app"))
        self.assertEqual(self.command[0], str(self.shell))
        self.assertEqual(self.options["creationflags"], subprocess.CREATE_NO_WINDOW)
        self.assertEqual(self.options["stderr"], subprocess.DEVNULL)
        self.assertEqual(self.options["env"]["PSModulePath"], str(self.shell.parent / "Modules"))
        self.assertNotIn("shell", self.options)

    def test_missing_script_writes_actionable_status(self):
        self.script.unlink()
        with patch.object(diagnostics.subprocess, "Popen") as launch:
            result = diagnostics.run_startup_diagnostics(self.stop)
        launch.assert_not_called()
        self.assertFalse(result.completed)
        self.assertIn("missing", (result.directory / "collector-status.txt").read_text())

    def test_launch_error_does_not_leak_raw_exception(self):
        with patch.object(diagnostics.subprocess, "Popen", side_effect=OSError(5, "token=secret")):
            result = diagnostics.run_startup_diagnostics(self.stop)
        self.assertFalse(result.completed)
        self.assertNotIn("secret", (result.directory / "collector-status.txt").read_text())

    def test_nonzero_exit_is_not_reported_as_success(self):
        def failed(*args, **kwargs):
            process = self.process(*args, **kwargs)
            process.poll.return_value = 1
            process.returncode = 1
            return process
        with patch.object(diagnostics.subprocess, "Popen", side_effect=failed):
            result = diagnostics.run_startup_diagnostics(self.stop)
        self.assertFalse(result.completed)
        self.assertIn("code 1", result.message)

    def test_incomplete_report_is_not_reported_as_success(self):
        def partial(*args, **kwargs):
            process = self.process(*args, **kwargs)
            directory = Path(self.command[self.command.index("-ReportDirectory") + 1])
            (directory / "report.json").write_text('{"complete": false, "findings": []}')
            return process
        with patch.object(diagnostics.subprocess, "Popen", side_effect=partial):
            result = diagnostics.run_startup_diagnostics(self.stop)
        self.assertFalse(result.completed)

    def test_timeout_kills_only_collector_and_preserves_status(self):
        def hung(*args, **kwargs):
            process = self.process(*args, **kwargs)
            process.poll.return_value = None
            return process
        with (
            patch.object(diagnostics.subprocess, "Popen", side_effect=hung),
            patch.object(diagnostics, "DIAGNOSTICS_TIMEOUT_SECONDS", 0),
        ):
            result = diagnostics.run_startup_diagnostics(self.stop)
        self.child.kill.assert_called_once()
        self.child.wait.assert_called_once()
        self.assertFalse(result.completed)
        self.assertIn("timed out", result.message)

    def test_shutdown_cancels_active_collector(self):
        def stopping(*args, **kwargs):
            process = self.process(*args, **kwargs)
            process.poll.return_value = None
            self.stop.set()
            return process
        with patch.object(diagnostics.subprocess, "Popen", side_effect=stopping):
            result = diagnostics.run_startup_diagnostics(self.stop)
        self.assertTrue(result.cancelled)
        self.child.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
