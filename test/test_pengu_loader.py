import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import utils.integration.pengu_loader as pengu_loader


class PenguLoaderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        state_dir = Path(self.temp_dir.name)
        self.session_file = state_dir / 'pengu_session.json'
        self.active_flag = state_dir / 'pengu_active.flag'
        self.pengu_dir = state_dir / 'Pengu Loader'
        self.pengu_exe = self.pengu_dir / 'Pengu Loader.exe'
        self.pengu_log = self.pengu_dir / 'pengu.log'
        self.paths = patch.multiple(
            pengu_loader,
            _SESSION_FILE=self.session_file,
            _ACTIVE_FLAG=self.active_flag,
            PENGU_DIR=self.pengu_dir,
            PENGU_EXE=self.pengu_exe,
            _PENGU_LOG=self.pengu_log,
        )
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _result(args, code=0, stdout='', stderr=''):
        return CompletedProcess(args, code, stdout=stdout, stderr=stderr)

    def test_no_managed_commands_are_used(self):
        source = Path(pengu_loader.__file__).read_text(encoding='utf-8')
        loader_source = Path('vendor/PenguLoader-1.1.6/loader/Program.cs').read_text(encoding='utf-8')
        logger_source = Path(
            'vendor/PenguLoader-1.1.6/loader/Main/Logger.cs'
        ).read_text(encoding='utf-8')
        for forbidden in ('--rose-managed', '--rose-stop', '--force-deactivate', 'taskkill'):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, loader_source)
        self.assertIn('if (active && Module.IsLoaded)', loader_source)
        self.assertIn('pengu.log', logger_source)
        for obsolete in ('crash.log', 'CrashLogPath', 'LogFailure('):
            self.assertNotIn(obsolete, loader_source)
            self.assertNotIn(obsolete, logger_source)

    def test_legacy_pengu_logs_are_removed(self):
        for filename in ('rose.log', 'rose.log.old', 'crash.log'):
            path = self.pengu_dir / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('legacy diagnostics', encoding='utf-8')
        self.pengu_log.write_text('current diagnostics', encoding='utf-8')

        pengu_loader._remove_legacy_pengu_logs(self.pengu_dir)

        for filename in ('rose.log', 'rose.log.old', 'crash.log'):
            self.assertFalse((self.pengu_dir / filename).exists())
        self.assertTrue(self.pengu_log.exists())

    def test_legacy_cleanup_and_packaging_exclusions_are_wired(self):
        source = Path(pengu_loader.__file__).read_text(encoding='utf-8')
        spec_source = Path('Rose.spec').read_text(encoding='utf-8')
        program_source = Path(
            'vendor/PenguLoader-1.1.6/loader/Program.cs'
        ).read_text(encoding='utf-8')
        updater_source = Path(
            'vendor/PenguLoader-1.1.6/loader/Main/Updater.cs'
        ).read_text(encoding='utf-8')

        self.assertIn('_remove_legacy_pengu_logs(bundled)', source)
        self.assertIn('_remove_legacy_pengu_logs(runtime_dir)', source)
        self.assertIn('name.endswith(\'.log\')', spec_source)
        self.assertIn('name.endswith(\'.log.old\')', spec_source)
        self.assertIn('Logger.Error("CLI"', program_source)
        self.assertIn('Failed to download or apply the update', updater_source)

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader.subprocess, 'run')
    def test_activate_uses_official_cli(self, run, _available):
        run.side_effect = [
            self._result([], stdout='Pengu has been activated.'),
            self._result([], stdout='Pengu is currently ACTIVE.'),
        ]
        self.assertTrue(pengu_loader.activate())
        self.assertEqual(run.call_args_list[0].args[0][1:], ['--install', '--activate', '--silent'])
        self.assertEqual(run.call_args_list[1].args[0][1:], ['--status', '--silent'])

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader.subprocess, 'run')
    def test_deactivate_uses_official_cli(self, run, _available):
        run.side_effect = [
            self._result([], stdout='Pengu has been deactivated.'),
            self._result([], code=1, stdout='Pengu is currently INACTIVE.'),
        ]
        self.assertTrue(pengu_loader.deactivate())
        self.assertEqual(run.call_args_list[0].args[0][1:], ['--uninstall', '--deactivate', '--silent'])

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, 'get_status', return_value=pengu_loader.PenguStatus.INACTIVE)
    @patch.object(pengu_loader, 'activate', return_value=False)
    def test_activation_failure_does_not_create_session(self, activate, _status, _available):
        self.assertFalse(pengu_loader.activate_on_start())
        self.assertFalse(self.session_file.exists())
        activate.assert_called_once_with()

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, 'get_status', return_value=pengu_loader.PenguStatus.INACTIVE)
    @patch.object(pengu_loader, 'activate', return_value=True)
    @patch.object(pengu_loader, '_is_league_running', return_value=False)
    def test_successful_activation_creates_session(self, _running, activate, _status, _available):
        self.assertTrue(pengu_loader.activate_on_start())
        state = json.loads(self.session_file.read_text(encoding='utf-8'))
        self.assertFalse(state['pengu_was_active_before_rose'])
        self.assertTrue(state['rose_activated_pengu'])
        activate.assert_called_once_with()

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, 'get_status', return_value=pengu_loader.PenguStatus.INACTIVE)
    @patch.object(pengu_loader, 'activate', return_value=True)
    @patch.object(pengu_loader, '_is_league_running', return_value=True)
    @patch.object(pengu_loader, 'restart_client', return_value=True)
    def test_startup_with_running_league_restarts_client(
        self, restart_client, _running, activate, _status, _available
    ):
        self.assertTrue(pengu_loader.activate_on_start())
        activate.assert_called_once_with()
        restart_client.assert_called_once_with()

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, 'get_status', return_value=pengu_loader.PenguStatus.ACTIVE)
    @patch.object(pengu_loader, '_is_league_running', return_value=True)
    @patch.object(pengu_loader, 'deactivate')
    @patch.object(pengu_loader, 'activate')
    def test_stale_active_session_is_adopted_when_league_is_running(
        self, activate, deactivate, _running, _status, _available
    ):
        pengu_loader._write_session(False, True)

        self.assertTrue(pengu_loader.cleanup_if_dirty())
        self.assertTrue(pengu_loader.activate_on_start())

        activate.assert_not_called()
        deactivate.assert_not_called()
        state = json.loads(self.session_file.read_text(encoding='utf-8'))
        self.assertTrue(state['rose_activated_pengu'])
        self.assertFalse(state['pengu_was_active_before_rose'])

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, '_is_league_running', return_value=False)
    @patch.object(pengu_loader, 'deactivate', return_value=True)
    def test_successful_shutdown_removes_session(self, deactivate, _running, _available):
        pengu_loader._write_session(False, True)
        self.assertTrue(pengu_loader.restore_after_rose())
        self.assertFalse(self.session_file.exists())
        deactivate.assert_called_once_with()

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, '_is_league_running', return_value=True)
    @patch.object(pengu_loader, 'restart_client', return_value=True)
    @patch.object(pengu_loader, 'deactivate', return_value=True)
    def test_shutdown_restarts_running_league_client(
        self, deactivate, restart_client, _running, _available
    ):
        pengu_loader._write_session(False, True)
        self.assertTrue(pengu_loader.restore_after_rose())
        deactivate.assert_called_once_with()
        restart_client.assert_called_once_with()
        self.assertFalse(self.session_file.exists())

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, 'deactivate', return_value=False)
    def test_failed_shutdown_keeps_recovery_session(self, deactivate, _available):
        pengu_loader._write_session(False, True)
        self.assertFalse(pengu_loader.restore_after_rose())
        self.assertTrue(self.session_file.exists())
        deactivate.assert_called_once_with()

    @patch.object(pengu_loader, 'deactivate')
    def test_preexisting_active_state_is_preserved(self, deactivate):
        pengu_loader._write_session(True, False)
        self.assertTrue(pengu_loader.restore_after_rose())
        self.assertFalse(self.session_file.exists())
        deactivate.assert_not_called()

    def test_unsigned_windows_exit_code_is_normalized(self):
        self.assertEqual(pengu_loader._signed_exit_code(4294967272), -24)
        self.assertEqual(pengu_loader._signed_exit_code(0), 0)

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader.subprocess, 'run')
    def test_failed_command_logs_stdout_and_stderr(self, run, _available):
        run.return_value = self._result([], code=4294967272, stdout='stdout details', stderr='stderr details')
        with self.assertLogs(pengu_loader.log, level='ERROR') as logs:
            result = pengu_loader._run_cli_result(['--activate'])
        self.assertEqual(result.returncode, 4294967272)
        message = '\n'.join(logs.output)
        self.assertIn('stdout details', message)
        self.assertIn('stderr details', message)
        self.assertIn('signed_exit_code=-24', message)


    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader.subprocess, 'run')
    def test_failed_command_includes_pengu_log_tail(self, run, _available):
        self.pengu_log.parent.mkdir(parents=True, exist_ok=True)
        self.pengu_log.write_text(
            'old entry\nlatest entry\n',
            encoding='utf-8',
        )
        run.return_value = self._result([], code=7, stdout='command stdout')
        with self.assertLogs(pengu_loader.log, level='ERROR') as logs:
            result = pengu_loader._run_cli_result(['--activate'])
        self.assertEqual(result.returncode, 7)
        message = '\n'.join(logs.output)
        self.assertIn('command stdout', message)
        self.assertIn('Pengu Loader log tail', message)
        self.assertIn('latest entry', message)

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader.subprocess, 'run')
    def test_missing_pengu_log_does_not_hide_original_failure(self, run, _available):
        run.return_value = self._result([], code=9, stdout='original failure output')
        with self.assertLogs(pengu_loader.log, level='ERROR') as logs:
            result = pengu_loader._run_cli_result(['--activate'])
        self.assertEqual(result.returncode, 9)
        message = '\n'.join(logs.output)
        self.assertIn('original failure output', message)
        self.assertIn('Pengu log is missing', message)

    def test_unreadable_pengu_log_does_not_raise(self):
        self.pengu_log.parent.mkdir(parents=True, exist_ok=True)
        self.pengu_log.write_text('secret details', encoding='utf-8')
        with patch.object(pengu_loader.Path, 'open', side_effect=OSError('permission denied')):
            result = pengu_loader._read_log_tail(self.pengu_log)
        self.assertIn('could not be read', result)
        self.assertIn('permission denied', result)

    def test_log_tail_is_limited_by_lines(self):
        self.pengu_log.parent.mkdir(parents=True, exist_ok=True)
        self.pengu_log.write_text(
            ''.join(f'entry-{index}\n' for index in range(200)),
            encoding='utf-8',
        )
        result = pengu_loader._read_log_tail(self.pengu_log, max_lines=120)
        lines = result.splitlines()
        self.assertEqual(len(lines), 120)
        self.assertEqual(lines[0], 'entry-80')
        self.assertEqual(lines[-1], 'entry-199')

    def test_log_tail_is_limited_by_character_count(self):
        self.pengu_log.parent.mkdir(parents=True, exist_ok=True)
        self.pengu_log.write_text('0123456789\n' * 100, encoding='utf-8')
        result = pengu_loader._read_log_tail(self.pengu_log, max_chars=37)
        self.assertLessEqual(len(result), 37)
        self.assertTrue(result.endswith('0123456789'))

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader.subprocess, 'run')
    def test_successful_command_does_not_dump_pengu_log(self, run, _available):
        self.pengu_log.parent.mkdir(parents=True, exist_ok=True)
        self.pengu_log.write_text('should not be included', encoding='utf-8')
        run.return_value = self._result([], code=0, stdout='successful command output')
        with self.assertLogs(pengu_loader.log, level='DEBUG') as logs:
            result = pengu_loader._run_cli_result(['--status'])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('should not be included', '\n'.join(logs.output))


if __name__ == '__main__':
    unittest.main()
