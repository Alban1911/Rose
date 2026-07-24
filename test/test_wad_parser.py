import json
import struct
import time
import zipfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from injection.mods.storage import ModStorageService
from injection.mods.wad_extractor import extract_wad_to_directory
from injection.mods.wad_parser import (
    find_matching_wad_paths,
    hash_wad_path,
    read_wad_path_hashes,
    xxhash64,
)


def build_test_wad(*path_hashes: int) -> bytes:
    header = bytearray(0x110)
    header[0:2] = b"RW"
    header[2] = 3
    header[3] = 4
    struct.pack_into("<I", header, 0x10C, len(path_hashes))

    entries = bytearray()
    for path_hash in path_hashes:
        entry = bytearray(0x20)
        struct.pack_into("<Q", entry, 0, path_hash)
        entries.extend(entry)

    return bytes(header) + bytes(entries) + b"payload"


def write_test_wad(path: Path, *path_hashes: int) -> None:
    path.write_bytes(build_test_wad(*path_hashes))


def write_test_fantome(path: Path, wad_bytes: bytes = b"packed wad") -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("META/info.json", "{}")
        archive.writestr("WAD/Test.wad.client", wad_bytes)

def write_asset(root: Path, relative_path: str) -> None:
    path = root.joinpath(*relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"asset")



