import unittest
from unittest.mock import MagicMock

from state import SharedState
from threads.handlers.injection_trigger import InjectionTrigger
from threads.websocket.websocket_connection import WebSocketConnection


class RefusalWarningTests(unittest.TestCase):
    """The ticker retries every tick inside the threshold window, so a refused
    injection repeated its WARNING hundreds of times per game"""

    def setUp(self):
        self.state = SharedState()
        self.state.locked_champ_id = 60055
        self.trigger = InjectionTrigger(MagicMock(), self.state)

    def test_the_same_refusal_warns_once(self):
        self.state.last_hovered_skin_id = 99009
        with self.assertLogs(level='WARNING') as logs:
            for _ in range(50):
                self.trigger.trigger_injection('skin_99009', ticker_id=1)
        self.assertEqual(len(logs.output), 1)
        self.assertIn('champion mismatch', logs.output[0])

    def test_a_new_selection_warns_again(self):
        with self.assertLogs(level='WARNING') as logs:
            self.state.last_hovered_skin_id = 99009
            self.trigger.trigger_injection('skin_99009', ticker_id=1)
            self.state.last_hovered_skin_id = 98001
            self.trigger.trigger_injection('skin_98001', ticker_id=1)
        self.assertEqual(len(logs.output), 2)

    def test_a_refusal_still_skips_the_injection(self):
        manager = MagicMock()
        self.trigger.injection_manager = manager
        self.state.last_hovered_skin_id = 99009
        with self.assertLogs(level='WARNING'):
            self.trigger.trigger_injection('skin_99009', ticker_id=1)
        manager.inject_skin_immediately.assert_not_called()
        self.assertFalse(self.state.last_hover_written)


class WebSocketErrorTests(unittest.TestCase):
    def test_the_error_is_kept_for_the_retry_warning(self):
        connection = WebSocketConnection(MagicMock(), SharedState())
        error = ConnectionRefusedError(10061, 'refused')
        connection._on_error(None, error)
        self.assertIs(connection._last_error, error)
        self.assertFalse(connection.is_connected)


if __name__ == '__main__':
    unittest.main()
