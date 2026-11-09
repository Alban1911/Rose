import json
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from injection.mods.fantome import (
    deflated_packed_wads,
    fantome_display_name,
    fantome_metadata,
    read_info,
    store_packed_wads,
    write_fantome_zip,
)


class StorePackedWadsTests(unittest.TestCase):
    """An archive whose packed WADs are deflated is rewritten in one pass,
    with no folder in between: a voiceover pack is gigabytes"""

    FILES = {
        "META/info.json": json.dumps({"Name": "VO Japanese"}),
        "WAD/Ahri.ja_JP.wad.client": b"voice" * 1000,
        "WAD_chroma/Ahri.wad": b"chroma" * 1000,
        "WAD/Map11.wad.client/data/loose.bin": b"loose" * 1000,
    }

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.source = self.root / "VO.fantome"
        with zipfile.ZipFile(self.source, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in self.FILES.items():
                archive.writestr(name, data)

    def test_the_packed_wads_are_stored_and_every_file_kept(self):
        self.assertEqual(sorted(deflated_packed_wads(self.source)), ["WAD/Ahri.ja_JP.wad.client", "WAD_chroma/Ahri.wad"])

        store_packed_wads(self.source, self.root / "out.fantome")

        with zipfile.ZipFile(self.root / "out.fantome") as archive:
            methods = {info.filename: info.compress_type for info in archive.infolist()}
            contents = {name: archive.read(name) for name in archive.namelist()}
        self.assertEqual(contents, {name: data.encode() if isinstance(data, str) else data
                                    for name, data in self.FILES.items()})
        self.assertEqual(methods["WAD/Ahri.ja_JP.wad.client"], zipfile.ZIP_STORED)
        self.assertEqual(methods["WAD_chroma/Ahri.wad"], zipfile.ZIP_STORED)
        self.assertEqual(methods["WAD/Map11.wad.client/data/loose.bin"], zipfile.ZIP_DEFLATED)
        self.assertEqual(deflated_packed_wads(self.root / "out.fantome"), [])

    def test_a_name_held_twice_is_written_once_the_last(self):
        with zipfile.ZipFile(self.source, "a", zipfile.ZIP_DEFLATED) as archive, \
                warnings.catch_warnings():
            warnings.simplefilter("ignore")  # zipfile warns of the duplicate name
            archive.writestr("WAD/Ahri.ja_JP.wad.client", b"newer")

        store_packed_wads(self.source, self.root / "out.fantome")

        with zipfile.ZipFile(self.root / "out.fantome") as archive:
            self.assertEqual(archive.namelist().count("WAD/Ahri.ja_JP.wad.client"), 1)
            self.assertEqual(archive.read("WAD/Ahri.ja_JP.wad.client"), b"newer")


class FantomeZipTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.folder = self.root / "1001-EternalAspect"
        (self.folder / "META").mkdir(parents=True)
        (self.folder / "WAD").mkdir()
        (self.folder / "META" / "info.json").write_text(
            json.dumps({
                "Name": "Eternal Aspect Leona",
                "Author": "Tester",
                "Version": "1.2.3",
                "Description": "a test mod",
            }),
            encoding="utf-8",
        )
        (self.folder / "WAD" / "Aatrox.wad.client").write_bytes(b"wad-bytes")

    def _pack(self) -> dict:
        dest = self.root / "packed.fantome"
        write_fantome_zip(self.folder, dest)
        with zipfile.ZipFile(dest) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def test_the_archive_is_the_folder_with_a_metadata_header(self):
        members = self._pack()

        self.assertIn("WAD/Aatrox.wad.client", members)
        self.assertEqual(members["WAD/Aatrox.wad.client"], b"wad-bytes")
        self.assertIn("META/info.json", members)
        metadata = json.loads(members["metadata.json"])
        self.assertEqual(metadata["name"], "Eternal Aspect Leona")
        self.assertEqual(metadata["author"], "Tester")
        self.assertEqual(metadata["version"], "1.2.3")
        self.assertEqual(metadata["description"], "a test mod")

    def test_packed_wads_are_stored_and_the_rest_deflated(self):
        # LTK Manager's own rule: its chunks are compressed already, and a stored WAD reads in place (#425)
        (self.folder / "WAD" / "Leona.wad.client").write_bytes(b"wad" * 100)
        (self.folder / "WAD_chroma").mkdir()
        (self.folder / "WAD_chroma" / "Leona.wad").write_bytes(b"wad" * 100)
        (self.folder / "WAD" / "Map11.wad.client" / "data").mkdir(parents=True)
        (self.folder / "WAD" / "Map11.wad.client" / "data" / "loose.bin").write_bytes(b"bin" * 100)
        archive = write_fantome_zip(self.folder, self.root / "out.fantome")

        with zipfile.ZipFile(archive) as zf:
            methods = {info.filename: info.compress_type for info in zf.infolist()}
        self.assertEqual(methods["WAD/Leona.wad.client"], zipfile.ZIP_STORED)
        self.assertEqual(methods["WAD_chroma/Leona.wad"], zipfile.ZIP_STORED)
        self.assertEqual(methods["WAD/Map11.wad.client/data/loose.bin"], zipfile.ZIP_DEFLATED)
        self.assertEqual(methods["META/info.json"], zipfile.ZIP_DEFLATED)

    def test_an_existing_metadata_json_is_kept(self):
        (self.folder / "metadata.json").write_text(
            json.dumps({"name": "Kept Name", "author": "Someone"}), encoding="utf-8"
        )

        metadata = json.loads(self._pack()["metadata.json"])

        self.assertEqual(metadata["name"], "Kept Name")
        self.assertEqual(metadata["author"], "Someone")

    def test_without_info_json_the_folder_name_is_the_mod_name(self):
        (self.folder / "META" / "info.json").unlink()

        metadata = json.loads(self._pack()["metadata.json"])

        self.assertEqual(metadata["name"], "1001-EternalAspect")

    def test_metadata_of_an_unreadable_info_json_falls_back_to_the_folder(self):
        (self.folder / "META" / "info.json").write_text("{not json", encoding="utf-8")

        metadata = json.loads(self._pack()["metadata.json"])

        self.assertEqual(metadata["name"], "1001-EternalAspect")

    def test_packing_a_missing_folder_raises(self):
        with self.assertRaises(FileNotFoundError):
            write_fantome_zip(self.root / "nope", self.root / "out.fantome")


class FantomeNameTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)

    def test_the_info_json_name_wins(self):
        folder = self.root / "ROSE-LoadingName"
        (folder / "META").mkdir(parents=True)
        (folder / "META" / "info.json").write_text(
            json.dumps({"Name": "Loading screen name"}), encoding="utf-8"
        )

        self.assertEqual(fantome_display_name(folder), "Loading screen name")

    def test_without_info_json_the_folder_name_is_used(self):
        folder = self.root / "party_12345"
        folder.mkdir()

        self.assertEqual(fantome_display_name(folder), "party_12345")

    def test_read_info_of_a_missing_file_is_empty(self):
        self.assertEqual(read_info(self.root / "missing"), {})

    def test_fantome_metadata_reads_an_existing_header(self):
        folder = self.root / "mod"
        folder.mkdir()
        (folder / "metadata.json").write_text(json.dumps({"name": "Named"}), encoding="utf-8")

        self.assertEqual(fantome_metadata(folder)["name"], "Named")


if __name__ == "__main__":
    unittest.main()
