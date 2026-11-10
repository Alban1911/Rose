import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from threads.websocket import websocket_connection
from threads.websocket.websocket_connection import WebSocketConnection


class ConnectionCase(unittest.TestCase):
    """A connection whose waits return at once and whose log is watched"""

    def setUp(self):
        self.connection = WebSocketConnection.__new__(WebSocketConnection)
        self.connection.state = SimpleNamespace(stop=False)
        self.connection._stop_event = threading.Event()
        self.connection._retry_attempt = 0
        self.connection._warned_retry_reason = None
        wait = patch.object(self.connection._stop_event, 'wait', return_value=False)
        self.wait = wait.start()
        self.addCleanup(wait.stop)
        log = patch.object(websocket_connection, 'log')
        self.log = log.start()
        self.addCleanup(log.stop)


class RetryLoggingTests(ConnectionCase):
    """With the client closed Rose retried every 15s and logged a WARNING each
    time, thousands per day (#261)"""

    def test_a_repeated_reason_is_warned_once(self):
        for _ in range(5):
            self.connection._wait_before_retry('LCU WebSocket unavailable on port 5000')

        self.assertEqual(self.log.warning.call_count, 1)
        self.assertEqual(self.log.debug.call_count, 4)

    def test_a_new_reason_is_warned_again(self):
        self.connection._wait_before_retry('LCU lockfile is not ready')
        self.connection._wait_before_retry('LCU WebSocket unavailable on port 5000')

        self.assertEqual(self.log.warning.call_count, 2)


class ClientStartTests(ConnectionCase):
    """A client started after Rose was noticed up to 15s late, then its
    WebSocket, not open yet, was retried 15s later again: Rose connected 20s
    after the client was up"""

    def waited(self):
        return [call.args[0] for call in self.wait.call_args_list]

    def test_a_closed_client_is_looked_for_every_second(self):
        for _ in range(20):
            self.connection._wait_for_client()

        self.assertEqual(self.waited(), [websocket_connection.WS_RECONNECT_DELAY] * 20)

    def test_a_closed_client_is_logged_once(self):
        for _ in range(20):
            self.connection._wait_for_client()

        self.assertEqual(self.log.warning.call_count, 1)
        self.log.debug.assert_not_called()

    def test_a_starting_client_is_retried_without_backoff(self):
        for _ in range(20):
            self.connection._wait_for_client()
        self.wait.reset_mock()

        for _ in range(websocket_connection.WS_RECONNECT_FAST_ATTEMPTS):
            self.connection._wait_before_retry('LCU WebSocket unavailable on port 5000')

        shortest = websocket_connection.WS_RECONNECT_DELAY
        self.assertLessEqual(max(self.waited()), shortest * (1 + websocket_connection.WS_RECONNECT_JITTER))

    def test_a_client_that_never_answers_is_retried_less_often(self):
        for _ in range(websocket_connection.WS_RECONNECT_FAST_ATTEMPTS + 10):
            self.connection._wait_before_retry('LCU WebSocket unavailable on port 5000')

        self.assertEqual(self.waited()[-1], websocket_connection.WS_RECONNECT_MAX_DELAY)


if __name__ == '__main__':
    unittest.main()
