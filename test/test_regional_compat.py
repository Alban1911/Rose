import logging
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

# Isolate import-time configuration from an installed Rose instance.
from utils.core import paths
_test_data = tempfile.TemporaryDirectory()
unittest.addModuleCleanup(_test_data.cleanup)
_path_patch = patch.object(paths, '_cached_user_data_dir', Path(_test_data.name))
_path_patch.start()
unittest.addModuleCleanup(_path_patch.stop)

import config
from injection.config.config_manager import ConfigManager
from injection.game.game_detector import GameDetector
from injection.game.game_monitor import _GAME_PROCESS_NAMES
from lcu.core import lockfile
from lcu.core.lcu_connection import LCUConnection


def process(name='LeagueClientUx.exe', args=None, pid=42, denied=False):
    proc = SimpleNamespace(info={'name': name}, pid=pid)
    proc.cmdline = Mock(return_value=args or ['client', '--app-port=12345', '--remoting-auth-token=test-token'])
    if denied:
        proc.cmdline.side_effect = lockfile.psutil.AccessDenied(pid)
    return proc


class CredentialsTests(unittest.TestCase):
    def test_equals_arguments(self):
        with patch.object(lockfile.psutil, 'process_iter', return_value=[process()]):
            result = lockfile.find_process_credentials()
        self.assertEqual((result.port, result.password, result.protocol), (12345, 'test-token', 'https'))

    def test_separate_quoted_arguments(self):
        proc = process(name='LEAGUECLIENTUX.EXE', args=['client', '--app-port', '12345', '--remoting-auth-token', '"quoted-token"'])
        with patch.object(lockfile.psutil, 'process_iter', return_value=[proc]):
            self.assertEqual(lockfile.find_process_credentials().password, 'quoted-token')

    def test_access_denied_client_does_not_block_ux(self):
        with patch.object(lockfile.psutil, 'process_iter', return_value=[process('LeagueClient.exe', denied=True), process()]):
            self.assertIsNotNone(lockfile.find_process_credentials())

    def test_unrelated_process_not_read(self):
        proc = process('Other.exe')
        with patch.object(lockfile.psutil, 'process_iter', return_value=[proc]):
            self.assertIsNone(lockfile.find_process_credentials())
        proc.cmdline.assert_not_called()

    def test_invalid_credentials(self):
        for args in (['--app-port=0', '--remoting-auth-token=x'], ['--app-port=65536', '--remoting-auth-token=x'],
                     ['--app-port=invalid', '--remoting-auth-token=x'], ['--app-port=12345'],
                     ['--app-port=12345', '--remoting-auth-token=']):
            with self.subTest(args=args), patch.object(lockfile.psutil, 'process_iter', return_value=[process(args=args)]):
                self.assertIsNone(lockfile.find_process_credentials())

    def test_normal_lockfile(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lockfile'
            path.write_text('LeagueClient:42:12345:sample:https', encoding='utf-8')
            self.assertEqual(lockfile.parse_lockfile(str(path)).port, 12345)
            path.write_text('', encoding='utf-8')
            self.assertIsNone(lockfile.parse_lockfile(str(path)))


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'lockfile'
        self.path.write_text('', encoding='utf-8')
        self.lf = self.enterContext(patch('lcu.core.lcu_connection.find_lockfile', return_value=str(self.path)))
        self.proc = self.enterContext(patch('lcu.core.lcu_connection.find_process_credentials', return_value=lockfile.Lockfile('LeagueClientUx', 42, 12345, 'a', 'https')))

    def test_empty_lockfile_uses_process(self):
        connection = LCUConnection()
        self.assertTrue(connection.ok)
        self.assertEqual(connection.websocket_credentials(), (12345, 'a'))

    def test_missing_lockfile_uses_process(self):
        self.lf.return_value = None
        self.assertTrue(LCUConnection().ok)

    def test_valid_lockfile_preferred(self):
        self.path.write_text('LeagueClient:42:23456:file:https', encoding='utf-8')
        connection = LCUConnection()
        self.assertEqual(connection.port, 23456)
        self.proc.assert_not_called()

    def test_unchanged_credentials_keep_session(self):
        connection = LCUConnection()
        session = connection.session
        connection._next_credentials_check = 0
        connection.refresh_if_needed()
        self.assertIs(connection.session, session)

    def test_restart_rotates_credentials(self):
        connection = LCUConnection()
        self.proc.return_value = lockfile.Lockfile('LeagueClientUx', 43, 23456, 'b', 'https')
        connection.refresh_if_needed(force=True)
        self.assertEqual(connection.websocket_credentials(), (23456, 'b'))
        self.assertEqual(connection.session.auth, ('riot', 'b'))

    def test_process_exit_disables_connection(self):
        connection = LCUConnection()
        self.proc.return_value = None
        connection.refresh_if_needed(force=True)
        self.assertFalse(connection.ok)
        self.assertIsNone(connection.websocket_credentials())

    def test_scan_throttling(self):
        connection = LCUConnection()
        self.proc.reset_mock()
        connection.refresh_if_needed()
        self.proc.assert_not_called()


class PathsAndEncodingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manager = ConfigManager()
        self.manager._config_path = self.root / 'config.ini'

    def make_layout(self, regional=True, alternate=False):
        game = self.root / 'Game'
        client = self.root / 'LeagueClient' if regional else self.root
        game.mkdir()
        client.mkdir(exist_ok=True)
        (client / 'LeagueClient.exe').touch()
        (game / config.GAME_EXECUTABLE_NAMES[int(alternate)]).touch()
        return game, client

    def test_regional_directory_inferred_and_persisted(self):
        game, client = self.make_layout()
        self.manager.save_league_path(str(game))
        self.assertEqual(GameDetector(self.manager).detect_paths(), (game, client))
        self.assertEqual(self.manager.load_client_path(), str(client))

    def test_international_layout_preserved(self):
        game, client = self.make_layout(regional=False)
        self.assertEqual(self.manager.infer_client_path_from_league_path(str(game)), str(client))

    def test_alternate_game_filename(self):
        game, client = self.make_layout(alternate=True)
        self.manager.save_paths(str(game), str(client))
        self.assertEqual(GameDetector(self.manager).detect_paths(), (game, client))

    def test_ux_process_can_discover_regional_layout(self):
        game, client = self.make_layout()
        proc = SimpleNamespace(info={'name': 'LeagueClientUx.exe', 'exe': str(client / 'LeagueClientUx.exe')})
        with patch('injection.game.game_detector.psutil.process_iter', return_value=[proc]):
            self.assertEqual(GameDetector(self.manager).detect_paths(), (game, client))

    def test_utf8_chinese_paths_roundtrip(self):
        game, client = 'E:/英雄联盟/Game', 'E:/英雄联盟/LeagueClient'
        self.manager.save_paths(game, client)
        self.assertEqual(self.manager.load_league_path(), game)
        self.assertEqual(self.manager.load_client_path(), client)
        self.assertIn(game, self.manager._config_path.read_text(encoding='utf-8'))

    def test_utf8_bom_config(self):
        self.manager._config_path.write_text('[General]\nleaguePath=E:/英雄联盟/Game\n', encoding='utf-8-sig')
        self.assertEqual(self.manager.load_league_path(), 'E:/英雄联盟/Game')

    def test_main_config_utf8_read_and_write(self):
        with patch.object(config, 'get_config_file_path', return_value=self.manager._config_path):
            config.set_config_option('General', 'leaguePath', 'E:/英雄联盟/Game')
            config._CONFIG_MTIME = 0
            self.assertEqual(config.get_config_option('General', 'leaguePath'), 'E:/英雄联盟/Game')

    def test_both_process_names_recognized(self):
        self.assertIn('league of legends.exe', _GAME_PROCESS_NAMES)
        self.assertIn('league of legends (tm) client.exe', _GAME_PROCESS_NAMES)
        self.assertNotIn('leagueclient.exe', _GAME_PROCESS_NAMES)


class ExternalPenguTests(unittest.TestCase):
    def test_external_loader_preserved_without_activation(self):
        from utils.integration import pengu_loader
        with patch.object(pengu_loader, '_external_pengu_with_rose_plugins', return_value=Path('C:/ExternalPengu')), \
             patch.object(pengu_loader, '_write_session', return_value=True) as write_session, \
             patch.object(pengu_loader, 'activate') as activate, \
             patch.object(pengu_loader, 'restart_client') as restart:
            self.assertTrue(pengu_loader.activate_on_start('E:/LOL/LeagueClient'))
            write_session.assert_called_once_with(was_active=True, rose_activated=False)
            activate.assert_not_called()
            restart.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows registry integration')
    def test_external_loader_requires_rose_plugins(self):
        import winreg
        from utils.integration import pengu_loader
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'core.dll').touch()
            (directory / 'Pengu Loader.exe').touch()
            debugger = f'rundll32 "{directory / "core.dll"}", #6000 '
            with patch.object(winreg, 'OpenKey'), patch.object(winreg, 'QueryValueEx', return_value=(debugger, winreg.REG_SZ)):
                self.assertIsNone(pengu_loader._external_pengu_with_rose_plugins())
                for name in ('ROSE-SkinMonitor', 'ROSE-UI'):
                    plugin = directory / 'plugins' / name
                    plugin.mkdir(parents=True)
                    (plugin / 'index.js').touch()
                self.assertEqual(pengu_loader._external_pengu_with_rose_plugins(), directory)


