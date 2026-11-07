import unittest
from types import SimpleNamespace

from injection.game import game_monitor
from injection.game.game_monitor import make_game_ended_callback


class GameEndedCallbackTests(unittest.TestCase):
    @staticmethod
    def _run(phases):
        state = SimpleNamespace(phase=None)
        callback = make_game_ended_callback(state)
        results = []
        for phase in phases:
            state.phase = phase
            results.append(callback())
        return results

    def test_ends_once_the_game_is_over(self):
        self.assertEqual(
            self._run(['ChampSelect', 'GameStart', 'InProgress', 'WaitingForStats']),
            [False, False, False, True],
        )

    def test_reconnect_is_not_the_end(self):
        self.assertEqual(
            self._run(['InProgress', 'Reconnect', 'GameStart', 'InProgress', 'EndOfGame']),
            [False, False, False, False, True],
        )

    def test_never_ends_without_a_game(self):
        # A dodge: the lobby cleanup stops the patcher instead
        self.assertEqual(self._run(['ChampSelect', 'Lobby']), [False, False])

    def test_client_outage_during_reconnect_keeps_the_match(self):
        self.assertEqual(
            # the phase thread reads the client's "None" as None
            self._run(['InProgress', None, None, None, 'Reconnect',
                       'GameStart', 'InProgress', 'WaitingForStats']),
            [False, False, False, False, False, False, False, True],
        )

    def test_a_phase_after_the_outage_ends_the_match(self):
        for phase in ('WaitingForStats', 'PreEndOfGame', 'EndOfGame', 'TerminatedInError',
                      'Lobby', 'Matchmaking', 'ReadyCheck', 'ChampSelect'):
            with self.subTest(phase=phase):
                self.assertEqual(self._run(['InProgress', None, phase]),
                                 [False, False, True])

    def test_a_client_gone_past_the_grace_ends_the_match(self):
        """The client closed for good, or reopened on its home screen (no phase either)."""
        state = SimpleNamespace(phase='InProgress')
        now = [0.0]
        callback = make_game_ended_callback(state, clock=lambda: now[0])
        self.assertFalse(callback())
        state.phase = None
        self.assertFalse(callback())
        now[0] = game_monitor.CLIENT_OUTAGE_GRACE_S - 1
        self.assertFalse(callback())
        now[0] = game_monitor.CLIENT_OUTAGE_GRACE_S
        self.assertTrue(callback())

    def test_the_grace_restarts_with_each_outage(self):
        state = SimpleNamespace(phase='InProgress')
        now = [0.0]
        callback = make_game_ended_callback(state, clock=lambda: now[0])
        callback()
        state.phase = None
        callback()
        now[0] = game_monitor.CLIENT_OUTAGE_GRACE_S - 1
        state.phase = 'InProgress'  # back in the game
        self.assertFalse(callback())
        state.phase = None
        self.assertFalse(callback())
        now[0] += game_monitor.CLIENT_OUTAGE_GRACE_S - 1
        self.assertFalse(callback())

    def test_closing_rose_stops_waiting_for_reconnect(self):
        state = SimpleNamespace(phase='InProgress', stop=False)
        callback = make_game_ended_callback(state)
        self.assertFalse(callback())
        state.phase = None
        self.assertFalse(callback())
        state.stop = True
        self.assertTrue(callback())

    def test_each_injection_tracks_its_own_game(self):
        state = SimpleNamespace(phase='InProgress')
        first = make_game_ended_callback(state)
        first()
        state.phase = 'EndOfGame'
        second = make_game_ended_callback(state)
        self.assertTrue(first())
        self.assertFalse(second())


if __name__ == '__main__':
    unittest.main()
