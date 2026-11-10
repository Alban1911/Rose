import json
import unittest
from unittest.mock import MagicMock, patch

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
        self.handler.mod_storage.set_category_mod_hidden.return_value = True

        self.handler._handle_hide_category_mod({"category": "others", "modName": "dark-hud", "hidden": True})

        self.handler.mod_storage.set_category_mod_hidden.assert_called_once_with("others", "dark-hud", True)
        self.handler._clear_category_selection_if_matches.assert_called_once_with("others", "dark-hud")
        self.assertEqual(self.sent[-1], {"type": "category-mod-hidden", "success": True, "category": "others",
                                         "modName": "dark-hud", "hidden": True})
        self.assertIn("hide-category-mod", BACKGROUND_MESSAGE_TYPES)

    def test_a_hidden_one_is_not_offered_to_pick(self):
        self.handler.mod_storage.list_mods_for_category.return_value = [
            {"id": "others/dark-hud.fantome", "name": "dark-hud", "mirrored": True, "hidden": True},
            {"id": "others/Glow.fantome", "name": "Glow", "mirrored": True, "hidden": False},
        ]

        with patch("utils.core.mod_historic.get_historic_mod", return_value=None):
            self.handler._handle_request_category_mods({"category": "others"})

        self.assertEqual([mod["name"] for mod in self.sent[-1]["mods"]], ["Glow"])


if __name__ == "__main__":
    unittest.main()
