import unittest
from unittest.mock import Mock, patch

from utils.integration import tray_manager


class TrayQuitTests(unittest.TestCase):
    def setUp(self):
        self.tray = tray_manager.TrayManager()
        self.icon = Mock()
        logger = patch.object(tray_manager, "log")
        logger.start()
        self.addCleanup(logger.stop)

    def test_a_quit_clicked_while_rose_starts_keeps_the_icon_and_runs_once_started(self):
        self.tray._on_quit(self.icon, None)
        self.icon.stop.assert_not_called()

        self.tray.quit_callback = Mock()
        self.tray.restart_callback = Mock()
        self.tray.run_pending_request()

        self.tray.quit_callback.assert_called_once()
        self.tray.restart_callback.assert_not_called()
        self.icon.stop.assert_called_once()
        self.tray.run_pending_request()
        self.tray.quit_callback.assert_called_once()

    def test_a_restart_clicked_while_rose_starts_keeps_the_icon_and_runs_once_started(self):
        self.tray._on_restart(self.icon, None)
        self.icon.stop.assert_not_called()

        self.tray.quit_callback = Mock()
        self.tray.restart_callback = Mock()
        self.tray.run_pending_request()

        self.tray.restart_callback.assert_called_once()
        self.tray.quit_callback.assert_not_called()
        self.icon.stop.assert_called_once()

    def test_a_quit_clicked_once_started_runs_at_once(self):
        self.tray.quit_callback = Mock()
        self.tray._on_quit(self.icon, None)

        self.tray.quit_callback.assert_called_once()
        self.icon.stop.assert_called_once()
        self.tray.run_pending_request()
        self.tray.quit_callback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
