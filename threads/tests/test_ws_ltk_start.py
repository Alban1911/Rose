import unittest
from unittest.mock import MagicMock, patch

from state import SharedState
from threads.websocket import websocket_event_handler
from threads.websocket.websocket_event_handler import WebSocketEventHandler


class ChampSelectLtkManagerTests(unittest.TestCase):
    """LTK Manager took 7-14s from its launch to its patcher's scan, more
    than Practice Tool's countdown: it comes up as champion select begins,
    and goes away when champion select ends without a game (#431)"""

    def setUp(self):
        self.manager = MagicMock()
        self.handler = WebSocketEventHandler(MagicMock(), SharedState(), injection_manager=self.manager)
        for target in ("log", "_on_champ_select_exit"):
            patcher = patch.object(websocket_event_handler, target)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("threads.handlers.champ_select_reset.perform_champ_select_reset")
        patcher.start()
        self.addCleanup(patcher.stop)

    def phases(self, *phases):
        for phase in phases:
            self.handler.handle_api_event({"uri": "/lol-gameflow/v1/gameflow-phase", "data": phase})

    def test_ltk_manager_comes_up_as_champion_select_begins(self):
        self.phases("Lobby", "ChampSelect")

        self.manager.start_patcher_in_background.assert_called_once()
        self.manager.discard_early_patcher.assert_not_called()

    def test_a_game_keeps_it(self):
        for game_phase in ("GameStart", "InProgress"):
            with self.subTest(phase=game_phase):
                self.manager.reset_mock()
                self.phases("Lobby", "ChampSelect", game_phase)

                self.manager.discard_early_patcher.assert_not_called()

    def test_a_dodge_stops_it(self):
        self.phases("Lobby", "ChampSelect", "Lobby")

        self.manager.discard_early_patcher.assert_called_once()

    def test_swiftplay_champion_select_keeps_its_own_flow(self):
        self.handler.state.is_swiftplay_mode = True
        self.handler.swiftplay_handler = MagicMock()
        self.phases("Lobby", "ChampSelect")

        self.manager.start_patcher_in_background.assert_not_called()


if __name__ == "__main__":
    unittest.main()
