import configparser
import ctypes
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import config
import utils.integration.pengu_loader as pengu_loader


def _ansi_can_encode(text):
    try:
        text.encode('mbcs')
        return True
    except (LookupError, UnicodeEncodeError):
        return False


class PenguLoaderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        state_dir = Path(self.temp_dir.name)
        self.session_file = state_dir / 'pengu_session.json'
        self.active_flag = state_dir / 'pengu_active.flag'
        self.pengu_dir = state_dir / 'Pengu Loader'
        self.pengu_exe = self.pengu_dir / 'Pengu Loader.exe'
        self.pengu_log = self.pengu_dir / 'pengu.log'
        # Never write the developer's real config.ini
        self.config_file = state_dir / 'config.ini'
        self.paths = patch.multiple(
            pengu_loader,
            _SESSION_FILE=self.session_file,
            _ACTIVE_FLAG=self.active_flag,
            PENGU_DIR=self.pengu_dir,
            PENGU_EXE=self.pengu_exe,
            _PENGU_LOG=self.pengu_log,
            _CONFIG_FILE=self.config_file,
        )
        self.paths.start()
        external = patch.object(pengu_loader, '_external_pengu_with_rose_plugins', return_value=None)
        external.start()
        self.addCleanup(external.stop)
        processes = patch.object(pengu_loader, '_process_running', return_value=False)
        processes.start()
        self.addCleanup(processes.stop)
        # Never read the developer's real registered hook, or restart their client
        registered = patch.object(pengu_loader, '_registered_pengu_core', return_value=None)
        registered.start()
        self.addCleanup(registered.stop)
        restart = patch.object(pengu_loader, 'restart_client', return_value=False)
        restart.start()
        self.addCleanup(restart.stop)
        pengu_loader._restart_pending = frozenset()
        self.addCleanup(self.paths.stop)
        # Never close the developer's real Pengu Loader windows
        self.close_menu = patch.object(pengu_loader, '_close_loader_menu')
        self.close_menu.start()
        self.addCleanup(self.close_menu.stop)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _result(args, code=0, stdout='', stderr=''):
        return CompletedProcess(args, code, stdout=stdout, stderr=stderr)

    def test_official_loader_boundary_is_preserved(self):
        integration_source = Path(pengu_loader.__file__).read_text(encoding='utf-8')
        program_source = Path('vendor/PenguLoader-1.1.6/loader/Program.cs').read_text(encoding='utf-8')
        ifeo_source = Path('vendor/PenguLoader-1.1.6/loader/Main/IFEO.cs').read_text(encoding='utf-8')

        for forbidden in ('--rose-managed', '--rose-stop', '--force-deactivate', 'taskkill'):
            self.assertNotIn(forbidden, integration_source)
            self.assertNotIn(forbidden, program_source)

        self.assertIn('if (!createdNew || (active && Module.IsLoaded))', program_source)
        # Registry API like current upstream: v1.1.6's "cmd /C reg add" broke on & and ^ in paths
        self.assertNotIn('cmd.exe', ifeo_source)
        self.assertIn('RegistryView.Registry64', ifeo_source)
        self.assertFalse(Path('vendor/PenguLoader-1.1.6/loader/Main/Elevation.cs').exists())
        self.assertFalse(Path('vendor/PenguLoader-1.1.6/loader/Main/Win32Registry.cs').exists())

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
        self.assertIn('public static async void CheckUpdate()', updater_source)
        self.assertIn('ApplyUpdate(updateDir)', updater_source)

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader.subprocess, 'run')
    def test_activate_uses_official_cli(self, run, _available):
        run.side_effect = [
            self._result([], stdout='Pengu has been activated.'),
            self._result([], stdout='Pengu is currently ACTIVE.'),
        ]
        self.assertTrue(pengu_loader.activate())
        self.assertEqual(run.call_args_list[0].args[0][1:], ['--install', '--silent'])
        self.assertEqual(run.call_args_list[1].args[0][1:], ['--status', '--silent'])

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader.subprocess, 'run')
    def test_deactivate_uses_official_cli(self, run, _available):
        run.side_effect = [
            self._result([], stdout='Pengu has been deactivated.'),
            self._result([], code=1, stdout='Pengu is currently INACTIVE.'),
        ]
        self.assertTrue(pengu_loader.deactivate())
        self.assertEqual(run.call_args_list[0].args[0][1:], ['--uninstall', '--silent'])

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
    @patch.object(pengu_loader, '_process_running', return_value=True)
    @patch.object(pengu_loader, 'restart_client', return_value=True)
    def test_startup_with_running_league_restarts_client(
        self, restart_client, _running, activate, _status, _available
    ):
        self.assertTrue(pengu_loader.activate_on_start())
        activate.assert_called_once_with()
        restart_client.assert_called_once_with()
        self.assertFalse(pengu_loader._restart_pending)

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, 'get_status', return_value=pengu_loader.PenguStatus.INACTIVE)
    @patch.object(pengu_loader, 'activate', return_value=True)
    @patch.object(pengu_loader, '_process_running', return_value=True)
    @patch.object(pengu_loader, '_process_ids', return_value=frozenset({1234}))
    @patch.object(pengu_loader, 'restart_client', return_value=False)
    def test_refused_restart_waits_for_the_running_client(
        self, _restart_client, _pids, _running, _activate, _status, _available
    ):
        # The client isn't ready yet: restart that client once it is
        self.assertTrue(pengu_loader.activate_on_start())
        self.assertEqual(pengu_loader._restart_pending, frozenset({1234}))

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
    @patch.object(pengu_loader, 'get_status', return_value=pengu_loader.PenguStatus.ACTIVE)
    @patch.object(pengu_loader, '_is_league_running', return_value=True)
    @patch.object(pengu_loader, 'restart_client', return_value=True)
    @patch.object(pengu_loader, 'deactivate', return_value=True)
    @patch.object(pengu_loader, 'activate')
    def test_rose_loader_left_active_is_unloaded_on_exit(
        self, activate, deactivate, restart_client, _running, _status, _available
    ):
        # --status reports only this loader's own core.dll: an earlier Rose left it
        # on without a session, so this Rose owns it and unloads it when it quits
        self.assertTrue(pengu_loader.activate_on_start())
        activate.assert_not_called()
        state = json.loads(self.session_file.read_text(encoding='utf-8'))
        self.assertTrue(state['rose_activated_pengu'])
        self.assertFalse(state['pengu_was_active_before_rose'])

        self.assertTrue(pengu_loader.restore_after_rose())
        deactivate.assert_called_once_with()
        restart_client.assert_called_once_with()

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

    def test_loader_writes_roses_config_ini(self):
        self.assertEqual(os.environ['ROSE_CONFIG_PATH'], str(config.get_config_file_path()))

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, 'get_status', return_value=pengu_loader.PenguStatus.ACTIVE)
    @patch.object(pengu_loader, '_is_league_running', return_value=False)
    @patch.object(pengu_loader, 'activate')
    def test_active_hook_is_switched_on_in_config_ini(self, activate, _running, _status, _available):
        # Left off, e.g. by the loader writing another account's config.ini
        self.config_file.write_text(
            '[General]\ninjection_threshold = 0.5\ndisabled=1\nloaderpath=\n', encoding='mbcs'
        )
        self.assertTrue(pengu_loader.activate_on_start())
        activate.assert_not_called()
        self.assertEqual(ConfigIniTests.core_dll_reads(self.config_file, 'disabled'), '0')
        self.assertEqual(ConfigIniTests.core_dll_reads(self.config_file, 'loaderpath'), str(self.pengu_dir))
        self.assertEqual(ConfigIniTests.core_dll_reads(self.config_file, 'injection_threshold'), '0.5')

    def test_hook_switch_already_on_is_left_alone(self):
        self.config_file.write_text(
            f'[General]\ndisabled=0\nloaderpath={self.pengu_dir}\n', encoding='mbcs'
        )
        with patch.object(pengu_loader, 'write_config_file') as write:
            pengu_loader._ensure_loader_config()
        write.assert_not_called()

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, 'get_status', return_value=pengu_loader.PenguStatus.ACTIVE)
    @patch.object(pengu_loader, '_process_running', return_value=True)
    @patch.object(pengu_loader, 'restart_client', return_value=True)
    @patch.object(pengu_loader, 'activate')
    def test_loader_left_active_still_restarts_the_running_client(
        self, activate, restart_client, _running, _status, _available
    ):
        # The client may have started while the hook was off, or still run the
        # plugins of a closed Rose: it loads Rose's only when it starts
        self.assertTrue(pengu_loader.activate_on_start())
        activate.assert_not_called()
        restart_client.assert_called_once_with()

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader.subprocess, 'run')
    def test_deactivate_removes_our_own_hook(self, run, _available):
        run.side_effect = [
            self._result([], stdout='Pengu has been deactivated.'),
            self._result([], code=1, stdout='Pengu is currently INACTIVE.'),
        ]
        with patch.object(pengu_loader, '_registered_pengu_core', return_value=self.pengu_dir / 'core.dll'):
            self.assertTrue(pengu_loader.deactivate())
        self.assertEqual(run.call_args_list[0].args[0][1:], ['--uninstall', '--silent'])

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader.subprocess, 'run')
    def test_deactivate_leaves_another_loaders_hook_on(self, run, _available):
        # --uninstall would still switch off the config.ini that loader's core.dll reads
        other_core = Path(self.temp_dir.name) / 'Other Rose' / 'core.dll'
        with patch.object(pengu_loader, '_registered_pengu_core', return_value=other_core):
            self.assertTrue(pengu_loader.deactivate())
        run.assert_not_called()

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, '_is_league_running', return_value=True)
    @patch.object(pengu_loader, 'restart_client')
    @patch.object(pengu_loader.subprocess, 'run')
    def test_shutdown_leaves_another_loaders_hook_on(self, run, restart_client, _running, _available):
        pengu_loader._write_session(False, True)
        other_core = Path(self.temp_dir.name) / 'Other Rose' / 'core.dll'
        with patch.object(pengu_loader, '_registered_pengu_core', return_value=other_core):
            self.assertTrue(pengu_loader.restore_after_rose())
        run.assert_not_called()
        restart_client.assert_not_called()
        self.assertFalse(self.session_file.exists())

    def test_the_bundled_copy_is_not_another_loader(self):
        bundled = Path(self.temp_dir.name) / 'Program Files' / 'Rose' / '_internal' / 'Pengu Loader'
        with patch.object(pengu_loader, '_get_bundled_pengu_dir', return_value=bundled), \
                patch.object(pengu_loader, '_registered_pengu_core', return_value=bundled / 'core.dll'):
            self.assertIsNone(pengu_loader._hook_of_another_loader())

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, '_is_league_running', return_value=False)
    @patch.object(pengu_loader, '_remove_hook', return_value=True)
    @patch.object(pengu_loader.subprocess, 'run')
    def test_shutdown_removes_a_hook_left_on_the_bundled_copy(self, run, remove_hook, _running, _available):
        # The loader's --uninstall leaves a hook on another core.dll and --status
        # calls it inactive: the hook stayed while Rose thought it was gone
        run.side_effect = [
            self._result([], stdout='Pengu has been deactivated.'),
            self._result([], code=1, stdout='Pengu is currently INACTIVE.'),
        ]
        bundled = Path(self.temp_dir.name) / 'Program Files' / 'Rose' / '_internal' / 'Pengu Loader'
        pengu_loader._write_session(False, True)
        with patch.object(pengu_loader, '_get_bundled_pengu_dir', return_value=bundled), \
                patch.object(pengu_loader, '_registered_pengu_core', return_value=bundled / 'core.dll'):
            self.assertTrue(pengu_loader.restore_after_rose())
        self.assertEqual(run.call_args_list[0].args[0][1:], ['--uninstall', '--silent'])
        remove_hook.assert_called_once_with(bundled / 'core.dll')
        self.assertFalse(self.session_file.exists())

    @patch.object(pengu_loader, '_is_available', return_value=True)
    @patch.object(pengu_loader, '_remove_hook')
    @patch.object(pengu_loader.subprocess, 'run')
    def test_deactivate_leaves_the_registry_alone_once_our_hook_is_gone(self, run, remove_hook, _available):
        run.side_effect = [
            self._result([], stdout='Pengu has been deactivated.'),
            self._result([], code=1, stdout='Pengu is currently INACTIVE.'),
        ]
        self.assertTrue(pengu_loader.deactivate())
        remove_hook.assert_not_called()


