
import hashlib
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from injection.loadingname import loading_name
from injection.mods import mod_facts
from injection.mods.mod_facts import ModFacts, compute_mod_facts, stamp_of
from injection.tests.test_ltf_session import FakeBridge, LtfSessionTestCase
from party.discovery import custom_mods
from test.test_loading_name import make_wad

PNG = b"\x89PNG\r\n\x1a\npreview"
KO_TABLE = loading_name._xxh64(b"data/menu/ko_kr/lol.stringtable")

SKIN_WITH_KOREAN_WAD = {
    "META/image.png": PNG,
    "META/info.json": json.dumps({"Name": "Shockblade Zed"}),
    "WAD/Global.ko_KR.wad.client": make_wad(b"RST", path_hash=KO_TABLE),
    "WAD/Zed.wad.client": make_wad(b"zed", path_hash=0x1234),
}


def make_archive(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def manifest_folder_hash(archive):
    """The folderHash and wadHashes earlier Roses wrote into a champion's
    manifest for the mod at *archive*: a renamed file is still matched to its
    entry by them, so the facts' full hash must be the same."""
    folder_hash, wad_hashes = hashlib.sha256(), {}
    with zipfile.ZipFile(archive) as packed:
        names = sorted((info.filename for info in packed.infolist() if not info.is_dir()), key=str.casefold)
        for name in names:
            if name.casefold() == "meta/image.png":
                continue
            digest = hashlib.sha256(packed.read(name))
            folder_hash.update(name.encode("utf-8") + b"\0" + digest.digest() + b"\0")
            if name.casefold().endswith((".wad", ".wad.client")):
                wad_hashes[name] = digest.hexdigest()
    return folder_hash.hexdigest(), wad_hashes


def make_folder(path, files):
    for name, data in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


class ComputeFactsTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)

    def test_an_archive_and_its_folder_have_the_same_facts(self):
        archive = make_archive(self.root / "Shockblade Zed.fantome", SKIN_WITH_KOREAN_WAD)
        folder = make_folder(self.root / "Shockblade Zed", SKIN_WITH_KOREAN_WAD)

        archive_facts, archive_hash, archive_wads = compute_mod_facts(archive)
        folder_facts, folder_hash, folder_wads = compute_mod_facts(folder)

        self.assertEqual(archive_facts, folder_facts)
        self.assertEqual(archive_hash, folder_hash)
        self.assertEqual(archive_wads, folder_wads)

    def test_the_full_hash_is_the_manifests_folder_hash(self):
        archive = make_archive(self.root / "Shockblade Zed.fantome", SKIN_WITH_KOREAN_WAD)

        _facts, full_hash, wad_hashes = compute_mod_facts(archive)

        self.assertEqual((full_hash, wad_hashes), manifest_folder_hash(archive))
        self.assertEqual(sorted(wad_hashes), ["WAD/Global.ko_KR.wad.client", "WAD/Zed.wad.client"])

    def test_the_language_table_is_what_the_loading_name_reads(self):
        archive = make_archive(self.root / "Shockblade Zed.fantome", SKIN_WITH_KOREAN_WAD)
        plain = make_archive(self.root / "Plain Zed.fantome", {
            "WAD/Global.en_US.wad.client": make_wad(b"font", path_hash=0x1234),
            "WAD/Zed.wad.client": b"zed",
        })

        facts, _, _ = compute_mod_facts(archive)
        plain_facts, _, _ = compute_mod_facts(plain)

        self.assertTrue(facts.ships_language_table)
        self.assertFalse(plain_facts.ships_language_table)
        for mod, found in ((archive, facts), (plain, plain_facts)):
            self.assertEqual(found.ships_language_table, loading_name.ships_language_table(mod))

    def test_a_mod_linked_without_its_extension_is_read_as_an_archive(self):
        linked_as_in_the_mods_folder = self.root / "Shockblade Zed"
        archive = make_archive(linked_as_in_the_mods_folder, SKIN_WITH_KOREAN_WAD)

        facts, _, _ = compute_mod_facts(archive)

        self.assertTrue(facts.ships_language_table, "its Korean WAD read")

    def test_a_mod_holding_only_its_preview_hashes_as_its_manifest_entry(self):
        archive = make_archive(self.root / "Preview.fantome", {"META/image.png": PNG})

        facts, full_hash, _ = compute_mod_facts(archive)

        self.assertFalse(facts.ships_language_table)
        self.assertIsNone(custom_mods.mod_hashes(archive)[0])
        self.assertEqual(full_hash, manifest_folder_hash(archive)[0])

    def test_a_modpkg_is_read_through_its_unpacked_files(self):
        from utils.tests.test_modpkg import SKIN0, Chunk, build_package

        package = self.root / "old-aatrox_1.2.0.modpkg"
        package.write_bytes(build_package([Chunk(SKIN0, b"skin" * 100)]))
        injection = self.root / "injection"
        injection.mkdir()

        with patch.object(mod_facts, "get_injection_dir", return_value=injection):
            _facts, full_hash, _ = compute_mod_facts(package)
            party_hash, _ = custom_mods.mod_hashes(package)

        self.assertEqual(full_hash[:32], party_hash, "the files it unpacks to, as party mode hashes them")
        self.assertEqual(list((injection / "mod_facts").iterdir()), [], "unpacked, then removed")

    def test_rose_s_start_removes_the_modpkgs_a_closed_rose_left_unpacked(self):
        injection = self.root / "injection"
        leftover = injection / "mod_facts" / "facts-0123abcd"
        (leftover / "WAD").mkdir(parents=True)
        (leftover / "WAD" / "Aatrox.wad.client").write_bytes(b"gigabytes")
        (injection / "mod_facts" / "facts-4567ef01").mkdir()

        with patch.object(mod_facts, "get_injection_dir", return_value=injection):
            mod_facts.remove_unpacked_leftovers()
            self.assertEqual(list((injection / "mod_facts").iterdir()), [])
            shutil.rmtree(injection)
            with self.subTest("none to remove"):
                mod_facts.remove_unpacked_leftovers()

    def test_a_mod_it_cannot_read_has_no_facts(self):
        broken = self.root / "Broken.fantome"
        broken.write_bytes(b"not a zip")

        with self.assertRaises(OSError):
            compute_mod_facts(self.root / "Gone.fantome")
        with self.assertRaises(zipfile.BadZipFile):
            compute_mod_facts(broken)

    def test_the_stamp_is_the_size_and_time_of_the_archive(self):
        archive = make_archive(self.root / "Shockblade Zed.fantome", SKIN_WITH_KOREAN_WAD)
        os.utime(archive, ns=(1_000_000_000, 2_000_000_000))

        self.assertEqual(stamp_of(archive), [archive.stat().st_size, 2_000_000_000])
        self.assertIsNone(stamp_of(self.root / "Gone.fantome"))
        self.assertIsNone(stamp_of(self.root), "a folder is no archive")


