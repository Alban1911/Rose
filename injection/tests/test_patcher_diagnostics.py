import hashlib
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from injection.overlay import overlay_manager
from injection.overlay.overlay_manager import LATE_JOIN_ERROR, OverlayManager
from injection.overlay.process_manager import ProcessManager
from injection.tools.patcher import LTK_PATCHER_DLL, LTK_PATCHER_HOST, describe_ltk_patcher_files


class PatcherFilesTests(unittest.TestCase):
    """Users bring patcher files from different LTK Manager releases: a report
    has to say which copy was used"""

    def test_each_file_is_identified_by_its_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp)
            (tools / LTK_PATCHER_HOST).write_bytes(b'host')
            (tools / LTK_PATCHER_DLL).write_bytes(b'dll')
            description = describe_ltk_patcher_files(tools)

        self.assertIn(f"{LTK_PATCHER_HOST}: 4 bytes", description)
        self.assertIn(hashlib.sha256(b'dll').hexdigest(), description)

    def test_a_missing_file_is_named_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as temp:
            description = describe_ltk_patcher_files(Path(temp))

        self.assertIn(f"{LTK_PATCHER_DLL}: unreadable", description)


class FailureHintTests(unittest.TestCase):
    """Every patcher failure used to get the same "update your files" hint (#294)"""

    def hint(self, reason):
        return OverlayManager._ltk_failure_hint(reason)

    def test_hook_failure_does_not_blame_the_files(self):
        self.assertNotIn('up to date', self.hint('SetWindowsHookEx failed: 0x00000000'))

    def test_late_join_says_the_game_started_first(self):
        self.assertIn('started before the patcher', self.hint(LATE_JOIN_ERROR))

    def test_disabled_overlay_points_at_the_skin_or_mods(self):
        self.assertIn('custom mods', self.hint('overlay verification failed, disabling overlay'))

    def test_unknown_failures_keep_the_update_hint(self):
        self.assertIn('up to date', self.hint('exited with code 3'))


class FailureContextTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        self.overlay_dir = root / 'overlay'
        self.overlay_dir.mkdir()
        self.overlay = OverlayManager(root / 'tools', root / 'mods', root / 'game', ProcessManager())
        reporter = patch.object(overlay_manager, 'report_issue')
        self.report_issue = reporter.start()
        self.addCleanup(reporter.stop)
        running_game = patch.object(OverlayManager, '_running_game', return_value=None)
        running_game.start()
        self.addCleanup(running_game.stop)

    def test_a_failed_session_logs_its_context_and_a_specific_hint(self):
        proc = subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(60)'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
        )
        self.addCleanup(proc.stdin.close)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        reader = threading.Thread(target=lambda: None)
        reader.start()
        session = {
            'proc': proc,
            'session': {'state': 'failed', 'error': 'SetWindowsHookEx failed: 0x00000000', 'eol': False},
            'reader': reader,
            'log': None,
        }

        with self.assertLogs(level='ERROR') as logs:
            code = self.overlay._run_ltk_patcher(session, self.overlay_dir)

        self.assertEqual(code, 1)
        self.assertTrue(any('LTK patcher context: last state=failed' in line for line in logs.output))
        self.assertNotIn('up to date', self.report_issue.call_args.kwargs['hint'])


if __name__ == '__main__':
    unittest.main()
