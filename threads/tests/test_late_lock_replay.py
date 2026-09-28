import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from threads.core.lcu_monitor_thread import LCUMonitorThread

MORDEKAISER = 82


class LateLockReplayTests(unittest.TestCase):
    """A champion already locked when Rose picks up the champ select gets the
    skin the client showed just before, so every plugin learns the new skin"""

    def setUp(self):
        self.monitor = LCUMonitorThread.__new__(LCUMonitorThread)
        self.monitor.state = SimpleNamespace(
            locked_champ_id=MORDEKAISER,
            champ_select_generation=5,
            ui_last_text='Mordekaiser',
            ui_last_text_champion_id=None,
            ui_last_text_generation=5,
            ui_last_text_timestamp=time.monotonic(),
        )
        self.ui_thread = MagicMock()
        # The locked champion's skins, as the late lock scraped them
        skins = {'Mordekaiser': 82000, 'PROJECT: Mordekaiser': 82044}
        self.monitor.skin_scraper = MagicMock()
        self.monitor.skin_scraper.find_skin_by_text.side_effect = lambda name: (
            (skins[name], name, 1.0) if name in skins else (82044, 'PROJECT: Mordekaiser', 0.8)
        )

    def _replayed(self):
        self.monitor._replay_cached_skin_name(self.ui_thread)
        return self.ui_thread.message_handler.handle_message.called

    def test_a_skin_seen_before_any_champion_was_known_is_replayed(self):
        self.assertTrue(self._replayed())

    def test_the_same_champion_is_replayed(self):
        self.monitor.state.ui_last_text_champion_id = MORDEKAISER
        self.assertTrue(self._replayed())

    def test_another_champions_skin_is_not(self):
        self.monitor.state.ui_last_text = 'Master Yi'
        self.monitor.state.ui_last_text_champion_id = 11
        self.assertFalse(self._replayed())

    def test_a_skin_hovered_on_another_champion_is_not(self):
        # Fuzzy matching would take it for PROJECT: Mordekaiser
        self.monitor.state.ui_last_text = 'PROJECT: Master Yi'
        self.assertFalse(self._replayed())

    def test_a_skin_from_an_earlier_champ_select_is_not(self):
        self.monitor.state.ui_last_text_generation = 4
        self.assertFalse(self._replayed())


if __name__ == '__main__':
    unittest.main()