class OverlayLifetimeTests(unittest.TestCase):
    def setUp(self):
        from injection.overlay.overlay_manager import OverlayManager
        self.manager = OverlayManager(Path('tools'), Path('mods'), Path('game'))

    def test_client_disconnect_during_game_keeps_overlay(self):
        with patch.object(self.manager, '_game_process_running', return_value=True):
            self.assertEqual(self.manager._overlay_should_stop(True, lambda: True), (False, True))

    def test_game_exit_stops_overlay_without_lcu(self):
        with patch.object(self.manager, '_game_process_running', return_value=False):
            self.assertEqual(self.manager._overlay_should_stop(True, lambda: False), (True, True))

    def test_wait_for_game_launch(self):
        with patch.object(self.manager, '_game_process_running', return_value=False):
            self.assertEqual(self.manager._overlay_should_stop(False, lambda: False), (False, False))

    def test_cancel_before_game_launch(self):
        with patch.object(self.manager, '_game_process_running', return_value=False):
            self.assertEqual(self.manager._overlay_should_stop(False, lambda: True), (True, False))

    def test_failed_process_scan_does_not_kill_overlay(self):
        with patch.object(self.manager, '_game_process_running', return_value=None):
            self.assertEqual(self.manager._overlay_should_stop(True, lambda: True), (False, True))

    def test_game_detection_accepts_both_names(self):
        from injection.overlay import overlay_manager
        for name in config.GAME_EXECUTABLE_NAMES:
            with self.subTest(name=name), patch.object(overlay_manager.psutil, 'process_iter', return_value=[SimpleNamespace(info={'name': name})]):
                self.assertTrue(self.manager._game_process_running())


