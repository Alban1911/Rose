import subprocess
import sys
import unittest
from unittest.mock import patch

import psutil

from injection.overlay import overlay_manager
from injection.overlay.overlay_manager import OverlayManager


class RunningGameTests(unittest.TestCase):
    """A stand-in process listed under the game's name"""

    def setUp(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(child.wait)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        self.child = child

    def _listed(self, *processes):
        return patch.object(overlay_manager, 'running_processes', return_value=list(processes))

    def test_the_game_is_found_by_name_without_listing_through_psutil(self):
        with self._listed((4, 'System'), (self.child.pid, 'League of Legends.exe')), \
                patch.object(psutil.Process, 'name', autospec=True, return_value='LEAGUE OF LEGENDS.EXE') as name, \
                patch.object(psutil, 'process_iter') as process_iter:
            game = OverlayManager._running_game()

        process_iter.assert_not_called()
        self.assertEqual(game.pid, self.child.pid)
        name.assert_called_once_with(game)
        # The game Rose holds: the process itself, not a stale stand-in
        game.suspend()
        self.assertEqual(game.status(), psutil.STATUS_STOPPED)
        game.resume()

    def test_a_game_that_exited_since_the_snapshot_is_not_returned(self):
        self.child.kill()
        self.child.wait()

        with self._listed((self.child.pid, 'League of Legends.exe')):
            self.assertIsNone(OverlayManager._running_game())

    def test_snapshot_pid_now_belongs_to_another_executable(self):
        with self._listed((self.child.pid, 'League of Legends.exe')):
            self.assertIsNone(OverlayManager._running_game())

    def test_no_game_running(self):
        with self._listed((self.child.pid, 'LeagueClientUx.exe')):
            self.assertIsNone(OverlayManager._running_game())


if __name__ == '__main__':
    unittest.main()
