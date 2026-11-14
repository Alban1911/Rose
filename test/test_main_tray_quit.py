import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import main as rose_main
from utils.integration import tray_manager


class TrayQuitWhileStartingTests(unittest.TestCase):
    def test_a_quit_clicked_while_preparing_the_mods_stops_rose_once_its_state_exists(self):
        """The tray has no callback while the stored mods are converted: the
        Quit clicked then must still reach the state, not only hide the icon"""
        tray = tray_manager.TrayManager()
        icon = Mock()
        state = SimpleNamespace(stop=False, skin_write_ms=0, inject_batch=1)
        injection_manager = Mock(injection_threshold=0.5)

        def convert(tray_arg):
            tray_arg._on_quit(icon, None)
            icon.stop.assert_not_called()

        with patch.object(rose_main, "check_single_instance"), \
                patch.object(rose_main, "_update_registry_version"), \
                patch.object(rose_main.pengu_loader, "cleanup_if_dirty"), \
                patch.object(rose_main, "setup_logging_and_cleanup"), \
                patch.object(rose_main, "initialize_tray_manager", return_value=tray), \
                patch.object(rose_main, "AppStatus"), \
                patch.object(rose_main, "remove_unpacked_leftovers"), \
                patch.object(rose_main, "convert_stored_mods", convert), \
                patch.object(rose_main, "start_saved_mods_sync"), \
                patch.object(rose_main, "initialize_core_components",
                             return_value=(MagicMock(), MagicMock(), state, injection_manager)), \
                patch.object(rose_main, "create_lcu_disconnection_handler"), \
                patch.object(rose_main, "create_daemon_thread") as watchdog, \
                patch.object(rose_main, "initialize_threads") as threads, \
                patch.object(rose_main, "perform_cleanup") as cleanup, \
                patch.object(tray_manager, "log"):
            rose_main.run_league_unlock(args=SimpleNamespace())

        self.assertTrue(state.stop)
        # Rose ends there: no threads, no Pengu activation restarting the client
        threads.assert_not_called()
        cleanup.assert_called_once()
        watchdog.return_value.start.assert_called_once()
        icon.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