class LoaderFallbackTests(unittest.TestCase):
    def setUp(self):
        from utils.integration import pengu_loader
        self.loader = pengu_loader
        self.loader._next_activation_check = 0
        self.loader._restart_pending = False
        self.loader._waiting_loader_window = False
        self.processes = self.enterContext(patch.object(self.loader, '_process_running', return_value=False))
        self.external = self.enterContext(patch.object(self.loader, '_external_pengu_with_rose_plugins', return_value=None))
        self.registered = self.enterContext(patch.object(self.loader, '_registered_pengu_core', return_value=None))
        self.activate = self.enterContext(patch.object(self.loader, 'activate_on_start', return_value=True))
        self.lcu = SimpleNamespace(ok=True, phase='Lobby')

    def test_disabled_external_loader_triggers_bundled_loader(self):
        self.loader.maintain_activation(self.lcu)
        self.activate.assert_called_once()

    def test_active_external_loader_is_preserved(self):
        self.external.return_value = Path('C:/StandalonePengu')
        self.loader.maintain_activation(self.lcu)
        self.activate.assert_not_called()

    def test_active_bundled_loader_does_not_reactivate(self):
        self.registered.return_value = self.loader.PENGU_DIR / 'core.dll'
        self.loader.maintain_activation(self.lcu)
        self.activate.assert_not_called()

    def test_game_process_prevents_switch_even_when_lcu_disconnected(self):
        self.processes.return_value = True
        self.loader.maintain_activation(SimpleNamespace(ok=False))
        self.activate.assert_not_called()

    def test_champion_select_prevents_switch(self):
        self.lcu.phase = 'ChampSelect'
        self.loader.maintain_activation(self.lcu)
        self.activate.assert_not_called()

    def test_open_gui_delays_activation_until_closed(self):
        self.processes.side_effect = lambda names: 'Pengu Loader.exe' in names
        self.loader.maintain_activation(self.lcu)
        self.activate.assert_not_called()
        self.loader._next_activation_check = 0
        self.processes.side_effect = None
        self.loader.maintain_activation(self.lcu)
        self.activate.assert_called_once()

    def test_monitor_throttles_attempts(self):
        self.loader.maintain_activation(self.lcu)
        self.loader.maintain_activation(self.lcu)
        self.activate.assert_called_once()

    def test_deferred_restart_retried_without_reactivation(self):
        self.registered.return_value = self.loader.PENGU_DIR / 'core.dll'
        self.loader._restart_pending = True
        self.processes.side_effect = lambda names: 'LeagueClientUx.exe' in names
        with patch.object(self.loader, 'restart_client', return_value=True) as restart:
            self.loader.maintain_activation(self.lcu)
            restart.assert_called_once()
        self.activate.assert_not_called()
        self.assertFalse(self.loader._restart_pending)


