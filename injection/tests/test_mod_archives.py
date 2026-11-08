"""Rose keeps mods as the archives LTK Manager installs: nothing is unpacked
to be packed again (a voiceover pack took a minute, every game)."""

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
from injection.mods.mod_files import ModFiles, is_mod_archive
from injection.mods.mod_manager import ModManager
from injection.mods.storage import ModStorageService
from utils.core import historic, mod_historic
from utils.core.junction import link_or_extract

PNG = b"\x89PNG\r\n\x1a\npreview"


def make_archive(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


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

        link_or_extract(source, dest, cache_dir=cache)

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

        stored, name = self.service.import_category_mod_file("voiceover", source)

        self.assertEqual(name, "VO Korean")
        self.assertEqual(stored, self.service.mods_root / "voiceover" / "VO Korean.fantome")
        self.assertEqual(stored.read_bytes(), source.read_bytes())
        self.assertEqual(stored.with_suffix(".png").read_bytes(), PNG)  # for the mods UI
        listed = self.service.list_mods_for_category("voiceover")
        self.assertEqual([(m["name"], m["path"]) for m in listed], [("VO Korean", "voiceover/VO Korean.fantome")])

    def test_a_zip_is_stored_as_a_fantome(self):
        stored, _ = self.service.import_category_mod_file("maps", make_archive(self.root / "Rift.zip", VOICEOVER))
        self.assertEqual(stored.name, "Rift.fantome")

    def test_an_archive_without_its_info_is_packed_as_an_injection_packed_it(self):
        source = make_archive(self.root / "Rift.fantome", {"WAD/Map11.wad.client": b"map"})

        stored, _ = self.service.import_category_mod_file("maps", source)

        with ModFiles(stored) as files:
            self.assertEqual(files.read("WAD/Map11.wad.client"), b"map")
            # Named after the mod, as its folder named it, not after where it was unpacked
            self.assertEqual(json.loads(files.read("metadata.json")), {"name": "Rift"})

    def test_deflated_packed_wads_are_stored_once_at_import(self):
        # LTK Manager rewrites an archive whose packed WADs are deflated at every install
        source = self.root / "VO.fantome"
        with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in VOICEOVER.items():
                archive.writestr(name, data)

        stored, _ = self.service.import_category_mod_file("voiceover", source)

        with zipfile.ZipFile(stored) as archive:
            infos = {info.filename: info for info in archive.infolist()}
        self.assertEqual(infos["WAD/Ahri.ko_KR.wad.client"].compress_type, zipfile.ZIP_STORED)
        self.assertNotIn("metadata.json", infos)  # nothing added: the same mod for a friend's copy
        with ModFiles(stored) as files, ModFiles(source) as original:
            for name in VOICEOVER:
                self.assertEqual(files.read(name), original.read(name))

    def test_an_unsafe_archive_is_refused_and_nothing_is_left(self):
        source = make_archive(self.root / "Evil.fantome", {"../../evil.txt": b"x", "META/info.json": "{}"})

        with self.assertRaises(Exception):
            self.service.import_category_mod_file("maps", source)

        self.assertEqual([p.name for p in (self.service.mods_root / "maps").iterdir()], [])

    def test_a_name_taken_by_a_folder_mod_is_not_reused(self):
        (self.service.mods_root / "maps" / "Rift").mkdir()
        stored, name = self.service.import_category_mod_file("maps", make_archive(self.root / "Rift.fantome", VOICEOVER))
        self.assertEqual((name, stored.name), ("Rift (2)", "Rift (2).fantome"))

    def test_deleting_an_archive_mod_removes_what_sits_beside_it(self):
        stored, name = self.service.import_category_mod_file("voiceover", make_archive(self.root / "VO.fantome", VOICEOVER))
        stored.with_suffix(".txt").write_text("description", encoding="utf-8")

        self.assertTrue(self.service.delete_category_mod("voiceover", name))

        self.assertEqual([p.name for p in (self.service.mods_root / "voiceover").iterdir()],
                         [ModStorageService.CATEGORY_METADATA])
        self.assertEqual(self.service.list_mods_for_category("voiceover"), [])

    def test_a_skin_mod_archive_is_listed_and_deleted_by_its_name(self):
        stored, _manifest, name = self.service.import_mod_file(
            81, make_archive(self.root / "Arcane Ezreal.fantome", VOICEOVER), [81020])

        self.assertEqual([(e.mod_name, e.path) for e in self.service.list_mods_for_skin(81020)], [(name, stored)])
        self.assertTrue(self.service.delete_champion_mod(81, mod_name=name))
        self.assertFalse(stored.exists())
        self.assertFalse(stored.with_suffix(".png").exists())

    def test_an_archive_mods_image_is_set_beside_it(self):
        stored, _manifest, _name = self.service.import_mod_file(
            81, make_archive(self.root / "Ezreal.fantome", VOICEOVER), [81020])
        before = stored.read_bytes()
        relative = stored.relative_to(self.service.mods_root).as_posix()

        image = self.service.set_champion_mod_image(81, relative, PNG + b"new")

        self.assertEqual(image, stored.with_suffix(".png"))
        self.assertEqual(image.read_bytes(), PNG + b"new")
        self.assertEqual(stored.read_bytes(), before)  # LTK Manager installs it as it was

    def test_an_archive_and_its_folder_hash_the_same(self):
        archive = make_archive(self.root / "mod.fantome", VOICEOVER)
        folder = make_folder(self.root / "mod", VOICEOVER)
        self.assertEqual(self.service._hash_mod_folder(archive), self.service._hash_mod_folder(folder))


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
