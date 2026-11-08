
import ctypes
import json
import os
import sys
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch

from injection.mods import conversion, migration, mod_facts
from injection.mods.fingerprint import mod_fingerprint
from injection.mods.manifest import iter_saved_mods
from injection.mods.migration import MigrationReport, Step, migrate_saved_mods, needs_migration, size_text
from injection.mods.mod_facts import ModFacts, compute_mod_facts, stamp_of
from injection.mods.storage import ModStorageService
from injection.overlay import ltf_session
from injection.overlay.ltf_session import ALREADY_OPEN_REASON, LtfHost, MissingComponent
from injection.overlay.ltk_library import LibrarySession, LtkLibrary
from injection.tests.test_ltf_session import FakeBridge, LtfSessionTestCase
from injection.tests.test_mod_archives import PNG, VOICEOVER, add_entries, make_archive, make_folder
from injection.tools.bridge import BridgeCommandError, BridgeUnavailable
from injection.tools.tools_manager import ToolsManager
from threads.handlers.injection_trigger import InjectionTrigger
from utils.core import historic, mod_historic

KEPT_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"
MOVED_ID = "d6f841c7-140b-4ac2-a11c-b37e18eb8006"
LEONA = {
    "META/info.json": json.dumps({"Name": "Eternal Aspect Leona"}),
    "WAD/Leona.wad.client": b"leona" * 50,
}
GB = 1024 ** 3


class FakeUi:
    """The launcher's dialog: what the migration showed, asked and told"""

    def __init__(self, backup=False):
        self.backup = backup
        self.steps = []
        self.asked = []
        self.notices = []

    def progress(self, step, index=0, total=0, name="", done_bytes=0, total_bytes=0):
        self.steps.append((step, index, total, name, done_bytes, total_bytes))

    def ask_backup(self, size, free):
        self.asked.append((size, free))
        return self.backup

    def notify(self, message):
        self.notices.append(message)

    def step_names(self):
        return list(dict.fromkeys(step for step, *_ in self.steps))