class LoaderRestartTests(unittest.TestCase):
    def setUp(self):
        from utils.integration import pengu_loader
        self.loader = pengu_loader
        self.processes = self.enterContext(patch.object(self.loader, '_process_running', return_value=False))
        self.connection = Mock(ok=True, base='https://127.0.0.1:12345')
        self.connection.session.get.return_value = Mock(status_code=200)
        self.connection.session.get.return_value.json.return_value = 'Lobby'
        self.connection.session.post.return_value = Mock(status_code=200)
        self.enterContext(patch('lcu.core.lcu_connection.LCUConnection', return_value=self.connection))

    def test_restart_uses_regional_connection(self):
        self.assertTrue(self.loader.restart_client())
        self.connection.session.post.assert_called_once_with('https://127.0.0.1:12345/riotclient/kill-and-restart-ux', timeout=5)
        self.connection.session.close.assert_called_once()

    def test_failed_http_response_is_not_reported_as_success(self):
        self.connection.session.post.return_value.status_code = 500
        self.assertFalse(self.loader.restart_client())

    def test_no_restart_while_selecting_champion(self):
        self.connection.session.get.return_value.json.return_value = 'ChampSelect'
        self.assertFalse(self.loader.restart_client())
        self.connection.session.post.assert_not_called()

    def test_no_restart_while_game_process_running(self):
        self.processes.return_value = True
        self.assertFalse(self.loader.restart_client())
        self.connection.session.post.assert_not_called()


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    unittest.main(verbosity=2)