class WadParserTests(unittest.TestCase):
    def test_xxhash64_known_empty_value(self) -> None:
        self.assertEqual(xxhash64(b""), 0xEF46DB3751D8E999)

    def test_reads_toc_without_extracting_payload(self) -> None:
        archive_path = Path(tempfile.mktemp(suffix=".wad.client"))
        try:
            target_path = "data/characters/ahri/skins/skin33.bin"
            write_test_wad(archive_path, hash_wad_path(target_path))

            self.assertEqual(
                read_wad_path_hashes(archive_path),
                {hash_wad_path(target_path)},
            )
            self.assertTrue(archive_path.is_file())
        finally:
            archive_path.unlink(missing_ok=True)

    def test_wad_candidate_scan_is_capped_at_200_skin_numbers(self) -> None:
        candidates = ModStorageService._candidate_wad_skin_paths(901, "Smolder")
        self.assertEqual(len(candidates), 600)
        self.assertEqual(candidates[0], ("data/characters/smolder/skins/skin0.bin", 901000))
        self.assertEqual(candidates[1], ("data/characters/smolder/skins/skin00.bin", 901000))
        self.assertEqual(candidates[2], ("assets/characters/smolder/skins/skin0.bin", 901000))
        self.assertEqual(candidates[-1], ("assets/characters/smolder/skins/skin199.bin", 901199))
    def test_asset_path_scanner_supports_data_assets_and_padding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for relative_path in (
                "DATA/Characters/Syndra/Skins/Skin44/file.bin",
                "ASSETS/Characters/Syndra/Skins/Skin07/file.tex",
                "assets/characters/syndra/skins/skin7/file.skn",
                "assets/characters/syndra/skins/skin_07/file.bin",
                "assets/characters/syndra/skins/skin-08/file.bin",
                "temporary/syndra.wad.client/assets/characters/syndra/skins/skin09/file.tex",
                "data/characters/syndra/skins/skin44.bin",
                "assets/characters/lux/skins/skin07/file.tex",
            ):
                write_asset(root, relative_path)

            self.assertEqual(
                ModStorageService._skin_ids_from_asset_paths(root, 134, "Syndra"),
                {134007, 134008, 134009, 134044},
            )

    def test_path_only_wad_extractor_materializes_resolved_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wad_path = root / "Syndra.wad.client"
            output = root / "output"
            hashes = root / "hashes.game.txt"
            target_path = "assets/characters/syndra/skins/skin07/file.tex"
            write_test_wad(wad_path, hash_wad_path(target_path))
            hashes.write_text(
                f"{hash_wad_path(target_path):016x} {target_path}\n",
                encoding="utf-8",
            )

            extract_wad_to_directory(wad_path, output, hashes)

            self.assertTrue((output / target_path).is_file())
    def test_matches_candidate_skin_path(self) -> None:
        target_path = "data/characters/ahri/skins/skin33.bin"
        self.assertEqual(
            find_matching_wad_paths(
                {hash_wad_path(target_path)},
                [(target_path, 103033)],
            ),
            {103033},
        )

    def test_reads_real_v34_wad(self) -> None:
        wad_path = Path(
            r"C:\Users\Alban\AppData\Local\Rose\mods\skins\901000\Midnight Ink\WAD\Smolder.wad.client"
        )
        if not wad_path.is_file():
            self.skipTest("local Smolder WAD is not available")
        hashes = read_wad_path_hashes(wad_path)
        self.assertEqual(len(hashes), 40)
    def test_storage_resolves_wad_targets_without_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "103000" / "AhriMod"
            mod_dir.mkdir(parents=True)
            wad_path = mod_dir / "AhriMod.wad.client"
            write_test_wad(
                wad_path,
                hash_wad_path("data/characters/ahri/skins/skin33.bin"),
            )

            service = ModStorageService(mods_root)
            with mock.patch(
                "injection.mods.storage.extract_wad_to_directory"
            ) as extractor:
                entries = service.list_mods_for_skin(103000, "Ahri")
                extractor.assert_not_called()
            self.assertEqual(len(entries), 1)
            self.assertIn(103033, entries[0].affected_skin_ids)
            self.assertTrue(wad_path.is_file())
            self.assertFalse((mod_dir / "AhriMod.wad").exists())



    def test_extracted_paths_are_scoped_to_champion_data_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "901000" / "ZaahenMod"
            extracted_wad = mod_dir / "WAD" / "Zaahen.wad.client"
            (extracted_wad / "data" / "characters" / "zaahen" / "skins" / "skin12").mkdir(
                parents=True
            )
            (extracted_wad / "data" / "characters" / "zaahen" / "skins" / "skin12" / "vfx.bin").write_bytes(b"data")
            unrelated = mod_dir / "assets" / "rep" / "characters" / "ahri" / "skins" / "skin88"
            unrelated.mkdir(parents=True)
            (unrelated / "vfx.bin").write_bytes(b"unrelated")

            service = ModStorageService(mods_root)
            entries = service.list_mods_for_skin(901000, "Zaahen")
            self.assertEqual(entries[0].affected_skin_ids, (901012,))
            self.assertTrue(
                (mods_root / "skins" / "901000" / "rose_wad_targets.json").is_file()
            )
            self.assertTrue(
                all(
                    path.startswith(("data/characters/", "assets/characters/"))
                    for path, _ in service._candidate_wad_skin_paths(901, "Zaahen")
                )
            )

    def test_asset_target_overrides_storage_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "134000" / "SyndraMod"
            write_asset(
                mod_dir,
                "assets/characters/syndra/skins/skin44/file.tex",
            )

            service = ModStorageService(mods_root)
            try:
                entries = service.list_mods_for_skin(134000, "Syndra")
                self.assertEqual(entries[0].affected_skin_ids, (134044,))
            finally:
                service.stop()

    def test_empty_toc_uses_extraction_and_cleans_temporary_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "134000" / "SyndraMod"
            mod_dir.mkdir(parents=True)
            wad_path = mod_dir / "Syndra.wad.client"
            write_test_wad(
                wad_path,
                hash_wad_path("assets/characters/syndra/skins/skin07/custom.tex"),
            )
            extraction_roots: list[Path] = []

            def fake_extract(_wad_path: Path, output_directory: Path) -> None:
                extraction_roots.append(output_directory)
                write_asset(
                    output_directory,
                    "assets/characters/syndra/skins/skin07/file.tex",
                )

            service = ModStorageService(mods_root)
            try:
                with mock.patch(
                    "injection.mods.storage.extract_wad_to_directory",
                    side_effect=fake_extract,
                ) as extractor:
                    entries = service.list_mods_for_skin(134000, "Syndra")
                    extractor.assert_called_once()
                self.assertEqual(entries[0].affected_skin_ids, (134007,))
                self.assertFalse(extraction_roots[0].exists())
            finally:
                service.stop()

    def test_extraction_failure_uses_storage_fallback_and_is_not_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "901000" / "BrokenMod"
            mod_dir.mkdir(parents=True)
            wad_path = mod_dir / "Smolder.wad.client"
            write_test_wad(wad_path, hash_wad_path("unknown/file.bin"))
            extraction_roots: list[Path] = []

            def fail_extract(_wad_path: Path, output_directory: Path) -> None:
                extraction_roots.append(output_directory)
                raise RuntimeError("test extraction failure")

            service = ModStorageService(mods_root)
            try:
                with mock.patch(
                    "injection.mods.storage.extract_wad_to_directory",
                    side_effect=fail_extract,
                ):
                    entries = service.list_mods_for_skin(901000, "Smolder")
                self.assertEqual(entries[0].affected_skin_ids, (901000,))
                self.assertFalse(extraction_roots[0].exists())
                self.assertFalse((mods_root / "skins" / "901000" / "rose_wad_targets.json").exists())
            finally:
                service.stop()

    def test_extraction_targets_are_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "901000" / "ExtractedMod"
            mod_dir.mkdir(parents=True)
            wad_path = mod_dir / "Smolder.wad.client"
            write_test_wad(
                wad_path,
                hash_wad_path("assets/characters/smolder/skins/skin44/custom.tex"),
            )

            def fake_extract(_wad_path: Path, output_directory: Path) -> None:
                write_asset(
                    output_directory,
                    "assets/characters/smolder/skins/skin44/file.tex",
                )

            service = ModStorageService(mods_root)
            try:
                with mock.patch(
                    "injection.mods.storage.extract_wad_to_directory",
                    side_effect=fake_extract,
                ) as extractor:
                    first = service.list_mods_for_skin(901000, "Smolder")
                    second = service.list_mods_for_skin(901000, "Smolder")
                self.assertEqual(first[0].affected_skin_ids, (901044,))
                self.assertEqual(second[0].affected_skin_ids, (901044,))
                extractor.assert_called_once()
            finally:
                service.stop()

    def test_version_one_empty_cache_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            skin_dir = mods_root / "skins" / "901000"
            mod_dir = skin_dir / "LegacyCacheMod"
            mod_dir.mkdir(parents=True)
            wad_path = mod_dir / "Smolder.wad.client"
            write_test_wad(
                wad_path,
                hash_wad_path("assets/characters/smolder/skins/skin44/custom.tex"),
            )
            (skin_dir / "rose_wad_targets.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "championId": 901,
                        "mods": {
                            "LegacyCacheMod": {
                                "wadFiles": {},
                                "affectedSkinIds": [],
                            }
                            }
                        }
                ),
                encoding="utf-8",
            )

            def fake_extract(_wad_path: Path, output_directory: Path) -> None:
                write_asset(
                    output_directory,
                    "assets/characters/smolder/skins/skin44/file.tex",
                )

            service = ModStorageService(mods_root)
            try:
                with mock.patch(
                    "injection.mods.storage.extract_wad_to_directory",
                    side_effect=fake_extract,
                ) as extractor:
                    entries = service.list_mods_for_skin(901000, "Smolder")
                self.assertEqual(entries[0].affected_skin_ids, (901044,))
                extractor.assert_called_once()
            finally:
                service.stop()

    def test_wad_targets_are_cached_once_per_champion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            skin_dir = mods_root / "skins" / "901000"
            first_wad = skin_dir / "First" / "WAD" / "Smolder.wad.client"
            second_wad = skin_dir / "Second" / "WAD" / "Smolder.wad.client"
            first_wad.parent.mkdir(parents=True)
            second_wad.parent.mkdir(parents=True)
            write_test_wad(
                first_wad,
                hash_wad_path("data/characters/smolder/skins/skin12.bin"),
            )
            write_test_wad(
                second_wad,
                hash_wad_path("data/characters/smolder/skins/skin25.bin"),
            )

            service = ModStorageService(mods_root)
            try:
                entries = service.list_mods_for_skin(901000, "Smolder")
                self.assertEqual(len(entries), 2)
                cache_path = skin_dir / "rose_wad_targets.json"
                payload = json.loads(cache_path.read_text())
                self.assertEqual(set(payload["mods"]), {"First", "Second"})
                self.assertEqual(
                    payload["mods"]["First"]["affectedSkinIds"],
                    [901012],
                )
                self.assertEqual(
                    payload["mods"]["Second"]["affectedSkinIds"],
                    [901025],
                )
            finally:
                service.stop()
    def test_startup_prepares_existing_extracted_wad_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "901000" / "Existing"
            wad_path = mod_dir / "WAD" / "Smolder.wad.client"
            wad_path.parent.mkdir(parents=True)
            write_test_wad(
                wad_path,
                hash_wad_path("data/characters/smolder/skins/skin12.bin"),
            )

            service = ModStorageService(
                mods_root,
                champion_name_resolver=lambda champion_id: "Smolder",
            )
            try:
                cache_path = mods_root / "skins" / "901000" / "rose_wad_targets.json"
                self.assertTrue(cache_path.is_file())
                self.assertEqual(
                    json.loads(cache_path.read_text())["mods"]["Existing"]["affectedSkinIds"],
                    [901012],
                )
            finally:
                service.stop()
    def test_startup_reconciles_offline_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            skin_dir = mods_root / "skins" / "901000"
            skin_dir.mkdir(parents=True)
            existing = skin_dir / "Existing.fantome"
            write_test_fantome(existing)

            baseline = ModStorageService(mods_root)
            baseline.stop()
            self.assertTrue(existing.is_file())

            offline_archive = skin_dir / "Offline.fantome"
            write_test_fantome(offline_archive)
            service = ModStorageService(mods_root)
            try:
                self.assertFalse(offline_archive.exists())
                self.assertTrue(
                    (skin_dir / "Offline" / "WAD" / "Test.wad.client").is_file()
                )
                self.assertTrue(existing.is_file())
            finally:
                service.stop()

    def test_wad_target_cache_invalidates_when_wad_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            wad_path = mods_root / "skins" / "901000" / "Changing" / "WAD" / "Smolder.wad.client"
            wad_path.parent.mkdir(parents=True)
            write_test_wad(
                wad_path,
                hash_wad_path("data/characters/smolder/skins/skin12.bin"),
            )

            service = ModStorageService(mods_root)
            try:
                first = service.list_mods_for_skin(901000, "Smolder")
                self.assertEqual(first[0].affected_skin_ids, (901012,))

                write_test_wad(
                    wad_path,
                    hash_wad_path("data/characters/smolder/skins/skin25.bin"),
                )
                second = service.list_mods_for_skin(901000, "Smolder")
                self.assertEqual(second[0].affected_skin_ids, (901025,))
            finally:
                service.stop()
    def test_watcher_extracts_archive_added_while_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            skin_dir = mods_root / "skins" / "901000"
            skin_dir.mkdir(parents=True)
            service = ModStorageService(mods_root, watch_archives=True)
            archive = skin_dir / "Online.fantome"
            write_test_fantome(archive)
            target_wad = skin_dir / "Online" / "WAD" / "Test.wad.client"
            deadline = time.monotonic() + 3.0
            try:
                while time.monotonic() < deadline and not target_wad.is_file():
                    time.sleep(0.05)
                self.assertTrue(target_wad.is_file())
                self.assertFalse(archive.exists())
            finally:
                service.stop()


    def test_watcher_prepares_wad_targets_after_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            skin_dir = mods_root / "skins" / "901000"
            skin_dir.mkdir(parents=True)
            service = ModStorageService(
                mods_root,
                watch_archives=True,
                champion_name_resolver=lambda champion_id: "Smolder",
            )
            archive = skin_dir / "Online.fantome"
            write_test_fantome(
                archive,
                build_test_wad(
                    hash_wad_path("data/characters/smolder/skins/skin12.bin")
                ),
            )
            cache_path = skin_dir / "rose_wad_targets.json"
            deadline = time.monotonic() + 3.0
            try:
                while time.monotonic() < deadline and not cache_path.is_file():
                    time.sleep(0.05)
                self.assertTrue(cache_path.is_file())
                self.assertEqual(
                    json.loads(cache_path.read_text())["mods"]["Online"]["affectedSkinIds"],
                    [901012],
                )
            finally:
                service.stop()
if __name__ == "__main__":
    unittest.main()