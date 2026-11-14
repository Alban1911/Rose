import unittest
from unittest.mock import Mock, patch

from main.core import cleanup
from main.core.state import get_app_state


class CleanupTests(unittest.TestCase):
    def test_the_force_quit_timeout_stands_down_before_the_client_is_restored(self):
        """A tray Quit starts a force quit that fires unless Rose is shutting
        down: restoring the client alone outlasts it"""
        app_state = get_app_state()
        previous = app_state.shutting_down
        app_state.shutting_down = False
        self.addCleanup(setattr, app_state, "shutting_down", previous)
        seen = []
        thread_manager = Mock()
        thread_manager.stop_all.return_value = ([], 0.0)

        with patch.object(cleanup.pengu_loader, "deactivate_on_exit",
                          side_effect=lambda: seen.append(app_state.shutting_down)), \
                patch("injection.game.game_monitor.resume_orphaned_game"), \
                patch.object(cleanup, "cleanup_lock_file"), \
                patch.object(cleanup, "cleanup_console"), \
                patch.object(cleanup, "log"):
            cleanup.perform_cleanup(Mock(), thread_manager, Mock(), Mock())

        self.assertEqual(seen, [True])


if __name__ == "__main__":
    unittest.main()
