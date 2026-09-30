import json
import unittest
from unittest.mock import MagicMock, patch

from state import SharedState
from threads.websocket import websocket_event_handler
from threads.websocket.websocket_event_handler import WebSocketEventHandler

EVENT = json.dumps([8, 'OnJsonApiEvent', {'uri': '/lol-gameflow/v1/gameflow-phase', 'data': 'ChampSelect'}])


class EventErrorTests(unittest.TestCase):
    """Every LCU event is dispatched from one handler that swallowed any error,
    so a failed phase change or champ select update left no trace"""

    def setUp(self):
        self.handler = WebSocketEventHandler(MagicMock(), SharedState())
        log = patch.object(websocket_event_handler, 'log')
        self.log = log.start()
        self.addCleanup(log.stop)

    def test_a_failing_event_is_logged_once(self):
        with patch.object(self.handler, 'handle_api_event', side_effect=KeyError('eventType')):
            for _ in range(20):
                self.handler.handle_message(None, EVENT)

        self.log.exception.assert_called_once()

    def test_a_different_error_is_logged_again(self):
        errors = [KeyError('eventType'), TypeError('bad data')]
        with patch.object(self.handler, 'handle_api_event', side_effect=errors):
            self.handler.handle_message(None, EVENT)
            self.handler.handle_message(None, EVENT)

        self.assertEqual(self.log.exception.call_count, 2)


if __name__ == '__main__':
    unittest.main()
