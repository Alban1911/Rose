import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from injection.core import manager as manager_module
from injection.core.manager import InjectionManager


class ManagerWarmupTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(stop=False, phase="Lobby")
        self.manager = InjectionManager(shared_state=self.state)
        self.tasks = []
        threads = patch.object(manager_module.threading, "Thread", side_effect=self.queue_thread)
        threads.start()
        self.addCleanup(threads.stop)

    def queue_thread(self, target, **kwargs):
        return SimpleNamespace(start=lambda: self.tasks.append(target))

    def initialize(self):
        self.manager.injector = MagicMock()
        self.manager._initialized = True

    def test_startup_warms_the_manager_before_a_countdown(self):
        with patch.object(self.manager, "_ensure_initialized", side_effect=self.initialize):
            self.manager.initialize_when_ready()
            self.assertFalse(self.manager._initialized)  # initialization stays asynchronous
            self.tasks.pop(0)()
        self.assertEqual(len(self.tasks), 1)
        self.tasks.pop(0)()
        self.manager.injector.overlay_manager.start_patcher_early.assert_called_once()

    def test_failed_initialization_does_not_launch_the_manager(self):
        with patch.object(self.manager, "_ensure_initialized"):
            self.manager.initialize_when_ready()
            self.tasks.pop(0)()
        self.assertEqual(self.tasks, [])

    def test_shutdown_while_initializing_does_not_launch_the_manager(self):
        with patch.object(self.manager, "_ensure_initialized", side_effect=self.initialize):
            self.manager.initialize_when_ready()
            self.state.stop = True
            self.tasks.pop(0)()
        self.assertEqual(self.tasks, [])

    def test_lobby_cleanup_finishes_before_the_next_warmup(self):
        self.initialize()
        self.manager.kill_all_runoverlay_processes()
        self.assertEqual(len(self.tasks), 1)
        self.tasks.pop(0)()
        self.manager.injector.kill_all_runoverlay_processes.assert_called_once()
        self.assertFalse(self.manager._cleanup_in_progress)
        self.assertEqual(len(self.tasks), 1)
        self.tasks.pop(0)()
        self.manager.injector.overlay_manager.start_patcher_early.assert_called_once()

    def test_cleanup_does_not_restart_the_manager_outside_the_lobby(self):
        for phase in (None, "InProgress", "EndOfGame"):
            with self.subTest(phase=phase):
                self.initialize()
                self.state.phase = phase
                self.manager.kill_all_runoverlay_processes()
                self.tasks.pop(0)()
                self.assertEqual(self.tasks, [])

    def test_shutdown_during_cleanup_does_not_restart_the_manager(self):
        self.initialize()
        self.manager.kill_all_runoverlay_processes()
        self.state.stop = True
        self.tasks.pop(0)()
        self.assertEqual(self.tasks, [])

    def test_shutdown_after_warmup_was_queued_does_not_launch_the_manager(self):
        self.initialize()
        self.manager.start_patcher_in_background()
        self.state.stop = True
        self.tasks.pop(0)()
        self.manager.injector.overlay_manager.start_patcher_early.assert_not_called()

    def test_shutdown_cancels_an_in_flight_warmup_before_closing_the_manager(self):
        self.initialize()
        self.state.stop = True
        self.manager.kill_all_modtools_processes()
        calls = self.manager.injector.mock_calls
        self.assertIn(call.overlay_manager.discard_early_patcher(), calls)
        self.assertLess(calls.index(call.overlay_manager.discard_early_patcher()),
                        calls.index(call.kill_all_modtools_processes()))


if __name__ == "__main__":
    unittest.main()
