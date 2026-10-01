import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pengu.communication import message_handler
from pengu.communication.message_handler import MessageHandler


class BulkImportTests(unittest.TestCase):
    """Several mod files can be picked at once; each is imported on its own"""

    def setUp(self):
        self.handler = MessageHandler.__new__(MessageHandler)
        self.handler.mod_storage = MagicMock()
        self.handler.mod_storage.MOD_CATEGORIES = ("skins", "maps", "fonts")
        self.handler.mod_storage.mods_root = Path("C:/mods")
        self.handler.mod_storage.get_champion_dir.return_value = Path("C:/mods/skins/157000")
        self.sent = []
        self.handler._send_response = lambda message: self.sent.append(json.loads(message))

    def _pick(self, *names):
        return patch.object(message_handler, "_choose_mod_files", return_value=[Path(n) for n in names])

    def test_every_picked_skin_mod_is_imported_for_the_selected_skins(self):
        def import_mod_file(champion_id, path, skin_ids):
            if path.name == "broken.zip":
                raise ValueError("Not a valid mod archive")
            return Path("C:/mods/skins/157000") / path.stem, Path("manifest.json"), path.stem

        self.handler.mod_storage.import_mod_file.side_effect = import_mod_file
        with self._pick("a.fantome", "broken.zip", "c.modpkg"):
            self.handler._handle_add_custom_mods_skin_selected(
                {"action": "create", "championId": 157, "skinIds": [157001, 157002]}
            )

        calls = self.handler.mod_storage.import_mod_file.call_args_list
        self.assertEqual([c.args[1].name for c in calls], ["a.fantome", "broken.zip", "c.modpkg"])
        self.assertTrue(all(c.args[0] == 157 and c.args[2] == [157001, 157002] for c in calls))

        (response,) = self.sent
        self.assertEqual(response["type"], "folder-opened-response")
        self.assertTrue(response["success"])
        self.assertEqual(response["importedCount"], 2)
        self.assertEqual(response["failedCount"], 1)
        self.assertEqual(response["modName"], "c")
        self.assertEqual(response["skinIds"], [157001, 157002])
        self.assertEqual(
            response["results"][1],
            {"file": "broken.zip", "success": False, "error": "Not a valid mod archive"},
        )

    def test_every_picked_category_mod_is_imported(self):
        self.handler.mod_storage.import_category_mod_file.side_effect = (
            lambda category, path: (Path("C:/mods") / category / path.stem, path.stem)
        )
        with self._pick("map1.fantome", "map2.fantome"):
            self.handler._handle_add_custom_mods_category_selected({"category": "maps"})

        (response,) = self.sent
        self.assertTrue(response["success"])
        self.assertEqual(response["category"], "maps")
        self.assertEqual([r["modName"] for r in response["results"]], ["map1", "map2"])
        self.assertEqual(response["failedCount"], 0)

    def test_all_failing_reports_an_error(self):
        self.handler.mod_storage.import_category_mod_file.side_effect = ValueError("Unsupported mod archive")
        with self._pick("x.rar"):
            self.handler._handle_add_custom_mods_category_selected({"category": "fonts"})

        (response,) = self.sent
        self.assertFalse(response["success"])
        self.assertEqual(response["error"], "Unsupported mod archive")

    def test_cancelling_the_picker(self):
        with self._pick():
            self.handler._handle_add_custom_mods_skin_selected(
                {"action": "create", "championId": 157, "skinIds": [157001]}
            )
        self.assertEqual(self.sent, [{
            "type": "folder-opened-response",
            "success": False,
            "cancelled": True,
            "error": "Mod selection cancelled",
        }])
        self.handler.mod_storage.import_mod_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
