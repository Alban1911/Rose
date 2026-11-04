import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from injection.mods.mod_manager import ModManager, empty_directory
from injection.overlay.overlay_manager import OverlayManager


class OverlayCleanupTests(unittest.TestCase):
    """Both wipes empty a directory without deleting it: Rose creates the
    mods directory before every injection, and an injection that runs while
    Rose restarts must not trip over a missing one."""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.overlay = self.root / "overlay"
        (self.overlay / "DATA" / "FINAL").mkdir(parents=True)
        (self.overlay / "DATA" / "FINAL" / "Zed.wad.client").write_bytes(b"wad")
        (self.overlay / "cslol-config.json").write_text("{}", encoding="utf-8")
        self.mods = self.root / "mods"
        (self.mods / "1001-EternalAspect" / "WAD").mkdir(parents=True)
        (self.mods / "1001-EternalAspect" / "WAD" / "Leona.wad.client").write_bytes(b"wad")

        real_rmtree = shutil.rmtree
        self.removed = []

        def spy(path, *args, **kwargs):
            self.removed.append(Path(path))
            return real_rmtree(path, *args, **kwargs)

        self.enterContext(patch("shutil.rmtree", side_effect=spy))

    def assert_emptied_not_removed(self, directory):
        self.assertTrue(directory.is_dir())
        self.assertEqual(list(directory.iterdir()), [])
        self.assertNotIn(directory, self.removed)

    def test_cleaning_before_an_injection_keeps_the_directory(self):
        ModManager(self.mods).clean_overlay_dir()
        self.assert_emptied_not_removed(self.overlay)

    def test_wiping_after_an_import_keeps_the_directory(self):
        OverlayManager(self.root / "tools", self.mods, self.root)._wipe_mods_dir()
        self.assert_emptied_not_removed(self.mods)

    def test_a_missing_directory_is_created(self):
        shutil.rmtree(self.overlay)
        empty_directory(self.overlay)
        self.assertTrue(self.overlay.is_dir())


if __name__ == "__main__":
    unittest.main()
