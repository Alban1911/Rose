import hashlib
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from injection.overlay import overlay_manager
from injection.overlay.overlay_manager import LATE_JOIN_ERROR, OverlayManager, ltk_failure_cause
from injection.overlay.process_manager import ProcessManager
from injection.tools import patcher
from injection.tools.patcher import (
    LTK_PATCHER_DLL,
    LTK_PATCHER_HOST,
    check_ltk_patcher,
    describe_ltk_patcher_files,
)


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

        self.assertIn(f"{LTK_PATCHER_DLL}: missing", description)


class MisnamedPatcherFilesTests(unittest.TestCase):
    """A browser download appends "(1)" and the patcher is then never found"""

    # What read_dll_eol() looks for; present in every release of the patcher DLL
    EOL_SIGNATURE = b"end of life reached, please update: "

    def test_a_dll_with_the_patcher_signature_is_renamed_back(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp)
            (tools / "ltk_patcher_dll(1).dll").write_bytes(b'MZ' + self.EOL_SIGNATURE)
            (tools / LTK_PATCHER_HOST).write_bytes(b'host')

            status = check_ltk_patcher(tools)

            self.assertEqual([], status.missing)
            self.assertTrue((tools / LTK_PATCHER_DLL).is_file())
            self.assertFalse((tools / "ltk_patcher_dll(1).dll").exists())
            self.assertEqual(tools / LTK_PATCHER_DLL, status.dll)

    def test_a_dll_matching_a_pinned_hash_is_renamed_back(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp)
            digest = hashlib.sha256(b'release').hexdigest()
            with patch.object(patcher, 'KNOWN_DLL_SHA256', frozenset({digest})):
                (tools / "ltk_patcher_dll (1).dll").write_bytes(b'release')
                (tools / LTK_PATCHER_HOST).write_bytes(b'host')

                status = check_ltk_patcher(tools)

            self.assertEqual([], status.missing)
            self.assertTrue((tools / LTK_PATCHER_DLL).is_file())

    def test_a_host_matching_a_pinned_hash_is_renamed_back(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp)
            digest = hashlib.sha256(b'host').hexdigest()
            with patch.object(patcher, 'KNOWN_HOST_SHA256', frozenset({digest})):
                (tools / "ltk_patcher_host(1).exe").write_bytes(b'host')
                (tools / LTK_PATCHER_DLL).write_bytes(b'dll')

                status = check_ltk_patcher(tools)

            self.assertEqual([], status.missing)
            self.assertTrue((tools / LTK_PATCHER_HOST).is_file())
            self.assertEqual(tools / LTK_PATCHER_HOST, status.host)

    def test_a_host_from_another_build_is_found_without_the_pinned_hash(self):
        """The pinned hash covers one release; LeagueToolkit ships new ones
        often, and a renamed host must still be recognised"""
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp)
            host = (b'MZ' + b'ltk_patcher_dll.dll' + b'\x00' + b'\\\\.\\pipe\\ltk-patcher-pipe')
            with patch.object(patcher, 'KNOWN_HOST_SHA256', frozenset()):
                (tools / "ltk_patcher_host (1).exe").write_bytes(host)
                (tools / LTK_PATCHER_DLL).write_bytes(b'dll')

                status = check_ltk_patcher(tools)

            self.assertEqual([], status.missing)
            self.assertTrue((tools / LTK_PATCHER_HOST).is_file())

    def test_an_exe_with_only_one_signature_is_not_a_patcher(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp)
            (tools / "random.exe").write_bytes(b'MZ ltk_patcher_dll.dll')
            (tools / LTK_PATCHER_DLL).write_bytes(b'dll')

            status = check_ltk_patcher(tools)

            self.assertIn(LTK_PATCHER_HOST, status.missing)
            self.assertTrue((tools / "random.exe").is_file())

    def test_a_file_matching_nothing_is_left_alone(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp)
            (tools / "cslol-dll.dll").write_bytes(b'stub')
            (tools / "mod-tools.exe").write_bytes(b'tools')
            (tools / LTK_PATCHER_HOST).write_bytes(b'host')

            status = check_ltk_patcher(tools)

            self.assertEqual([LTK_PATCHER_DLL], status.missing)
            self.assertTrue((tools / "cslol-dll.dll").is_file())
            self.assertTrue((tools / "mod-tools.exe").is_file())

    def test_the_canonical_name_is_never_moved(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp)
            (tools / LTK_PATCHER_DLL).write_bytes(b'dll')
            (tools / LTK_PATCHER_HOST).write_bytes(b'host')

            check_ltk_patcher(tools)

            # resolve_*() short-circuits on the exact name, so a same-content
            # copy elsewhere is left where it is
            self.assertEqual(b'dll', (tools / LTK_PATCHER_DLL).read_bytes())


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

    def test_unknown_failures_do_not_blame_the_files(self):
        self.assertNotIn('update', self.hint('exited with code 3 (0x00000003)'))

    def test_a_patcher_killed_by_another_program_points_at_the_antivirus(self):
        # 0x40010004, seen on a PC whose antivirus closed the patcher
        hint = self.hint('exited with code 1073807364 (0x40010004)')
        self.assertIn('antivirus', hint)
        self.assertNotIn('update', hint)

    def test_a_crashed_patcher_suggests_updating_it(self):
        self.assertIn('update your LTK patcher files', self.hint('exited with code 3221225477 (0xC0000005)'))


class FailureCauseTests(unittest.TestCase):
    """Troubleshooting picks its hint by cause"""

    def test_each_reason_has_its_cause(self):
        for reason, cause in [
            ('SetWindowsHookEx failed: 0x00000000', 'hook'),
            (LATE_JOIN_ERROR, 'late'),
            ('overlay verification failed, disabling overlay', 'rejected'),
            ('could not start ([WinError 2] file not found)', 'start'),
            ('exited with code 1073807364 (0x40010004)', 'killed'),
            ('exited with code 3221225477 (0xC0000005)', 'crashed'),
            ('exited with code -1073741819', 'crashed'),
            ('exited with code 3 (0x00000003)', 'unknown'),
            ('something new', 'unknown'),
        ]:
            self.assertEqual(ltk_failure_cause(reason), cause, reason)


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

    def test_context_logging_never_changes_the_reported_failure(self):
        """The patcher's own exit code must survive a context probe that fails"""
        patcher = SimpleNamespace(returncode=3, poll=lambda: 3, stdin=None)
        session = {
            'proc': patcher,
            'session': {'state': None, 'error': None, 'eol': False},
            'reader': threading.Thread(target=lambda: None),
            'log': None,
        }
        session['reader'].start()
        with patch.object(OverlayManager, '_running_game', return_value=SimpleNamespace()),                 patch.object(OverlayManager, '_stop_ltk_patcher'),                 self.assertLogs(level='ERROR'):
            code = self.overlay._run_ltk_patcher(session, self.overlay_dir)

        self.assertEqual(code, 3)
        self.assertIn('exited with code 3', self.report_issue.call_args[0][2])


if __name__ == '__main__':
    unittest.main()
