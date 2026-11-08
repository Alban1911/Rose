"""Adding mods makes them match the base skin, then has LTK Manager check them
(outside champion select and games); a mod LTK Manager will turn off in game is
not added."""

import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pengu.communication import message_handler

SKINHACK = {"rule": "bin/skinhack", "title": "Skinhack",
            "description": "A base skin that uses the mesh or the name of another skin of its champion"}


def handler(phase, check_result=None, injecting=False, game_dir=None):
    overlay = MagicMock()
    overlay.check_mod.return_value = check_result
    overlay.game_dir = game_dir
    manager = SimpleNamespace(injector=SimpleNamespace(overlay_manager=overlay), _injection_in_progress=injecting)
    instance = object.__new__(message_handler.MessageHandler)
    instance.injection_manager = manager
    instance.shared_state = SimpleNamespace(phase=phase)
    instance.sent = []
    instance._send_response = lambda message: instance.sent.append(json.loads(message))
    return instance, overlay


def imported_mod():
    return [{"fileName": "gojo-ezreal-v1.0.0.fantome", "path": "C:/mods/gojo", "modName": "gojo-ezreal-v1.0.0"}]


class ModCheckOnImportTests(unittest.TestCase):
    def test_a_repaired_mod_is_kept_with_ltk_managers_verdict(self):
        verdict = {"health": "repairable", "repaired": 4300, "problems": []}
        instance, overlay = handler("Lobby", verdict)
        imported, errors, remove = imported_mod(), [], MagicMock()

        kept = instance._check_imported_mods(imported, errors, remove)

        overlay.check_mod.assert_called_once()
        self.assertEqual(kept[0]["health"], verdict)
        self.assertEqual(errors, [])
        remove.assert_not_called()
        self.assertEqual(instance.sent, [{"type": "mod-import-checking", "fileCount": 1}])

    def test_a_skinhack_is_removed_and_reported_as_a_failed_import(self):
        """The Ezreal custom skin LTK Manager turned off in game"""
        instance, _ = handler("Lobby", {"health": "repairable", "repaired": 3224, "problems": [SKINHACK]})
        imported, errors, remove = imported_mod(), [], MagicMock()

        kept = instance._check_imported_mods(imported, errors, remove)

        self.assertEqual(kept, [])
        remove.assert_called_once_with(imported[0])
        self.assertEqual(errors[0]["code"], "ltk_skinhack")
        self.assertEqual(errors[0]["fileName"], "gojo-ezreal-v1.0.0.fantome")
        self.assertIn("skinhack", errors[0]["error"])

    def test_another_problem_ltk_manager_cannot_repair_is_reported_with_its_reason(self):
        problem = {"rule": "audio/bank-id", "title": "Bank", "description": "An audio bank the game will not load"}
        instance, _ = handler("Lobby", {"health": "unrepairable", "repaired": 0, "problems": [problem]})
        errors = []

        instance._check_imported_mods(imported_mod(), errors, MagicMock())

        self.assertEqual((errors[0]["code"], errors[0]["reason"]), ("ltk_rejected", "An audio bank the game will not load"))

    def test_a_rejected_mod_that_cannot_be_removed_stays_with_the_verdict(self):
        verdict = {"health": "unrepairable", "repaired": 0, "problems": [SKINHACK]}
        instance, _ = handler("Lobby", verdict)
        errors = []

        kept = instance._check_imported_mods(imported_mod(), errors, MagicMock(side_effect=OSError("in use")))

        self.assertEqual(kept[0]["health"], verdict)
        self.assertEqual(errors, [])

    def test_a_check_that_did_not_run_leaves_the_mod_as_it_was(self):
        instance, _ = handler("None", None)

        kept = instance._check_imported_mods(imported_mod(), [], MagicMock())

        self.assertNotIn("health", kept[0])

    def test_nothing_is_checked_in_champion_select_or_while_injecting(self):
        for phase, injecting in (("ChampSelect", False), ("InProgress", False), ("Lobby", True)):
            instance, overlay = handler(phase, {"health": "healthy"}, injecting)

            kept = instance._check_imported_mods(imported_mod(), [], MagicMock())

            overlay.check_mod.assert_not_called()
            self.assertEqual(len(kept), 1)
            self.assertEqual(instance.sent, [])


