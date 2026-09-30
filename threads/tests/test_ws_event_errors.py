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

    def test_the_failing_event_uri_is_logged(self):
        with patch.object(self.handler, 'handle_api_event', side_effect=KeyError('eventType')):
            self.handler.handle_message(None, EVENT)

        self.assertIn('/lol-gameflow/v1/gameflow-phase', self.log.exception.call_args[0][0])

    def test_a_message_that_is_not_json_is_not_an_error(self):
        with patch.object(self.handler, 'handle_api_event') as handle:
            self.handler.handle_message(None, 'not json')

        handle.assert_not_called()
        self.log.exception.assert_not_called()
        self.log.warning.assert_not_called()

    def test_routing_is_unchanged(self):
        event = {'uri': '/lol-gameflow/v1/gameflow-phase', 'data': 'Lobby'}
        with patch.object(self.handler, 'handle_api_event') as handle:
            self.handler.handle_message(None, json.dumps([8, 'OnJsonApiEvent', event]))
            self.handler.handle_message(None, json.dumps(event))
            self.handler.handle_message(None, json.dumps([5, 'OnJsonApiEvent', event]))
            self.handler.handle_message(None, json.dumps({'data': {}}))

        self.assertEqual(handle.call_count, 2)
        handle.assert_called_with(event)


if __name__ == '__main__':
    unittest.main()
