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
        self.paths = patch.multiple(
            pengu_loader,
            _SESSION_FILE=self.session_file,
            _ACTIVE_FLAG=self.active_flag,
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
        for forbidden in ('--rose-managed', '--rose-stop', '--force-deactivate', 'taskkill'):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, loader_source)
        self.assertIn('if (active && Module.IsLoaded)', loader_source)

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


if __name__ == '__main__':
    unittest.main()
