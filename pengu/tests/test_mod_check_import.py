"""Adding mods has LTK Manager check them, outside champion select and games;
a mod LTK Manager will turn off in game is not added."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from pengu.communication import message_handler

SKINHACK = {"rule": "bin/skinhack", "title": "Skinhack",
            "description": "A base skin that uses the mesh or the name of another skin of its champion"}


def handler(phase, check_result=None, injecting=False):
    overlay = MagicMock()
    overlay.check_mod.return_value = check_result
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


if __name__ == "__main__":
    unittest.main()