class MigrationTestCase(LtfSessionTestCase):
    """A temporary Rose data folder, LTK Manager behind FakeBridge, and none of
    this PC's own: its Rose, mutexes, LTK Manager data, desktop and disks"""

    def setUp(self):
        super().setUp()
        FakeBridge.mod_storage = self.root / "ltk-mods"
        self.mods_root = self.host.saved_mods_root
        self.storage = ModStorageService(self.mods_root)
        self.library = LtkLibrary(self.host)
        self.desktop = self.root / "Desktop"
        self.free = 100 * GB
        tag = uuid.uuid4().hex
        self.single_instance = rf"Local\RoseTest-{tag}"
        self.migration_mutex = rf"Local\RoseTestMigration-{tag}"
        for patcher in (
            patch.object(conversion, "get_injection_dir", return_value=self.root / "injection"),
            patch.object(mod_facts, "get_injection_dir", return_value=self.root / "injection"),
            patch.object(historic, "get_user_data_dir", return_value=self.root),
            patch.object(mod_historic, "get_user_data_dir", return_value=self.root),
            patch.object(migration, "mod_storage_root", return_value=self.root / "ltk-mods"),
            patch.object(migration, "get_desktop_user_desktop_dir", return_value=self.desktop),
            patch.object(migration, "free_space", side_effect=lambda _path: self.free),
            patch.object(migration, "SINGLE_INSTANCE_MUTEX_NAME", self.single_instance),
            patch.object(migration, "MOD_MIGRATION_MUTEX_NAME", self.migration_mutex),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def migrate(self, ui=None):
        self.ui = ui or FakeUi()
        return migrate_saved_mods(self.storage, self.library, self.ui)

    def category_mod(self, name, category="voiceover", files=VOICEOVER, suffix=".fantome", **entry):
        """A saved category mod as an older Rose left it (no facts unless given), its image and description beside it"""
        archive = make_archive(self.mods_root / category / f"{name}{suffix}", files)
        archive.with_suffix(".png").write_bytes(PNG)
        archive.with_suffix(".txt").write_text(f"{name}'s description", encoding="utf-8")
        add_entries(self.mods_root / category / ModStorageService.CATEGORY_METADATA,
                    {name: {"name": name, "path": name, **entry}}, category=category)
        return archive

    def entry(self, relative_path):
        mod = self.storage.saved_mod(relative_path)
        self.assertIsNotNone(mod, f"{relative_path} is not listed")
        return mod

    def ltk_entry(self, ltk_id):
        return next((e for e in self.bridge.library_entries if e["id"] == ltk_id), None)


class MoveTests(MigrationTestCase):
    def test_pending_mods_move_into_ltk_manager_and_rose_keeps_no_copy(self):
        voiceover = self.category_mod("VO Korean")
        expected_facts = compute_mod_facts(voiceover)[0]
        leona = make_archive(self.mods_root / "skins" / "89000" / "Leona.fantome", LEONA)
        add_entries(self.mods_root / "skins" / "89000" / ModStorageService.TARGET_METADATA,
                    {"Leona": {"name": "Leona", "targets": [89001]}}, championId=89, targets=[])

        report = self.migrate()

        self.assertEqual(report.moved, ["VO Korean"], "a custom skin stays Rose's")
        self.assertEqual((report.failed, report.skipped_reason), ([], None))
        mod = self.entry("voiceover/VO Korean.fantome")
        self.assertFalse(voiceover.exists())
        self.assertIsNone(mod.rose_copy)
        self.assertFalse(self.ltk_entry(mod.ltk_id)["enabled"])
        self.assertEqual(mod.metadata["ltkStamp"], stamp_of(FakeBridge.mod_storage / f"mod-{mod.ltk_id[:8]}.fantome"))
        self.assertIsInstance(mod.metadata["updatedAt"], float)
        self.assertEqual(mod.facts, expected_facts)
        skin = self.entry("skins/89000/Leona.fantome")
        self.assertEqual((skin.ltk_id, skin.rose_copy, skin.target_skin_ids), (None, leona, (89001,)))
        self.assertEqual(voiceover.with_suffix(".png").read_bytes(), PNG)
        self.assertEqual(voiceover.with_suffix(".txt").read_text(encoding="utf-8"), "VO Korean's description")
        self.assertNotIn("uninstall", self.bridge.command_names())
        self.assertEqual(self.state()["installed"], {})
        self.assertEqual(self.ui.notices, [])
        self.assertFalse(needs_migration(self.mods_root))

    def test_the_dialog_follows_each_mod_with_the_bytes_moved(self):
        first = self.category_mod("A")
        second = self.category_mod("B", category="maps")
        sizes = [first.stat().st_size, second.stat().st_size]

        self.migrate()

        moves = [step for step in self.ui.steps if step[0] is Step.MOVE]
        total = sum(sizes)
        self.assertEqual([(index, count, done, of) for _, index, count, _, done, of in moves],
                         [(1, 2, 0, total), (2, 2, sizes[0], total)])
        self.assertEqual(self.ui.step_names(), [Step.CONNECT, Step.MOVE])

    def test_one_failed_import_leaves_that_mod_in_rose_and_moves_the_others(self):
        broken = self.category_mod("Broken")
        self.category_mod("VO Korean", category="maps")
        real_import = FakeBridge.import_fantome

        def import_fantome(bridge, path, name=None):
            if name == "Broken":
                raise BridgeCommandError("import failed: unsupported archive")
            return real_import(bridge, path, name)

        with patch.object(FakeBridge, "import_fantome", import_fantome):
            report = self.migrate()

        self.assertEqual(report.moved, ["VO Korean"])
        self.assertEqual(report.failed, [("Broken", "import failed: unsupported archive")])
        self.assertTrue(broken.exists())
        self.assertIsNone(self.entry("voiceover/Broken.fantome").ltk_id)
        self.assertIsNotNone(self.entry("maps/VO Korean.fantome").ltk_id)
        (notice,) = self.ui.notices
        self.assertIn("Rose moved 1 of your 2 mods", notice)
        self.assertIn("- Broken: import failed: unsupported archive", notice)
        self.assertTrue(needs_migration(self.mods_root))

    def test_ltk_manager_stopping_leaves_the_remaining_mods_in_rose(self):
        archives = [self.category_mod("A"), self.category_mod("B")]

        with patch.object(FakeBridge, "import_fantome", side_effect=BridgeUnavailable("gone")):
            report = self.migrate()

        self.assertEqual(report.moved, [])
        self.assertEqual([name for name, _ in report.failed], ["A", "B"])
        self.assertTrue(all(archive.exists() for archive in archives))
        self.assertEqual(len(self.ui.notices), 1)

    def test_an_entry_ltk_manager_does_not_list_after_the_import_keeps_roses_copy(self):
        archive = self.category_mod("VO Korean")

        with patch.object(LibrarySession, "confirm", return_value=None):
            report = self.migrate()

        self.assertEqual(report.failed, [("VO Korean", "LTK Manager does not list it after the import")])
        self.assertTrue(archive.exists())
        self.assertIsNone(self.entry("voiceover/VO Korean.fantome").ltk_id)
        self.assertEqual(self.bridge.library_entries, [], "Rose's import, not kept, is removed with the session")
        self.assertEqual(self.state()["installed"], {})

    def test_an_entry_its_manifest_cannot_name_is_removed_again(self):
        archive = self.category_mod("VO Korean")

        with patch.object(ModStorageService, "attach_ltk_entry", return_value=False):
            report = self.migrate()

        self.assertEqual(report.failed, [("VO Korean", "its manifest could not be written")])
        self.assertTrue(archive.exists())
        self.assertEqual(self.bridge.library_entries, [])

    def test_a_copy_in_use_is_left_for_the_next_start(self):
        self.category_mod("VO Korean")

        with patch.object(ModStorageService, "drop_stored_copy", return_value=False):
            report = self.migrate()

        mod = self.entry("voiceover/VO Korean.fantome")
        self.assertEqual(report.moved, ["VO Korean"])
        self.assertIsNotNone(mod.ltk_id)
        self.assertIsNotNone(mod.rose_copy)
        self.assertTrue(needs_migration(self.mods_root))

    def test_the_injection_folders_are_emptied_first(self):
        archive = self.category_mod("VO Korean")
        injection = self.root / "injection"
        os.link(archive, self.mods / "VO Korean.fantome")
        make_folder(injection / "stage" / "pick-1", {"skin/WAD/Ahri.wad.client": b"x"})
        (injection / "ltf_staging").mkdir()
        (injection / "ltf_staging" / "import.fantome").write_bytes(b"x")
        self.state_path.write_text(json.dumps({"installed": {}}), encoding="utf-8")

        with patch.object(LtkLibrary, "session", side_effect=AssertionError("emptied before LTK Manager")):
            with self.assertRaises(AssertionError):
                self.migrate()

        for name in ("mods", "stage", "ltf_staging"):
            self.assertEqual(list((injection / name).iterdir()), [], name)
        self.assertTrue(self.state_path.exists())
        self.assertTrue(archive.exists())


class WhatIsMovedTests(MigrationTestCase):
    def test_mods_stored_as_folders_are_packed_first(self):
        folder = make_folder(self.mods_root / "maps" / "Rift", VOICEOVER)
        add_entries(self.mods_root / "maps" / ModStorageService.CATEGORY_METADATA,
                    {"Rift": {"name": "Rift", "path": "Rift"}}, category="maps")
        mod_historic.write_historic_mod("map", "maps/Rift")

        report = self.migrate()

        self.assertEqual(report.moved, ["Rift"])
        self.assertEqual(self.ui.step_names(), [Step.CONVERT, Step.CONNECT, Step.MOVE])
        (imported,) = [call for call in self.bridge.calls if call[0] == "import"]
        self.assertEqual(Path(imported[1]).name, "Rift.fantome")
        self.assertFalse(folder.exists())
        self.assertFalse((self.mods_root / "maps" / "Rift.fantome").exists())
        self.assertIsNotNone(self.entry("maps/Rift.fantome").ltk_id)
        self.assertEqual(mod_historic.get_historic_mod("map"), "maps/Rift.fantome")

    def test_custom_skins_are_never_moved(self):
        """Not a registered one, nor one an older Rose kept in a per-skin folder"""
        registered = make_archive(self.mods_root / "skins" / "89000" / "Leona.fantome", LEONA)
        add_entries(self.mods_root / "skins" / "89000" / ModStorageService.TARGET_METADATA,
                    {"Leona": {"name": "Leona", "targets": [89001]}}, championId=89, targets=[])
        per_skin = make_archive(self.mods_root / "skins" / "89001" / "Old Leona.fantome", LEONA)

        self.assertFalse(needs_migration(self.mods_root))
        report = self.migrate()

        self.assertEqual(report, MigrationReport())
        self.assertEqual(FakeBridge.created, [], "LTK Manager not even started")
        self.assertTrue(registered.exists() and per_skin.exists())
        self.assertFalse((per_skin.parent / ModStorageService.TARGET_METADATA).exists())
        self.assertEqual(sorted(listed.mod_name for listed in self.storage.list_mods_for_skin(89001)),
                         ["Leona", "Old Leona"])

    def test_a_zip_points_the_saved_selections_at_its_new_identity(self):
        archive = self.category_mod("Rift", category="maps", suffix=".zip")
        mod_historic.write_historic_mod("map", "maps/Rift.zip")
        historic.write_historic_entry(75, "path:skins/75000/Nasus.fantome")

        self.migrate()

        self.assertFalse(archive.exists())
        self.assertIsNotNone(self.entry("maps/Rift.fantome").ltk_id)
        self.assertEqual(mod_historic.get_historic_mod("map"), "maps/Rift.fantome")
        self.assertEqual(historic.get_historic_skin_for_champion(75), "path:skins/75000/Nasus.fantome")

    def test_a_zip_copy_left_in_use_keeps_the_renamed_selection_injected(self):
        """The selection names maps/Rift.fantome before the copy goes; a copy
        in use stays, and the injection must still find the mod by that name"""
        archive = self.category_mod("Rift", category="maps", suffix=".zip")
        mod_historic.write_historic_mod("map", "maps/Rift.zip")

        with patch.object(ModStorageService, "drop_stored_copy", return_value=False):
            self.migrate()

        self.assertTrue(archive.exists())
        self.assertEqual(mod_historic.get_historic_mod("map"), "maps/Rift.fantome")
        ltk_id_the_old_path_names = self.entry("maps/Rift.zip").ltk_id
        selection = InjectionTrigger._find_saved_mod(self.storage, "maps", "maps/Rift.fantome")
        self.assertIsNotNone(selection)
        self.assertEqual(selection["source"].ltk_id, ltk_id_the_old_path_names)
        self.assertEqual([mod["id"] for mod in self.storage.list_mods_for_category("maps")], ["maps/Rift.fantome"])

        FakeBridge.initial_library = self.bridge.library_entries
        self.migrate()

        self.assertFalse(archive.exists())
        self.assertEqual(mod_historic.get_historic_mod("map"), "maps/Rift.fantome")
        self.assertIsNotNone(InjectionTrigger._find_saved_mod(self.storage, "maps", "maps/Rift.fantome"))

    def test_a_selection_that_cannot_be_renamed_keeps_roses_copy_until_a_later_start(self):
        """Deleted first, the .zip would leave the selection naming nothing, and
        with no copy left no later start would rename it"""
        archive = self.category_mod("Rift", category="maps", suffix=".zip")
        mod_historic.write_historic_mod("map", "maps/Rift.zip")

        with patch.object(mod_historic, "_write_json", side_effect=OSError(13, "Access is denied")):
            report = self.migrate()

        self.assertEqual(report.moved, ["Rift"])
        self.assertTrue(archive.exists())
        self.assertEqual(mod_historic.get_historic_mod("map"), "maps/Rift.zip")
        ltk_id = self.entry("maps/Rift.zip").ltk_id
        self.assertIsNotNone(ltk_id)
        self.assertTrue(needs_migration(self.mods_root))

        FakeBridge.initial_library = self.bridge.library_entries
        self.migrate()

        self.assertNotIn("import", self.bridge.command_names())
        self.assertFalse(archive.exists())
        self.assertEqual(mod_historic.get_historic_mod("map"), "maps/Rift.fantome")
        self.assertEqual(self.entry("maps/Rift.fantome").ltk_id, ltk_id)

    def test_a_copy_a_game_kept_is_taken_without_an_import(self):
        archive = self.category_mod("VO Korean")
        kept_archive = make_archive(FakeBridge.mod_storage / "kept-vo.fantome", VOICEOVER)
        FakeBridge.initial_library = [{"id": KEPT_ID, "name": "VO Korean", "enabled": False, "storage": "archive",
                                       "format": "fantome", "modDir": str(FakeBridge.mod_storage / "kept-vo")}]
        self.state_path.write_text(json.dumps({"kept": {KEPT_ID: {
            "folder": "VO Korean", "fingerprint": mod_fingerprint(archive), "source": str(archive.resolve()),
        }}}), encoding="utf-8")

        report = self.migrate()

        self.assertEqual(report.moved, ["VO Korean"])
        self.assertNotIn("import", self.bridge.command_names())
        mod = self.entry("voiceover/VO Korean.fantome")
        self.assertEqual(mod.ltk_id, KEPT_ID)
        self.assertEqual(mod.metadata["ltkStamp"], stamp_of(kept_archive))
        self.assertFalse(archive.exists())
        self.assertEqual(self.state()["kept"], {}, "a saved mod's for good, no game's copy")
        self.assertEqual([(e["id"], e["enabled"]) for e in self.bridge.library_entries], [(KEPT_ID, False)])

    def test_a_copy_a_game_kept_of_other_content_is_not_taken(self):
        archive = self.category_mod("VO Korean")
        FakeBridge.initial_library = [{"id": KEPT_ID, "name": "VO Korean", "enabled": False}]
        self.state_path.write_text(json.dumps({"kept": {KEPT_ID: {
            "folder": "VO Korean", "fingerprint": "an older version", "source": str(archive.resolve()),
        }}}), encoding="utf-8")

        self.migrate()

        mod = self.entry("voiceover/VO Korean.fantome")
        self.assertNotEqual(mod.ltk_id, KEPT_ID)
        self.assertIn("import", self.bridge.command_names())

    def test_a_resumed_run_deletes_the_copy_left_of_a_moved_mod(self):
        facts = ModFacts(ships_language_table=True)
        archive = self.category_mod("VO Korean", ltkId=MOVED_ID, **facts.to_manifest())
        mod_historic.write_historic_mod("voiceover", ["voiceover/VO Korean.fantome"])
        FakeBridge.initial_library = [{"id": MOVED_ID, "name": "VO Korean", "enabled": False}]

        report = self.migrate()

        self.assertEqual(report, MigrationReport())
        self.assertFalse(archive.exists())
        self.assertNotIn("import", self.bridge.command_names())
        self.assertEqual(self.entry("voiceover/VO Korean.fantome").ltk_id, MOVED_ID)
        self.assertEqual(self.ui.asked, [])
        self.assertFalse(needs_migration(self.mods_root))

    def test_a_copy_left_of_an_entry_ltk_manager_lost_is_moved_again(self):
        archive = self.category_mod("VO Korean", ltkId=MOVED_ID, missing=True)

        report = self.migrate()

        mod = self.entry("voiceover/VO Korean.fantome")
        self.assertEqual(report.moved, ["VO Korean"])
        self.assertNotEqual(mod.ltk_id, MOVED_ID)
        self.assertIsNotNone(self.ltk_entry(mod.ltk_id))
        self.assertFalse(mod.missing)
        self.assertFalse(archive.exists())


class WhenNothingMovesTests(MigrationTestCase):
    def test_nothing_to_move_starts_no_ltk_manager(self):
        add_entries(self.mods_root / "voiceover" / ModStorageService.CATEGORY_METADATA,
                    {"VO Korean": {"name": "VO Korean", "path": "VO Korean", "ltkId": MOVED_ID}})
        make_folder(self.mods_root / "maps" / "Not registered", VOICEOVER)

        self.assertFalse(needs_migration(self.mods_root))
        report = self.migrate()

        self.assertEqual(report, MigrationReport())
        self.assertEqual(FakeBridge.created, [])
        self.assertEqual((self.ui.steps, self.ui.asked, self.ui.notices), ([], [], []))

    def test_ltk_manager_not_installed_moves_nothing_and_leaves_telling_to_the_dll_check(self):
        archive = self.category_mod("VO Korean")

        with patch.object(ToolsManager, "detect_ltk_manager", return_value=None):
            report = self.migrate()

        self.assertEqual(report.skipped_reason, MissingComponent.LTK_MANAGER)
        self.assertEqual((self.ui.asked, self.ui.notices), ([], []))
        self.assertTrue(archive.exists())
        self.assertIsNone(self.entry("voiceover/VO Korean.fantome").ltk_id)

    def test_an_ltk_manager_rose_cannot_use_is_told_and_moves_nothing(self):
        archive = self.category_mod("VO Korean")

        with patch.object(ltf_session, "find_bridge", return_value=None), \
                patch.object(LtfHost, "_ltk_manager_running", return_value=True):
            report = self.migrate()

        self.assertEqual(report.skipped_reason, ALREADY_OPEN_REASON)
        (notice,) = self.ui.notices
        self.assertIn(ALREADY_OPEN_REASON, notice)
        self.assertEqual(self.ui.asked, [], "asked only once LTK Manager can take the mods")
        self.assertTrue(archive.exists())

    def test_not_enough_space_on_ltk_managers_drive_moves_nothing(self):
        archive = self.category_mod("VO Korean")
        self.free = 100 * 1024 ** 2

        report = self.migrate()

        self.assertIn("needed", report.skipped_reason)
        (notice,) = self.ui.notices
        self.assertIn("100 MB is free there", notice)
        self.assertNotIn("import", self.bridge.command_names())
        self.assertTrue(archive.exists())

    def test_a_copy_a_game_kept_needs_no_space(self):
        archive = self.category_mod("VO Korean")
        FakeBridge.initial_library = [{"id": KEPT_ID, "name": "VO Korean", "enabled": False}]
        self.state_path.write_text(json.dumps({"kept": {KEPT_ID: {
            "folder": "VO Korean", "fingerprint": mod_fingerprint(archive), "source": str(archive.resolve()),
        }}}), encoding="utf-8")
        self.free = 0

        report = self.migrate()

        self.assertEqual(report.moved, ["VO Korean"])

    @unittest.skipUnless(sys.platform == "win32", "Windows mutexes")
    def test_another_rose_running_moves_nothing(self):
        folder = make_folder(self.mods_root / "maps" / "Rift", VOICEOVER)
        add_entries(self.mods_root / "maps" / ModStorageService.CATEGORY_METADATA,
                    {"Rift": {"name": "Rift", "path": "Rift"}})

        for name, reason in ((self.single_instance, "Rose is running already"),
                             (self.migration_mutex, "another Rose is moving the mods")):
            with self.subTest(reason):
                handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
                self.assertTrue(handle)
                try:
                    report = self.migrate()
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)

                self.assertEqual(report.skipped_reason, reason)
                self.assertEqual(FakeBridge.created, [])
                self.assertEqual((self.ui.steps, self.ui.notices), ([], []))
                self.assertTrue(folder.is_dir(), "not even packed")


