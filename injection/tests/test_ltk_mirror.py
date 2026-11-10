import json
import unittest

from injection.mods.ltk_mirror import category_of
from injection.mods.manifest import ltk_removals
from injection.mods.mod_facts import compute_mod_facts
from injection.tests import test_ltk_sync
from injection.tests.test_ltk_sync import MAP, MAP_ID, NEW_ID, VO_ID
from injection.tests.test_mod_archives import PNG, VOICEOVER

USERS_HUD = {
    "META/info.json": json.dumps({"Name": "Dark HUD", "Description": "A darker HUD"}),
    "META/image.png": PNG,
    "WAD/UI.wad.client": b"hud" * 50,
}


class MirrorTests(unittest.TestCase):
    """The mods the user added in LTK Manager are listed in Rose, to pick for
    a game; Rose never removes one from LTK Manager. Never this PC's Rose or
    LTK Manager: both data folders are temporary"""

    setUp = test_ltk_sync.LtkSyncTests.setUp
    ltk_archive = test_ltk_sync.LtkSyncTests.ltk_archive
    write_index = test_ltk_sync.LtkSyncTests.write_index
    save = test_ltk_sync.LtkSyncTests.save
    sync = test_ltk_sync.LtkSyncTests.sync

    def analysed(self, **derived_by_id):
        """LTK Manager's own analysis of its mods (wad-reports.json)."""
        reports = {mod_id: {"modId": mod_id, "derived": derived} for mod_id, derived in derived_by_id.items()}
        (self.data / "wad-reports.json").write_text(json.dumps({"version": 1, "reports": reports}), encoding="utf-8")

    def listed(self, category=None):
        """The mods the user added in LTK Manager that Rose lists, by name."""
        return {mod.name: mod for mod in self.storage.saved_mods(category) if mod.mirrored}

    def test_a_mod_the_user_added_in_ltk_manager_is_listed_with_its_name_image_and_facts(self):
        hud = self.ltk_archive("dark-hud", USERS_HUD)
        self.write_index((NEW_ID, "dark-hud"))
        self.analysed(**{NEW_ID: {"tags": ["ui"], "maps": [], "champions": []}})

        self.sync()

        mod = self.listed("ui")["dark-hud"]
        self.assertEqual((mod.ltk_id, mod.display_name, mod.facts), (NEW_ID, "Dark HUD", compute_mod_facts(hud)[0]))
        self.assertEqual(mod.image_paths()[0].read_bytes(), PNG)
        self.assertEqual(mod.sidecar(".txt").read_text(encoding="utf-8"), "A darker HUD")
        listing = self.storage.list_mods_for_category("ui")
        self.assertEqual([(m["ltkId"], m["mirrored"], m["hidden"]) for m in listing], [(NEW_ID, True, False)])

    def test_its_category_is_ltk_managers_analysis_of_it(self):
        self.assertEqual(category_of({"tags": ["map-skin"]}), "maps")
        self.assertEqual(category_of({"tags": [], "maps": ["summoners-rift"]}), "maps")
        self.assertEqual(category_of({"tags": ["ui"]}), "ui")
        self.assertEqual(category_of({"tags": ["emote"]}), "others")
        self.assertEqual(category_of(None), "others", "not analysed yet")
        self.assertIsNone(category_of({"tags": ["champion-skin", "map-skin"]}))

    def test_a_champion_skin_is_not_listed(self):
        self.ltk_archive("talon", MAP)
        self.write_index((NEW_ID, "talon"))
        self.analysed(**{NEW_ID: {"tags": ["champion-skin"], "champions": ["Talon"]}})

        self.sync()

        self.assertEqual(self.listed(), {})

    def test_the_mods_rose_added_are_never_listed_as_the_users(self):
        self.save("VO Korean", VO_ID, archive=self.ltk_archive("vo-korean", VOICEOVER))
        journal = self.root / "injection" / "ltf_installed.json"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps({"installed": {MAP_ID: "1001-Skin"}, "kept": {NEW_ID: {
            "folder": "Rift", "fingerprint": "f" * 64, "source": "Rift.fantome"}}}), encoding="utf-8")
        self.write_index((VO_ID, "vo-korean"), (MAP_ID, "skin"), (NEW_ID, "rift"))

        self.sync()

        self.assertEqual(self.listed(), {})

    def test_one_gone_from_ltk_manager_leaves_rose_s_lists_and_is_never_missing(self):
        self.ltk_archive("dark-hud", USERS_HUD)
        self.write_index((NEW_ID, "dark-hud"))
        self.sync()
        self.write_index()

        report = self.sync()

        self.assertEqual(self.listed(), {})
        self.assertEqual(report.gone_from_library, [])
        self.assertEqual(ltk_removals(self.mods_root), [], "LTK Manager's own: nothing to remove there")

    def test_one_that_turns_out_to_be_rose_s_leaves_the_users_list(self):
        self.ltk_archive("dark-hud", USERS_HUD)
        self.write_index((NEW_ID, "dark-hud"))
        self.sync()
        self.save("Dark HUD", NEW_ID, category="ui")

        self.sync()

        self.assertEqual(self.listed(), {})
        self.assertEqual([mod.name for mod in self.storage.saved_mods("ui")], ["Dark HUD"])

    def test_one_deleted_in_rose_stays_in_ltk_manager_and_is_listed_again_at_the_next_sync(self):
        self.ltk_archive("dark-hud", USERS_HUD)
        self.write_index((NEW_ID, "dark-hud"))
        self.sync()

        self.assertTrue(self.storage.delete_category_mod("others", "dark-hud"))
        self.assertEqual(ltk_removals(self.mods_root), [])
        self.sync()

        self.assertEqual(list(self.listed()), ["dark-hud"])

    def test_a_hidden_one_stays_hidden(self):
        self.ltk_archive("dark-hud", USERS_HUD)
        self.write_index((NEW_ID, "dark-hud"))
        self.sync()

        self.assertTrue(self.storage.set_category_mod_hidden("others", "dark-hud", True))
        self.sync()

        self.assertTrue(self.listed()["dark-hud"].hidden)
        self.assertTrue(self.storage.set_category_mod_hidden("others", "dark-hud", False))
        self.assertFalse(self.listed()["dark-hud"].hidden)

    def test_only_a_mod_the_user_added_in_ltk_manager_can_be_hidden(self):
        self.save("VO Korean", VO_ID, archive=self.ltk_archive("vo-korean", VOICEOVER))

        self.assertFalse(self.storage.set_category_mod_hidden("voiceover", "VO Korean", True))


if __name__ == "__main__":
    unittest.main()