@unittest.skipUnless(sys.platform == 'win32', 'a loaded DLL is locked on Windows')
class RuntimeLoaderSyncTests(unittest.TestCase):
    """Rose copies its loader to a writable folder at start. With the client
    open, core.dll is loaded there and can't be replaced: Rose ran the bundled
    copy instead, took its own runtime loader for another one, and left its
    hook on at exit, every time the client was open when Rose started"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        self.bundled = root / 'bundled' / 'Pengu Loader'
        self.runtime = root / 'user' / 'Pengu Loader'
        real_dll = Path(sys.base_prefix) / 'DLLs' / '_ctypes.pyd'
        for folder in (self.bundled, self.runtime):
            folder.mkdir(parents=True)
            (folder / 'Pengu Loader.exe').write_bytes(b'loader')
            (folder / 'core.dll').write_bytes(real_dll.read_bytes())
        (self.bundled / 'plugins' / 'ROSE-UI').mkdir(parents=True)
        (self.bundled / 'plugins' / 'ROSE-UI' / 'index.js').write_text('new plugin', encoding='utf-8')

    def test_a_core_dll_in_use_keeps_the_runtime_loader(self):
        loaded = ctypes.WinDLL(str(self.runtime / 'core.dll'))  # the client runs it
        kernel32 = ctypes.WinDLL('kernel32')
        kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
        self.addCleanup(kernel32.FreeLibrary, loaded._handle)

        with patch.object(pengu_loader.sys, 'frozen', True, create=True), \
                patch.object(pengu_loader, '_get_bundled_pengu_dir', return_value=self.bundled), \
                patch.object(pengu_loader, 'get_user_data_dir', return_value=self.runtime.parent), \
                self.assertLogs(pengu_loader.log, level='WARNING'):
            self.assertEqual(pengu_loader._resolve_pengu_dir(), self.runtime)
        # Everything else was still updated
        self.assertEqual((self.runtime / 'plugins' / 'ROSE-UI' / 'index.js').read_text(encoding='utf-8'), 'new plugin')


@unittest.skipUnless(sys.platform == 'win32', 'config.ini is shared through the Windows INI API')
class ConfigIniTests(unittest.TestCase):
    """config.ini is read by core.dll and written by the Pengu loader through
    the Windows INI API (ANSI code page), and by Rose in Python"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.config_file = Path(temp_dir.name) / 'config.ini'
        paths = patch.object(config, 'get_config_file_path', return_value=self.config_file)
        paths.start()
        self.addCleanup(paths.stop)

    @staticmethod
    def core_dll_reads(path, key):
        buffer = ctypes.create_unicode_buffer(1024)
        ctypes.windll.kernel32.GetPrivateProfileStringW('General', key, '', buffer, 1024, str(path))
        return buffer.value

    def loader_writes(self, key, value):
        ctypes.windll.kernel32.WritePrivateProfileStringW('General', key, value, str(self.config_file))

    @unittest.skipUnless(_ansi_can_encode('é'), 'the ANSI code page has no é')
    def test_non_ascii_loaderpath_survives_rose_writes(self):
        loader_dir = r'C:\Users\José\AppData\Local\Rose\Pengu Loader'
        self.config_file.write_text('[General]\ninjection_threshold = 0.5\n', encoding='mbcs')
        self.loader_writes('disabled', '0')
        self.loader_writes('loaderpath', loader_dir)

        config.set_config_option('General', 'injection_threshold', '0.8')
        config.set_config_option('General', 'injection_threshold', '0.9')

        self.assertEqual(self.core_dll_reads(self.config_file, 'loaderpath'), loader_dir)
        self.assertEqual(self.core_dll_reads(self.config_file, 'injection_threshold'), '0.9')
        self.assertEqual(config.get_config_option('General', 'loaderpath'), loader_dir)

    @unittest.skipUnless(_ansi_can_encode('é'), 'the ANSI code page has no é')
    def test_reads_lines_older_rose_wrote_as_utf8(self):
        self.config_file.write_bytes(
            '[General]\r\nleaguepath = C:\\Jeux\\Légendes\r\n'.encode('utf-8')
            + 'loaderpath=C:\\Users\\José\\Pengu Loader\r\n'.encode('mbcs')
        )
        parser = configparser.ConfigParser(interpolation=None)
        config.read_config_file(parser, self.config_file)
        self.assertEqual(parser.get('General', 'leaguepath'), 'C:\\Jeux\\Légendes')
        self.assertEqual(parser.get('General', 'loaderpath'), 'C:\\Users\\José\\Pengu Loader')

    def test_write_replaces_the_file_without_leftovers(self):
        self.config_file.write_text('[General]\nold = 1\n', encoding='mbcs')
        parser = configparser.ConfigParser()
        parser['General'] = {'new': '2'}
        config.write_config_file(parser, self.config_file)
        self.assertEqual(self.core_dll_reads(self.config_file, 'new'), '2')
        self.assertEqual(self.core_dll_reads(self.config_file, 'old'), '')
        self.assertEqual(list(self.config_file.parent.iterdir()), [self.config_file])


if __name__ == '__main__':
    unittest.main()
