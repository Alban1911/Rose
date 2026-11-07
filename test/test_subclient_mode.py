"""A sub-client's Rose (python -m subclient) keeps off what belongs to the real client."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Isolate configuration from an installed Rose instance (see test_regional_compat)
from utils.core import paths
_test_data = tempfile.TemporaryDirectory()
_path_patch = patch.object(paths, '_cached_user_data_dir', Path(_test_data.name))


def setUpModule():
    _path_patch.start()
    unittest.addModuleCleanup(_test_data.cleanup)
    unittest.addModuleCleanup(_path_patch.stop)


import main as rose_main
import utils.integration.pengu_loader as pengu_loader
from injection.core import manager as injection_manager
from injection.game import game_monitor
from lcu.core import lockfile
from lcu.core.lcu_connection import LCUConnection
from main.core import lockfile as single_instance


class SubclientModeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.enterContext(patch.dict(os.environ, {'ROSE_SUBCLIENT': '1', 'LCU_LOCKFILE': str(self.dir / 'lockfile')}))

    def test_data_folder_comes_from_the_launcher(self):
        with patch.dict(os.environ, {'ROSE_DATA_DIR': str(self.dir / 'data')}), \
                patch.object(paths, '_cached_user_data_dir', None):
            self.assertEqual(paths.get_user_data_dir(), (self.dir / 'data').resolve())

    def test_runs_beside_roses_with_other_data_folders(self):
        names = set()
        for folder in ('a', 'b'):
            with patch.dict(os.environ, {'ROSE_DATA_DIR': str(self.dir / folder)}):
                names.add(single_instance.single_instance_mutex_name())
        with patch.dict(os.environ, {'ROSE_DATA_DIR': ''}):
            names.add(single_instance.single_instance_mutex_name())
        self.assertEqual(len(names), 3)

    def test_never_looks_for_the_real_client(self):
        with patch.object(lockfile.psutil, 'process_iter') as scan:
            self.assertIsNone(lockfile.find_lockfile())
            self.assertIsNone(lockfile.find_process_credentials())
            self.assertFalse(LCUConnection().ok)
        scan.assert_not_called()

    def test_talks_plain_http_to_its_subclient(self):
        (self.dir / 'lockfile').write_text('RoseSubclient:1:5555:key:http', encoding='utf-8')
        connection = LCUConnection()
        self.assertEqual(connection.base, 'http://127.0.0.1:5555')
        self.assertEqual(connection.websocket_credentials(), (5555, 'key', 'http'))

    def test_leaves_the_pengu_hook_alone(self):
        with patch.object(pengu_loader, '_run_cli_result') as cli, \
                patch.object(pengu_loader, 'restart_client') as restart:
            self.assertTrue(pengu_loader.activate_on_start('C:/League'))
            pengu_loader.ensure_active_for_client()
        cli.assert_not_called()
        restart.assert_not_called()

    def test_never_starts_injection(self):
        manager = injection_manager.InjectionManager.__new__(injection_manager.InjectionManager)
        manager._initialized = False
        manager.injection_lock = MagicMock()
        with patch.object(injection_manager, 'SkinInjector') as injector:
            manager._ensure_initialized()
        injector.assert_not_called()
        self.assertFalse(manager._initialized)

    def test_never_looks_for_the_real_install(self):
        with patch.object(rose_main, 'GameDetector') as detector:
            detector.return_value.detect_paths.return_value = (None, None)
            rose_main._setup_pengu_and_injection(MagicMock(), MagicMock())
        detector.assert_not_called()

    def test_leaves_suspended_games_alone(self):
        with patch.object(game_monitor.psutil, 'process_iter') as scan:
            self.assertEqual(game_monitor.resume_orphaned_game(), 0)
        scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
