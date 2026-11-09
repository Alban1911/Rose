import tempfile
import unittest
from pathlib import Path

from injection.mods.mod_facts import compute_mod_facts
from injection.mods.storage import ModStorageService


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


class ChampionModImageTests(unittest.TestCase):
    def setUp(self):
        self.root = self.resolved_temp_dir()
        self.service = ModStorageService(self.root / "mods")
        self.mod_folder = self.add_folder_mod(1, "Example")
        self.relative_path = self.mod_folder.relative_to(self.service.mods_root).as_posix()

    def resolved_temp_dir(self) -> Path:
        """A temporary folder, resolved as storage resolves its paths: the
        paths the test compares are then written the same way."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name).resolve()

    def add_folder_mod(self, champion_id, name):
        """A mod an older Rose stored as a folder, registered in its champion's manifest"""
        folder = self.service.get_champion_dir(champion_id) / name
        folder.mkdir(parents=True)
        self.service.set_champion_target_ids(champion_id, [champion_id * 1000 + 1], mod_name=name)
        return folder

    def test_image_is_added_and_replaced_at_the_skin_mod_meta_path(self):
        first_image = PNG_HEADER + b"first"
        image_path = self.service.set_champion_mod_image(1, self.relative_path, first_image)
        self.assertEqual(image_path, self.mod_folder / "META" / "image.png")
        self.assertEqual(image_path.read_bytes(), first_image)

        second_image = PNG_HEADER + b"second"
        self.service.set_champion_mod_image(1, self.relative_path, second_image)
        self.assertEqual(image_path.read_bytes(), second_image)

    def test_selected_image_file_is_size_checked_and_saved(self):
        source = self.root / "selected.png"
        image_data = PNG_HEADER + b"preview"
        source.write_bytes(image_data)

        image_path = self.service.set_champion_mod_image(
            1,
            self.relative_path,
            source,
        )

        self.assertEqual(image_path.read_bytes(), image_data)

    def test_image_path_must_stay_inside_the_selected_champion_mod(self):
        with self.assertRaisesRegex(ValueError, "Invalid skin mod path"):
            self.service.set_champion_mod_image(1, "skins/1000/../1001/Other", PNG_HEADER)

        other_champion = self.add_folder_mod(2, "Other")
        other_relative_path = other_champion.relative_to(self.service.mods_root).as_posix()
        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.service.set_champion_mod_image(1, other_relative_path, PNG_HEADER)

    def test_only_bounded_png_data_is_written(self):
        with self.assertRaisesRegex(ValueError, "not a PNG"):
            self.service.set_champion_mod_image(1, self.relative_path, b"not png")
        with self.assertRaisesRegex(ValueError, "5 MB"):
            self.service.set_champion_mod_image(
                1,
                self.relative_path,
                PNG_HEADER + b"x" * self.service.MAX_MOD_IMAGE_BYTES,
            )
        self.assertFalse((self.mod_folder / "META").exists())

    def test_preview_image_is_excluded_from_the_folder_target_hash(self):
        wad = self.mod_folder / "WAD"
        wad.mkdir()
        (wad / "Ahri.wad.client").write_bytes(b"skin data")
        before = compute_mod_facts(self.mod_folder)[1]
        image = self.mod_folder / "META" / "image.png"
        image.parent.mkdir()
        image.write_bytes(PNG_HEADER + b"preview")

        after = compute_mod_facts(self.mod_folder)[1]

        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
