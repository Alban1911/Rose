import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from threads.websocket import websocket_connection
from threads.websocket.websocket_connection import WebSocketConnection


class RetryLoggingTests(unittest.TestCase):
    """With the client closed Rose retried every 15s and logged a WARNING each
    time, thousands per day (#261)"""

    def setUp(self):
        self.connection = WebSocketConnection.__new__(WebSocketConnection)
        self.connection.state = SimpleNamespace(stop=False)
        self.connection._stop_event = threading.Event()
        self.connection._retry_attempt = 0
        self.connection._warned_retry_reason = None
        wait = patch.object(self.connection._stop_event, 'wait', return_value=False)
        wait.start()
        self.addCleanup(wait.stop)
        log = patch.object(websocket_connection, 'log')
        self.log = log.start()
        self.addCleanup(log.stop)

    def test_a_repeated_reason_is_warned_once(self):
        for _ in range(5):
            self.connection._wait_before_retry('LCU lockfile is not ready')

        self.assertEqual(self.log.warning.call_count, 1)
        self.assertEqual(self.log.debug.call_count, 4)

    def test_a_new_reason_is_warned_again(self):
        self.connection._wait_before_retry('LCU lockfile is not ready')
        self.connection._wait_before_retry('LCU WebSocket unavailable on port 5000')

        self.assertEqual(self.log.warning.call_count, 2)


if __name__ == '__main__':
    unittest.main()
