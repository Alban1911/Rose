import unittest
from types import SimpleNamespace

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
