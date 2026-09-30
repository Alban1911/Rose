import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from state import SharedState
from threads.utilities import loadout_ticker
from threads.utilities.loadout_ticker import LoadoutTicker

TICKER_ID = 3


class TickerErrorTests(unittest.TestCase):
    """An error inside the countdown used to kill the ticker with the countdown
    still flagged active, so no ticker ran again and the match had no skin"""

    def setUp(self):
        self.state = SharedState()
        self.state.phase = 'FINALIZATION'
        self.state.current_ticker = TICKER_ID
        self.state.loadout_countdown_active = True
        self.state.loadout_t0 = time.monotonic()
        self.state.loadout_left0_ms = 300
        lcu = SimpleNamespace(session={})
        self.ticker = LoadoutTicker(lcu, self.state, hz=100, fallback_ms=0, ticker_id=TICKER_ID)
        self.ticker.skin_name_resolver = MagicMock()
        self.ticker.skin_name_resolver.resolve_injection_name.return_value = 'skin_1001'
        self.ticker.injection_trigger = MagicMock()
        log = patch.object(loadout_ticker, 'log')
        self.log = log.start()
        self.addCleanup(log.stop)

    def test_a_failed_trigger_is_retried_on_the_next_tick(self):
        def trigger(*_):
            if self.ticker.injection_trigger.trigger_injection.call_count == 1:
                raise RuntimeError('session not ready')
            self.state.last_hover_written = True

        self.ticker.injection_trigger.trigger_injection.side_effect = trigger
        self.ticker.run()

        self.assertEqual(self.ticker.injection_trigger.trigger_injection.call_count, 2)
        self.assertFalse(self.state.loadout_countdown_active)

    def test_a_repeated_error_is_logged_once(self):
        self.ticker.injection_trigger.trigger_injection.side_effect = RuntimeError('broken')
        self.ticker.run()

        self.assertGreater(self.ticker.injection_trigger.trigger_injection.call_count, 1)
        self.assertEqual(self.log.exception.call_count, 1)

    def test_the_countdown_is_released_when_the_ticker_dies(self):
        with patch.object(self.ticker, '_countdown', side_effect=RuntimeError('boom')):
            self.ticker.run()

        self.assertFalse(self.state.loadout_countdown_active)
        self.log.exception.assert_called_once()


if __name__ == '__main__':
    unittest.main()
