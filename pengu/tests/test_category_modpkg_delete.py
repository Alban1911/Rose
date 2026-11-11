import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from injection.mods import manifest as saved_manifest
from injection.mods.storage import ModStorageService
from pengu.communication.message_handler import MessageHandler


class PendingModpkgDeleteTests(unittest.TestCase):
    """A .modpkg LTK Manager has not taken yet keeps its extension in its identity."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "mods"
        self.storage = ModStorageService(root)
        for category in ("maps", "vfx"):
            archive = root / category / "Rift.modpkg"
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(b"not checked by the listing")
            saved_manifest.add_saved_mod(root, archive, facts=None)

        self.handler = MessageHandler.__new__(MessageHandler)
        self.handler.mod_storage = self.storage
        self.sent = []
        self.handler._send_response = lambda message: self.sent.append(json.loads(message))
        self.handler.shared_state = SimpleNamespace(
            selected_map_mod={"mod_name": "Rift", "relative_path": "maps/Rift.modpkg"},
            selected_other_mods=[{"mod_name": "Rift", "relative_path": "vfx/Rift.modpkg"}],
        )
        self.historic = {"map": "maps/Rift.modpkg", "vfx": ["vfx/Rift.modpkg"]}
        for name, kwargs in (
            ("get_historic_mod", {"side_effect": self.historic.get}),
            ("clear_historic_mod", {"side_effect": lambda k: self.historic.pop(k, None)}),
            ("write_historic_mod", {"side_effect": self.historic.__setitem__}),
        ):
            patcher = mock.patch(f"utils.core.mod_historic.{name}", **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_single_delete_clears_selection_and_historic(self):
        self.handler._handle_delete_category_mod({"category": "maps", "modName": "Rift"})
        self.handler._handle_delete_category_mod({"category": "vfx", "modName": "Rift"})

        self.assertTrue(all(r["success"] for r in self.sent))
        self.assertIsNone(self.handler.shared_state.selected_map_mod)
        self.assertEqual(self.handler.shared_state.selected_other_mods, [])
        self.assertEqual(self.historic, {})

    def test_bulk_delete_clears_selection_and_historic(self):
        self.handler._handle_delete_category_mods({"category": "maps", "mods": [{"modName": "Rift"}]})
        self.handler._handle_delete_category_mods({"category": "vfx", "mods": [{"modName": "Rift"}]})

        self.assertTrue(all(r["success"] for r in self.sent))
        self.assertIsNone(self.handler.shared_state.selected_map_mod)
        self.assertEqual(self.handler.shared_state.selected_other_mods, [])
        self.assertEqual(self.historic, {})


if __name__ == "__main__":
    unittest.main()
