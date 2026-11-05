import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pengu.communication import message_handler


class SelectOtherDeselectTests(unittest.TestCase):
    """A category's "None" entry deselects each mod with otherData null (#425):
    it used to fail, leaving the mods selected and saved for the next game"""

    def setUp(self):
        self.handler = object.__new__(message_handler.MessageHandler)
        self.handler.mod_storage = MagicMock()
        self.handler.shared_state = SimpleNamespace(selected_other_mods=[
            {"mod_name": "VO Chinese", "relative_path": "voiceover/VO Chinese"},
            {"mod_name": "Zeri VFX", "relative_path": "vfx/winter-wonder-zeri"},
        ])
        self.saved = {}
        for target, effect in (
            ("utils.core.mod_historic.write_historic_mod", lambda cat, paths: self.saved.__setitem__(cat, paths)),
            ("utils.core.mod_historic.clear_historic_mod", lambda cat: self.saved.__setitem__(cat, [])),
        ):
            patcher = patch(target, side_effect=effect)
            patcher.start()
            self.addCleanup(patcher.stop)

    def remaining(self):
        return [mod["relative_path"] for mod in self.handler.shared_state.selected_other_mods]

    def test_deselecting_without_other_data_removes_the_mod(self):
        self.handler._handle_select_other({
            "type": "select-other", "category": "voiceover",
            "otherId": "voiceover/VO Chinese", "otherData": None, "action": "deselect",
        })

        self.assertEqual(self.remaining(), ["vfx/winter-wonder-zeri"])
        self.assertEqual(self.saved["voiceover"], [])  # no longer saved for the next game
        self.assertEqual(self.saved["vfx"], ["vfx/winter-wonder-zeri"])

    def test_deselecting_with_other_data_still_works(self):
        self.handler._handle_select_other({
            "otherId": "vfx/winter-wonder-zeri", "otherData": {"id": "vfx\\winter-wonder-zeri"}, "action": "deselect",
        })

        self.assertEqual(self.remaining(), ["voiceover/VO Chinese"])


if __name__ == "__main__":
    unittest.main()
