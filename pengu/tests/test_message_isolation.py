import json
import threading
import unittest
from unittest.mock import patch

from pengu.communication.message_handler import MessageHandler


class MessageIsolationTests(unittest.TestCase):
    """An error in one message used to escape to the WebSocket server, which
    closed the bridge: the plugins lost Rose until they reconnected"""

    def setUp(self):
        self.handler = MessageHandler.__new__(MessageHandler)
        self.handler._background_queue = None
        self.handler._background_lock = threading.Lock()

    def test_a_failing_handler_does_not_raise_to_the_connection(self):
        with patch.object(MessageHandler, "_handle_request_skin_mods", side_effect=KeyError("skinId")), \
                self.assertLogs(level="ERROR"):
            self.handler.handle_message(json.dumps({"type": "request-skin-mods"}))

    def test_the_next_message_is_still_handled(self):
        handled = []
        with patch.object(MessageHandler, "_handle_request_skin_mods",
                          side_effect=[KeyError("skinId"), None]) as request_skin_mods, \
                self.assertLogs(level="ERROR"):
            self.handler.handle_message(json.dumps({"type": "request-skin-mods"}))
            self.handler.handle_message(json.dumps({"type": "request-skin-mods", "skinId": 1}))
            handled.append(request_skin_mods.call_count)
        self.assertEqual(handled, [2])

    def test_json_that_is_not_an_object_is_ignored(self):
        for message in ("[1, 2]", "42", '"text"', "null"):
            with self.subTest(message=message), self.assertLogs(level="WARNING"):
                self.handler.handle_message(message)


if __name__ == "__main__":
    unittest.main()
