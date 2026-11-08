import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from injection.game import game_monitor
from injection.game.game_monitor import make_game_ended_callback
from injection.overlay import overlay_manager
from injection.overlay.ltf_session import LtfSession
from injection.overlay.overlay_manager import OverlayManager


class PatcherReconnectTests(unittest.TestCase):
    """#413: the client closing and the game crashing, then the client relaunching
    it with Reconnect, must find the LTK patcher still running."""

    def run_session(self, phases, clock=None):
        """Serve a session while state.phase walks through *phases* (one per
        loop tick). Returns (exit code, the phases seen, whether it ended)."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            overlay = OverlayManager(root / 'tools', root / 'mods', root / 'game')
        state = SimpleNamespace(phase='InProgress', stop=False)
        remaining = iter(phases)
        observed = []
        session = {'ltf': LtfSession(None, launched=False), 'error': None, 'done': False}

        def tick(_):
            observed.append(state.phase)
            try:
                state.phase = next(remaining)
            except StopIteration:
                session['ltf'].ended = True

        callback = make_game_ended_callback(state, clock=clock) if clock else make_game_ended_callback(state)
        with patch.object(overlay_manager.time, 'sleep', side_effect=tick), \
                patch.object(overlay, '_running_game', return_value=None), \
                patch.object(overlay, '_check_bridge', return_value=True), \
                patch.object(overlay, '_poll_patcher_status'), \
                patch.object(overlay, '_check_patcher_verdict'), \
                patch.object(overlay, '_stopped_by_rose', return_value=False), \
                patch.object(overlay, '_end_session') as end:
            code = overlay._run_session(session, callback)
        ended_by_game = not session['ltf'].ended
        end.assert_called_once()
        return code, observed, ended_by_game

    def test_game_crash_and_client_outage_keep_the_patcher_until_the_match_ends(self):
        code, observed, ended = self.run_session(
            [None, None, 'Reconnect', 'GameStart', 'InProgress', 'EndOfGame'])
        self.assertEqual(code, 0)
        self.assertTrue(ended)
        self.assertEqual(observed, ['InProgress', None, None, 'Reconnect', 'GameStart', 'InProgress'])

    def test_a_client_that_never_comes_back_ends_the_session(self):
        seconds = iter(range(1000))  # a second passes at each reading
        with patch.object(game_monitor, 'CLIENT_OUTAGE_GRACE_S', 3.0):
            code, observed, ended = self.run_session([None] * 10, clock=lambda: float(next(seconds)))
        self.assertEqual(code, 0)
        self.assertTrue(ended, 'the session outlived a client gone for good')
        self.assertLess(len(observed), 10)


if __name__ == '__main__':
    unittest.main()
