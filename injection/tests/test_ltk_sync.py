"""The saved mods' manifests follow LTK Manager's library: a mod whose entry
is gone is marked missing (and found again), one LTK Manager changed gets its
facts read again from LTK Manager's archive, and Rose's leftover copy goes
once LTK Manager lists the entry. An index Rose cannot read changes nothing."""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from injection.mods import ltk_sync, mod_facts
from injection.mods.ltk_sync import start_saved_mods_sync, sync_saved_mods
from injection.mods.mod_facts import ModFacts, compute_mod_facts, stamp_of
from injection.mods.storage import ModStorageService
from injection.overlay import ltk_library
from injection.tests.test_mod_archives import PNG, VOICEOVER, add_entries, make_archive
from utils.core import historic, mod_historic

VO_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"
MAP_ID = "d6f841c7-140b-4ac2-a11c-b37e18eb8006"
MAP = {
    "META/info.json": json.dumps({"Name": "Summoner's Rift"}),
    "WAD/Map11.wad.client": b"map" * 50,
}
STALE = ModFacts("0123456789abcdef0123456789abcdef", ("Ezreal",), False)
INDEX_TIME = 1_700_000_000


class LtkSyncTests(unittest.TestCase):
    """Never this PC's Rose or LTK Manager: both data folders are temporary"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name).resolve()
        self.data = self.root / "Roaming" / "dev.leaguetoolkit.manager"
        self.data.mkdir(parents=True)
        self.ltk_mods = self.root / "ltk-mods"
        (self.data / "settings.json").write_text(json.dumps({"modStoragePath": str(self.ltk_mods)}),
                                                 encoding="utf-8")
        self.state = self.root / "state"
        for patcher in (
            patch.object(ltk_library, "ltk_data_dir", return_value=self.data),
            patch.object(ltk_sync, "get_state_dir", return_value=self.state),
            patch.object(mod_facts, "get_injection_dir", return_value=self.root / "injection"),
            patch.object(historic, "get_user_data_dir", return_value=self.root),
            patch.object(mod_historic, "get_user_data_dir", return_value=self.root),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.mods_root = self.root / "mods"
        self.storage = ModStorageService(self.mods_root)

    def ltk_archive(self, slug, files):
        """LTK Manager's copy of a mod, where its library keeps it"""
        return make_archive(self.ltk_mods / f"{slug}.fantome", files)

    def write_index(self, *entries, when=INDEX_TIME):
        """LTK Manager's library.json listing *entries* ((id, slug) pairs)"""
        index = self.data / "library.json"
        index.write_text(json.dumps({
            "version": 2,
            "mods": [{"id": ltk_id, "format": "fantome", "storage": "archive", "slug": slug}
                     for ltk_id, slug in entries],
            "profiles": [{"id": "default", "enabledMods": []}],
            "activeProfileId": "default",
        }), encoding="utf-8")
        os.utime(index, (when, when))

    def save(self, name, ltk_id, category="voiceover", archive=None, **entry):
        """A saved mod LTK Manager holds, its facts read from *archive* (its
        copy in LTK Manager's library) unless given"""
        if archive is not None:
            entry = {**compute_mod_facts(archive)[0].to_manifest(), "ltkStamp": stamp_of(archive), **entry}
        add_entries(self.mods_root / category / ModStorageService.CATEGORY_METADATA,
                    {name: {"name": name, "path": name, "ltkId": ltk_id, **entry}}, category=category)

    def saved(self, name, category="voiceover"):
        mod = self.storage.saved_mod(f"{category}/{name}.fantome")
        self.assertIsNotNone(mod, f"{name} is not listed")
        return mod

    def sync(self, only_if_changed=False):
        return sync_saved_mods(self.storage, only_if_changed=only_if_changed)

    def test_a_mod_ltk_manager_lost_is_marked_missing_and_one_listed_again_is_not(self):
        voiceover = self.ltk_archive("vo-korean", VOICEOVER)
        self.save("VO Korean", VO_ID, archive=voiceover, missing=True)
        self.save("Rift", MAP_ID, category="maps", archive=self.ltk_archive("rift", MAP))
        self.write_index((VO_ID, "vo-korean"))

        report = self.sync()

        self.assertEqual((report.missing, report.found), (["Rift"], ["VO Korean"]))
        self.assertTrue(self.saved("Rift", "maps").missing)
        self.assertFalse(self.saved("VO Korean").missing)
        self.assertNotIn("missing", self.saved("VO Korean").metadata)
        self.assertEqual(report.refreshed, [])

    def test_an_index_rose_cannot_read_changes_nothing_and_is_read_again_later(self):
        self.save("VO Korean", VO_ID, archive=self.ltk_archive("vo-korean", VOICEOVER))

        self.assertIsNone(self.sync())  # LTK Manager never wrote one
        self.write_index()
        text = (self.data / "library.json").read_text(encoding="utf-8")
        (self.data / "library.json").write_text(text[: len(text) // 2], encoding="utf-8")
        self.assertIsNone(self.sync())  # LTK Manager writing it

        self.assertFalse(self.saved("VO Korean").missing)
        self.assertFalse((self.state / ltk_sync.SYNC_STATE).exists())
        self.write_index()
        self.assertEqual(self.sync(only_if_changed=True).missing, ["VO Korean"])

    def test_facts_are_read_again_from_an_archive_ltk_manager_changed(self):
        voiceover = self.ltk_archive("vo-korean", VOICEOVER)
        self.save("VO Korean", VO_ID, **STALE.to_manifest(), ltkStamp=[1, 1])
        self.write_index((VO_ID, "vo-korean"))

        report = self.sync()

        mod = self.saved("VO Korean")
        self.assertEqual(report.refreshed, ["VO Korean"])
        self.assertEqual(mod.facts, compute_mod_facts(voiceover)[0])
        self.assertEqual(mod.metadata["ltkStamp"], stamp_of(voiceover))

    def test_a_mod_ltk_manager_repaired_as_it_was_added_gets_the_facts_of_its_repair(self):
        """A repaired mod is recorded with the facts of Rose's copy and no stamp"""
        repaired = self.ltk_archive("vo-korean", dict(VOICEOVER, **{"WAD/Ahri.ko_KR.wad.client": b"fixed"}))
        self.save("VO Korean", VO_ID, **STALE.to_manifest())
        self.write_index((VO_ID, "vo-korean"))

        self.assertEqual(self.sync().refreshed, ["VO Korean"])
        self.assertEqual(self.saved("VO Korean").facts, compute_mod_facts(repaired)[0])
        self.assertEqual(self.saved("VO Korean").metadata["ltkStamp"], stamp_of(repaired))

    def test_an_archive_ltk_manager_did_not_change_is_not_read_again(self):
        self.save("VO Korean", VO_ID, archive=self.ltk_archive("vo-korean", VOICEOVER))
        self.write_index((VO_ID, "vo-korean"))

        with patch.object(ltk_sync, "compute_mod_facts", side_effect=AssertionError("read again")):
            report = self.sync()

        self.assertFalse(report)

    def test_an_archive_that_cannot_be_read_is_left_for_the_next_sync(self):
        (self.ltk_mods / "vo-korean.fantome").parent.mkdir(parents=True)
        (self.ltk_mods / "vo-korean.fantome").write_bytes(b"not a zip")
        self.save("VO Korean", VO_ID, **STALE.to_manifest(), ltkStamp=[1, 1])
        self.write_index((VO_ID, "vo-korean"))

        self.assertEqual(self.sync().refreshed, [])
        self.assertEqual(self.saved("VO Korean").facts, STALE)
        self.assertEqual(self.saved("VO Korean").metadata["ltkStamp"], [1, 1])

    def test_champion_select_syncs_only_once_ltk_managers_index_changed(self):
        self.save("VO Korean", VO_ID, archive=self.ltk_archive("vo-korean", VOICEOVER))
        self.write_index((VO_ID, "vo-korean"))
        self.assertIsNotNone(self.sync())

        self.write_index()  # the entry removed, the index's time as it was
        self.assertIsNone(self.sync(only_if_changed=True))
        self.assertFalse(self.saved("VO Korean").missing)

        self.write_index(when=INDEX_TIME + 60)
        self.assertEqual(self.sync(only_if_changed=True).missing, ["VO Korean"])

    def test_rose_s_start_syncs_whatever_the_index_s_time(self):
        self.save("VO Korean", VO_ID, archive=self.ltk_archive("vo-korean", VOICEOVER))
        self.write_index((VO_ID, "vo-korean"))
        self.sync()

        self.write_index()

        self.assertEqual(self.sync().missing, ["VO Korean"])

    def test_a_leftover_copy_goes_only_once_ltk_manager_lists_its_entry(self):
        listed = make_archive(self.mods_root / "voiceover" / "VO Korean.fantome", VOICEOVER)
        listed.with_suffix(".png").write_bytes(PNG)
        lost = make_archive(self.mods_root / "maps" / "Rift.fantome", MAP)
        self.save("VO Korean", VO_ID, archive=self.ltk_archive("vo-korean", VOICEOVER))
        self.save("Rift", MAP_ID, category="maps", **STALE.to_manifest())
        self.write_index((VO_ID, "vo-korean"))

        report = self.sync()

        self.assertEqual(report.copies_deleted, ["VO Korean"])
        self.assertFalse(listed.exists())
        self.assertEqual(listed.with_suffix(".png").read_bytes(), PNG)
        self.assertIsNone(self.saved("VO Korean").stored)
        self.assertTrue(lost.exists())  # the mod's only copy now: the next start moves it again
        self.assertTrue(self.saved("Rift", "maps").missing)

    def test_a_sync_already_running_is_not_started_again(self):
        self.save("VO Korean", VO_ID, **STALE.to_manifest())
        self.write_index()
        self.assertTrue(ltk_sync._SYNC_LOCK.acquire(blocking=False))
        try:
            self.assertIsNone(self.sync())
        finally:
            ltk_sync._SYNC_LOCK.release()

        self.assertFalse(self.saved("VO Korean").missing)

    def test_the_sync_runs_beside_rose_on_a_daemon_thread(self):
        ran = threading.Event()

        def sync(*, only_if_changed):
            self.assertTrue(only_if_changed)
            self.assertTrue(threading.current_thread().daemon)
            ran.set()
            raise OSError("the mods folder is gone")  # logged: Rose goes on

        with patch.object(ltk_sync, "sync_saved_mods", side_effect=sync):
            thread = start_saved_mods_sync(only_if_changed=True)
            thread.join(5)

        self.assertTrue(ran.is_set())
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
