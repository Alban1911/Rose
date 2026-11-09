"""Adding mods makes custom skins match the base skin, then has LTK Manager
check them (outside a queue, champion select and games): a category's mod moves into
its library, a custom skin stays Rose's; a mod LTK Manager will turn off in
game is not added."""

import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from injection.baseskin import library as base_skin_library
from injection.mods.manifest import ltk_removals
from injection.mods.mod_facts import compute_mod_facts
from injection.mods.storage import ModStorageService
from pengu.communication import message_handler

SKINHACK = {"rule": "bin/skinhack", "title": "Skinhack",
            "description": "A base skin that uses the mesh or the name of another skin of its champion"}
LTK_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"


def make_archive(path, wad_name, data):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META/info.json", json.dumps({"Name": path.stem}))
        archive.writestr(f"WAD/{wad_name}", data)
    return path


class ModCheckCase(unittest.TestCase):
    """A real mods folder holds the added mods, a voiceover pack and a custom
    skin; LTK Manager's library is faked at LtkLibrary.check_mod"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        self.storage = ModStorageService(root / "mods")
        self.source = make_archive(root / "vo-korean-v2.fantome", "Ahri.ko_KR.wad.client", b"voice")
        self.stored, name, _ = self.storage.import_category_mod_file("voiceover", self.source)
        self.relative_path = self.stored.relative_to(self.storage.mods_root).as_posix()
        self.imported = [{"fileName": self.source.name, "path": str(self.stored), "relativePath": self.relative_path,
                          "modName": name}]
        self.skin_source = make_archive(root / "gojo-ezreal-v1.0.0.fantome", "Ezreal.wad.client", b"skin")
        self.skin, skin_name, _ = self.storage.import_mod_file(81, self.skin_source, [81020])
        self.skin_path = self.skin.relative_to(self.storage.mods_root).as_posix()
        self.skin_imported = [{"fileName": self.skin_source.name, "path": str(self.skin),
                               "relativePath": self.skin_path, "modName": skin_name}]
        library_class = patch.object(message_handler, "LtkLibrary")
        self.library_class = library_class.start()
        self.library = self.library_class.return_value
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

    def saved(self, relative_path=None):
        return self.storage.saved_mod(relative_path or self.relative_path)


class ModCheckOnImportTests(ModCheckCase):
    """A category's mod moves into LTK Manager's library as it is checked"""

    def ltk_keeps_it(self, verdict, stamp=(10, 20)):
        """LTK Manager keeps the mod: the check records its entry, then answers"""
        def check(mod, display_name, on_kept, stop=None):
            self.assertTrue(on_kept(LTK_ID, stamp=list(stamp) if stamp else None))
            self.assertTrue(Path(mod).exists(), "still Rose's while it is recorded")
            return dict(verdict, ltkId=LTK_ID)
        self.library.check_mod.side_effect = check

    def test_a_kept_mod_names_its_entry_and_rose_deletes_its_copy(self):
        verdict = {"health": "healthy", "repaired": 0, "problems": []}
        self.ltk_keeps_it(verdict)
        instance = self.handler()

        kept = instance._check_imported_mods(self.imported, [], MagicMock())

        overlay = instance.injection_manager.injector.overlay_manager
        self.library_class.assert_called_once_with(overlay.host, overlay.game_dir)
        self.assertEqual(kept[0]["health"], dict(verdict, ltkId=LTK_ID))
        mod = self.saved()
        self.assertEqual((mod.ltk_id, mod.rose_copy, mod.pending), (LTK_ID, None, False))
        self.assertEqual(mod.metadata["ltkStamp"], [10, 20])
        self.assertIsNotNone(mod.facts, "read at import, kept")
        self.assertFalse(self.stored.exists())
        self.assertEqual(instance.sent, [{"type": "mod-import-checking", "fileCount": 1}])

    def test_a_mod_ltk_manager_repaired_has_no_stamp(self):
        self.ltk_keeps_it({"health": "repairable", "repaired": 4300, "problems": []}, stamp=None)

        with patch.object(self.storage, "refresh_mod_hashes") as refresh:
            kept = self.handler()._check_imported_mods(self.imported, [], MagicMock())

        self.assertEqual(kept[0]["health"]["repaired"], 4300)
        self.assertNotIn("ltkStamp", self.saved().metadata, "the next sync reads LTK Manager's copy")
        self.assertFalse(self.stored.exists())
        refresh.assert_not_called()

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

    def test_the_same_mod_added_again_is_not_checked_again(self):
        """LTK Manager holds it, its copy still in Rose: importing that copy
        again would put another entry in the place of the one Rose recorded,
        and leave that one in LTK Manager for good"""
        self.storage.attach_ltk_entry(self.relative_path, LTK_ID)
        instance = self.handler()

        with patch.object(message_handler, "_choose_mod_files", return_value=[self.source]):
            instance._handle_add_custom_mods_category_selected({"category": "voiceover"})

        self.library.check_mod.assert_not_called()
        response = instance.sent[-1]
        self.assertTrue(response["success"])
        self.assertEqual(response["imported"][0]["relativePath"], self.relative_path)
        self.assertEqual(self.saved().ltk_id, LTK_ID)

    def test_nothing_is_checked_in_a_queue_champion_select_or_while_injecting(self):
        for phase, injecting in (("Matchmaking", False), ("ReadyCheck", False), ("ChampSelect", False),
                                 ("InProgress", False), ("Lobby", True)):
            instance = self.handler(phase, injecting)

            kept = instance._check_imported_mods(self.imported, [], MagicMock())

            self.library.check_mod.assert_not_called()
            self.assertEqual(len(kept), 1)
            self.assertEqual(instance.sent, [])
        self.assertTrue(self.saved().pending)

    def test_a_check_gives_way_when_the_client_queues(self):
        """A check started in the lobby held LTK Manager into champion select (#486)"""
        instance = self.handler("Lobby")
        stops = []

        def check(mod, display_name, on_kept, stop=None):
            stops.append(stop())
            instance.shared_state.phase = "Matchmaking"
            stops.append(stop())
            return None
        self.library.check_mod.side_effect = check

        kept = instance._check_imported_mods(self.imported, [], MagicMock())

        self.assertEqual(stops, [False, True])
        self.assertEqual(len(kept), 1)
        self.assertTrue(self.saved().pending)

    def test_the_mods_left_once_the_client_queues_are_not_checked(self):
        second = make_archive(Path(self.source).with_name("vo-japanese.fantome"), "Ahri.ja_JP.wad.client", b"voice")
        stored, name, _ = self.storage.import_category_mod_file("voiceover", second)
        self.imported.append({"fileName": second.name, "path": str(stored),
                              "relativePath": stored.relative_to(self.storage.mods_root).as_posix(), "modName": name})
        instance = self.handler("Lobby")

        def check(mod, display_name, on_kept, stop=None):
            instance.shared_state.phase = "ReadyCheck"
            return None
        self.library.check_mod.side_effect = check

        kept = instance._check_imported_mods(self.imported, [], MagicMock())

        self.assertEqual(self.library.check_mod.call_count, 1)
        self.assertEqual(len(kept), 2)


class AddedAsPickedTests(ModCheckCase):
    """A category's mod LTK Manager takes as it is added is stored as it was
    picked: LTK Manager copies it into its library and stores its packed WADs
    as it imports it, once (a 3 GB voiceover pack was unpacked and packed
    again first)"""

    def setUp(self):
        super().setUp()
        self.picked = Path(self.source).with_name("vo-japanese.fantome")
        with zipfile.ZipFile(self.picked, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("META/info.json", json.dumps({"Name": "VO Japanese"}))
            archive.writestr("WAD/Ahri.ja_JP.wad.client", b"japanese voice" * 100)
        self.before = self.picked.read_bytes()

    def add(self, phase="Lobby"):
        instance = self.handler(phase)
        with patch.object(message_handler, "_choose_mod_files", return_value=[self.picked]):
            instance._handle_add_custom_mods_category_selected({"category": "voiceover"})
        response = instance.sent[-1]
        self.assertTrue(response["success"], response)
        return self.saved(response["imported"][0]["relativePath"])

    def test_a_mod_ltk_manager_keeps_is_neither_copied_nor_rewritten_by_rose(self):
        def check(mod, display_name, on_kept, stop=None):
            self.assertTrue(os.path.samefile(mod, self.picked), "LTK Manager imports the file as picked")
            self.assertTrue(on_kept(LTK_ID, stamp=None))
            return {"health": "healthy", "repaired": 0, "problems": [], "ltkId": LTK_ID}
        self.library.check_mod.side_effect = check

        mod = self.add()

        self.assertEqual((mod.ltk_id, mod.rose_copy), (LTK_ID, None))
        self.assertEqual(self.picked.read_bytes(), self.before, "the file the user picked is theirs")

    def test_a_mod_ltk_manager_did_not_take_is_stored_as_rose_keeps_one(self):
        self.library.check_mod.return_value = None

        mod = self.add()

        self.assertTrue(mod.pending)
        self.assertFalse(os.path.samefile(mod.rose_copy, self.picked))
        with zipfile.ZipFile(mod.rose_copy) as archive:
            self.assertEqual(archive.getinfo("WAD/Ahri.ja_JP.wad.client").compress_type, zipfile.ZIP_STORED)
        self.assertEqual(self.picked.read_bytes(), self.before)

    def test_a_mod_added_while_a_game_wants_ltk_manager_is_stored_at_once(self):
        mod = self.add("ChampSelect")

        self.library.check_mod.assert_not_called()
        self.assertTrue(mod.pending)
        self.assertFalse(os.path.samefile(mod.rose_copy, self.picked))
        with zipfile.ZipFile(mod.rose_copy) as archive:
            self.assertEqual(archive.getinfo("WAD/Ahri.ja_JP.wad.client").compress_type, zipfile.ZIP_STORED)


class SkinCheckOnImportTests(ModCheckCase):
    """A custom skin is checked and repaired as it is added, and stays Rose's:
    imported for each game, as Rose's own skins are"""

    def test_a_custom_skin_is_checked_and_never_kept_in_ltk_manager(self):
        verdict = {"health": "repairable", "repaired": 3, "problems": []}
        self.library.check_mod.return_value = verdict

        kept = self.handler()._check_imported_mods(self.skin_imported, [], MagicMock())

        path, _display_name = self.library.check_mod.call_args.args
        self.assertEqual(Path(path), self.skin)
        self.assertEqual(set(self.library.check_mod.call_args.kwargs), {"stop"},
                         "no on_kept: LTK Manager's repair comes back")
        self.assertEqual(kept[0]["health"], verdict)
        skin = self.saved(self.skin_path)
        self.assertEqual((skin.ltk_id, skin.rose_copy, skin.pending), (None, self.skin, False))
        self.assertNotIn("ltkId", skin.metadata)
        self.assertTrue(self.skin.exists())

    def test_the_manifest_follows_the_repair_written_into_a_custom_skin(self):
        """LTK Manager's repair rewrote Rose's file: the manifest finds it by its new hashes"""
        def repair_into_roses_file(mod, display_name, on_kept=None, stop=None):
            with zipfile.ZipFile(mod, "w") as archive:
                archive.writestr("WAD/Ezreal.wad.client", b"repaired skin")
            return {"health": "repairable", "repaired": 1, "problems": []}
        self.library.check_mod.side_effect = repair_into_roses_file
        added_hash = compute_mod_facts(self.skin)[1]

        self.handler()._check_imported_mods(self.skin_imported, [], MagicMock())

        repaired_hash = compute_mod_facts(self.skin)[1]
        self.assertNotEqual(repaired_hash, added_hash, "the repair was written into Rose's file")
        self.assertEqual(self.saved(self.skin_path).metadata["folderHash"], repaired_hash)
        self.assertIsNotNone(self.storage.saved_mod(self.skin_path).metadata.get("sourceHashes"),
                             "what party mode shares, as the skin was added")

    def test_a_custom_skin_is_checked_only_once_the_base_skin_fix_lets_go_of_it(self):
        """The idle pass rewriting the skin and LTK Manager's repair written into
        it would meet on the open file, which Windows refuses: the check waits"""
        checked = threading.Event()

        def check(mod, display_name, on_kept=None, stop=None):
            checked.set()
            return {"health": "repairable", "repaired": 1, "problems": []}
        self.library.check_mod.side_effect = check
        instance = self.handler()

        with base_skin_library.stored_skin_rewrite():
            worker = threading.Thread(target=instance._check_imported_mods, args=(self.skin_imported, [], MagicMock()))
            worker.start()
            self.addCleanup(worker.join, 10)
            self.assertFalse(checked.wait(0.5), "checked while the base-skin fix held the skin")
        worker.join(10)

        self.assertTrue(checked.is_set())
        self.assertFalse(worker.is_alive())

    def test_a_skinhack_is_removed_and_reported_as_a_failed_import(self):
        """The Ezreal custom skin LTK Manager turned off in game"""
        self.library.check_mod.return_value = {"health": "repairable", "repaired": 3224, "problems": [SKINHACK]}
        errors = []

        kept = self.handler()._check_imported_mods(
            self.skin_imported, errors, lambda item: self.storage.delete_champion_mod(81, mod_name=item["modName"]))

        self.assertEqual(kept, [])
        self.assertIsNone(self.saved(self.skin_path))
        self.assertFalse(self.skin.exists())
        self.assertEqual(ltk_removals(self.storage.mods_root), [], "nothing of it was kept in LTK Manager")
        self.assertEqual(errors[0]["code"], "ltk_skinhack")
        self.assertEqual(errors[0]["fileName"], "gojo-ezreal-v1.0.0.fantome")
        self.assertIn("skinhack", errors[0]["error"])

    def test_the_same_skin_added_again_is_not_checked_again(self):
        instance = self.handler()

        with patch.object(message_handler, "_choose_mod_files", return_value=[self.skin_source]):
            instance._handle_add_custom_mods_skin_selected({"action": "create", "championId": 81, "skinIds": [81021]})

        self.library.check_mod.assert_not_called()
        response = instance.sent[-1]
        self.assertTrue(response["success"])
        self.assertEqual(response["imported"][0]["relativePath"], self.skin_path)
        self.assertEqual(self.saved(self.skin_path).target_skin_ids, (81020, 81021))


def imported_mod():
    return [{"fileName": "gojo-ezreal-v1.0.0.fantome", "path": "C:/mods/gojo", "modName": "gojo-ezreal-v1.0.0",
             "relativePath": "skins/81000/gojo.fantome"}]


class BaseSkinFixOnImportTests(unittest.TestCase):
    """A skin is fixed before LTK Manager sees it, and without LTK Manager."""

    GAME = "C:/Riot Games/League of Legends/Game"
    FIX = "injection.baseskin.library.fix_stored_mod"

    def handler(self, phase, check_result=None, injecting=False, game_dir=None):
        """The handler, its added mod a custom skin, and LTK Manager faked at LtkLibrary"""
        library_class = patch.object(message_handler, "LtkLibrary")
        ltk = library_class.start().return_value
        self.addCleanup(library_class.stop)
        ltk.check_mod.return_value = check_result
        overlay = MagicMock()
        overlay.game_dir = game_dir
        manager = SimpleNamespace(injector=SimpleNamespace(overlay_manager=overlay), _injection_in_progress=injecting)
        instance = object.__new__(message_handler.MessageHandler)
        instance.injection_manager = manager
        instance.mod_storage = MagicMock()
        instance.mod_storage.saved_mod.return_value.pending = False
        instance.shared_state = SimpleNamespace(phase=phase)
        instance.sent = []
        instance._send_response = lambda message: instance.sent.append(json.loads(message))
        return instance, ltk

    def fixed(self, fixes=3):
        findings = SimpleNamespace(names=[("EzrealSkin21", "BaseEzreal")] * fixes, meshes=[], audio_merges=0,
                                   unit_renames=0, notes=["name: ezreal: ..."])
        return SimpleNamespace(changed=fixes > 0, fixes=fixes, findings=findings)

    def check(self, instance, skins=True):
        return instance._check_imported_mods(imported_mod(), [], MagicMock(), skins=skins)

    def test_a_fixed_skin_is_kept_with_what_was_fixed(self):
        instance, ltk = self.handler("Lobby", {"health": "healthy", "repaired": 0, "problems": []}, game_dir=self.GAME)
        with patch(self.FIX, return_value=self.fixed(302)) as fix:
            kept = self.check(instance)

        fix.assert_called_once()
        self.assertEqual(str(fix.call_args.args[1]).replace("\\", "/"), "C:/mods/gojo")
        self.assertEqual(kept[0]["baseSkin"], {"fixes": 302})
        ltk.check_mod.assert_called_once()  # LTK Manager then checks the fixed mod

    def test_a_skin_that_already_matches_gets_no_note(self):
        instance, _ = self.handler("Lobby", None, game_dir=self.GAME)
        with patch(self.FIX, return_value=self.fixed(0)):
            kept = self.check(instance)
        self.assertNotIn("baseSkin", kept[0])

    def test_the_fix_runs_in_champion_select_when_ltk_manager_is_the_games(self):
        instance, ltk = self.handler("ChampSelect", {"health": "healthy"}, game_dir=self.GAME)
        with patch(self.FIX, return_value=self.fixed(5)):
            kept = self.check(instance)
        ltk.check_mod.assert_not_called()
        self.assertEqual(kept[0]["baseSkin"], {"fixes": 5})

    def test_the_fix_waits_for_the_client_to_be_idle_during_a_game_or_an_injection(self):
        for phase, injecting in (("FINALIZATION", False), ("InProgress", False), ("Lobby", True)):
            instance, _ = self.handler(phase, None, injecting, game_dir=self.GAME)
            with patch(self.FIX) as fix:
                kept = self.check(instance)
            fix.assert_not_called()
            self.assertEqual(len(kept), 1)

    def test_map_font_and_other_mods_are_not_fixed(self):
        instance, ltk = self.handler("Lobby", None, game_dir=self.GAME)
        with patch(self.FIX) as fix:
            self.check(instance, skins=False)
        fix.assert_not_called()
        ltk.check_mod.assert_called_once()

    def test_a_fix_that_fails_leaves_the_mod_as_it_was_added(self):
        instance, ltk = self.handler("Lobby", None, game_dir=self.GAME)
        with patch(self.FIX, side_effect=OSError("disk full")):
            kept = self.check(instance)
        self.assertEqual(len(kept), 1)
        self.assertNotIn("baseSkin", kept[0])
        ltk.check_mod.assert_called_once()

    def test_a_fix_that_cannot_be_loaded_does_not_fail_the_import(self):
        instance, ltk = self.handler("Lobby", None, game_dir=self.GAME)
        with patch.dict(sys.modules, {"injection.baseskin.library": None}):
            kept = self.check(instance)
        self.assertEqual(len(kept), 1)
        ltk.check_mod.assert_called_once()

    def test_nothing_is_fixed_without_the_games_folder(self):
        instance, _ = self.handler("Lobby", None, game_dir=None)
        with patch(self.FIX) as fix:
            self.check(instance)
        fix.assert_not_called()

    def test_a_mod_ltk_manager_repaired_gets_its_new_hashes_recorded(self):
        instance, _ = self.handler("Lobby", {"health": "repairable", "repaired": 2, "problems": []})
        instance._check_imported_mods(imported_mod(), [], MagicMock())
        instance.mod_storage.refresh_mod_hashes.assert_called_once()
        self.assertEqual(str(instance.mod_storage.refresh_mod_hashes.call_args.args[0]).replace("\\", "/"),
                         "C:/mods/gojo")


if __name__ == "__main__":
    unittest.main()
