import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from injection.mods.storage import AddedMod
from pengu.communication.message_handler import MessageHandler

MODS_ROOT = Path("C:/Rose/mods")
RIFT = AddedMod(MODS_ROOT / "maps" / "Summoner's Rift.fantome", "Summoner's Rift")


class ModImportLoadingTests(unittest.TestCase):
    """The Settings panel shows a loading animation from mod-import-started
    until the folder-opened-response that ends the import"""

    def setUp(self):
        self.handler = MessageHandler.__new__(MessageHandler)
        self.sent = []
        self.handler._send_response = lambda message: self.sent.append(json.loads(message))
        storage = MagicMock()
        storage.MOD_CATEGORIES = ("maps",)
        storage.mods_root = MODS_ROOT
        storage.import_category_mod_file.side_effect = self._import(RIFT)
        storage.import_mod_file.side_effect = self._import(
            AddedMod(MODS_ROOT / "skins" / "81000" / "Arcane Ezreal.fantome", "Arcane Ezreal"))
        self.handler.mod_storage = storage

    def _import(self, result):
        def run(*args, **kwargs):
            self.sent.append({"type": "import"})
            return result
        return run

    def _types(self):
        return [message["type"] for message in self.sent]

    def _pick(self, *paths):
        selected = [] if paths == (None,) else list(paths)
        return patch("pengu.communication.message_handler._choose_mod_files", return_value=selected)

    def test_a_category_import_is_announced_before_it_runs(self):
        with self._pick(Path("C:/Mods/Rift.fantome")):
            self.handler._handle_add_custom_mods_category_selected({"category": "maps"})
        self.assertEqual(self._types(), ["mod-import-started", "import", "folder-opened-response"])
        self.assertEqual(self.sent[0]["fileName"], "Rift.fantome")
        self.assertEqual(self.sent[0]["fileCount"], 1)
        self.assertTrue(self.sent[-1]["success"])

    def test_a_skin_import_is_announced_before_it_runs(self):
        with self._pick(Path("C:/Mods/Ezreal.modpkg")):
            self.handler._handle_add_custom_mods_skin_selected(
                {"action": "create", "championId": 81, "skinIds": [81020]}
            )
        self.assertEqual(self._types(), ["mod-import-started", "import", "folder-opened-response"])
        self.assertEqual(self.sent[0]["fileName"], "Ezreal.modpkg")
        self.assertEqual(self.sent[0]["fileCount"], 1)

    def test_multiple_category_mods_are_imported_and_reported(self):
        files = [Path("C:/Mods/Rift.fantome"), Path("C:/Mods/HowlingAbyss.zip")]
        with self._pick(*files):
            self.handler._handle_add_custom_mods_category_selected({"category": "maps"})
        self.assertEqual(self.handler.mod_storage.import_category_mod_file.call_count, 2)
        self.assertEqual(self.sent[0]["fileCount"], 2)
        self.assertNotIn("fileName", self.sent[0])
        self.assertTrue(self.sent[-1]["success"])
        self.assertEqual(len(self.sent[-1]["imported"]), 2)
        self.assertEqual(self.sent[-1]["imported"][0]["relativePath"], "maps/Summoner's Rift.fantome")

    def test_bulk_import_reports_partial_failures_and_continues(self):
        self.handler.mod_storage.import_category_mod_file.side_effect = [
            RIFT,
            OSError("archive is invalid"),
        ]
        files = [Path("C:/Mods/Rift.fantome"), Path("C:/Mods/Invalid.zip")]
        with self._pick(*files), self.assertLogs(level="ERROR"):
            self.handler._handle_add_custom_mods_category_selected({"category": "maps"})
        self.assertTrue(self.sent[-1]["partial"])
        self.assertEqual(len(self.sent[-1]["imported"]), 1)
        self.assertEqual(self.sent[-1]["importErrors"][0]["fileName"], "Invalid.zip")

    def test_multiple_skin_mods_use_the_selected_skin_targets(self):
        files = [Path("C:/Mods/Ezreal.fantome"), Path("C:/Mods/Arcane.modpkg")]
        with self._pick(*files):
            self.handler._handle_add_custom_mods_skin_selected(
                {"action": "create", "championId": 81, "skinIds": [81020]}
            )
        self.assertEqual(self.handler.mod_storage.import_mod_file.call_count, 2)
        self.assertEqual(self.handler.mod_storage.import_mod_file.call_args.args[2], [81020])
        self.assertTrue(self.sent[-1]["success"])
        self.assertEqual(len(self.sent[-1]["imported"]), 2)

    def test_a_failed_import_still_ends_the_loading(self):
        self.handler.mod_storage.import_category_mod_file.side_effect = OSError("disk full")
        with self._pick(Path("C:/Mods/Rift.fantome")), self.assertLogs(level="ERROR"):
            self.handler._handle_add_custom_mods_category_selected({"category": "maps"})
        self.assertEqual(self._types(), ["mod-import-started", "folder-opened-response"])
        self.assertFalse(self.sent[-1]["success"])
        self.assertEqual(self.sent[-1]["importErrors"][0]["error"], "disk full")
        self.assertEqual(self.sent[-1]["error"], "disk full")

    def test_multiple_failed_imports_keep_per_file_errors_and_generic_summary(self):
        self.handler.mod_storage.import_category_mod_file.side_effect = [
            OSError("disk full"),
            ValueError("archive is invalid"),
        ]
        files = [Path("C:/Mods/Rift.fantome"), Path("C:/Mods/Bad.zip")]
        with self._pick(*files), self.assertLogs(level="ERROR"):
            self.handler._handle_add_custom_mods_category_selected({"category": "maps"})

        self.assertEqual(self.sent[-1]["error"], "Failed to import all selected mods")
        self.assertEqual(
            self.sent[-1]["importErrors"],
            [
                {"fileName": "Rift.fantome", "error": "disk full"},
                {"fileName": "Bad.zip", "error": "archive is invalid"},
            ],
        )

    def test_nothing_loads_when_the_picker_is_cancelled(self):
        with self._pick(None):
            self.handler._handle_add_custom_mods_category_selected({"category": "maps"})
        self.assertEqual(self._types(), ["folder-opened-response"])
        self.assertTrue(self.sent[0]["cancelled"])


if __name__ == "__main__":
    unittest.main()
