"""Each champion select syncs the saved mods with LTK Manager's library in the
background, so its listing shows the mods LTK Manager lost since"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from threads.handlers.phase_handler import PhaseHandler


class ChampSelectSyncTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(
            is_swiftplay_mode=False, swiftplay_extracted_mods=[], swiftplay_skin_tracking={},
            current_queue_id=None, champ_select_reset_done=False,
        )
        self.handler = PhaseHandler(MagicMock(), self.state)
        for patcher in (
            patch("threads.handlers.champ_select_reset.perform_champ_select_reset"),
            patch("ui.core.user_interface.get_user_interface"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def enter(self, phase, previous="Lobby"):
        with patch("injection.mods.ltk_sync.start_saved_mods_sync") as start:
            self.handler.handle_phase_change(phase, previous)
        return start

    def test_champion_select_starts_the_sync_once_the_index_changed(self):
        self.enter("ChampSelect").assert_called_once_with(only_if_changed=True)

    def test_a_swiftplay_champion_select_starts_it_too(self):
        self.state.is_swiftplay_mode = True

        self.enter("ChampSelect", previous="Matchmaking").assert_called_once_with(only_if_changed=True)

    def test_other_phases_do_not(self):
        self.enter("Matchmaking").assert_not_called()


if __name__ == "__main__":
    unittest.main()
