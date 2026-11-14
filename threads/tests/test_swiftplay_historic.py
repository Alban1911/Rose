import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from state import SharedState
from threads.handlers import swiftplay_handler as swiftplay_module
from threads.handlers.phase_handler import PhaseHandler
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
        self.lcu.get_swiftplay_dual_champion_selection.return_value = None
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
        self.handler._remember_injected_skins({ANIVIA: 34062, 1: 1000})
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

    def test_lobby_poll_prunes_a_pick_after_the_champion_changes(self):
        self.tracking[ANIVIA] = 34062
        self.lcu.get_swiftplay_dual_champion_selection.side_effect = [
            {"champions": [{"championId": ANIVIA}, {"championId": 1}]},
            {"champions": [{"championId": 51}, {"championId": 1}]},
        ]
        self.handler._sync_tracking_with_lobby()
        self.handler._sync_tracking_with_lobby()

        self.assertNotIn(ANIVIA, self.tracking)

    def test_preparing_a_queue_prefers_current_slots_over_cached_ones(self):
        self.tracking[ANIVIA] = 34062
        self.handler._last_sync_active_ids = frozenset({ANIVIA})
        self.lcu.get_swiftplay_dual_champion_selection.return_value = {
            "champions": [{"championId": 51}],
        }
        self.handler.injection_manager = MagicMock()

        self.handler.trigger_swiftplay_injection()

        self.handler.injection_manager.injector._resolve_zip.assert_not_called()
        self.assertFalse(self.handler._injection_triggered)

    def test_canceling_and_requeueing_after_a_missing_archive_cannot_reuse_prepared_mods(self):
        self.tracking[ANIVIA] = 34062
        self.handler.injection_manager = MagicMock()
        injector = self.handler.injection_manager.injector
        self.lcu.get.side_effect = [
            {"searchState": "Searching"}, {"searchState": "Invalid"}, {"searchState": "Searching"},
        ]
        with TemporaryDirectory() as folder:
            archive = Path(folder) / "first.fantome"
            archive.touch()
            injector._resolve_zip.side_effect = [archive, None]
            injector._link_archive.return_value = archive

            self.handler.monitor_swiftplay_matchmaking()
            self.assertEqual(self.handler.state.swiftplay_extracted_mods, [archive.name])
            self.handler.monitor_swiftplay_matchmaking()
            self.assertEqual(self.handler.state.swiftplay_extracted_mods, [])
            self.assertEqual(self.tracking, {ANIVIA: 34062})

            self.tracking[ANIVIA] = 34063
            self.handler.monitor_swiftplay_matchmaking()

        self.assertFalse(self.handler._injection_triggered)
        self.assertEqual(self.handler.state.swiftplay_extracted_mods, [])

    def test_partial_preparation_remembers_only_the_skin_sent_to_the_overlay(self):
        self.tracking.update({ANIVIA: 34062, 1: 1001})
        self.handler.injection_manager = MagicMock()
        injector = self.handler.injection_manager.injector
        with TemporaryDirectory() as folder:
            archive = Path(folder) / "anivia.fantome"
            archive.touch()
            injector._resolve_zip.side_effect = [archive, None]
            injector._link_archive.return_value = archive
            injector._mk_run_overlay.return_value = 0

            self.handler.trigger_swiftplay_injection()
            self.handler.run_swiftplay_overlay()

        self.assertEqual(injector._mk_run_overlay.call_args.args[0], [archive.name])
        self.mocks["write_historic_entry"].assert_called_once_with(ANIVIA, 34062)

    def test_returning_to_lobby_discards_preparation_even_without_a_search_state_update(self):
        state = self.handler.state
        state.is_swiftplay_mode = True
        state.current_queue_id = 480
        state.swiftplay_extracted_mods = ["old.fantome"]
        self.tracking[ANIVIA] = 34062
        self.handler._injection_triggered = True
        phases = PhaseHandler(self.lcu, state, swiftplay_handler=self.handler)

        with patch("injection.baseskin.library.on_phase"):
            phases.handle_phase_change("Lobby", "Matchmaking")

        self.assertEqual(state.swiftplay_extracted_mods, [])
        self.assertFalse(self.handler._injection_triggered)
        self.assertEqual(self.tracking, {ANIVIA: 34062})


if __name__ == '__main__':
    unittest.main()
