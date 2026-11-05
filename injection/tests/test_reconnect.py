import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psutil

from injection.game import reconnect
from injection.game.reconnect import PHASE_URI, RECONNECT_URI, kill_game, reconnect_to_game


class FakeLcu:
    """The client's gameflow: phases in turn (the last repeats), reconnect answers"""

    def __init__(self, phases, reconnect_status=204, ok=True):
        self.ok = ok
        self.base = "https://127.0.0.1:1234"
        self.phases = list(phases)
        self.reconnect_status = reconnect_status
        self.posts = []
        self.session = SimpleNamespace(get=self._get, post=self._post)

    def refresh_if_needed(self):
        pass

    def _get(self, url, timeout=None):
        assert url == self.base + PHASE_URI
        phase = self.phases.pop(0) if len(self.phases) > 1 else self.phases[0]
        return SimpleNamespace(json=lambda: phase)

    def _post(self, url, timeout=None):
        self.posts.append(url)
        return SimpleNamespace(status_code=self.reconnect_status)


class ReconnectTests(unittest.TestCase):
    """A killed game is launched again by the client's reconnect (LCU
    POST /lol-gameflow/v1/reconnect), once the client noticed it is gone"""

    def setUp(self):
        patcher = patch.object(reconnect, "RECONNECT_POLL_S", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_it_reconnects_once_the_client_offers_it(self):
        lcu = FakeLcu(["InProgress", "InProgress", "Reconnect"])

        self.assertTrue(reconnect_to_game(lcu, timeout=5))
        self.assertEqual(lcu.posts, [lcu.base + RECONNECT_URI])

    def test_a_refused_reconnect_is_asked_again(self):
        lcu = FakeLcu(["Reconnect"], reconnect_status=500)
        answers = iter([500, 204])
        lcu._post = lambda url, timeout=None: (lcu.posts.append(url), SimpleNamespace(status_code=next(answers)))[1]
        lcu.session = SimpleNamespace(get=lcu._get, post=lcu._post)

        self.assertTrue(reconnect_to_game(lcu, timeout=5))
        self.assertEqual(len(lcu.posts), 2)

    def test_a_match_that_ended_is_not_reconnected(self):
        lcu = FakeLcu(["InProgress", "EndOfGame"])

        self.assertFalse(reconnect_to_game(lcu, timeout=5))
        self.assertEqual(lcu.posts, [])

    def test_a_stopped_session_stops_waiting(self):
        self.assertFalse(reconnect_to_game(FakeLcu(["InProgress"]), stopped=lambda: True, timeout=5))

    def test_it_gives_up_after_the_timeout(self):
        self.assertFalse(reconnect_to_game(FakeLcu(["InProgress"]), timeout=0.05))


class KillGameTests(unittest.TestCase):
    def test_the_game_is_killed_and_waited_for(self):
        game = MagicMock()

        self.assertTrue(kill_game(game))
        game.kill.assert_called_once()
        game.wait.assert_called_once()

    def test_a_game_already_gone_counts_as_killed(self):
        game = MagicMock()
        game.kill.side_effect = psutil.NoSuchProcess(1234)

        self.assertTrue(kill_game(game))

    def test_a_game_that_cannot_be_killed_is_not(self):
        game = MagicMock()
        game.kill.side_effect = psutil.AccessDenied(1234)

        self.assertFalse(kill_game(game))
        self.assertFalse(kill_game(None))


if __name__ == "__main__":
    unittest.main()
