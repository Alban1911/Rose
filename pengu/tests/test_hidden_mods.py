import json
import unittest
from unittest.mock import MagicMock, call, patch

from pengu.communication.message_handler import BACKGROUND_MESSAGE_TYPES, MessageHandler


class HiddenModTests(unittest.TestCase):
    """A mod the user added in LTK Manager and hid in Rose is no longer
    offered to pick for a game"""

    def setUp(self):
        self.handler = MessageHandler.__new__(MessageHandler)
        self.sent = []
        self.handler._send_response = lambda message: self.sent.append(json.loads(message))
        self.handler.mod_storage = MagicMock(MOD_CATEGORIES=("maps", "others"))
        self.handler._clear_category_selection_if_matches = MagicMock()

    def test_hiding_one_unpicks_it(self):
        with patch("pengu.communication.message_handler.set_hidden", return_value=True) as hide:
            self.handler._handle_hide_category_mod({"category": "others", "modName": "dark-hud", "hidden": True})

        hide.assert_called_once_with(self.handler.mod_storage.mods_root, "others/dark-hud", True)
        self.handler._clear_category_selection_if_matches.assert_called_once_with("others", "dark-hud")
        self.assertEqual(self.sent[-1], {"type": "category-mod-hidden", "success": True, "category": "others",
                                         "modName": "dark-hud", "hidden": True})
        self.assertIn("hide-category-mod", BACKGROUND_MESSAGE_TYPES)

    def test_mod_management_alone_asks_for_the_hidden_ones(self):
        self.handler.mod_storage.list_mods_for_category.return_value = []

        self.handler._handle_request_manage_category_mods({"category": "others"})
        with patch("utils.core.mod_historic.get_historic_mod", return_value=None):
            self.handler._handle_request_category_mods({"category": "others"})

        self.assertEqual(self.handler.mod_storage.list_mods_for_category.call_args_list,
                         [call("others", include_hidden=True), call("others")])


if __name__ == "__main__":
    unittest.main()
