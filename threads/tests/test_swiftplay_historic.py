import unittest
from unittest.mock import MagicMock, patch

from state import SharedState
from threads.handlers import swiftplay_handler as swiftplay_module
from threads.handlers.swiftplay_handler import SwiftplayHandler

ANIVIA = 34


class SwiftplayHistoricTests(unittest.TestCase):
    """Historic mode in Swiftplay/Quickplay, as in champ select: the saved skin
    applies while the lobby shows the default skin, the user's choice wins"""

    def setUp(self):
        self.saved = {ANIVIA: 34062}
        # Never touch the developer's real historic.json
        patches = {
            'get_historic_skin_for_champion': patch.object(
                swiftplay_module, 'get_historic_skin_for_champion', side_effect=self.saved.get
            ),
            'write_historic_entry': patch.object(swiftplay_module, 'write_historic_entry'),
            'clear_historic_entry': patch.object(swiftplay_module, 'clear_historic_entry'),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)
        self.lcu = MagicMock()
        self.handler = SwiftplayHandler(self.lcu, SharedState())
        self.tracking = self.handler.state.swiftplay_skin_tracking

    def test_saved_skin_replaces_the_default_skin(self):
        self.tracking[ANIVIA] = 34000
        self.handler._apply_historic_skins({ANIVIA})
        self.assertEqual(self.tracking[ANIVIA], 34062)

    def test_saved_skin_applies_to_an_untouched_champion(self):
        self.handler._apply_historic_skins({ANIVIA, 1})
        self.assertEqual(self.tracking, {ANIVIA: 34062})

    def test_the_users_choice_wins(self):
        self.handler.mark_champion_changed(ANIVIA, 34005)
        self.tracking[ANIVIA] = 34005
        self.handler._apply_historic_skins({ANIVIA})
        self.assertEqual(self.tracking[ANIVIA], 34005)

        # Going back to the default skin is a choice too
        self.handler.mark_champion_changed(ANIVIA, 34000)
        self.tracking[ANIVIA] = 34000
        self.handler._apply_historic_skins({ANIVIA})
        self.assertEqual(self.tracking[ANIVIA], 34000)

    def test_default_skin_reported_by_the_client_is_not_a_choice(self):
        # e.g. after the base skin is forced before queueing
        self.handler.mark_champion_changed(ANIVIA, 34000)
        self.tracking[ANIVIA] = 34000
        self.handler._apply_historic_skins({ANIVIA})
        self.assertEqual(self.tracking[ANIVIA], 34062)

    def test_saved_custom_mods_are_left_alone(self):
        self.saved[ANIVIA] = 'path:skins/34000/Mod'
        self.handler._apply_historic_skins({ANIVIA})
        self.assertEqual(self.tracking, {})

    def test_skins_a_game_used_are_saved(self):
        self.handler._last_injected_tracking = {ANIVIA: 34062, 1: 1000}
        self.handler._remember_injected_skins()
        self.mocks['write_historic_entry'].assert_called_once_with(ANIVIA, 34062)

    def test_queueing_with_the_default_skin_by_choice_forgets_the_saved_skin(self):
        self.handler.mark_champion_changed(ANIVIA, 34005)
        self.handler._forget_declined_historic_skins({ANIVIA: 34000})
        self.mocks['clear_historic_entry'].assert_called_once_with(ANIVIA)

        self.mocks['clear_historic_entry'].reset_mock()
        self.handler._forget_declined_historic_skins({ANIVIA: 34005})
        self.mocks['clear_historic_entry'].assert_not_called()

    def test_base_skin_is_forced_for_a_saved_skin(self):
        self.handler._last_sync_active_ids = frozenset({ANIVIA})
        self.handler.force_base_skins_if_needed()
        tracking, _owned = self.lcu.force_swiftplay_base_skins.call_args.args
        self.assertEqual(tracking, {ANIVIA: 34062})


if __name__ == '__main__':
    unittest.main()
