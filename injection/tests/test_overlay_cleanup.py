import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from injection.mods.mod_manager import ModManager, empty_directory
from injection.overlay.overlay_manager import OverlayManager


class OverlayCleanupTests(unittest.TestCase):
    """The LTK patcher starts before the overlay is built and fails with "prefix
    not configured" if its overlay directory is missing when it is configured:
    cleaning must empty the directory, never delete it."""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.overlay = self.root / "overlay"
        (self.overlay / "DATA" / "FINAL").mkdir(parents=True)
        (self.overlay / "DATA" / "FINAL" / "Zed.wad.client").write_bytes(b"wad")
        (self.overlay / "cslol-config.json").write_text("{}", encoding="utf-8")

        real_rmtree = shutil.rmtree
        self.removed = []

        def spy(path, *args, **kwargs):
            self.removed.append(Path(path))
            return real_rmtree(path, *args, **kwargs)

        self.enterContext(patch("shutil.rmtree", side_effect=spy))

    def assert_emptied_not_removed(self):
        self.assertTrue(self.overlay.is_dir())
        self.assertEqual(list(self.overlay.iterdir()), [])
        self.assertNotIn(self.overlay, self.removed)

    def test_cleaning_before_an_injection_keeps_the_directory(self):
        ModManager(self.root / "mods").clean_overlay_dir()
        self.assert_emptied_not_removed()

    def test_wiping_after_a_game_keeps_the_directory(self):
        OverlayManager._wipe_overlay_dir(self.overlay)
        self.assert_emptied_not_removed()

    def test_a_missing_directory_is_created(self):
        shutil.rmtree(self.overlay)
        empty_directory(self.overlay)
        self.assertTrue(self.overlay.is_dir())


if __name__ == "__main__":
    unittest.main()
