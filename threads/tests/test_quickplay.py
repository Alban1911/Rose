import unittest
from unittest.mock import MagicMock

from state import SharedState
from threads.handlers.lobby_processor import LobbyProcessor


class LobbyPickQueueTests(unittest.TestCase):
    """Queues whose champions and skins are picked in the lobby take the Swiftplay path"""

    @staticmethod
    def _takes_lobby_pick_path(mode, queue):
        swiftplay_handler = MagicMock()
        swiftplay_handler.detect_swiftplay_in_lobby.return_value = (mode, queue)
        LobbyProcessor(
            MagicMock(ok=True, is_swiftplay=False, game_mode=None),
            SharedState(),
            injection_manager=MagicMock(),
            swiftplay_handler=swiftplay_handler,
        ).process_lobby_state(force=True)
        return swiftplay_handler.handle_swiftplay_lobby.called

    def test_quickplay_picks_skins_in_the_lobby(self):
        # Quickplay reports the CLASSIC game mode: only its queue tells
        self.assertTrue(self._takes_lobby_pick_path('CLASSIC', 490))

    def test_swiftplay_still_does(self):
        self.assertTrue(self._takes_lobby_pick_path('SWIFTPLAY', 480))
        self.assertTrue(self._takes_lobby_pick_path(None, 480))

    def test_champ_select_queues_do_not(self):
        for queue in (400, 420, 430, 440):
            self.assertFalse(self._takes_lobby_pick_path('CLASSIC', queue))


if __name__ == '__main__':
    unittest.main()
