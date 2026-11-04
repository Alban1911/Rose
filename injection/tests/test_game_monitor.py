import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

import psutil

from injection.game import game_monitor
from injection.game.game_monitor import GameMonitor, resume_orphaned_game


class SuspendedGameTests(unittest.TestCase):
    """A stand-in game process, suspended the way Rose suspends League"""

    def setUp(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(child.wait)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.game = psutil.Process(child.pid)
        self.game.suspend()
        self.addCleanup(self._resume_quietly)
        # Only the stand-in counts as the game, never a real League process
        names = patch.object(game_monitor, '_GAME_PROCESS_NAMES', frozenset({self.game.name().lower()}))
        names.start()
        self.addCleanup(names.stop)
        processes = patch.object(game_monitor.psutil, 'process_iter', side_effect=lambda *a, **k: [self._iterated()])
        processes.start()
        self.addCleanup(processes.stop)

    def _iterated(self):
        proc = psutil.Process(self.game.pid)
        proc.info = {'name': self.game.name(), 'pid': self.game.pid}
        return proc

    def _resume_quietly(self):
        try:
            self.game.resume()
        except psutil.Error:
            pass

    def test_startup_resumes_a_game_a_dead_rose_left_suspended(self):
        self.assertEqual(resume_orphaned_game(), 1)
        self.assertNotEqual(self.game.status(), psutil.STATUS_STOPPED)

    def test_startup_leaves_a_running_game_alone(self):
        self.game.resume()
        self.assertEqual(resume_orphaned_game(), 0)

    def test_stop_resumes_the_game_after_the_monitor_deactivated_itself(self):
        monitor = GameMonitor(lambda: 60.0)
        monitor._suspended_game_process = self.game
        monitor._monitor_active = False  # the loop exits on its own once the patcher starts
        monitor.stop()
        self.assertNotEqual(self.game.status(), psutil.STATUS_STOPPED)


class SuspendRetryTests(unittest.TestCase):
    """A game that refuses the handle once must still be frozen in time."""

    def setUp(self):
        self.monitor = GameMonitor(lambda: 60.0)

    def test_a_transient_access_denied_is_retried(self):
        proc = MagicMock()
        proc.suspend.side_effect = [psutil.AccessDenied(pid=1), None]

        with patch.object(game_monitor.time, 'sleep') as sleep:
            self.assertTrue(self.monitor._suspend_process(proc))

        self.assertEqual(proc.suspend.call_count, 2)
        sleep.assert_called_once_with(game_monitor.SUSPEND_RETRY_DELAY_S)

    def test_a_permanent_access_denied_gives_up_after_the_retries(self):
        proc = MagicMock()
        proc.suspend.side_effect = psutil.AccessDenied(pid=1)

        with patch.object(game_monitor, 'SUSPEND_RETRY_ATTEMPTS', 3), \
             patch.object(game_monitor.time, 'sleep'):
            self.assertFalse(self.monitor._suspend_process(proc))

        self.assertEqual(proc.suspend.call_count, 3)

    def test_a_vanished_process_is_not_retried(self):
        proc = MagicMock()
        proc.suspend.side_effect = psutil.NoSuchProcess(pid=1)

        self.assertFalse(self.monitor._suspend_process(proc))
        self.assertEqual(proc.suspend.call_count, 1)


if __name__ == '__main__':
    unittest.main()
