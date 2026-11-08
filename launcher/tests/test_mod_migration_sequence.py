"""The launcher moves the saved mods into LTK Manager after the skin sync, in
its dialog: it offers a backup on the desktop first, sized, and a backup that
fails moves nothing."""

import re
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from injection.mods import migration
from injection.tests.test_ltf_session import FakeBridge
from injection.tests.test_mod_archives import PNG
from injection.tests.test_mod_migration import MigrationTestCase
from launcher.core import launcher
from launcher.sequences import mod_migration_sequence
from launcher.sequences.mod_migration_sequence import BACKUP_QUESTION, IDYES, TITLE, ModMigrationSequence

IDNO = 7


class FakeDialog:
    """The launcher's UpdateDialog: what it was told"""

    hwnd = 4242

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name not in {"set_detail", "set_status", "update_transfer_progress", "clear_transfer_text",
                        "pump_messages", "set_marquee", "set_progress", "reset_progress"}:
            raise AttributeError(name)
        return lambda *args: self.calls.append((name, *args))

    def details(self):
        return [call[1] for call in self.calls if call[0] == "set_detail"]


class ModMigrationSequenceTests(MigrationTestCase):
    def setUp(self):
        super().setUp()
        self.free = 120 * 1024 ** 3
        self.dialog = FakeDialog()
        self.user32 = MagicMock()
        self.user32.MessageBoxW.return_value = IDNO
        patcher = patch.object(mod_migration_sequence, "user32", self.user32)
        patcher.start()
        self.addCleanup(patcher.stop)

    def perform(self):
        return ModMigrationSequence(self.storage, self.library).perform(self.dialog)

    def boxes(self):
        return [call.args for call in self.user32.MessageBoxW.call_args_list]

    def backup_folders(self):
        return sorted(self.desktop.iterdir()) if self.desktop.exists() else []

    def test_the_prompt_shows_the_backup_size_and_the_free_space(self):
        archive = self.category_mod("VO Korean")
        size = sum(path.stat().st_size for path in self.mods_root.rglob("*") if path.is_file())

        self.perform()

        (box,) = self.boxes()
        self.assertEqual(box, (4242, BACKUP_QUESTION.format(size=migration.size_text(size), free="120 GB"),
                               TITLE, mod_migration_sequence.MB_YESNO | mod_migration_sequence.MB_ICONQUESTION
                               | mod_migration_sequence.MB_TOPMOST))
        self.assertIn(f"({migration.size_text(size)}, 120 GB free)", box[1])
        self.assertFalse(archive.exists())

    def test_yes_copies_the_mods_to_the_desktop_before_moving_them(self):
        archive = self.category_mod("VO Korean")
        original = archive.read_bytes()
        self.user32.MessageBoxW.return_value = IDYES

        report = self.perform()

        (backup,) = self.backup_folders()
        self.assertRegex(backup.name, re.escape(f"Rose mods backup {date.today():%Y-%m-%d}") + "$")
        self.assertEqual((backup / "voiceover" / "VO Korean.fantome").read_bytes(), original)
        self.assertEqual((backup / "voiceover" / "VO Korean.png").read_bytes(), PNG)
        self.assertEqual(report.moved, ["VO Korean"])
        self.assertFalse(archive.exists())
        details = self.dialog.details()
        self.assertLess(details.index("Backing up your mods to your desktop…"),
                        details.index("Moving your mods into LTK Manager (1/1): VO Korean"))
        transfers = [call for call in self.dialog.calls if call[0] == "update_transfer_progress"]
        self.assertTrue(transfers)

    def test_no_moves_the_mods_without_a_backup(self):
        archive = self.category_mod("VO Korean")

        report = self.perform()

        self.assertEqual(self.backup_folders(), [])
        self.assertEqual(report.moved, ["VO Korean"])
        self.assertFalse(archive.exists())
        self.assertEqual(len(self.boxes()), 1)

    def test_a_backup_that_fails_moves_nothing_and_says_so(self):
        archive = self.category_mod("VO Korean")
        self.user32.MessageBoxW.return_value = IDYES

        with patch.object(migration.shutil, "copystat", side_effect=OSError(28, "No space left on device")):
            report = self.perform()

        self.assertEqual(self.backup_folders(), [])
        self.assertTrue(archive.exists())
        self.assertEqual(report.moved, [])
        question, notice = self.boxes()
        self.assertIn("Rose could not back up your mods to your desktop", notice[1])
        self.assertEqual(notice[3], mod_migration_sequence.MB_OK | mod_migration_sequence.MB_ICONWARNING
                         | mod_migration_sequence.MB_TOPMOST)

    def test_nothing_to_move_asks_nothing(self):
        report = self.perform()

        self.assertEqual(report.moved, [])
        self.assertEqual(self.boxes(), [])
        self.assertEqual(self.dialog.details(), [])
        self.assertEqual(FakeBridge.created, [])

    def test_a_migration_that_crashes_lets_rose_start(self):
        self.category_mod("VO Korean")

        with patch.object(migration, "convert_folder_mods", side_effect=RuntimeError("a bug")):
            self.assertIsNone(self.perform())

        self.assertIn(("clear_transfer_text",), self.dialog.calls)


class LauncherTests(unittest.TestCase):
    def test_the_mods_move_after_the_skin_sync(self):
        order = []

        def step(name):
            return lambda *args, **kwargs: order.append(name)

        with patch.object(launcher, "UpdateDialog", return_value=MagicMock(hwnd=0)), \
                patch.object(launcher, "_perform_update", step("update")), \
                patch.object(launcher.HashCheckSequence, "perform_hash_check", step("hashes")), \
                patch.object(launcher.SkinSyncSequence, "perform_skin_sync", step("skins")), \
                patch.object(launcher.ModMigrationSequence, "perform", step("mods")), \
                patch.object(launcher.time, "sleep"):
            launcher._run_launcher_dialog(dev_mode=False, test_download_fail=False)

        self.assertEqual(order, ["update", "hashes", "skins", "mods"])


if __name__ == "__main__":
    unittest.main()
