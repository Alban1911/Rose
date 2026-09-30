import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import config


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.path = Path(temp_dir.name) / 'config.ini'
        patcher = patch.object(config, 'get_config_file_path', return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Start every test from an empty cache
        saved = (config._CONFIG, config._CONFIG_MTIME)
        self.addCleanup(lambda: setattr(config, '_CONFIG', saved[0]) or setattr(config, '_CONFIG_MTIME', saved[1]))
        config._CONFIG_MTIME = -1.0

    def rewrite(self, text):
        """Change the file with a new modification time, like a settings save"""
        self.path.write_text(text, encoding='utf-8')
        mtime = time.time() + 10
        os.utime(self.path, (mtime, mtime))


class ReloadConsistencyTests(ConfigTestCase):
    """Reloads cleared the shared parser before reading the file again, so a
    thread reading a setting at that moment got the default value"""

    def test_a_reader_during_a_reload_sees_the_previous_value(self):
        self.rewrite('[General]\nthreshold = 1.5\n')
        self.assertEqual(config.get_config_option('General', 'threshold'), '1.5')
        self.rewrite('[General]\nthreshold = 2.0\n')

        reading = threading.Event()
        release = threading.Event()
        real_read = config.read_config_file

        def slow_read(parser, path):
            reading.set()
            release.wait(5)
            real_read(parser, path)

        with patch.object(config, 'read_config_file', side_effect=slow_read):
            reloader = threading.Thread(target=config._reload_config)
            reloader.start()
            reading.wait(5)
            seen_during_reload = config._CONFIG.get('General', 'threshold', fallback=None)
            release.set()
            reloader.join(5)

        self.assertEqual(seen_during_reload, '1.5')
        self.assertEqual(config.get_config_option('General', 'threshold'), '2.0')

    def test_an_unreadable_file_keeps_the_last_good_settings(self):
        self.rewrite('[General]\nthreshold = 1.5\n')
        config.get_config_option('General', 'threshold')
        self.rewrite('[General]\nthreshold = 2.0\n')

        with patch.object(config, 'read_config_file', side_effect=ValueError('corrupt')):
            self.assertEqual(config.get_config_option('General', 'threshold'), '1.5')


class PercentSignTests(ConfigTestCase):
    """configparser's default interpolation rejects a lone '%', which a game
    path can contain: saving it raised and reading it back failed"""

    def test_a_path_with_a_percent_sign_round_trips(self):
        path = r'D:\Games 100%\Riot Games\League of Legends\Game'
        config.set_config_option('General', 'leaguePath', path)
        self.assertEqual(config.get_config_option('General', 'leaguePath'), path)

    def test_the_config_manager_keeps_a_percent_sign_in_game_paths(self):
        from injection.config.config_manager import ConfigManager

        manager = ConfigManager()
        manager._config_path = self.path
        path = r'D:\Games 100%\Riot Games\League of Legends\Game'
        manager.save_league_path(path)
        manager.save_client_path(r'D:\Games 100%\Riot Games\League of Legends')

        self.assertEqual(manager.load_league_path(), path)
        self.assertEqual(manager.load_client_path(), r'D:\Games 100%\Riot Games\League of Legends')


if __name__ == '__main__':
    unittest.main()
