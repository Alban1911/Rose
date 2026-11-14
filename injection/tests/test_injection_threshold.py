import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import config
from injection.config import base_skin_tracker, threshold_manager
from injection.config.threshold_manager import ThresholdManager
from threads.handlers import injection_trigger
from threads.handlers.injection_trigger import InjectionTrigger


class InjectionThresholdRangeTests(unittest.TestCase):
    """The injection threshold is at least a second: a skin changed after it
    is ignored, and under a second a late change missed the game (base skin)"""

    def test_values_are_kept_within_one_to_two_seconds(self):
        self.assertEqual(config.clamp_injection_threshold(0.42), 1.0)
        self.assertEqual(config.clamp_injection_threshold("1.5"), 1.5)
        self.assertEqual(config.clamp_injection_threshold(3), 2.0)

    def test_an_unreadable_value_is_the_default(self):
        for value in (None, "soon", float("nan")):
            self.assertEqual(config.clamp_injection_threshold(value), config.INJECTION_THRESHOLD_DEFAULT_S)

    def test_an_older_config_below_the_minimum_is_raised(self):
        state = SimpleNamespace(skin_write_ms=420)
        with patch.object(threshold_manager, "get_config_float", return_value=0.42):
            manager = ThresholdManager(state)
            self.assertEqual(manager.injection_threshold, 1.0)
            self.assertEqual(manager.refresh(), 1.0)

    def test_a_new_value_reaches_the_countdown(self):
        state = SimpleNamespace(skin_write_ms=1000)
        with patch.object(threshold_manager, "get_config_float", return_value=1.0):
            manager = ThresholdManager(state)
        with patch.object(threshold_manager, "get_config_float", return_value=1.5):
            self.assertEqual(manager.refresh(), 1.5)

        self.assertEqual(state.skin_write_ms, 1500)

    def test_the_recommended_threshold_is_never_under_the_minimum(self):
        samples = [{"confirmed": True, "elapsed_ms": 120}] * 10
        with patch.object(base_skin_tracker, "_load_samples", return_value=samples):
            stats = base_skin_tracker.get_stats()

        self.assertEqual(stats["recommended_threshold_ms"], 1000)

    def test_a_lower_threshold_is_only_recommended_from_enough_confirmations(self):
        confirmed = {"confirmed": True, "elapsed_ms": 120}
        missing = {"confirmed": False, "elapsed_ms": 900}
        for samples, enough in (([confirmed] * 9, False), ([confirmed] * 10, True), ([confirmed] * 10 + [missing], False)):
            with self.subTest(samples=len(samples)), \
                    patch.object(base_skin_tracker, "_load_samples", return_value=samples):
                self.assertEqual(base_skin_tracker.get_stats()["can_recommend_lower"], enough)


class BaseSkinConfirmationTests(unittest.TestCase):
    """The recommended threshold comes from how long the client takes to show
    a forced base skin. Timed from after the client's answer, each sample
    lasted until the end of champion select: about the threshold itself, so
    the recommendation always ended at the maximum"""

    BASE_SKIN = 55000

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.samples = Path(folder.name) / "base_skin_samples.json"
        for patcher in (
            patch.object(base_skin_tracker, "_data_path", return_value=self.samples),
            patch.object(injection_trigger, "log"),
            patch.object(injection_trigger, "report_issue"),
            patch.object(injection_trigger.time, "sleep"),
            patch("ui.core.user_interface.get_user_interface", return_value=MagicMock()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(base_skin_tracker.cancel_tracking)

    def force_base_skin(self, request):
        """Force the base skin: *request* stands for the client's answer to it."""
        trigger = object.__new__(InjectionTrigger)
        session = {"actions": [], "myTeam": [{"cellId": 0, "selectedSkinId": self.BASE_SKIN}]}
        trigger.lcu = SimpleNamespace(session=session, set_my_selection_skin=request)
        trigger.state = SimpleNamespace(local_cell_id=0, random_mode_active=False, ui_skin_thread=MagicMock())
        trigger.skin_scraper = None
        trigger.injection_manager = None
        trigger._force_base_skin(self.BASE_SKIN)

    def test_a_confirmation_that_precedes_the_clients_answer_is_timed(self):
        def request(skin_id):
            base_skin_tracker.on_skin_confirmed(skin_id)  # the session update
            return True

        self.force_base_skin(request)

        stats = base_skin_tracker.get_stats()
        self.assertEqual(stats["confirmed_count"], 1)
        self.assertLess(stats["max_ms"], 500)
        self.assertIsNone(base_skin_tracker.on_champ_select_exit())

    def test_the_check_after_the_request_confirms_a_skin_no_update_showed(self):
        self.force_base_skin(lambda skin_id: True)

        self.assertEqual(base_skin_tracker.get_stats()["confirmed_count"], 1)
        self.assertIsNone(base_skin_tracker.on_champ_select_exit())

    def test_a_base_skin_that_could_not_be_forced_is_not_awaited(self):
        self.force_base_skin(lambda skin_id: False)

        self.assertIsNone(base_skin_tracker.on_champ_select_exit())

    def test_samples_timed_until_the_end_of_champion_select_are_dropped(self):
        self.samples.write_text(json.dumps([{"elapsed_ms": 1986, "confirmed": True, "ts": 1}] * 10))

        self.assertEqual(base_skin_tracker.get_stats()["total_samples"], 0)


if __name__ == "__main__":
    unittest.main()
