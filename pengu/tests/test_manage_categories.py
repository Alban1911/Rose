import json
import threading
import unittest
from unittest.mock import MagicMock

from pengu.communication.message_handler import MessageHandler


class ManageCategoriesTests(unittest.TestCase):
    """The Manage Mods menu asks Rose which categories have a mod added"""

    def test_answers_with_the_categories_that_have_mods(self):
        handler = MessageHandler.__new__(MessageHandler)
        handler._background_queue = None
        handler._background_lock = threading.Lock()
        handler.mod_storage = MagicMock()
        handler.mod_storage.categories_with_mods.return_value = ['skins', 'maps']
        answered = threading.Event()
        sent = []

        def send(message):
            sent.append(json.loads(message))
            answered.set()

        handler._send_response = send
        handler.handle_message(json.dumps({'type': 'request-manage-categories'}))

        self.assertTrue(answered.wait(5))
        self.assertEqual(sent, [{'type': 'manage-categories-response', 'categories': ['skins', 'maps']}])


if __name__ == '__main__':
    unittest.main()
