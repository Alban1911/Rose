"""Adding mods moves them into LTK Manager's library, which checks them,
outside champion select and games; a mod LTK Manager will turn off in game is
not added."""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from injection.mods.manifest import ltk_removals
from injection.mods.storage import ModStorageService
from pengu.communication import message_handler

SKINHACK = {"rule": "bin/skinhack", "title": "Skinhack",
            "description": "A base skin that uses the mesh or the name of another skin of its champion"}
LTK_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"


class ModCheckOnImportTests(unittest.TestCase):
    """A real mods folder holds the added mod; LTK Manager's library is faked
    at LtkLibrary.check_mod"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        self.storage = ModStorageService(root / "mods")
        source = root / "gojo-ezreal-v1.0.0.fantome"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("META/info.json", '{"Name": "Gojo Ezreal"}')
            archive.writestr("WAD/Ezreal.wad.client", b"skin")
        self.stored, _manifest, name = self.storage.import_mod_file(81, source, [81020])
        self.relative_path = self.stored.relative_to(self.storage.mods_root).as_posix()
        self.imported = [{"fileName": source.name, "path": str(self.stored), "relativePath": self.relative_path,
                          "modName": name}]
        library_class = patch.object(message_handler, "LtkLibrary")
        self.library = library_class.start().return_value
        self.addCleanup(library_class.stop)

    def handler(self, phase="Lobby", injecting=False):
        manager = SimpleNamespace(injector=SimpleNamespace(overlay_manager=MagicMock()),
                                  _injection_in_progress=injecting)
        instance = object.__new__(message_handler.MessageHandler)
        instance.injection_manager = manager
        instance.mod_storage = self.storage
        instance.shared_state = SimpleNamespace(phase=phase)
        instance.sent = []
        instance._send_response = lambda message: instance.sent.append(json.loads(message))
        return instance

    def ltk_keeps_it(self, verdict, stamp=(10, 20)):
        """LTK Manager keeps the mod: the check records its entry, then answers"""
        def check(mod, display_name, on_kept):
            self.assertTrue(on_kept(LTK_ID, stamp=list(stamp) if stamp else None))
            self.assertTrue(Path(mod).exists())  # still Rose's while it is recorded
            return dict(verdict, ltkId=LTK_ID)
        self.library.check_mod.side_effect = check

    def saved(self):
        return self.storage.saved_mod(self.relative_path)

    def test_a_kept_mod_names_its_entry_and_rose_deletes_its_copy(self):
        verdict = {"health": "healthy", "repaired": 0, "problems": []}
        self.ltk_keeps_it(verdict)
        instance = self.handler()

        kept = instance._check_imported_mods(self.imported, [], MagicMock())

        self.assertEqual(kept[0]["health"], dict(verdict, ltkId=LTK_ID))
        mod = self.saved()
        self.assertEqual((mod.ltk_id, mod.stored, mod.pending), (LTK_ID, None, False))
        self.assertEqual(mod.metadata["ltkStamp"], [10, 20])
        self.assertIsNotNone(mod.facts)  # read at import, kept
        self.assertFalse(self.stored.exists())
        self.assertEqual(instance.sent, [{"type": "mod-import-checking", "fileCount": 1}])

    def test_a_mod_ltk_manager_repaired_has_no_stamp(self):
        self.ltk_keeps_it({"health": "repairable", "repaired": 4300, "problems": []}, stamp=None)

        kept = self.handler()._check_imported_mods(self.imported, [], MagicMock())

        self.assertEqual(kept[0]["health"]["repaired"], 4300)
        self.assertNotIn("ltkStamp", self.saved().metadata)  # the next sync reads LTK Manager's copy
        self.assertFalse(self.stored.exists())

    def test_a_check_that_did_not_run_leaves_the_mod_pending(self):
        self.library.check_mod.return_value = None

        kept = self.handler()._check_imported_mods(self.imported, [], MagicMock())

        self.assertNotIn("health", kept[0])
        self.assertTrue(self.saved().pending)
        self.assertTrue(self.stored.exists())

    def test_a_mod_ltk_manager_did_not_keep_stays_pending(self):
        self.library.check_mod.return_value = {"health": "healthy", "repaired": 0, "problems": []}

        kept = self.handler()._check_imported_mods(self.imported, [], MagicMock())

        self.assertEqual(kept[0]["health"]["health"], "healthy")
        self.assertTrue(self.saved().pending)

    def test_a_skinhack_is_removed_and_reported_as_a_failed_import(self):
        """The Ezreal custom skin LTK Manager turned off in game"""
        self.library.check_mod.return_value = {"health": "repairable", "repaired": 3224, "problems": [SKINHACK]}
        errors = []

        kept = self.handler()._check_imported_mods(
            self.imported, errors, lambda item: self.storage.delete_champion_mod(81, mod_name=item["modName"]))

        self.assertEqual(kept, [])
        self.assertIsNone(self.saved())
        self.assertFalse(self.stored.exists())
        self.assertEqual(ltk_removals(self.storage.mods_root), [])  # nothing of it was kept in LTK Manager
        self.assertEqual(errors[0]["code"], "ltk_skinhack")
        self.assertEqual(errors[0]["fileName"], "gojo-ezreal-v1.0.0.fantome")
        self.assertIn("skinhack", errors[0]["error"])

    def test_another_problem_ltk_manager_cannot_repair_is_reported_with_its_reason(self):
        problem = {"rule": "audio/bank-id", "title": "Bank", "description": "An audio bank the game will not load"}
        self.library.check_mod.return_value = {"health": "unrepairable", "repaired": 0, "problems": [problem]}
        errors = []

        self.handler()._check_imported_mods(self.imported, errors, MagicMock())

        self.assertEqual((errors[0]["code"], errors[0]["reason"]), ("ltk_rejected", "An audio bank the game will not load"))

    def test_a_rejected_mod_that_cannot_be_removed_stays_with_the_verdict(self):
        verdict = {"health": "unrepairable", "repaired": 0, "problems": [SKINHACK]}
        self.library.check_mod.return_value = verdict
        errors = []

        kept = self.handler()._check_imported_mods(self.imported, errors, MagicMock(side_effect=OSError("in use")))

        self.assertEqual(kept[0]["health"], verdict)
        self.assertEqual(errors, [])

    def test_nothing_is_checked_in_champion_select_or_while_injecting(self):
        for phase, injecting in (("ChampSelect", False), ("InProgress", False), ("Lobby", True)):
            instance = self.handler(phase, injecting)

            kept = instance._check_imported_mods(self.imported, [], MagicMock())

            self.library.check_mod.assert_not_called()
            self.assertEqual(len(kept), 1)
            self.assertEqual(instance.sent, [])
        self.assertTrue(self.saved().pending)


if __name__ == "__main__":
    unittest.main()
