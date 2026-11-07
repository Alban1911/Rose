import json
import unittest
from unittest.mock import MagicMock

from pengu.communication.message_handler import (
    BACKGROUND_MESSAGE_TYPES,
    MessageHandler,
)


class BulkModDeleteTests(unittest.TestCase):
    def setUp(self):
        self.handler = MessageHandler.__new__(MessageHandler)
        self.sent = []
        self.handler._send_response = lambda message: self.sent.append(json.loads(message))
        self.handler.mod_storage = MagicMock()
        self.handler.shared_state = MagicMock()
        self.handler._clear_active_selection_if_matches = MagicMock()
        self.handler._clear_category_selection_if_matches = MagicMock()

    def test_bulk_champion_delete_continues_after_a_failure(self):
        self.handler.mod_storage.delete_champion_mod.side_effect = [
            True,
            OSError("folder is locked"),
            True,
        ]
        mods = [
            {"modName": "First", "relativePath": "skins/1000/First"},
            {"modName": "Locked", "relativePath": "skins/1000/Locked"},
            {"modName": "Third", "relativePath": "skins/1000/Third"},
        ]

        with self.assertLogs(level="ERROR"):
            self.handler._handle_delete_champion_mods({
                "championId": 1,
                "mods": mods,
            })

        response = self.sent[-1]
        self.assertEqual(response["type"], "champion-mods-bulk-deleted")
        self.assertTrue(response["partial"])
        self.assertEqual(response["deletedCount"], 2)
        self.assertEqual([item["success"] for item in response["results"]], [True, False, True])
        self.assertEqual(self.handler.mod_storage.delete_champion_mod.call_count, 3)
        self.assertEqual(self.handler._clear_active_selection_if_matches.call_count, 2)

    def test_bulk_category_delete_clears_selection_for_each_deleted_mod(self):
        self.handler.mod_storage.delete_category_mod.side_effect = [True, True]
        self.handler._handle_delete_category_mods({
            "category": "maps",
            "mods": [{"modName": "Rift"}, {"modName": "Abyss"}],
        })

        response = self.sent[-1]
        self.assertEqual(response["type"], "category-mods-bulk-deleted")
        self.assertTrue(response["success"])
        self.assertEqual(response["deletedCount"], 2)
        self.assertEqual(self.handler._clear_category_selection_if_matches.call_count, 2)

    def test_bulk_category_delete_continues_and_reports_partial_failure(self):
        self.handler.mod_storage.delete_category_mod.side_effect = [
            OSError("folder is locked"),
            True,
        ]
        with self.assertLogs(level="ERROR"):
            self.handler._handle_delete_category_mods({
                "category": "maps",
                "mods": [{"modName": "Locked"}, {"modName": "Abyss"}],
            })

        response = self.sent[-1]
        self.assertTrue(response["partial"])
        self.assertEqual(response["deletedCount"], 1)
        self.assertEqual([item["success"] for item in response["results"]], [False, True])
        self.assertEqual(self.handler.mod_storage.delete_category_mod.call_count, 2)

    def test_empty_or_invalid_batch_is_rejected(self):
        self.handler._handle_delete_champion_mods({"championId": 1, "mods": []})
        self.assertFalse(self.sent[-1]["success"])
        self.assertEqual(self.sent[-1]["error"], "At least one skin mod is required")
        self.handler.mod_storage.delete_champion_mod.assert_not_called()

    def test_bulk_delete_messages_run_on_the_background_worker(self):
        self.assertIn("delete-champion-mods", BACKGROUND_MESSAGE_TYPES)
        self.assertIn("delete-category-mods", BACKGROUND_MESSAGE_TYPES)

    def test_missing_storage_returns_an_explicit_failure(self):
        self.handler.mod_storage = None
        self.handler._handle_delete_category_mods({
            "category": "maps",
            "mods": [{"modName": "Rift"}],
        })
        self.assertFalse(self.sent[-1]["success"])
        self.assertEqual(self.sent[-1]["error"], "Mod storage is not available")


if __name__ == "__main__":
    unittest.main()