class BackupTests(MigrationTestCase):
    def test_the_backup_is_offered_only_for_mods_an_older_rose_saved(self):
        """A mod added while LTK Manager was busy has its facts already: it moves without a question"""
        facts = compute_mod_facts(make_archive(self.root / "probe.fantome", VOICEOVER))[0]
        self.category_mod("Added during a game", **facts.to_manifest())

        self.migrate()
        self.assertEqual(self.ui.asked, [])

        self.category_mod("From an older Rose", category="maps")
        self.migrate()
        self.assertEqual(len(self.ui.asked), 1)

    def test_the_backup_is_rose_s_mods_folder_as_it_is(self):
        archive = self.category_mod("VO Korean")
        original = archive.read_bytes()
        manifest = (archive.parent / ModStorageService.CATEGORY_METADATA).read_bytes()

        report = self.migrate(FakeUi(backup=True))

        (backup,) = self.desktop.iterdir()
        self.assertEqual(backup.name, f"Rose mods backup {date.today():%Y-%m-%d}")
        self.assertEqual((backup / "voiceover" / "VO Korean.fantome").read_bytes(), original)
        self.assertEqual((backup / "voiceover" / ModStorageService.CATEGORY_METADATA).read_bytes(), manifest)
        self.assertEqual((backup / "voiceover" / "VO Korean.png").read_bytes(), PNG)
        self.assertEqual(report.moved, ["VO Korean"])
        size = sum(path.stat().st_size for path in backup.rglob("*") if path.is_file())
        self.assertEqual(self.ui.asked, [(size, self.free)])
        backups = [step for step in self.ui.steps if step[0] is Step.BACKUP]
        self.assertEqual(backups[-1][4:], (size, size))

    def test_a_backup_of_the_same_day_gets_a_number(self):
        self.category_mod("VO Korean")
        (self.desktop / f"Rose mods backup {date.today():%Y-%m-%d}").mkdir(parents=True)

        self.migrate(FakeUi(backup=True))

        self.assertTrue((self.desktop / f"Rose mods backup {date.today():%Y-%m-%d} (2)" / "voiceover").is_dir())

    def test_a_failed_backup_is_removed_and_nothing_moves(self):
        archive = self.category_mod("VO Korean")

        with patch.object(migration.shutil, "copystat", side_effect=OSError(28, "No space left on device")):
            report = self.migrate(FakeUi(backup=True))

        self.assertEqual(list(self.desktop.iterdir()), [])
        self.assertTrue(archive.exists())
        self.assertEqual(FakeBridge.created[-1].command_names().count("import"), 0)
        self.assertIn("the backup failed", report.skipped_reason)
        (notice,) = self.ui.notices
        self.assertIn("Rose could not back up your mods to your desktop", notice)

    def test_a_desktop_without_room_for_the_backup_moves_nothing(self):
        archive = self.category_mod("VO Korean")
        self.free = 100

        report = self.migrate(FakeUi(backup=True))

        self.assertFalse(self.desktop.exists())
        self.assertTrue(archive.exists())
        self.assertEqual(report.skipped_reason, "not enough space for the backup")
        (notice,) = self.ui.notices
        self.assertIn("100 B free", notice)

    def test_a_backup_that_fits_is_made_without_the_room_imports_keep(self):
        """The 512 MB LTK Manager's imports keep free is no part of a backup's room"""
        self.category_mod("VO Korean")

        with patch.object(migration, "free_space",
                          side_effect=lambda path: 50 * 1024 ** 2 if Path(path) == self.desktop else 100 * GB):
            report = self.migrate(FakeUi(backup=True))

        (backup,) = self.desktop.iterdir()
        self.assertTrue((backup / "voiceover" / "VO Korean.fantome").is_file())
        self.assertEqual(report.moved, ["VO Korean"])

    def test_sizes_read_as_people_read_them(self):
        self.assertEqual([size_text(int(3.6 * GB)), size_text(120 * GB), size_text(850 * 1024 ** 2), size_text(512)],
                         ["3.6 GB", "120 GB", "850 MB", "512 B"])


class ListingTests(MigrationTestCase):
    def test_the_moved_mods_are_listed_as_ltk_managers(self):
        self.category_mod("VO Korean")

        self.migrate()

        (mod,) = iter_saved_mods(self.mods_root, "voiceover")
        self.assertEqual((mod.identity, mod.pending, mod.available), ("voiceover/VO Korean.fantome", False, True))
        (listed,) = self.storage.list_mods_for_category("voiceover")
        self.assertEqual(listed["description"], "VO Korean's description")


if __name__ == "__main__":
    unittest.main()
