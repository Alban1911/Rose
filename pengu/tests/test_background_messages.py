import json
import threading
import unittest
from unittest.mock import patch

from pengu.communication.message_handler import MessageHandler


class BackgroundMessageTests(unittest.TestCase):
    """The file picker and mod imports run off the bridge loop, so every plugin
    keeps getting answers while they wait (Manage Mods stayed on "Loading")"""

    def setUp(self):
        self.handler = MessageHandler.__new__(MessageHandler)
        self.handler._background_queue = None
        self.handler._background_lock = threading.Lock()
        self.release = threading.Event()
        self.done = []

    def _send(self, message_type, **payload):
        self.handler.handle_message(json.dumps({"type": message_type, **payload}))

    def test_a_waiting_import_does_not_hold_up_other_messages(self):
        def pick_file(payload):
            self.release.wait(5)  # the user choosing a file
            self.done.append("import")

        with patch.object(MessageHandler, "_handle_add_custom_mods_skin_selected", side_effect=pick_file), \
                patch.object(MessageHandler, "_handle_request_skin_mods",
                             side_effect=lambda payload: self.done.append("skin mods")):
            self._send("add-custom-mods-skin-selected", action="create")
            self._send("request-skin-mods", skinId=11000)
            self.assertEqual(self.done, ["skin mods"])

            self.release.set()
            for _ in range(100):
                if len(self.done) == 2:
                    break
                threading.Event().wait(0.02)
        self.assertEqual(self.done, ["skin mods", "import"])

    def test_background_messages_keep_their_order(self):
        finished = threading.Event()

        def record(name):
            def handle(payload):
                self.done.append(name)
                if name == "champions":
                    finished.set()
            return handle

        with patch.object(MessageHandler, "_handle_add_custom_mods_skin_selected", side_effect=record("import")), \
                patch.object(MessageHandler, "_handle_add_custom_mods_champion_selected", side_effect=record("champions")):
            self._send("add-custom-mods-skin-selected", action="create")
            self._send("add-custom-mods-champion-selected", action="list")
            self.assertTrue(finished.wait(5))
        self.assertEqual(self.done, ["import", "champions"])


if __name__ == "__main__":
    unittest.main()
