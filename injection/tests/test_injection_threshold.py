import unittest
from types import SimpleNamespace
from unittest.mock import patch

import config
from injection.config import base_skin_tracker, threshold_manager
from injection.config.threshold_manager import ThresholdManager


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


if __name__ == "__main__":
    unittest.main()
