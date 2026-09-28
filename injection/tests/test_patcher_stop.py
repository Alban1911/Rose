import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from injection.overlay import overlay_manager, process_manager
from injection.overlay.overlay_manager import OverlayManager
from injection.overlay.process_manager import ProcessManager
from injection.tools.patcher import LTK_PATCHER_HOST


class RoseStoppedPatcherTests(unittest.TestCase):
    """Rose's cleanup kills the patcher with exit code 1 (Popen) or 15 (psutil)"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        self.overlay_dir = root / 'overlay'
        self.overlay_dir.mkdir()
        self.process_manager = ProcessManager()
        self.overlay = OverlayManager(root / 'tools', root / 'mods', root / 'game', self.process_manager)

        reporter = patch.object(overlay_manager, 'report_issue')
        self.report_issue = reporter.start()
        self.addCleanup(reporter.stop)
        # Never touch the developer's real patcher or mod-tools processes
        self.running = []
        processes = patch.object(process_manager.psutil, 'process_iter', side_effect=lambda *a, **k: list(self.running))
        processes.start()
        self.addCleanup(processes.stop)

    def _start_patcher(self):
        """Stand-in patcher that runs until it's killed"""
        proc = subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(60)'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
        )
        self.addCleanup(proc.stdin.close)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.process_manager.current_overlay_process = proc
        reader = threading.Thread(target=lambda: None)
        reader.start()
        session = {
            'proc': proc,
            'session': {'state': None, 'error': None, 'eol': False},
            'reader': reader,
            'log': None,
        }
        return proc, session

    def _serve_until(self, session, stop):
        result = {}
        runner = threading.Thread(
            target=lambda: result.update(code=self.overlay._run_ltk_patcher(session, self.overlay_dir))
        )
        runner.start()
        stop()
        runner.join(timeout=15)
        self.assertFalse(runner.is_alive())
        return result['code']

    def test_end_of_game_stop_is_not_a_failure(self):
        proc, session = self._start_patcher()
        code = self._serve_until(session, self.process_manager.stop_overlay_process)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(code, 0)
        self.report_issue.assert_not_called()

    def test_lobby_cleanup_is_not_a_failure(self):
        proc, session = self._start_patcher()
        self.running = [SimpleNamespace(info={'pid': proc.pid, 'name': LTK_PATCHER_HOST})]
        code = self._serve_until(session, self.process_manager.kill_all_runoverlay_processes)
        self.assertEqual(proc.returncode, 15)
        self.assertEqual(code, 0)
        self.report_issue.assert_not_called()

    def test_patcher_dying_by_itself_is_reported(self):
        proc, session = self._start_patcher()
        code = self._serve_until(session, proc.terminate)
        self.assertEqual(code, 1)
        self.report_issue.assert_called_once()
        self.assertIn('exited with code 1', self.report_issue.call_args.args[2])

    def test_patcher_errors_are_still_reported_when_rose_stops_it(self):
        proc, session = self._start_patcher()
        session['session']['error'] = 'the game started before the patcher, overlay not applied'
        code = self._serve_until(session, self.process_manager.stop_overlay_process)
        self.assertEqual(code, 1)
        self.report_issue.assert_called_once()
        self.assertIn('overlay not applied', self.report_issue.call_args.args[2])


if __name__ == '__main__':
    unittest.main()
