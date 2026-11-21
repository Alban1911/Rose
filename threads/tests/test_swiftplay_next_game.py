import unittest
from unittest.mock import MagicMock

from state import SharedState
from threads.handlers.phase_handler import PhaseHandler
from threads.handlers.swiftplay_handler import SwiftplayHandler


class SwiftplayNextGameTests(unittest.TestCase):
    """#550: in Swiftplay/Quickplay, champ select skips the per-game reset, so
    the injection flags of a game must not reach the next one. With
    last_hover_written still set, the countdown neither stages nor injects."""

    def setUp(self):
        self.lcu = MagicMock()
        self.lcu.get_swiftplay_dual_champion_selection.return_value = None
        self.state = SharedState()
        self.handler = SwiftplayHandler(self.lcu, self.state)
        # Matchmaking would start the Swiftplay monitor threads
        self.handler.monitor_swiftplay_matchmaking = MagicMock()
        self.handler.trigger_swiftplay_injection = MagicMock()
        self.phases = PhaseHandler(self.lcu, self.state, swiftplay_handler=self.handler)

    def _first_game_injected(self):
        self.state.is_swiftplay_mode = True
        self.state.current_queue_id = 890
        # What the injection of the first game leaves behind
        self.state.last_hover_written = True
        self.state.injection_completed = True

    def test_next_champ_select_can_inject_again(self):
        self._first_game_injected()

        self.phases.handle_phase_change("PreEndOfGame", "InProgress")
        self.phases.handle_phase_change("EndOfGame", "PreEndOfGame")
        # Back in a Swiftplay lobby, the lobby detection sets the mode again
        # before the phase handler sees Lobby (the log shows
        # "Phase transition: EndOfGame -> Lobby (swiftplay=True)")
        self.state.is_swiftplay_mode = True
        self.state.current_queue_id = 890
        for previous, phase in [
            ("EndOfGame", "Lobby"),
            ("Lobby", "Matchmaking"),
            ("Matchmaking", "ReadyCheck"),
            ("ReadyCheck", "ChampSelect"),
        ]:
            self.phases.handle_phase_change(phase, previous)

        self.assertFalse(self.state.last_hover_written)
        self.assertFalse(self.state.injection_completed)

    def test_swiftplay_exit_clears_the_injection_flags(self):
        # Also reached without EndOfGame (lost session, queue changed)
        self._first_game_injected()

        self.handler.cleanup_swiftplay_exit()

        self.assertFalse(self.state.last_hover_written)
        self.assertFalse(self.state.injection_completed)


if __name__ == '__main__':
    unittest.main()