class ModpkgSessionTests(LtfSessionTestCase):
    def test_a_session_starting_while_a_modpkg_is_unpacked_leaves_its_files(self):
        """Each LTK session clears its staging folder as it starts: a sync
        reading a .modpkg LTK Manager holds during champion select read half
        a mod, then recorded the hashes of half a mod"""
        from utils.tests.test_modpkg import SKIN0, Chunk, build_package

        package = self.root / "old-aatrox_1.2.0.modpkg"
        package.write_bytes(build_package([Chunk(SKIN0, b"skin" * 100)]))
        injection = self.mods.parent
        real_extract = mod_facts.extract_modpkg

        def unpacked_as_a_session_starts(source, dest):
            real_extract(source, dest)
            self.overlay._end_session(self.overlay._start_ltf_session(report=False))

        with patch.object(mod_facts, "get_injection_dir", return_value=injection), \
                patch.object(mod_facts, "extract_modpkg", side_effect=unpacked_as_a_session_starts):
            _facts, full_hash, _ = compute_mod_facts(package)

        self.assertEqual(len(FakeBridge.created), 1, "a session did start")
        self.assertEqual(full_hash[:32], custom_mods.mod_hashes(package)[0], "all of it read")


class ManifestFactsTests(unittest.TestCase):
    FACTS = ModFacts(ships_language_table=True)

    def test_facts_survive_the_manifest(self):
        stored = json.loads(json.dumps({"name": "Zed", **self.FACTS.to_manifest()}))

        self.assertEqual(ModFacts.from_manifest(stored), self.FACTS)
        self.assertEqual(stored["shipsLanguageTable"], True)
        self.assertEqual(ModFacts.from_manifest(ModFacts(False).to_manifest()), ModFacts(False))

    def test_facts_can_go_into_an_injection_plan(self):
        self.assertEqual(len({self.FACTS, ModFacts(**vars(self.FACTS))}), 1)

    def test_an_entry_from_an_older_rose_has_no_facts(self):
        good = self.FACTS.to_manifest()
        for entry in (
            {},
            None,
            {"name": "Zed", "targets": [238001]},
            dict(good, shipsLanguageTable="yes"),
            dict(good, shipsLanguageTable=1),
        ):
            with self.subTest(entry=entry):
                self.assertIsNone(ModFacts.from_manifest(entry))

    def test_party_mode_hashes_with_the_same_functions(self):
        for name in ("_hash_stream", "_folder_content_hash", "_archive_content_hash"):
            self.assertIs(getattr(custom_mods, name), getattr(mod_facts, name))


if __name__ == "__main__":
    unittest.main()
