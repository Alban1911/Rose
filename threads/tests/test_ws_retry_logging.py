import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from threads.websocket import websocket_connection
from threads.websocket.websocket_connection import WebSocketConnection
from utils.system import folder_watch


class ConnectionCase(unittest.TestCase):
    """A connection whose waits return at once and whose log is watched"""

    def setUp(self):
        self.connection = WebSocketConnection.__new__(WebSocketConnection)
        self.connection.state = SimpleNamespace(stop=False)
        self.connection._stop_event = threading.Event()
        self.connection._retry_attempt = 0
        self.connection._client_wait_attempt = 0
        self.connection._warned_retry_reason = None
        self.connection._client_watch = Mock()
        self.connection._client_watch.wait.return_value = folder_watch.TIMEOUT
        self.connection.lcu = Mock()
        self.connection.lcu.lockfile_folders.return_value = ["C:/Riot Games/League of Legends"]
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

    def test_a_closed_client_is_waited_for_in_its_folders_not_on_a_timer(self):
        for _ in range(20):
            self.connection._wait_for_client()

        self.assertEqual(self.waited(), [])
        folders, timeout, _ready = self.connection._client_watch.wait.call_args.args
        self.assertEqual(folders, ["C:/Riot Games/League of Legends"])
        self.assertEqual(timeout, websocket_connection.WS_RECONNECT_MAX_DELAY)

    def test_the_lockfile_is_looked_at_again_once_its_folders_are_watched(self):
        self.connection._wait_for_client()
        ready = self.connection._client_watch.wait.call_args.args[2]

        self.connection.lcu.websocket_credentials.return_value = None
        self.assertFalse(ready())
        self.connection.lcu.websocket_credentials.return_value = (5000, "pw")
        self.assertTrue(ready())
        self.connection.lcu.refresh_if_needed.assert_called_with(force=True)

    def test_a_folder_that_keeps_changing_is_looked_at_once_a_second_at_most(self):
        self.connection._client_watch.wait.return_value = folder_watch.CHANGED
        self.connection._wait_for_client()

        (rest,) = self.waited()
        self.assertGreater(rest, 0)
        self.assertLessEqual(rest, websocket_connection.WS_RECONNECT_DELAY)

    def test_without_a_folder_to_watch_the_lockfile_is_looked_for_with_backoff(self):
        self.connection._client_watch.wait.return_value = None
        for _ in range(7):
            self.connection._wait_for_client()

        self.assertEqual(self.waited(), [1.0, 2.0, 4.0, 8.0, 15.0, 15.0, 15.0])

    def test_stopping_ends_the_wait_for_the_client(self):
        self.connection.ws = None
        self.connection.stop()

        self.connection._client_watch.wake.assert_called_once_with()

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



@unittest.skipUnless(os.name == "nt", "Windows change notifications")
class ClientFolderTests(unittest.TestCase):
    """The lockfile a starting client writes ends the wait at once"""

    def test_a_lockfile_written_in_the_watched_folder_ends_the_wait(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name)
        lockfile = folder / "lockfile"
        connection = WebSocketConnection.__new__(WebSocketConnection)
        connection.state = SimpleNamespace(stop=False)
        connection._stop_event = threading.Event()
        connection._retry_attempt = 0
        connection._client_wait_attempt = 0
        connection._warned_retry_reason = None
        connection._client_watch = folder_watch.FolderWatch()
        connection.lcu = Mock()
        connection.lcu.lockfile_folders.return_value = [folder]
        connection.lcu.websocket_credentials.side_effect = lambda: (5000, "pw") if lockfile.exists() else None
        done = {}

        def wait():
            started = time.monotonic()
            done["stopping"] = connection._wait_for_client()
            done["after"] = time.monotonic() - started

        with patch.object(websocket_connection, "log"):
            waiter = threading.Thread(target=wait)
            waiter.start()
            time.sleep(0.3)
            lockfile.write_text("LeagueClient:1:5000:pw:https")
            waiter.join(10)

        self.assertFalse(done["stopping"])
        self.assertLess(done["after"], websocket_connection.WS_RECONNECT_MAX_DELAY / 2)
        self.assertIsNotNone(connection.lcu.websocket_credentials())


if __name__ == '__main__':
    unittest.main()
