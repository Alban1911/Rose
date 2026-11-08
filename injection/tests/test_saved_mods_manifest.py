
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from injection.mods import manifest, storage
from injection.mods.manifest import (
    SavedMod,
    find_saved_mod,
    forget_ltk_removals,
    iter_saved_mods,
    leftover_copies,
    ltk_removals,
    manifest_ltk_ids,
    pending_mods,
    update_saved_mod,
)
from injection.mods.mod_facts import ModFacts, compute_mod_facts
from injection.mods.mod_source import LtkEntry, RoseFile
from injection.mods.storage import ModStorageService

MOVED_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"
GONE_ID = "d6f841c7-140b-4ac2-a11c-b37e18eb8006"
NIGHT_ID = "799b6c82-8324-4394-a0cf-ddebcd16eba7"
NEW_ID = "1beee5a2-6fe1-49e1-ba94-9d601ead2a0f"
FACTS = ModFacts("0123456789abcdef0123456789abcdef", ("Annie",), False)
PNG = b"\x89PNG\r\n\x1a\npreview"


def make_archive(path, files=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in (files or {"WAD/Annie.wad.client": path.stem.encode("utf-8")}).items():
            archive.writestr(name, data)
    return path


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class SavedModsTestCase(unittest.TestCase):
    """Annie's folder holds a pending mod, one LTK Manager holds, one it lost,
    one deleted long ago and a folder from before archives; the maps a
    pending mod and one LTK Manager holds"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.mods_root = self.root / "mods"
        self.annie = self.mods_root / "skins" / "1000"
        self.pending_archive = make_archive(self.annie / "Pending Skin.fantome")
        self.pending_hash = compute_mod_facts(self.pending_archive)[1]
        (self.annie / "Pending Skin.png").write_bytes(PNG)
        (self.annie / "Old Folder" / "WAD").mkdir(parents=True)
        (self.annie / "Old Folder" / "WAD" / "Annie.wad.client").write_bytes(b"old")
        make_archive(self.annie / "Dropped.fantome")
        self.write_annie_manifest()
        self.maps = self.mods_root / "maps"
        make_archive(self.maps / "Rift.fantome")
        make_archive(self.maps / "Stray.fantome")
        write_json(self.maps / manifest.CATEGORY_METADATA, {"version": 1, "category": "maps", "mods": {
            "Rift": {"name": "Rift", "path": "Rift", "displayName": "Summoner's Rift"},
            "Night": {"name": "Night", "path": "Night", "ltkId": NIGHT_ID},
        }})
        manifest._reported_manifests.clear()

    def write_annie_manifest(self, targets=(), **extra_mods):
        mods = {
            self.pending_hash: {"name": "Pending Skin", "folderHash": self.pending_hash, "wadHashes": {},
                                "targets": [1001], "displayName": "Pending!"},
            "Moved Skin": {"name": "Moved Skin", "targets": [1002], "ltkId": MOVED_ID,
                           "updatedAt": 1234.5, **FACTS.to_manifest()},
            "Gone Skin": {"name": "Gone Skin", "targets": [1003], "ltkId": GONE_ID, "missing": True},
            "Deleted Skin": {"name": "Deleted Skin", "targets": [1004]},
            "Old Folder": {"name": "Old Folder", "targets": [1005]},
            **extra_mods,
        }
        write_json(self.annie / manifest.TARGET_METADATA,
                   {"version": 1, "championId": 1, "targets": list(targets), "mods": mods})

    def annie_mods(self):
        return {mod.name: mod for mod in iter_saved_mods(self.mods_root, "skins", champion_id=1)}

    def entry(self, directory, key):
        name = manifest.TARGET_METADATA if directory.parent.name == "skins" else manifest.CATEGORY_METADATA
        return json.loads((directory / name).read_text(encoding="utf-8"))["mods"].get(key)


class ListingTests(SavedModsTestCase):
    def test_pending_moved_missing_and_gone_mods(self):
        mods = self.annie_mods()

        self.assertEqual(sorted(mods), ["Gone Skin", "Moved Skin", "Old Folder", "Pending Skin"])
        pending = mods["Pending Skin"]
        self.assertTrue(pending.pending and pending.available)
        self.assertEqual(pending.stored, self.pending_archive)
        self.assertEqual(pending.key, self.pending_hash)
        self.assertEqual(pending.display_name, "Pending!")
        self.assertEqual(pending.target_skin_ids, (1001,))
        self.assertEqual(pending.source, RoseFile(self.pending_archive, "Pending Skin"))
        self.assertIsNone(pending.facts)

        moved = mods["Moved Skin"]
        self.assertEqual(moved.ltk_id, MOVED_ID)
        self.assertIsNone(moved.stored)
        self.assertFalse(moved.pending)
        self.assertTrue(moved.available)
        self.assertEqual(moved.facts, FACTS)
        self.assertEqual(moved.source, LtkEntry(MOVED_ID, FACTS, missing=False))
        self.assertEqual(moved.updated_at, 1234.5)

        gone = mods["Gone Skin"]
        self.assertTrue(gone.missing)
        self.assertFalse(gone.available)
        self.assertEqual(gone.source, LtkEntry(GONE_ID, None, missing=True))

    def test_the_identity_is_the_archive_path_unless_a_folder_is_stored(self):
        mods = self.annie_mods()

        self.assertEqual(mods["Pending Skin"].relative_path, "skins/1000/Pending Skin.fantome")
        self.assertEqual(mods["Moved Skin"].relative_path, "skins/1000/Moved Skin.fantome")
        self.assertEqual(mods["Moved Skin"].path(self.mods_root), self.annie / "Moved Skin.fantome")
        self.assertFalse(mods["Moved Skin"].path(self.mods_root).exists())
        self.assertEqual(mods["Old Folder"].relative_path, "skins/1000/Old Folder")
        self.assertEqual(mods["Old Folder"].source, RoseFile(self.annie / "Old Folder", "Old Folder"))

    def test_images_and_descriptions_sit_beside_the_manifest_under_the_mods_name(self):
        moved = self.annie_mods()["Moved Skin"]

        self.assertEqual(moved.sidecar(".png"), self.annie / "Moved Skin.png")
        self.assertEqual(moved.sidecar(".txt"), self.annie / "Moved Skin.txt")

    def test_a_file_nobody_registered_needs_default_targets(self):
        self.assertNotIn("Dropped", self.annie_mods())

        self.write_annie_manifest(targets=[1001])
        dropped = self.annie_mods()["Dropped"]

        self.assertEqual(dropped.key, "")
        self.assertTrue(dropped.pending)
        self.assertEqual(dropped.target_skin_ids, (1001,))

    def test_a_legacy_per_skin_folder_targets_its_skin(self):
        make_archive(self.mods_root / "skins" / "1007" / "Legacy Mod.fantome")

        legacy = self.annie_mods()["Legacy Mod"]

        self.assertEqual(legacy.relative_path, "skins/1007/Legacy Mod.fantome")
        self.assertEqual(legacy.target_skin_ids, (1007,))

    def test_a_category_lists_only_the_mods_it_registered(self):
        maps = {mod.name: mod for mod in iter_saved_mods(self.mods_root, "maps")}

        self.assertEqual(sorted(maps), ["Night", "Rift"])
        self.assertTrue(maps["Rift"].pending)
        self.assertEqual(maps["Rift"].display_name, "Summoner's Rift")
        self.assertEqual(maps["Night"].ltk_id, NIGHT_ID)
        self.assertEqual(maps["Night"].relative_path, "maps/Night.fantome")
        self.assertEqual(maps["Night"].target_skin_ids, ())

    def test_every_kind_is_listed_without_a_filter(self):
        kinds = {mod.kind for mod in iter_saved_mods(self.mods_root)}

        self.assertEqual(kinds, {"skins", "maps"})
        self.assertEqual(iter_saved_mods(self.mods_root, "skins", champion_id=2), [])
        self.assertEqual(iter_saved_mods(self.mods_root, "not a category"), [])

    def test_a_renamed_file_is_still_matched_by_its_content(self):
        self.pending_archive.rename(self.annie / "Renamed.fantome")

        mods = self.annie_mods()

        self.assertNotIn("Pending Skin", mods)
        self.assertEqual(mods["Renamed"].key, self.pending_hash)
        self.assertEqual(mods["Renamed"].display_name, "Pending!")

    def test_a_renamed_file_moved_into_ltk_manager_keeps_its_name(self):
        """Content matching skips an entry LTK Manager holds: attaching must
        leave the entry naming the renamed file, or its copy is never dropped"""
        renamed = self.pending_archive.rename(self.annie / "Renamed.fantome")
        service = ModStorageService(self.mods_root)

        self.assertTrue(service.attach_ltk_entry("skins/1000/Renamed.fantome", NEW_ID))
        self.assertTrue(service.drop_stored_copy("skins/1000/Renamed.fantome"))

        self.assertFalse(renamed.exists())
        self.assertEqual(self.entry(self.annie, self.pending_hash)["name"], "Renamed")
        moved = service.saved_mod("skins/1000/Renamed.fantome")
        self.assertEqual((moved.ltk_id, moved.stored, moved.display_name), (NEW_ID, None, "Pending!"))

    def test_one_mod_per_name_and_the_one_ltk_manager_holds_wins(self):
        self.write_annie_manifest(**{"dup-key": {"name": "Pending Skin", "targets": [1001], "ltkId": NEW_ID}})

        pending = [mod for mod in iter_saved_mods(self.mods_root, "skins") if mod.name == "Pending Skin"]

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].ltk_id, NEW_ID)

    def test_pending_mods_and_leftover_copies(self):
        make_archive(self.annie / "Moved Skin.fantome")

        self.assertEqual(sorted(mod.name for mod in pending_mods(self.mods_root)),
                         ["Old Folder", "Pending Skin", "Rift"])
        self.assertEqual([mod.name for mod in leftover_copies(self.mods_root)], ["Moved Skin"])

    def test_reading_creates_nothing(self):
        missing = self.root / "no mods"

        self.assertEqual(iter_saved_mods(missing), [])
        self.assertIsNone(find_saved_mod(missing, "maps/Rift"))
        self.assertEqual(manifest_ltk_ids(missing), set())
        self.assertFalse(missing.exists())

    def test_an_unreadable_manifest_lists_nothing_and_says_so_once(self):
        (self.maps / manifest.CATEGORY_METADATA).write_text("{broken", encoding="utf-8")

        with self.assertLogs(level="WARNING") as logs:
            for _ in range(3):
                self.assertEqual(iter_saved_mods(self.mods_root, "maps"), [])
        self.assertEqual(len(logs.output), 1)


class FindTests(SavedModsTestCase):
    def test_either_identity_finds_the_mod_as_windows_compares_paths(self):
        for wanted, name in (
            ("skins/1000/Pending Skin.fantome", "Pending Skin"),
            ("skins/1000/pending skin", "Pending Skin"),
            ("skins/1000/Old Folder", "Old Folder"),
            ("skins/1000/Old Folder.fantome", "Old Folder"),
            ("SKINS\\1000\\Moved Skin.fantome", "Moved Skin"),
            ("skins/1000/Moved Skin", "Moved Skin"),
            ("maps/night", "Night"),
            ("maps/Rift.fantome", "Rift"),
            (str(self.maps / "Rift.fantome"), "Rift"),
        ):
            with self.subTest(wanted=wanted):
                found = find_saved_mod(self.mods_root, wanted)
                self.assertIsNotNone(found)
                self.assertEqual(found.name, name)

    def test_anything_else_finds_nothing(self):
        for wanted in ("", None, "skins/1000/Deleted Skin", "skins/1000/../1000/Moved Skin", "maps/Stray",
                       "skins/1000", "fonts/Rift", str(self.root / "elsewhere" / "Rift.fantome")):
            with self.subTest(wanted=wanted):
                self.assertIsNone(find_saved_mod(self.mods_root, wanted))


class UpdateTests(SavedModsTestCase):
    def test_fields_merge_into_the_entry(self):
        self.assertTrue(update_saved_mod(self.mods_root, "skins/1000/Pending Skin.fantome",
                                         ltkId=NEW_ID, **FACTS.to_manifest()))

        entry = self.entry(self.annie, self.pending_hash)
        self.assertEqual(entry["ltkId"], NEW_ID)
        self.assertEqual(entry["displayName"], "Pending!")
        self.assertEqual(entry["folderHash"], self.pending_hash)
        self.assertEqual(entry["targets"], [1001])
        self.assertEqual(entry["partyHash"], FACTS.party_hash)
        self.assertEqual(self.entry(self.annie, "Moved Skin")["ltkId"], MOVED_ID)

    def test_none_removes_a_key(self):
        update_saved_mod(self.mods_root, "skins/1000/Gone Skin.fantome", missing=None)

        self.assertNotIn("missing", self.entry(self.annie, "Gone Skin"))
        self.assertFalse(find_saved_mod(self.mods_root, "skins/1000/Gone Skin").missing)

    def test_a_file_nobody_registered_gets_its_entry_with_its_targets(self):
        self.write_annie_manifest(targets=[1001])

        self.assertTrue(update_saved_mod(self.mods_root, "skins/1000/Dropped.fantome", ltkId=NEW_ID))

        self.assertEqual(self.entry(self.annie, "Dropped"), {"name": "Dropped", "targets": [1001], "ltkId": NEW_ID})
        self.assertEqual(find_saved_mod(self.mods_root, "skins/1000/Dropped").key, "Dropped")

    def test_a_legacy_per_skin_folder_gets_its_manifest(self):
        legacy = self.mods_root / "skins" / "1007"
        make_archive(legacy / "Legacy Mod.fantome")

        self.assertTrue(update_saved_mod(self.mods_root, "skins/1007/Legacy Mod.fantome", ltkId=NEW_ID))

        payload = json.loads((legacy / manifest.TARGET_METADATA).read_text(encoding="utf-8"))
        self.assertEqual(payload, {"version": 1, "championId": 1, "targets": [1007], "mods": {
            "Legacy Mod": {"name": "Legacy Mod", "targets": [1007], "ltkId": NEW_ID}}})

    def test_a_category_entry_keeps_its_path(self):
        self.assertTrue(update_saved_mod(self.mods_root, "maps/Rift", ltkId=NEW_ID))

        self.assertEqual(self.entry(self.maps, "Rift"),
                         {"name": "Rift", "path": "Rift", "displayName": "Summoner's Rift", "ltkId": NEW_ID})

    def test_an_unreadable_manifest_is_left_unchanged(self):
        legacy = self.mods_root / "skins" / "1007"
        make_archive(legacy / "Legacy Mod.fantome")
        broken = legacy / manifest.TARGET_METADATA
        broken.write_text('{"version": 1, "mods": {"Other": ', encoding="utf-8")

        with self.assertLogs(level="WARNING"):
            self.assertFalse(update_saved_mod(self.mods_root, "skins/1007/Legacy Mod.fantome", ltkId=NEW_ID))

        self.assertEqual(broken.read_text(encoding="utf-8"), '{"version": 1, "mods": {"Other": ')

    def test_a_mod_that_is_not_listed_is_not_written(self):
        before = (self.annie / manifest.TARGET_METADATA).read_text(encoding="utf-8")

        self.assertFalse(update_saved_mod(self.mods_root, "skins/1000/Deleted Skin", ltkId=NEW_ID))
        self.assertEqual((self.annie / manifest.TARGET_METADATA).read_text(encoding="utf-8"), before)


class RemovalTests(SavedModsTestCase):
    """A deleted mod's LTK Manager entry is left to remove in its manifest,
    in the write that takes the mod out"""

    def manifest_root(self, directory):
        name = manifest.TARGET_METADATA if directory.parent.name == "skins" else manifest.CATEGORY_METADATA
        return json.loads((directory / name).read_text(encoding="utf-8"))

    def test_a_deleted_mods_entry_is_removed_then_forgotten(self):
        self.assertTrue(manifest.remove_saved_mod(self.mods_root, self.annie_mods()["Moved Skin"]))
        self.assertTrue(manifest.remove_saved_mod(self.mods_root, self.annie_mods()["Gone Skin"]))

        payload = self.manifest_root(self.annie)
        self.assertNotIn("Moved Skin", payload["mods"])
        self.assertEqual(payload["pendingRemovals"], [MOVED_ID, GONE_ID])
        self.assertEqual(ltk_removals(self.mods_root), [MOVED_ID, GONE_ID])
        forget_ltk_removals(self.mods_root, [GONE_ID])
        self.assertEqual(ltk_removals(self.mods_root), [MOVED_ID])
        forget_ltk_removals(self.mods_root, [MOVED_ID])
        self.assertEqual(ltk_removals(self.mods_root), [])
        self.assertNotIn("pendingRemovals", self.manifest_root(self.annie))

    def test_a_failed_write_leaves_nothing_to_remove(self):
        with patch.object(manifest, "_write_manifest", side_effect=OSError("disk full")), \
                self.assertRaises(OSError):
            manifest.remove_saved_mod(self.mods_root, self.annie_mods()["Moved Skin"])

        self.assertEqual(ltk_removals(self.mods_root), [])
        self.assertEqual(self.annie_mods()["Moved Skin"].ltk_id, MOVED_ID)

    def test_an_entry_another_manifest_names_is_not_to_remove(self):
        maps = self.manifest_root(self.maps)
        write_json(self.maps / manifest.CATEGORY_METADATA, {**maps, "pendingRemovals": [MOVED_ID, NEW_ID]})

        self.assertEqual(ltk_removals(self.mods_root), [NEW_ID])

    def test_every_id_rose_added_is_known(self):
        self.write_annie_manifest(**{"dup-key": {"name": "Moved Skin", "targets": [1002], "ltkId": NEW_ID}})
        maps = self.manifest_root(self.maps)
        write_json(self.maps / manifest.CATEGORY_METADATA,
                   {**maps, "pendingRemovals": ["0f0f0f0f-0000-4000-8000-000000000000", "not-an-id"]})

        self.assertEqual(manifest_ltk_ids(self.mods_root), {
            MOVED_ID, GONE_ID, NIGHT_ID, NEW_ID, "0f0f0f0f-0000-4000-8000-000000000000"})


class SourceTests(unittest.TestCase):
    def test_a_file_is_available_while_it_is_there(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            existing = Path(temp_dir) / "Rift.fantome"
            existing.write_bytes(b"map")

            self.assertTrue(RoseFile.at(existing).available)
            self.assertEqual(RoseFile.at(existing).name, "Rift")
            self.assertFalse(RoseFile.at(Path(temp_dir) / "Gone.fantome").available)

    def test_an_ltk_entry_is_available_until_a_sync_finds_it_gone(self):
        self.assertTrue(LtkEntry(MOVED_ID).available)
        self.assertEqual(LtkEntry(MOVED_ID).put(Path("nowhere")), f"ltk~{MOVED_ID}")
        self.assertFalse(LtkEntry(GONE_ID, missing=True).available)
        self.assertIsNone(LtkEntry(GONE_ID, missing=True).put(Path("nowhere")))


class StorageDelegationTests(SavedModsTestCase):
    def setUp(self):
        super().setUp()
        self.service = ModStorageService(self.mods_root)

    def test_the_storage_shares_the_writers_lock_and_names(self):
        self.assertIs(storage._STORAGE_LOCK, manifest._STORAGE_LOCK)
        self.assertEqual(manifest.MOD_CATEGORIES, ModStorageService.MOD_CATEGORIES)
        self.assertEqual(manifest.SKINS, ModStorageService.CATEGORY_SKINS)
        self.assertEqual((manifest.TARGET_METADATA, manifest.LEGACY_TARGET_METADATA, manifest.CATEGORY_METADATA),
                         (ModStorageService.TARGET_METADATA, ModStorageService.LEGACY_TARGET_METADATA,
                          ModStorageService.CATEGORY_METADATA))
        self.assertEqual(manifest.ARCHIVE_SUFFIX, ModStorageService.ARCHIVE_SUFFIX)

    def test_the_storage_lists_through_the_manifests(self):
        self.assertEqual(len(self.service.saved_mods()), len(iter_saved_mods(self.mods_root)))
        self.assertEqual(self.service.saved_mod("maps/Night").ltk_id, NIGHT_ID)
        self.assertEqual(sorted(m.name for m in self.service.pending_mods()), ["Old Folder", "Pending Skin", "Rift"])
        self.assertEqual(self.service.ltk_ids(), {MOVED_ID, GONE_ID, NIGHT_ID})
        self.assertIsInstance(self.service.saved_mods("maps")[0], SavedMod)

    def test_attaching_records_the_entry_its_facts_stamp_and_date(self):
        os.utime(self.pending_archive, (1_700_000_000, 1_700_000_000))

        self.assertTrue(self.service.attach_ltk_entry(
            "skins/1000/Pending Skin.fantome", NEW_ID, facts=FACTS, stamp=[10, 20]))

        entry = self.entry(self.annie, self.pending_hash)
        self.assertEqual(entry["ltkId"], NEW_ID)
        self.assertEqual(entry["ltkStamp"], [10, 20])
        self.assertEqual(entry["updatedAt"], 1_700_000_000)
        self.assertEqual(ModFacts.from_manifest(entry), FACTS)
        self.assertEqual(self.service.saved_mod("skins/1000/Pending Skin").ltk_id, NEW_ID)

    def test_attaching_again_clears_missing_and_keeps_facts_it_was_not_given(self):
        self.service.attach_ltk_entry("skins/1000/Moved Skin.fantome", MOVED_ID, facts=FACTS, stamp=[1, 2])
        update_saved_mod(self.mods_root, "skins/1000/Moved Skin.fantome", missing=True)
        self.assertEqual(self.entry(self.annie, "Moved Skin")["ltkStamp"], [1, 2])

        self.service.attach_ltk_entry("skins/1000/Moved Skin.fantome", NEW_ID)

        entry = self.entry(self.annie, "Moved Skin")
        self.assertEqual(entry["ltkId"], NEW_ID)
        self.assertNotIn("missing", entry)
        self.assertNotIn("ltkStamp", entry)
        self.assertEqual(ModFacts.from_manifest(entry), FACTS)
        self.assertEqual(entry["updatedAt"], 1234.5)

    def test_attaching_refuses_anything_but_a_library_id(self):
        with self.assertRaises(ValueError):
            self.service.attach_ltk_entry("maps/Rift", "kept-id")

    def test_dropping_the_copy_keeps_the_image_and_the_entry(self):
        self.service.attach_ltk_entry("skins/1000/Pending Skin.fantome", NEW_ID)

        self.assertTrue(self.service.drop_stored_copy("skins/1000/Pending Skin.fantome"))

        self.assertFalse(self.pending_archive.exists())
        self.assertEqual((self.annie / "Pending Skin.png").read_bytes(), PNG)
        moved = self.service.saved_mod("skins/1000/Pending Skin.fantome")
        self.assertEqual((moved.ltk_id, moved.stored, moved.display_name), (NEW_ID, None, "Pending!"))
        self.assertFalse(self.service.drop_stored_copy("skins/1000/Pending Skin.fantome"))

    def test_a_pending_copy_is_never_dropped(self):
        self.assertFalse(self.service.drop_stored_copy("skins/1000/Pending Skin.fantome"))
        self.assertFalse(self.service.drop_stored_copy("maps/Rift"))

        self.assertTrue(self.pending_archive.exists())
        self.assertTrue((self.maps / "Rift.fantome").exists())

    def test_a_dropped_folder_leaves_its_image_and_description_beside_the_manifest(self):
        folder = self.annie / "Old Folder"
        (folder / "META").mkdir()
        (folder / "META" / "image.png").write_bytes(PNG)
        (folder / "description.txt").write_text("An old one", encoding="utf-8")
        self.service.attach_ltk_entry("skins/1000/Old Folder", NEW_ID)

        self.assertTrue(self.service.drop_stored_copy("skins/1000/Old Folder"))

        self.assertFalse(folder.exists())
        self.assertEqual((self.annie / "Old Folder.png").read_bytes(), PNG)
        self.assertEqual((self.annie / "Old Folder.txt").read_text(encoding="utf-8"), "An old one")
        self.assertEqual(self.service.saved_mod("skins/1000/Old Folder.fantome").ltk_id, NEW_ID)


if __name__ == "__main__":
    unittest.main()