class BaseSkinFixOnImportTests(unittest.TestCase):
    """A skin is fixed before LTK Manager sees it, and without LTK Manager."""

    GAME = "C:/Riot Games/League of Legends/Game"
    FIX = "injection.baseskin.library.fix_stored_mod"

    def fixed(self, fixes=3):
        findings = SimpleNamespace(names=[("EzrealSkin21", "BaseEzreal")] * fixes, meshes=[], audio_merges=0,
                                   unit_renames=0, notes=["name: ezreal: ..."])
        return SimpleNamespace(changed=fixes > 0, fixes=fixes, findings=findings)

    def check(self, instance, skins=True):
        return instance._check_imported_mods(imported_mod(), [], MagicMock(), skins=skins)

    def test_a_fixed_skin_is_kept_with_what_was_fixed(self):
        instance, overlay = handler("Lobby", {"health": "healthy", "repaired": 0, "problems": []}, game_dir=self.GAME)
        with patch(self.FIX, return_value=self.fixed(302)) as fix:
            kept = self.check(instance)

        fix.assert_called_once()
        self.assertEqual(str(fix.call_args.args[1]).replace("\\", "/"), "C:/mods/gojo")
        self.assertEqual(kept[0]["baseSkin"], {"fixes": 302})
        overlay.check_mod.assert_called_once()  # LTK Manager then checks the fixed mod

    def test_a_skin_that_already_matches_gets_no_note(self):
        instance, _ = handler("Lobby", None, game_dir=self.GAME)
        with patch(self.FIX, return_value=self.fixed(0)):
            kept = self.check(instance)
        self.assertNotIn("baseSkin", kept[0])

    def test_the_fix_runs_in_champion_select_when_ltk_manager_is_the_games(self):
        instance, overlay = handler("ChampSelect", {"health": "healthy"}, game_dir=self.GAME)
        with patch(self.FIX, return_value=self.fixed(5)):
            kept = self.check(instance)
        overlay.check_mod.assert_not_called()
        self.assertEqual(kept[0]["baseSkin"], {"fixes": 5})

    def test_the_fix_waits_for_the_client_to_be_idle_during_a_game_or_an_injection(self):
        for phase, injecting in (("FINALIZATION", False), ("InProgress", False), ("Lobby", True)):
            instance, _ = handler(phase, None, injecting, game_dir=self.GAME)
            with patch(self.FIX) as fix:
                kept = self.check(instance)
            fix.assert_not_called()
            self.assertEqual(len(kept), 1)

    def test_map_font_and_other_mods_are_not_fixed(self):
        instance, overlay = handler("Lobby", None, game_dir=self.GAME)
        with patch(self.FIX) as fix:
            self.check(instance, skins=False)
        fix.assert_not_called()
        overlay.check_mod.assert_called_once()

    def test_a_fix_that_fails_leaves_the_mod_as_it_was_added(self):
        instance, overlay = handler("Lobby", None, game_dir=self.GAME)
        with patch(self.FIX, side_effect=OSError("disk full")):
            kept = self.check(instance)
        self.assertEqual(len(kept), 1)
        self.assertNotIn("baseSkin", kept[0])
        overlay.check_mod.assert_called_once()

    def test_a_fix_that_cannot_be_loaded_does_not_fail_the_import(self):
        instance, overlay = handler("Lobby", None, game_dir=self.GAME)
        with patch.dict(sys.modules, {"injection.baseskin.library": None}):
            kept = self.check(instance)
        self.assertEqual(len(kept), 1)
        overlay.check_mod.assert_called_once()

    def test_nothing_is_fixed_without_the_games_folder(self):
        instance, _ = handler("Lobby", None, game_dir=None)
        with patch(self.FIX) as fix:
            self.check(instance)
        fix.assert_not_called()

    def test_a_mod_ltk_manager_repaired_gets_its_new_hashes_recorded(self):
        instance, _ = handler("Lobby", {"health": "repairable", "repaired": 2, "problems": []})
        instance.mod_storage = MagicMock()
        instance._check_imported_mods(imported_mod(), [], MagicMock())
        instance.mod_storage.refresh_mod_hashes.assert_called_once()
        self.assertEqual(str(instance.mod_storage.refresh_mod_hashes.call_args.args[0]).replace("\\", "/"),
                         "C:/mods/gojo")


if __name__ == "__main__":
    unittest.main()
