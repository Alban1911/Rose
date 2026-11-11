import unittest
from unittest.mock import MagicMock, patch

from state import SharedState
from threads.handlers.champ_select_reset import note_phase_for_reset, perform_champ_select_reset
from threads.handlers.phase_handler import PhaseHandler

MORDEKAISER = 82


class PhasePollerResetTests(unittest.TestCase):
    """The WebSocket usually handles ChampSelect first; when the champion is
    assigned at once (ARAM) it is locked before the phase poller sees the
    same ChampSelect, which must not unlock it again"""

    def setUp(self):
        self.state = SharedState()
        self.lcu = MagicMock()
        self.lcu.owned_skins.return_value = [MORDEKAISER * 1000]
        self.handler = PhaseHandler(self.lcu, self.state)
        for patcher in (
            patch.object(PhaseHandler, "_sync_saved_mods_for_listing"),
            patch("ui.core.user_interface.get_user_interface"),
            patch("injection.baseskin.library.on_phase"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def lock_own_champion(self):
        self.state.locked_champ_id = MORDEKAISER
        self.state.locked_champ_timestamp = 123.0
        self.state.own_champion_locked = True

    def test_the_poller_keeps_a_lock_made_after_the_websocket_reset(self):
        note_phase_for_reset(self.state, "ChampSelect")
        perform_champ_select_reset(self.state, self.lcu)
        self.lock_own_champion()

        self.handler.handle_phase_change("ChampSelect", "ReadyCheck")

        self.assertEqual(self.state.locked_champ_id, MORDEKAISER)
        self.assertEqual(self.state.locked_champ_timestamp, 123.0)
        self.assertTrue(self.state.own_champion_locked)

    def test_the_poller_still_resets_when_it_sees_champ_select_first(self):
        # A lock left over from the previous game
        self.lock_own_champion()
        self.state.champion_exchange_triggered = True
        note_phase_for_reset(self.state, "Lobby")

        self.handler.handle_phase_change("ChampSelect", "ReadyCheck")

        self.assertTrue(self.state.champ_select_reset_done)
        self.assertIsNone(self.state.locked_champ_id)
        self.assertEqual(self.state.locked_champ_timestamp, 0.0)
        self.assertFalse(self.state.own_champion_locked)
        self.assertFalse(self.state.champion_exchange_triggered)


if __name__ == "__main__":
    unittest.main()
