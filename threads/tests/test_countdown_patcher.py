import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from state import SharedState
from threads.handlers.injection_trigger import InjectionTrigger
from threads.utilities import loadout_ticker
from threads.utilities.loadout_ticker import LoadoutTicker

TICKER_ID = 4
CASSIOPEIA = 69
CASSIOPEIA_BASE = 69000
SPIRIT_BLOSSOM = 69009


class CountdownPatcherTests(unittest.TestCase):
    """The LTK patcher starts with the loadout countdown, about 30s before the
    game: started with the injection at T-2, a PC that froze for 4s lost it"""

    def setUp(self):
        self.state = SharedState()
        self.state.phase = 'FINALIZATION'
        self.state.current_ticker = TICKER_ID
        self.state.loadout_countdown_active = True
        self.state.loadout_t0 = time.monotonic()
        self.state.loadout_left0_ms = 300
        self.manager = MagicMock()
        lcu = SimpleNamespace(session={})
        self.ticker = LoadoutTicker(
            lcu, self.state, hz=100, fallback_ms=0, ticker_id=TICKER_ID, injection_manager=self.manager,
        )
        self.ticker.skin_name_resolver = MagicMock()
        self.ticker.skin_name_resolver.resolve_injection_name.return_value = 'skin_1001'
        self.ticker.injection_trigger = MagicMock()
        log = patch.object(loadout_ticker, 'log')
        log.start()
        self.addCleanup(log.stop)

    def _inject(self, *_):
        self.state.last_hover_written = True

    def test_the_patcher_starts_with_the_countdown(self):
        self.ticker.injection_trigger.trigger_injection.side_effect = self._inject
        self.ticker.run()

        self.manager.start_patcher_in_background.assert_called_once()
        self.manager.discard_early_patcher.assert_not_called()

    def test_a_countdown_without_a_skin_stops_it(self):
        self.ticker.skin_name_resolver.resolve_injection_name.return_value = None
        self.ticker.run()

        self.manager.discard_early_patcher.assert_called_once()

    def test_a_refused_injection_stops_it(self):
        self.ticker.run()  # the trigger refuses: the selection is never written

        self.ticker.injection_trigger.trigger_injection.assert_called()
        self.manager.discard_early_patcher.assert_called_once()

    def test_a_countdown_taken_over_leaves_it_to_the_new_one(self):
        def take_over(*_):
            self.state.current_ticker = TICKER_ID + 1

        self.ticker.injection_trigger.trigger_injection.side_effect = take_over
        self.ticker.run()

        self.manager.discard_early_patcher.assert_not_called()


class TriggerStopsTheUnusedPatcherTests(unittest.TestCase):
    def setUp(self):
        self.state = SharedState()
        self.state.locked_champ_id = CASSIOPEIA
        self.manager = MagicMock()
        scraper = SimpleNamespace(cache=SimpleNamespace(chroma_id_map={}))
        self.trigger = InjectionTrigger(MagicMock(), self.state, self.manager, scraper)
        self.trigger._inject_unowned_skin = MagicMock()
        # Keep this machine's saved skins and mods out of the injection path
        for target, kwargs in (
            ("utils.core.historic.get_historic_skin_for_champion", {"return_value": None}),
            ("utils.core.historic.clear_historic_entry", {}),
            ("utils.core.mod_historic.load_mod_historic", {"return_value": {}}),
            ("injection.mods.storage.ModStorageService", {}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_default_skin_stops_it(self):
        self.state.last_hovered_skin_id = CASSIOPEIA_BASE
        self.trigger.trigger_injection(f"skin_{CASSIOPEIA_BASE}", ticker_id=1)

        self.manager.discard_early_patcher.assert_called_once()

    def test_a_failed_setup_stops_it(self):
        self.state.last_hovered_skin_id = SPIRIT_BLOSSOM
        self.trigger._is_selectable_owned = MagicMock(side_effect=RuntimeError('cache not loaded'))
        self.trigger.trigger_injection(f"skin_{SPIRIT_BLOSSOM}", ticker_id=1)

        self.manager.discard_early_patcher.assert_called_once()

    def test_an_injected_skin_keeps_it(self):
        self.state.last_hovered_skin_id = SPIRIT_BLOSSOM
        self.trigger.trigger_injection(f"skin_{SPIRIT_BLOSSOM}", ticker_id=1)

        self.trigger._inject_unowned_skin.assert_called_once()
        self.manager.discard_early_patcher.assert_not_called()


if __name__ == '__main__':
    unittest.main()
