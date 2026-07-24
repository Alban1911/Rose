import json
import struct
import time
import zipfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from injection.mods.storage import ModStorageService
from injection.mods.wad_extractor import resolve_wad_skin_targets
from injection.mods.wad_parser import (
    find_matching_wad_paths,
    hash_wad_path,
    read_wad_path_hashes,
    xxhash64,
)
SYNDRA_WAD_TOC_HASHES = (
    0x0545BDC8C387EF08,
    0x0653A2647A883EE0,
    0x2C03077C0B061387,
    0x368223119C852368,
    0x512C63DF3B426B30,
    0x526E09DBB42093DD,
    0x566B632DC405CF0D,
    0x5BE1615DC82A7F88,
    0x66569547FD84F437,
    0x668A2B3A29AE64EA,
    0x6A5BDBB48F7AF97B,
    0x7A38568CC8036E9E,
    0x7AEAB92AD94BD86A,
    0x7E8B536DC4054EC6,
    0x804A31351AA8F6A2,
    0x83CA43E6BF7D95C2,
    0x87DD418BAE0295E9,
    0x8E2ED1F3C8ECC589,
    0x8FCA1D50B2A964D2,
    0x970CD877BADFDFF0,
    0x9BC79411AE48B837,
    0x9DBF22B651340D49,
    0xA7088626D9B4C61E,
    0xAA03FDD066C204C1,
    0xB2A3DB000C9E122A,
    0xB2B28D78F9DF1C9A,
    0xB629DC81B6C72C53,
    0xC82D570E51E728D1,
    0xD36A43FE72F123BA,
    0xD92BE1DA49C59FA4,
    0xF38C4F6D19E93900,
    0xF9FD25FA073E0DCB,
    0xFA12D1D428522F77,
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

    def test_wad_path_resolution_streams_known_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wad_path = root / "Syndra.wad.client"
            hashes = root / "hashes.game.txt"
            target_path = "assets/characters/syndra/skins/skin07/file.tex"
            write_test_wad(wad_path, hash_wad_path(target_path))
            hashes.write_text(
                f"{hash_wad_path(target_path):016x} {target_path}\n",
                encoding="utf-8",
            )

            self.assertEqual(
                resolve_wad_skin_targets(wad_path, 134, "Syndra", hashes),
                {134007},
            )
    def test_matches_candidate_skin_path(self) -> None:
        target_path = "data/characters/ahri/skins/skin33.bin"
        self.assertEqual(
            find_matching_wad_paths(
                {hash_wad_path(target_path)},
                [(target_path, 103033)],
            ),
            {103033},
        )

    def test_reported_syndra_wad_fixture_resolves_known_asset_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mods_root = root / "mods"
            mod_dir = mods_root / "skins" / "134000" / "SyndraMod"
            wad_path = mod_dir / "WAD" / "syndra.wad.client"
            hashes = root / "hashes.game.txt"
            wad_path.parent.mkdir(parents=True)
            write_test_wad(wad_path, *SYNDRA_WAD_TOC_HASHES)
            target_path = "assets/characters/syndra/skins/skin07/file.tex"
            hashes.write_text(
                f"{SYNDRA_WAD_TOC_HASHES[7]:016x} {target_path}" + chr(10),
                encoding="utf-8",
            )

            service = ModStorageService(mods_root, wad_hash_file=hashes)
            try:
                entries = service.list_mods_for_skin(134000, "Syndra")
                self.assertEqual(entries[0].affected_skin_ids, (134007,))
                self.assertEqual(len(read_wad_path_hashes(wad_path)), 33)
            finally:
                service.stop()

    def test_extracted_wad_directory_without_client_suffix_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "134000" / "SyndraMod"
            extracted_wad = mod_dir / "WAD" / "syndra.wad"
            write_asset(
                extracted_wad,
                "assets/characters/syndra/skins/skin07/syndra_skin07.skn",
            )
            write_asset(
                extracted_wad,
                "assets/characters/syndra/skins/skin07/animations/syndra_skin07_recall.anm",
            )

            service = ModStorageService(mods_root)
            try:
                self.assertEqual(
                    service._get_wad_targets(mod_dir, 134, "Syndra"),
                    {134007},
                )
            finally:
                service.stop()

    def test_packed_wad_extraction_fallback_scans_resolved_asset_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mods_root = root / "mods"
            mod_dir = mods_root / "skins" / "134000" / "SyndraMod"
            wad_path = mod_dir / "WAD" / "syndra.wad.client"
            hashes = root / "missing-hashes.game.txt"
            wad_path.parent.mkdir(parents=True)
            write_test_wad(wad_path, 0x5BE1615DC82A7F88)
            temporary_outputs: list[Path] = []

            def fake_extract(_wad_path: Path, output_directory: Path) -> Path:
                temporary_outputs.append(output_directory)
                extracted_root = output_directory / "syndra.wad"
                write_asset(
                    extracted_root,
                    "assets/characters/syndra/skins/skin07/syndra_skin07.skn",
                )
                return extracted_root

            with mock.patch(
                "injection.mods.storage.extract_wad_to_directory",
                side_effect=fake_extract,
            ) as extract:
                service = ModStorageService(mods_root, wad_hash_file=hashes)
                try:
                    entries = service.list_mods_for_skin(134000, "Syndra")
                    self.assertEqual(entries[0].affected_skin_ids, (134007,))
                    self.assertEqual(extract.call_count, 1)
                    self.assertFalse(temporary_outputs[0].exists())

                    entries = service.list_mods_for_skin(134000, "Syndra")
                    self.assertEqual(entries[0].affected_skin_ids, (134007,))
                    self.assertEqual(extract.call_count, 1)
                finally:
                    service.stop()

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
            try:
                entries = service.list_mods_for_skin(103000, "Ahri")
            finally:
                service.stop()
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

    def test_known_path_resolution_fallback_detects_target_without_unpacking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "134000" / "SyndraMod"
            mod_dir.mkdir(parents=True)
            wad_path = mod_dir / "WAD" / "Syndra.wad.client"
            hash_file = Path(temp_dir) / "hashes.game.txt"
            target_path = "assets/characters/syndra/skins/skin07/custom.tex"
            wad_path.parent.mkdir(parents=True)
            write_test_wad(wad_path, hash_wad_path(target_path))
            hash_file.write_text(
                f"{hash_wad_path(target_path):016x} {target_path}" + chr(10),
                encoding="utf-8",
            )

            service = ModStorageService(mods_root, wad_hash_file=hash_file)
            try:
                entries = service.list_mods_for_skin(134000, "Syndra")
                self.assertEqual(entries[0].affected_skin_ids, (134007,))
            finally:
                service.stop()

    def test_path_resolution_failure_uses_storage_fallback_and_is_not_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "901000" / "BrokenMod"
            mod_dir.mkdir(parents=True)
            wad_path = mod_dir / "Smolder.wad.client"
            write_test_wad(wad_path, hash_wad_path("unknown/file.bin"))

            def fail_resolution(*_args) -> set[int]:
                raise RuntimeError("test path resolution failure")

            service = ModStorageService(mods_root)
            try:
                with mock.patch(
                    "injection.mods.storage.resolve_wad_skin_targets",
                    side_effect=fail_resolution,
                ), mock.patch(
                    "injection.mods.storage.extract_wad_to_directory",
                    side_effect=RuntimeError("test extraction failure"),
                ):
                    entries = service.list_mods_for_skin(901000, "Smolder")
                self.assertEqual(entries[0].affected_skin_ids, (901000,))
                self.assertFalse((mods_root / "skins" / "901000" / "rose_wad_targets.json").exists())
            finally:
                service.stop()

    def test_path_resolution_targets_are_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "901000" / "ExtractedMod"
            mod_dir.mkdir(parents=True)
            wad_path = mod_dir / "Smolder.wad.client"
            write_test_wad(
                wad_path,
                hash_wad_path("assets/characters/smolder/skins/skin44/custom.tex"),
            )

            def fake_resolution(*_args) -> set[int]:
                return {901044}

            service = ModStorageService(mods_root)
            try:
                with mock.patch(
                    "injection.mods.storage.resolve_wad_skin_targets",
                    side_effect=fake_resolution,
                ) as resolver:
                    first = service.list_mods_for_skin(901000, "Smolder")
                    second = service.list_mods_for_skin(901000, "Smolder")
                self.assertEqual(first[0].affected_skin_ids, (901044,))
                self.assertEqual(second[0].affected_skin_ids, (901044,))
                resolver.assert_called_once()
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

            def fake_resolution(*_args) -> set[int]:
                return {901044}

            service = ModStorageService(mods_root)
            try:
                with mock.patch(
                    "injection.mods.storage.resolve_wad_skin_targets",
                    side_effect=fake_resolution,
                ) as resolver:
                    entries = service.list_mods_for_skin(901000, "Smolder")
                self.assertEqual(entries[0].affected_skin_ids, (901044,))
                resolver.assert_called_once()
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

    def test_wad_target_cache_invalidates_when_hash_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_root = Path(temp_dir) / "mods"
            mod_dir = mods_root / "skins" / "901000" / "ChangingHash"
            wad_path = mod_dir / "WAD" / "Smolder.wad.client"
            hash_file = Path(temp_dir) / "hashes.game.txt"
            target_path = "assets/characters/smolder/skins/skin44/custom.tex"
            wad_path.parent.mkdir(parents=True)
            write_test_wad(wad_path, hash_wad_path(target_path))
            hash_file.write_text("# target path not available" + chr(10), encoding="utf-8")

            service = ModStorageService(mods_root, wad_hash_file=hash_file)
            try:
                first = service.list_mods_for_skin(901000, "Smolder")
                self.assertEqual(first[0].affected_skin_ids, (901000,))

                hash_file.write_text(
                    f"{hash_wad_path(target_path):016x} {target_path}" + chr(10),
                    encoding="utf-8",
                )
                second = service.list_mods_for_skin(901000, "Smolder")
                self.assertEqual(second[0].affected_skin_ids, (901044,))
            finally:
                service.stop()

            payload = json.loads(
                (mods_root / "skins" / "901000" / "rose_wad_targets.json").read_text()
            )
            self.assertEqual(payload["version"], 3)
            self.assertEqual(payload["hashFile"]["size"], hash_file.stat().st_size)


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