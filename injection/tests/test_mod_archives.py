"""Rose keeps mods as the archives LTK Manager installs: nothing is unpacked
to be packed again (a voiceover pack took a minute, every game)."""

import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from injection.mods import conversion
from injection.mods.fantome import fantome_display_name, read_info, write_fantome_zip
from injection.mods.fingerprint import mod_fingerprint
from injection.mods.manifest import ltk_removals
from injection.mods.mod_facts import ModFacts, archive_index_hash, compute_mod_facts
from injection.mods.mod_files import ModFiles, is_mod_archive
from injection.mods.mod_manager import ModManager
from injection.mods.mod_source import LtkEntry, RoseFile
from injection.mods.storage import ModStorageService
from utils.core import historic, mod_historic
from utils.core.junction import link_or_extract

PNG = b"\x89PNG\r\n\x1a\npreview"
MOVED_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"
LOST_ID = "d6f841c7-140b-4ac2-a11c-b37e18eb8006"
VOICE_ID = "799b6c82-8324-4394-a0cf-ddebcd16eba7"
OLD_ID = "1beee5a2-6fe1-49e1-ba94-9d601ead2a0f"
FACTS = ModFacts(ships_language_table=False)


def make_archive(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def add_entries(manifest_path, mods, **root):
    """Add *mods* to a manifest (and *root* to its root), as Rose wrote them."""
    payload = (json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists()
               else {"version": 1, "mods": {}})
    payload["mods"].update(mods)
    payload.update(root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")


def make_folder(path, files):
    for name, data in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


VOICEOVER = {
    "META/info.json": json.dumps({"Name": "VO Korean"}),
    "META/image.png": PNG,
    "WAD/Ahri.ko_KR.wad.client": b"voice" * 100,
    "WAD/Map11.wad.client/data/loose.bin": b"loose",
}


class TempCase(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name).resolve()


class ModFilesTests(TempCase):
    def test_an_archive_reads_as_its_folder_would(self):
        archive = make_archive(self.root / "vo", VOICEOVER)  # no extension, as in the mods folder
        folder = make_folder(self.root / "folder", VOICEOVER)

        self.assertTrue(is_mod_archive(archive))
        self.assertFalse(is_mod_archive(folder))
        for mod in (archive, folder):
            with self.subTest(mod=mod.name), ModFiles(mod) as files:
                self.assertEqual(sorted(files.children("WAD")), ["Ahri.ko_KR.wad.client", "Map11.wad.client"])
                self.assertTrue(files.is_file("wad/ahri.KO_KR.wad.client"))  # as Windows compares paths
                self.assertTrue(files.is_dir("WAD/Map11.wad.client"))
                self.assertFalse(files.is_file("WAD/Map11.wad.client"))
                self.assertEqual(files.files_under("WAD/Map11.wad.client"), ["WAD/Map11.wad.client/data/loose.bin"])
                self.assertEqual(sorted(files.files_under()), sorted(VOICEOVER))
                self.assertEqual(files.read("META/image.png"), PNG)
                with self.assertRaises(FileNotFoundError):
                    files.read("META/missing.json")

    def test_the_mods_name_comes_from_its_archive(self):
        archive = make_archive(self.root / "vo", VOICEOVER)
        self.assertEqual(read_info(archive), {"Name": "VO Korean"})
        self.assertEqual(fantome_display_name(archive), "VO Korean")
        self.assertEqual(fantome_display_name(make_archive(self.root / "unnamed", {"WAD/a.wad.client": b"a"})),
                         "unnamed")

    def test_an_archive_has_a_fingerprint_of_its_own_content(self):
        first = make_archive(self.root / "a", VOICEOVER)
        same = make_archive(self.root / "b", VOICEOVER)
        other = make_archive(self.root / "c", {**VOICEOVER, "WAD/Ahri.ko_KR.wad.client": b"other"})

        self.assertEqual(mod_fingerprint(first), mod_fingerprint(same))
        self.assertNotEqual(mod_fingerprint(first), mod_fingerprint(other))


class LinkTests(TempCase):
    def test_an_archive_is_linked_into_the_mods_folder_not_extracted(self):
        source = make_archive(self.root / "mods" / "voiceover" / "VO Korean.fantome", VOICEOVER)
        dest = self.root / "injection" / "mods" / "VO Korean"
        dest.parent.mkdir(parents=True)
        cache = self.root / "injection" / ".extract_cache"

        link_or_extract(source, dest)

        self.assertTrue(dest.is_file())
        self.assertTrue(os.path.samefile(source, dest))  # a hard link: no copy, whatever the size
        self.assertFalse(cache.exists())

    def test_a_skin_archive_is_linked_under_the_skins_name(self):
        skin = make_archive(self.root / "skins" / "1" / "1001" / "1001.fantome", {"WAD/Annie.wad.client": b"skin"})

        linked = ModManager(self.root / "injection" / "mods").link_archive(skin)

        self.assertEqual(linked, self.root / "injection" / "mods" / "1001")
        self.assertTrue(os.path.samefile(skin, linked))
        linked.unlink()  # the injection's cleanup removes the link only
        self.assertTrue(skin.is_file())


class StorageTests(TempCase):
    def setUp(self):
        super().setUp()
        self.service = ModStorageService(self.root / "mods")

    def test_an_imported_fantome_is_stored_as_it_is(self):
        source = make_archive(self.root / "VO Korean.fantome", VOICEOVER)

        stored, name, _ = self.service.import_category_mod_file("voiceover", source)

        self.assertEqual(name, "VO Korean")
        self.assertEqual(stored, self.service.mods_root / "voiceover" / "VO Korean.fantome")
        self.assertEqual(stored.read_bytes(), source.read_bytes())
        self.assertEqual(stored.with_suffix(".png").read_bytes(), PNG)  # for the mods UI
        listed = self.service.list_mods_for_category("voiceover")
        self.assertEqual([(m["name"], m["path"]) for m in listed], [("VO Korean", "voiceover/VO Korean.fantome")])

    def test_a_zip_is_stored_as_a_fantome(self):
        stored, *_ = self.service.import_category_mod_file("maps", make_archive(self.root / "Rift.zip", VOICEOVER))
        self.assertEqual(stored.name, "Rift.fantome")

    def test_an_archive_without_its_info_is_packed_as_an_injection_packed_it(self):
        source = make_archive(self.root / "Rift.fantome", {"WAD/Map11.wad.client": b"map"})

        stored, *_ = self.service.import_category_mod_file("maps", source)

        with ModFiles(stored) as files:
            self.assertEqual(files.read("WAD/Map11.wad.client"), b"map")
            # Named after the mod, as its folder named it, not after where it was unpacked
            self.assertEqual(json.loads(files.read("metadata.json")), {"name": "Rift"})

    def deflated(self, name="VO.fantome"):
        """A voiceover pack whose packed WADs are deflated, as mods are shared"""
        source = self.root / "Downloads" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
            for entry, data in VOICEOVER.items():
                archive.writestr(entry, data)
        return source

    def test_a_fantome_with_deflated_wads_is_stored_as_it_came(self):
        """LTK Manager stores its packed WADs uncompressed as it imports it: Rose rewrote it (25 s for 3 GB)"""
        source = self.deflated()

        stored, *_ = self.service.import_category_mod_file("voiceover", source)

        self.assertEqual(stored.read_bytes(), source.read_bytes())
        self.assertFalse(os.path.samefile(stored, source), "a copy of its own")

    def test_a_mod_ltk_manager_takes_as_it_is_added_is_linked_as_picked(self):
        """LTK Manager copies it into its library: Rose copying it first wrote it twice"""
        source = self.deflated()
        before = source.read_bytes()

        stored, name, _ = self.service.import_category_mod_file("voiceover", source, as_picked=True)

        self.assertTrue(os.path.samefile(stored, source), "linked, not copied")
        mod = self.service.saved_mod(f"voiceover/{name}.fantome")
        self.assertTrue(mod.pending)
        self.assertEqual(mod.facts, compute_mod_facts(source)[0])
        self.assertTrue(self.service.attach_ltk_entry(mod.identity, MOVED_ID))
        self.assertTrue(self.service.drop_stored_copy(mod.identity))
        self.assertEqual(source.read_bytes(), before, "the file the user picked is theirs")

    def test_a_linked_mod_left_in_rose_is_copied_into_it(self):
        source = self.deflated()
        before = source.read_bytes()
        stored, name, _ = self.service.import_category_mod_file("voiceover", source, as_picked=True)

        self.service.keep_own_copy(f"voiceover/{name}.fantome")

        self.assertFalse(os.path.samefile(stored, source))
        self.assertEqual(stored.read_bytes(), before)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(self.service.saved_mod(f"voiceover/{name}.fantome").rose_copy, stored)

    def test_a_copy_rose_owns_already_is_left_as_it_is(self):
        stored, name, _ = self.service.import_category_mod_file("voiceover", self.deflated())
        written = stored.stat().st_mtime_ns

        with patch("injection.mods.storage.shutil.copyfile") as copy:
            self.service.keep_own_copy(f"voiceover/{name}.fantome")

        copy.assert_not_called()
        self.assertEqual(stored.stat().st_mtime_ns, written)

    def test_an_unsafe_archive_is_refused_and_nothing_is_left(self):
        source = make_archive(self.root / "Evil.fantome", {"../../evil.txt": b"x", "META/info.json": "{}"})

        with self.assertRaises(Exception):
            self.service.import_category_mod_file("maps", source)

        self.assertEqual([p.name for p in (self.service.mods_root / "maps").iterdir()], [])

    def test_a_name_taken_by_a_folder_mod_is_not_reused(self):
        (self.service.mods_root / "maps" / "Rift").mkdir()
        stored, name, _ = self.service.import_category_mod_file("maps", make_archive(self.root / "Rift.fantome", VOICEOVER))
        self.assertEqual((name, stored.name), ("Rift (2)", "Rift (2).fantome"))

    def test_deleting_an_archive_mod_removes_what_sits_beside_it(self):
        stored, name, _ = self.service.import_category_mod_file("voiceover", make_archive(self.root / "VO.fantome", VOICEOVER))
        stored.with_suffix(".txt").write_text("description", encoding="utf-8")

        self.assertTrue(self.service.delete_category_mod("voiceover", name))

        self.assertEqual([p.name for p in (self.service.mods_root / "voiceover").iterdir()],
                         [ModStorageService.CATEGORY_METADATA])
        self.assertEqual(self.service.list_mods_for_category("voiceover"), [])

    def test_a_skin_mod_archive_is_listed_and_deleted_by_its_name(self):
        stored, name, _ = self.service.import_mod_file(
            81, make_archive(self.root / "Arcane Ezreal.fantome", VOICEOVER), [81020])

        self.assertEqual([(e.mod_name, e.path) for e in self.service.list_mods_for_skin(81020)], [(name, stored)])
        self.assertTrue(self.service.delete_champion_mod(81, mod_name=name))
        self.assertFalse(stored.exists())
        self.assertFalse(stored.with_suffix(".png").exists())

    def test_an_archive_mods_image_is_set_beside_it(self):
        stored, _name, _ = self.service.import_mod_file(
            81, make_archive(self.root / "Ezreal.fantome", VOICEOVER), [81020])
        before = stored.read_bytes()
        relative = stored.relative_to(self.service.mods_root).as_posix()

        image = self.service.set_champion_mod_image(81, relative, PNG + b"new")

        self.assertEqual(image, stored.with_suffix(".png"))
        self.assertEqual(image.read_bytes(), PNG + b"new")
        self.assertEqual(stored.read_bytes(), before)  # LTK Manager installs it as it was



class AddTests(TempCase):
    """An added mod is registered with what Rose needs to know about it, read
    once: a category's mod moves into LTK Manager, and Rose keeps no copy to
    read it from. Its name is its own in its folder, against the mods LTK
    Manager holds (or lost) too; a skin the folder holds already is not added
    twice, a category's mod added again is another mod"""

    def setUp(self):
        super().setUp()
        self.service = ModStorageService(self.root / "mods")
        self.maps = self.service.mods_root / "maps"
        self.maps_manifest = self.maps / ModStorageService.CATEGORY_METADATA
        self.ezreal = self.service.get_champion_dir(81)
        self.skins_manifest = self.ezreal / ModStorageService.TARGET_METADATA

    @staticmethod
    def entries(manifest_path):
        return json.loads(manifest_path.read_text(encoding="utf-8"))["mods"]

    def add_map(self, name="Rift"):
        return self.service.import_category_mod_file("maps", make_archive(self.root / f"{name}.fantome", VOICEOVER))

    def lost_map(self, **extra):
        add_entries(self.maps_manifest, {"Rift": {"name": "Rift", "path": "Rift", "ltkId": LOST_ID, "missing": True,
                                                  "displayName": "My Rift", **extra}})

    def test_what_rose_needs_and_the_date_are_written_as_the_mod_is_added(self):
        """A category's mod its facts; a custom skin its targets, the hash of the
        file picked (party mode) and its archive's index (a renamed skin)"""
        source = make_archive(self.root / "VO Korean.fantome", VOICEOVER)

        stored, name, _ = self.service.import_category_mod_file("voiceover", source)
        skin, skin_name, _ = self.service.import_mod_file(81, source, [81020])

        entry = self.entries(stored.parent / ModStorageService.CATEGORY_METADATA)[name]
        self.assertEqual(ModFacts.from_manifest(entry), compute_mod_facts(source)[0])
        self.assertEqual(entry["updatedAt"], stored.stat().st_mtime)
        skin_entry = self.entries(self.skins_manifest)[skin_name]
        self.assertEqual(skin_entry, {
            "name": skin_name,
            "targets": [81020],
            "sourceHash": hashlib.sha256(source.read_bytes()).hexdigest(),
            "indexHash": archive_index_hash(skin),
            "updatedAt": skin.stat().st_mtime,
        })

    def test_a_name_ltk_manager_holds_is_not_taken_again(self):
        add_entries(self.maps_manifest, {"Rift": {"name": "Rift", "path": "Rift", "ltkId": MOVED_ID}})

        stored, name, _ = self.add_map()

        self.assertEqual((name, stored.name), ("Rift (2)", "Rift (2).fantome"))
        self.assertEqual(self.entries(self.maps_manifest)["Rift"]["ltkId"], MOVED_ID)
        self.assertEqual(ltk_removals(self.service.mods_root), [])

    def test_a_name_an_image_or_a_description_holds_is_not_taken(self):
        (self.maps / "Rift.txt").write_text("Somebody's description", encoding="utf-8")
        (self.maps / "Abyss.webp").write_bytes(b"somebody's image")

        self.assertEqual(self.add_map("Rift")[1], "Rift (2)")
        abyss = make_archive(self.root / "Abyss.fantome", {**VOICEOVER, "WAD/Map12.wad.client": b"abyss"})
        self.assertEqual(self.service.import_category_mod_file("maps", abyss)[1], "Abyss (2)")
        self.assertEqual((self.maps / "Rift.txt").read_text(encoding="utf-8"), "Somebody's description")

    def test_a_mod_added_again_after_ltk_manager_lost_it_is_another_mod(self):
        """The lost one, the same mod, keeps its name and stays listed as
        missing until the user deletes it"""
        source = make_archive(self.root / "Rift.fantome", VOICEOVER)
        self.lost_map(folderHash=compute_mod_facts(source)[1])
        lost = self.entries(self.maps_manifest)["Rift"]

        stored, name, _ = self.service.import_category_mod_file("maps", source)

        self.assertEqual((name, stored.name), ("Rift (2)", "Rift (2).fantome"))
        mods = self.entries(self.maps_manifest)
        self.assertEqual(mods["Rift"], lost)
        listed = {mod.name: mod for mod in self.service.saved_mods("maps")}
        self.assertEqual((listed["Rift"].source, listed["Rift"].display_name),
                         (LtkEntry(LOST_ID, None, gone_at_last_sync=True), "My Rift"))
        self.assertEqual(listed[name].source, RoseFile.at(stored))
        self.assertEqual(ltk_removals(self.service.mods_root), [])

    def test_a_rejected_add_leaves_the_lost_mod_of_its_name_as_it_was(self):
        """LTK Manager rejects the mod added again: the add deletes it, and the
        lost one keeps its entry, image, description and display name"""
        self.lost_map()
        (self.maps / "Rift.png").write_bytes(PNG + b"mine")
        (self.maps / "Rift.txt").write_text("My notes", encoding="utf-8")
        before = self.entries(self.maps_manifest)

        stored, name, _ = self.add_map()
        self.assertEqual(name, "Rift (2)")
        self.assertTrue(self.service.delete_category_mod("maps", name))

        self.assertEqual(self.entries(self.maps_manifest), before)
        self.assertEqual(sorted(p.name for p in self.maps.iterdir()),
                         sorted([self.maps_manifest.name, "Rift.png", "Rift.txt"]))
        self.assertEqual((self.maps / "Rift.png").read_bytes(), PNG + b"mine")
        self.assertEqual((self.maps / "Rift.txt").read_text(encoding="utf-8"), "My notes")
        lost = self.service.saved_mod("maps/Rift.fantome")
        self.assertEqual((lost.ltk_id, lost.missing, lost.display_name), (LOST_ID, True, "My Rift"))
        self.assertEqual(ltk_removals(self.service.mods_root), [])

    def test_a_skin_is_added_without_hashing_its_content(self):
        """The file picked is hashed once (party mode); a renamed skin is found by its archive's index"""
        source = make_archive(self.root / "Ezreal.fantome", VOICEOVER)

        with patch("injection.mods.mod_facts._hash_stream", side_effect=AssertionError("content hashed")):
            stored, name, _ = self.service.import_mod_file(81, source, [81020])
            renamed = stored.rename(stored.with_name("Renamed Ezreal.fantome"))
            listed = self.service.saved_mod(renamed.relative_to(self.service.mods_root).as_posix())

        self.assertEqual((listed.key, listed.target_skin_ids), (name, (81020,)))

    def test_a_renamed_skin_an_older_rose_added_is_still_found_by_its_content(self):
        source = make_archive(self.root / "Ezreal.fantome", VOICEOVER)
        renamed = make_archive(self.ezreal / "Renamed Ezreal.fantome", VOICEOVER)
        add_entries(self.skins_manifest, {"old-key": {"name": "Ezreal", "targets": [81020],
                                                      "folderHash": compute_mod_facts(source)[1]}},
                    championId=81, targets=[])

        listed = self.service.saved_mod(renamed.relative_to(self.service.mods_root).as_posix())

        self.assertEqual((listed.key, listed.target_skin_ids), ("old-key", (81020,)))

    def test_the_same_skin_added_again_is_another_skin(self):
        """The user's problem: the saved one keeps its targets"""
        source = make_archive(self.root / "Ezreal.fantome", VOICEOVER)
        first, name, _ = self.service.import_mod_file(81, source, [81020])

        again = self.service.import_mod_file(81, source, [81021])

        self.assertEqual((again.name, again.nothing_added), ("Ezreal (2)", False))
        mods = self.entries(self.skins_manifest)
        self.assertEqual({key: entry["targets"] for key, entry in mods.items()},
                         {"Ezreal": [81020], "Ezreal (2)": [81021]})

    def test_a_category_mod_is_registered_without_hashing_its_content(self):
        """Hashing a voiceover pack took seconds; only a custom skin's hashes are ever read"""
        with patch("injection.mods.mod_facts._hash_stream", side_effect=AssertionError("hashed")), \
                patch("injection.mods.storage.hashlib.file_digest", side_effect=AssertionError("hashed")):
            stored, name, _ = self.add_map()

        entry = self.entries(self.maps_manifest)[name]
        self.assertEqual(ModFacts.from_manifest(entry), compute_mod_facts(stored)[0])
        for key in ("folderHash", "sourceHash", "wadHashes"):
            self.assertNotIn(key, entry)

    def test_the_same_category_mod_added_again_is_another_mod(self):
        """The one LTK Manager holds, or still Rose's, is left as it is"""
        first, name, _ = self.add_map()
        relative = first.relative_to(self.service.mods_root).as_posix()
        self.service.attach_ltk_entry(relative, MOVED_ID)
        self.service.drop_stored_copy(relative)

        again = self.add_map("Rift")
        pending_again = self.add_map("Rift")

        self.assertEqual([(added.name, added.nothing_added) for added in (again, pending_again)],
                         [("Rift (2)", False), ("Rift (3)", False)])
        mods = self.entries(self.maps_manifest)
        self.assertEqual(mods[name]["ltkId"], MOVED_ID)
        self.assertEqual(sorted(mods), ["Rift", "Rift (2)", "Rift (3)"])
        self.assertTrue(again.identity_path.is_file())
        self.assertEqual(ltk_removals(self.service.mods_root), [])


class ManifestListingTests(TempCase):
    """Mods are listed from their manifests: one LTK Manager holds has no file
    in Rose, and its image and description sit beside the manifest"""

    def setUp(self):
        super().setUp()
        self.service = ModStorageService(self.root / "mods")
        self.ezreal = self.service.get_champion_dir(81)
        self.skin, self.skin_name, _ = self.service.import_mod_file(
            81, make_archive(self.root / "Arcane Ezreal.fantome", VOICEOVER), [81020])
        self.skin_identity = self.skin.relative_to(self.service.mods_root).as_posix()
        self.skins_manifest = self.ezreal / ModStorageService.TARGET_METADATA
        self.voiceover = self.service.mods_root / "voiceover"
        add_entries(self.voiceover / ModStorageService.CATEGORY_METADATA, {
            "VO Korean": {"name": "VO Korean", "path": "VO Korean", "ltkId": VOICE_ID, **FACTS.to_manifest()},
        })
        (self.voiceover / "VO Korean.txt").write_text("Korean voices", encoding="utf-8")

    def manifest_mods(self):
        return json.loads(self.skins_manifest.read_text(encoding="utf-8"))["mods"]

    def champion_mods(self):
        return {entry.mod_name: entry for entry in self.service.list_mods_for_champion(81)}

    def skin_hash(self):
        return next(key for key, entry in self.manifest_mods().items() if entry["name"] == self.skin_name)

    def test_a_custom_skin_is_listed_by_its_file(self):
        skin = self.champion_mods()[self.skin_name]

        self.assertEqual((skin.path, skin.source), (self.skin, RoseFile(self.skin, self.skin_name)))
        self.assertEqual(skin.updated_at, self.skin.stat().st_mtime)
        self.assertEqual((skin.skin_id, skin.target_skin_ids), (81000, (81020,)))

    def test_a_mod_ltk_manager_lost_is_listed_as_missing(self):
        add_entries(self.voiceover / ModStorageService.CATEGORY_METADATA, {
            "Lost VO": {"name": "Lost VO", "path": "Lost VO", "ltkId": LOST_ID, "missing": True},
        })

        lost = {mod["name"]: mod for mod in self.service.list_mods_for_category("voiceover")}["Lost VO"]

        self.assertEqual((lost["ltkId"], lost["missing"], lost["pending"]), (LOST_ID, True, False))
        self.assertFalse(self.service.saved_mod("voiceover/Lost VO").source.available)

    def test_a_file_nobody_registered_is_listed_with_the_folders_targets(self):
        make_archive(self.ezreal / "Dropped.fantome", VOICEOVER)
        self.assertNotIn("Dropped", self.champion_mods())

        add_entries(self.skins_manifest, {}, targets=[81020])
        self.service._champion_listing_cache.clear()

        dropped = self.champion_mods()["Dropped"]
        self.assertEqual(dropped.target_skin_ids, (81020,))
        self.assertEqual(dropped.source, RoseFile(self.ezreal / "Dropped.fantome", "Dropped"))

    def test_a_categorys_listing_says_where_each_mod_is(self):
        self.service.import_category_mod_file("voiceover", make_archive(self.root / "VO Pending.fantome", VOICEOVER))

        listed = {mod["name"]: mod for mod in self.service.list_mods_for_category("voiceover")}

        self.assertEqual(listed["VO Korean"], {
            "id": "voiceover/VO Korean.fantome", "name": "VO Korean", "displayName": None,
            "path": "voiceover/VO Korean.fantome", "updatedAt": 0.0, "description": "Korean voices",
            "ltkId": VOICE_ID, "missing": False, "pending": False, "facts": FACTS.to_manifest(),
        })
        self.assertEqual((listed["VO Pending"]["pending"], listed["VO Pending"]["ltkId"]), (True, None))
        self.assertEqual(listed["VO Pending"]["facts"],
                         compute_mod_facts(self.root / "VO Pending.fantome")[0].to_manifest())

    def test_deleting_takes_out_every_entry_under_the_mods_name(self):
        voice_manifest = self.voiceover / ModStorageService.CATEGORY_METADATA
        add_entries(voice_manifest, {"older-key": {"name": "VO Korean", "path": "VO Korean", "ltkId": OLD_ID}})

        self.assertTrue(self.service.delete_category_mod("voiceover", "VO Korean"))

        self.assertEqual(json.loads(voice_manifest.read_text(encoding="utf-8"))["mods"], {})
        self.assertEqual(sorted(ltk_removals(self.service.mods_root)), sorted([VOICE_ID, OLD_ID]))

    def test_deleting_a_custom_skin_takes_its_file_and_queues_nothing(self):
        self.assertTrue(self.service.delete_champion_mod(81, mod_name=self.skin_name))

        self.assertFalse(self.skin.exists())
        self.assertFalse(self.skin.with_suffix(".png").exists())
        self.assertEqual(self.manifest_mods(), {})
        self.assertEqual(ltk_removals(self.service.mods_root), [])

    def test_deleting_a_folder_mod_leaves_a_mod_folder_named_like_its_description(self):
        legacy = self.service.get_skin_dir(81020)
        make_folder(legacy / "Example", VOICEOVER)
        sibling = make_folder(legacy / "Example.txt", VOICEOVER)

        self.assertTrue(self.service.delete_champion_mod(81, relative_path="skins/81020/Example"))

        self.assertFalse((legacy / "Example").exists())
        self.assertEqual(len([path for path in sibling.rglob("*") if path.is_file()]), len(VOICEOVER))

    def test_a_category_mod_ltk_manager_holds_is_deleted_by_its_name(self):
        self.assertTrue(self.service.delete_category_mod("voiceover", "VO Korean"))

        self.assertEqual(self.service.list_mods_for_category("voiceover"), [])
        self.assertFalse((self.voiceover / "VO Korean.txt").exists())
        self.assertEqual(ltk_removals(self.service.mods_root), [VOICE_ID])

    def test_another_champions_mod_or_an_unknown_one_is_not_deleted(self):
        self.assertFalse(self.service.delete_champion_mod(82, relative_path=self.skin_identity))
        self.assertFalse(self.service.delete_champion_mod(81, mod_name="Never Added"))
        self.assertFalse(self.service.delete_category_mod("voiceover", f"../skins/81000/{self.skin_name}"))

        self.assertTrue(self.skin.exists())
        self.assertEqual([entry["name"] for entry in self.manifest_mods().values()], [self.skin_name])
        self.assertEqual(ltk_removals(self.service.mods_root), [])

    def test_a_mod_is_renamed_by_its_identity_and_keeps_its_entry(self):
        self.assertEqual(self.service.set_champion_mod_display_name(81, " Shiny ", relative_path=self.skin_identity),
                         "Shiny")
        self.assertEqual(self.service.set_category_mod_display_name("voiceover", "VO Korean", "Korean"), "Korean")

        skin = self.manifest_mods()[self.skin_hash()]
        self.assertEqual((skin["displayName"], skin["indexHash"]), ("Shiny", archive_index_hash(self.skin)))
        self.assertEqual(self.champion_mods()[self.skin_name].display_name, "Shiny")
        voice = json.loads((self.voiceover / ModStorageService.CATEGORY_METADATA).read_text(encoding="utf-8"))
        self.assertEqual((voice["mods"]["VO Korean"]["displayName"], voice["mods"]["VO Korean"]["ltkId"]),
                         ("Korean", VOICE_ID))
        with self.assertRaises(ValueError):
            self.service.set_champion_mod_display_name(82, "Not mine", relative_path=self.skin_identity)

    def test_retargeting_a_custom_skin_keeps_its_entry(self):
        self.service.set_champion_mod_display_name(81, "Arcane!", relative_path=self.skin_identity)

        self.service.set_champion_target_ids(81, [81022, 81021], mod_name=self.skin_name)

        skin = self.manifest_mods()[self.skin_hash()]
        self.assertEqual((skin["targets"], skin["indexHash"], skin["displayName"]),
                         ([81021, 81022], archive_index_hash(self.skin), "Arcane!"))
        self.assertEqual(self.champion_mods()[self.skin_name].target_skin_ids, (81021, 81022))


class ConversionTests(TempCase):
    """Mods an earlier Rose stored as folders become archives when Rose starts"""

    def setUp(self):
        super().setUp()
        self.service = ModStorageService(self.root / "mods")
        for module in (historic, mod_historic):
            patcher = patch.object(module, "get_user_data_dir", return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(conversion, "get_injection_dir", return_value=self.root / "injection")
        patcher.start()
        self.addCleanup(patcher.stop)

    def convert(self):
        return conversion.convert_folder_mods(self.service)

    def test_a_folder_becomes_the_archive_of_its_files(self):
        folder = make_folder(self.service.mods_root / "voiceover" / "VO Korean 16.22.0",
                             {**VOICEOVER, "description.txt": b"Korean voices"})

        self.assertEqual(self.convert(), 1)

        archive = self.service.mods_root / "voiceover" / "VO Korean 16.22.0.fantome"
        self.assertFalse(folder.exists())
        with ModFiles(archive) as files:
            # The folder's files and nothing else: a friend's copy hashes the same
            self.assertEqual(sorted(files.files_under()), sorted([*VOICEOVER, "description.txt"]))
            self.assertEqual(files.read("WAD/Ahri.ko_KR.wad.client"), b"voice" * 100)
        self.assertEqual(archive.with_suffix(".png").read_bytes(), PNG)
        self.assertEqual(archive.with_suffix(".txt").read_text(encoding="utf-8"), "Korean voices")
        self.assertEqual(self.convert(), 0)  # once

    def test_a_folder_without_its_info_gets_the_metadata_an_injection_added(self):
        make_folder(self.service.mods_root / "maps" / "Rift", {"WAD/Map11.wad.client": b"map"})

        self.convert()

        with ModFiles(self.service.mods_root / "maps" / "Rift.fantome") as files:
            self.assertEqual(json.loads(files.read("metadata.json"))["name"], "Rift")

    def test_the_converted_mods_stay_listed_and_selected(self):
        self.service.import_category_mod_file("maps", make_archive(self.root / "Old.fantome", VOICEOVER))
        make_folder(self.service.mods_root / "maps" / "Rift", VOICEOVER)
        manifest = self.service.mods_root / "maps" / ModStorageService.CATEGORY_METADATA
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["mods"]["Rift"] = {"name": "Rift", "path": "Rift"}
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        make_folder(self.service.get_champion_dir(75) / "Nasus", VOICEOVER)
        mod_historic.write_historic_mod("map", "maps/Rift")
        mod_historic.write_historic_mod("voiceover", ["voiceover/Gone", "maps/Rift"])
        historic.write_historic_entry(75, "path:skins/75000/Nasus")
        historic.write_historic_entry(81, 81020)

        self.assertEqual(self.convert(), 2)

        self.assertEqual([m["path"] for m in self.service.list_mods_for_category("maps")],
                         ["maps/Old.fantome", "maps/Rift.fantome"])
        self.assertEqual(mod_historic.get_historic_mod("map"), "maps/Rift.fantome")
        self.assertEqual(mod_historic.get_historic_mod("voiceover"), ["voiceover/Gone", "maps/Rift.fantome"])
        self.assertEqual(historic.get_historic_skin_for_champion(75), "path:skins/75000/Nasus.fantome")
        self.assertEqual(historic.get_historic_skin_for_champion(81), 81020)

    def test_a_folder_whose_archive_exists_is_left_alone(self):
        folder = make_folder(self.service.mods_root / "maps" / "Rift", VOICEOVER)
        make_archive(self.service.mods_root / "maps" / "Rift.fantome", {"WAD/other.wad.client": b"x"})

        self.assertEqual(self.convert(), 0)
        self.assertTrue(folder.is_dir())

    def test_a_folder_that_cannot_be_packed_stays_a_folder(self):
        folder = make_folder(self.service.mods_root / "maps" / "Rift", VOICEOVER)

        with patch("injection.mods.storage.write_fantome_zip", side_effect=OSError("disk full")), \
                self.assertLogs(level="WARNING"):
            self.assertEqual(self.convert(), 0)

        self.assertTrue(folder.is_dir())
        self.assertEqual(sorted(p.name for p in folder.parent.iterdir()), ["Rift"])

    def test_a_folder_rose_cannot_read_is_never_taken_for_an_empty_one(self):
        # A folder an earlier Rose made with tempfile.mkdtemp is readable by its own account only
        folder = make_folder(self.service.mods_root / "maps" / "Rift", VOICEOVER)

        def walk(top, onerror=None):
            onerror(PermissionError(13, "Access is denied", str(top)))
            yield from ()

        with patch("injection.mods.storage.os.walk", walk), self.assertLogs(level="WARNING"):
            self.assertEqual(self.convert(), 0)

        self.assertEqual(sorted(p.name for p in folder.parent.iterdir()), ["Rift"])
        self.assertEqual((folder / "WAD" / "Ahri.ko_KR.wad.client").read_bytes(), b"voice" * 100)

    def test_a_folder_stays_unless_its_archive_holds_all_its_files(self):
        folder = make_folder(self.service.mods_root / "maps" / "Rift", VOICEOVER)

        def pack_part(mod_folder, dest, metadata=True, name=None):
            make_archive(dest, {"META/info.json": VOICEOVER["META/info.json"]})

        with patch("injection.mods.storage.write_fantome_zip", pack_part), self.assertLogs(level="WARNING"):
            self.assertEqual(self.convert(), 0)

        self.assertEqual(sorted(p.name for p in folder.parent.iterdir()), ["Rift"])
        self.assertEqual(len([path for path in folder.rglob("*") if path.is_file()]), len(VOICEOVER))

    def test_an_empty_folder_is_left_as_it_is(self):
        (self.service.mods_root / "maps" / "Empty").mkdir()

        self.assertEqual(self.convert(), 0)

        self.assertEqual([p.name for p in (self.service.mods_root / "maps").iterdir()], ["Empty"])

    def test_a_conversion_stopped_before_the_archive_was_in_place_is_undone(self):
        maps = self.service.mods_root / "maps"
        make_folder(maps / ".rose-convert-Rift.old", VOICEOVER)
        (maps / ".rose-convert-Rift.tmp").write_bytes(b"half an archive")

        self.service.folder_mods()

        self.assertEqual(sorted(p.name for p in maps.iterdir()), ["Rift"])

    def test_a_conversion_stopped_after_the_archive_was_in_place_is_finished(self):
        maps = self.service.mods_root / "maps"
        make_folder(maps / ".rose-convert-Rift.old", VOICEOVER)
        write_fantome_zip(maps / ".rose-convert-Rift.old", maps / "Rift.fantome", metadata=False)

        self.assertEqual(self.service.folder_mods(), [])

        self.assertEqual(sorted(p.name for p in maps.iterdir()), ["Rift.fantome"])

    def test_the_old_extractions_are_removed_once(self):
        cache = self.root / "injection" / conversion.EXTRACT_CACHE
        make_folder(cache / "VO Korean", VOICEOVER)

        self.convert()
        self.assertEqual([p.name for p in cache.iterdir()], [conversion.EXTRACT_CACHE_CLEARED])

        make_folder(cache / "pack", {"META/info.json": "{}"})  # a .modpkg's, which is still extracted
        self.convert()
        self.assertTrue((cache / "pack").is_dir())


if __name__ == "__main__":
    unittest.main()
