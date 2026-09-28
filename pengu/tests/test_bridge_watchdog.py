import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

from websockets.sync.client import connect

from pengu.core import websocket_server
from pengu.core.websocket_server import WebSocketServer


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def stuck_handler():
    time.sleep(1.5)


class BridgeWatchdogTests(unittest.TestCase):
    def setUp(self):
        limits = patch.object(websocket_server, 'BLOCKED_LOOP_WARNING_S', 0.5)
        limits.start()
        self.addCleanup(limits.stop)

        self.messages = []
        self.server = WebSocketServer(port=_free_port(), message_handler=self.messages.append)
        self.server.watchdog_interval_s = 0.1
        thread = threading.Thread(target=self.server.run, daemon=True)
        thread.start()
        self.assertTrue(self.server.ready_event.wait(5))

        def stop():
            self.server.stop()
            thread.join(timeout=5)

        self.addCleanup(stop)

    @staticmethod
    def _wait_for(condition, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not condition():
            time.sleep(0.05)
        return condition()

    def test_logs_where_the_loop_is_stuck(self):
        with self.assertLogs(websocket_server.log, level='WARNING') as logs:
            self.server.loop.call_soon_threadsafe(stuck_handler)
            self.assertTrue(self._wait_for(lambda: any('resumed' in line for line in logs.output)))
        blocked = [line for line in logs.output if 'Stuck at' in line]
        self.assertEqual(len(blocked), 1)
        self.assertIn('stuck_handler', blocked[0])

    def test_quiet_while_the_loop_is_free(self):
        with self.assertNoLogs(websocket_server.log, level='WARNING'):
            time.sleep(1.5)

    def test_names_the_message_type_but_never_its_content(self):
        message = json.dumps({'type': 'party-add-peer', 'token': 'ROSE:secret'})
        self.assertEqual(WebSocketServer._message_type(message), 'party-add-peer')
        self.assertEqual(WebSocketServer._message_type('not json'), 'non-JSON')
        self.assertIsNone(WebSocketServer._message_type(None))

    def test_logs_plugin_disconnects(self):
        with self.assertLogs(websocket_server.log, level='INFO') as logs:
            with connect(f'ws://127.0.0.1:{self.server.port}') as client:
                client.send('{"type": "ping"}')
                self.assertTrue(self._wait_for(lambda: self.messages))
            self.assertTrue(self._wait_for(lambda: any('Client disconnected' in line for line in logs.output)))
        disconnect = next(line for line in logs.output if 'Client disconnected' in line)
        self.assertIn('code 1000', disconnect)


if __name__ == '__main__':
    unittest.main()
