import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pengu.communication.message_handler import MessageHandler


class ModImportLoadingTests(unittest.TestCase):
    """The Settings panel shows a loading animation from mod-import-started
    until the folder-opened-response that ends the import"""

    def setUp(self):
        self.handler = MessageHandler.__new__(MessageHandler)
        self.sent = []
        self.handler._send_response = lambda message: self.sent.append(json.loads(message))
        storage = MagicMock()
        storage.MOD_CATEGORIES = ("maps",)
        storage.import_category_mod_file.side_effect = self._import(("maps-folder", "Summoner's Rift"))
        storage.import_mod_file.side_effect = self._import(("skin-folder", "manifest.json", "Arcane Ezreal"))
        self.handler.mod_storage = storage

    def _import(self, result):
        def run(*args):
            self.sent.append({"type": "import"})
            return result
        return run

    def _types(self):
        return [message["type"] for message in self.sent]

    def _pick(self, path):
        return patch("pengu.communication.message_handler._choose_mod_file", return_value=path)

    def test_a_category_import_is_announced_before_it_runs(self):
        with self._pick(Path("C:/Mods/Rift.fantome")):
            self.handler._handle_add_custom_mods_category_selected({"category": "maps"})
        self.assertEqual(self._types(), ["mod-import-started", "import", "folder-opened-response"])
        self.assertEqual(self.sent[0]["fileName"], "Rift.fantome")

    def test_a_skin_import_is_announced_before_it_runs(self):
        with self._pick(Path("C:/Mods/Ezreal.modpkg")):
            self.handler._handle_add_custom_mods_skin_selected(
                {"action": "create", "championId": 81, "skinIds": [81020]}
            )
        self.assertEqual(self._types(), ["mod-import-started", "import", "folder-opened-response"])
        self.assertEqual(self.sent[0]["fileName"], "Ezreal.modpkg")

    def test_a_failed_import_still_ends_the_loading(self):
        self.handler.mod_storage.import_category_mod_file.side_effect = OSError("disk full")
        with self._pick(Path("C:/Mods/Rift.fantome")), self.assertLogs(level="ERROR"):
            self.handler._handle_add_custom_mods_category_selected({"category": "maps"})
        self.assertEqual(self._types(), ["mod-import-started", "folder-opened-response"])
        self.assertFalse(self.sent[-1]["success"])

    def test_nothing_loads_when_the_picker_is_cancelled(self):
        with self._pick(None):
            self.handler._handle_add_custom_mods_category_selected({"category": "maps"})
        self.assertEqual(self._types(), ["folder-opened-response"])
        self.assertTrue(self.sent[0]["cancelled"])


if __name__ == "__main__":
    unittest.main()
