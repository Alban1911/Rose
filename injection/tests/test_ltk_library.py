"""LTK Manager's library holds the user's saved mods: read offline from its
own index, and changed through Rose's bridge outside any game."""

import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from injection.mods.mod_facts import stamp_of
from injection.overlay import ltk_library, overlay_manager
from injection.overlay.ltk_library import (
    IndexEntry,
    LibrarySession,
    LtkBusy,
    LtkLibrary,
    LtkUnavailable,
    entry_archive,
    library_index_mtime,
    read_library_index,
    stored_archive,
)
from injection.overlay.overlay_manager import (
    ALREADY_OPEN_REASON,
    LTF_MISSING_REASON,
    LTK_MANAGER_MISSING_REASON,
    LtkLogTail,
    OverlayManager,
)
from injection.tests.test_ltf_session import FakeBridge, LtfSessionTestCase
from injection.tools.bridge import BridgeCommandError
from injection.tools.tools_manager import ToolsManager

VO_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"
AATROX_ID = "d6f841c7-140b-4ac2-a11c-b37e18eb8006"
LOOSE_ID = "799b6c82-8324-4394-a0cf-ddebcd16eba7"

# library.json as LTK Manager 1.33 writes it: entries carry no enabled flag,
# the active profile lists the enabled ones
LIBRARY = {
    "version": 2,
    "mods": [
        {"id": VO_ID, "installedAt": "2026-11-01T10:00:00Z", "format": "fantome", "storage": "archive",
         "slug": "vo-korean", "harvest": {}, "sourceSha256": "ab" * 32},
        {"id": AATROX_ID, "format": "modpkg", "storage": "archive", "slug": "old-aatrox"},
        {"id": LOOSE_ID, "format": "fantome", "storage": "folder", "slug": "loose"},
        {"format": "fantome", "slug": "no-id"},
    ],
    "profiles": [
        {"id": "default", "name": "Default", "slug": "default", "enabledMods": [VO_ID], "modOrder": [VO_ID]},
        {"id": "other", "name": "Other", "slug": "other", "enabledMods": [AATROX_ID], "modOrder": [AATROX_ID]},
    ],
    "activeProfileId": "default",
    "folders": [],
    "folderOrder": [],
}


class OfflineIndexTests(unittest.TestCase):
    """Never this PC's LTK Manager: its data folder is a temporary one"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.data = self.root / "Roaming" / "dev.leaguetoolkit.manager"
        self.data.mkdir(parents=True)
        self.storage = self.root / "LTK mods"
        self.write("settings.json", {"modStoragePath": str(self.storage), "leaguePath": None})
        self.write("library.json", LIBRARY)
        patcher = patch.object(ltk_library, "ltk_data_dir", return_value=self.data)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, payload):
        (self.data / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_each_entry_is_listed_with_its_archive_and_whether_the_active_profile_enables_it(self):
        index = read_library_index()

        self.assertEqual(sorted(index), sorted([VO_ID, AATROX_ID, LOOSE_ID]))
        self.assertEqual(index[VO_ID], IndexEntry(VO_ID, "vo-korean", "fantome", "archive", True,
                                                  self.storage / "vo-korean.fantome"))
        self.assertEqual(index[AATROX_ID].archive, self.storage / "old-aatrox.modpkg")
        self.assertFalse(index[AATROX_ID].enabled)  # enabled in another profile only
        self.assertIsNone(index[LOOSE_ID].archive)  # kept as a folder

    def test_without_a_storage_path_the_archives_are_in_ltk_managers_data_folder(self):
        self.write("settings.json", {"modStoragePath": None})

        self.assertEqual(read_library_index()[VO_ID].archive, self.data / "mods" / "vo-korean.fantome")
        (self.data / "settings.json").write_text("{", encoding="utf-8")
        self.assertEqual(read_library_index()[VO_ID].archive, self.data / "mods" / "vo-korean.fantome")

    def test_an_index_it_cannot_read_is_none_never_empty(self):
        text = json.dumps(LIBRARY)
        for content in (text[: len(text) // 2], "garbage", json.dumps(dict(LIBRARY, version=3)),
                        json.dumps({"version": 2, "mods": {}}), json.dumps([LIBRARY])):
            with self.subTest(content=content[:30]):
                (self.data / "library.json").write_text(content, encoding="utf-8")
                self.assertIsNone(read_library_index())
        (self.data / "library.json").unlink()
        self.assertIsNone(read_library_index())
        self.assertIsNone(library_index_mtime())
        with patch.object(ltk_library, "ltk_data_dir", return_value=None):
            self.assertIsNone(read_library_index())

    def test_the_index_time_tells_when_the_library_changed(self):
        os.utime(self.data / "library.json", (1_700_000_000, 1_700_000_000))

        self.assertEqual(library_index_mtime(), 1_700_000_000)

    def test_the_stored_archive_only_when_it_is_there(self):
        self.assertIsNone(stored_archive(VO_ID))

        self.storage.mkdir()
        (self.storage / "vo-korean.fantome").write_bytes(b"PK\x05\x06" + bytes(18))

        self.assertEqual(stored_archive(VO_ID), self.storage / "vo-korean.fantome")
        self.assertIsNone(stored_archive(LOOSE_ID))
        self.assertIsNone(stored_archive("0f0f0f0f-0000-4000-8000-000000000000"))

    def test_an_entrys_archive_sits_beside_its_folder(self):
        mod_dir = str(self.storage / "vo-korean")

        self.assertEqual(entry_archive({"modDir": mod_dir, "storage": "archive", "format": "fantome"}),
                         self.storage / "vo-korean.fantome")
        self.assertEqual(entry_archive({"modDir": mod_dir, "format": "modpkg"}), self.storage / "vo-korean.modpkg")
        self.assertIsNone(entry_archive({"modDir": mod_dir, "storage": "folder"}))
        self.assertIsNone(entry_archive({"id": VO_ID, "storage": "archive"}))


class DataFolderTests(unittest.TestCase):
    """LTK Manager's data folder is the desktop user's, even when an elevated
    Rose runs as another account"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.desktop = self.root / "desk" / "AppData" / "Roaming" / "dev.leaguetoolkit.manager"
        self.admin = self.root / "admin" / "AppData" / "Roaming" / "dev.leaguetoolkit.manager"
        for patcher in (
            patch("utils.core.paths.get_user_data_dir", return_value=self.root / "desk" / "AppData" / "Local" / "Rose"),
            patch.dict(os.environ, {"APPDATA": str(self.admin.parent)}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_desktop_users_folder_comes_first(self):
        self.assertIsNone(ltk_library.ltk_data_dir())

        self.admin.mkdir(parents=True)
        self.assertEqual(ltk_library.ltk_data_dir(), self.admin)

        self.desktop.mkdir(parents=True)
        self.assertEqual(ltk_library.ltk_data_dir(), self.desktop)
        self.assertEqual(ltk_library.library_index_path(), self.desktop / "library.json")

    def test_ltk_managers_logs_are_found_as_before(self):
        self.desktop.mkdir(parents=True)  # never logged there
        (self.admin / "logs").mkdir(parents=True)

        self.assertEqual(LtkLogTail.log_dir(), self.admin / "logs")
        (self.desktop / "logs").mkdir()
        self.assertEqual(LtkLogTail.log_dir(), self.desktop / "logs")


class LibrarySessionTests(LtfSessionTestCase):
    def setUp(self):
        super().setUp()
        FakeBridge.mod_storage = self.root / "ltk-mods"
        self.overlay.saved_mods_root = self.root / "saved"
        self.archive = self.root / "saved" / "voiceover" / "VO Korean.fantome"
        self.archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.archive, "w") as packed:
            packed.writestr("META/info.json", '{"Name": "VO Korean"}')
            packed.writestr("WAD/Ahri.ko_KR.wad.client", b"voice")
        self.library = LtkLibrary(self.overlay)

    def test_a_kept_entry_stays_turned_off_and_is_rose_s_no_more(self):
        with self.library.session() as session:
            entry = session.import_archive(self.archive, "VO Korean")
            mod_id = str(entry["id"])
            self.assertEqual(list(self.state()["installed"]), [mod_id])  # a crash here removes it
            session.keep(mod_id)

        self.assertEqual([(e["id"], e["enabled"]) for e in self.bridge.library_entries], [(mod_id, False)])
        self.assertNotIn(("uninstall", mod_id), self.bridge.calls)
        self.assertEqual(self.state()["installed"], {})
        self.assertEqual(self.state()["kept"], {})  # a saved mod, not a kept copy

    def test_an_entry_not_kept_is_removed_at_the_end(self):
        with self.library.session() as session:
            mod_id = str(session.import_archive(self.archive, "VO Korean")["id"])

        self.assertIn(("uninstall", mod_id), self.bridge.calls)
        self.assertEqual(self.bridge.library_entries, [])
        self.assertEqual(self.state()["installed"], {})

    def test_the_archive_goes_to_ltk_manager_as_it_is(self):
        with patch.object(overlay_manager, "write_fantome_zip", side_effect=AssertionError("packed again")):
            with self.library.session() as session:
                session.import_archive(self.archive, "VO Korean")

        imported = [call for call in self.bridge.calls if call[0] == "import"]
        self.assertEqual([(Path(call[1]).name, call[2]) for call in imported], [("VO Korean.fantome", "VO Korean")])
        self.assertTrue(self.archive.exists())
        self.assertEqual(list((self.root / "injection" / "ltf_staging").iterdir()), [])

    def test_an_imported_entrys_archive_is_found(self):
        with self.library.session() as session:
            mod_id = str(session.import_archive(self.archive, "VO Korean")["id"])
            listed = session.confirm(mod_id)
            unknown = session.confirm("0f0f0f0f-0000-4000-8000-000000000000")
            session.keep(mod_id)

        self.assertEqual(entry_archive(listed), FakeBridge.mod_storage / f"mod-{mod_id[:8]}.fantome")
        self.assertIsNone(unknown)

    def test_switching_and_removing_an_entry(self):
        FakeBridge.initial_library = [{"id": VO_ID, "name": "VO", "enabled": False}]

        with self.library.session() as session:
            session.switch(VO_ID, True)
            self.assertTrue(session.library()[VO_ID]["enabled"])
            session.uninstall(VO_ID)

        self.assertEqual(self.bridge.library_entries, [])
        self.assertEqual(self.bridge.command_names().count("uninstall"), 1)

    def test_a_repair_stays_in_ltk_manager(self):
        FakeBridge.health_answers = [
            {"health": "repairable", "fixable": 2, "counts": {"errors": 2}},
            {"health": "healthy", "fixable": 0, "counts": {}},
        ]
        FakeBridge.repair_files = {"META/info.json": "{}", "WAD/Ahri.ko_KR.wad.client": b"fixed"}
        before = self.archive.read_bytes()

        with self.library.session() as session:
            mod_id = str(session.import_archive(self.archive, "VO Korean")["id"])
            result = session.check_and_repair(mod_id, "VO Korean")
            session.keep(mod_id)

        self.assertEqual(result, {"health": "repairable", "repaired": 2, "problems": []})
        self.assertEqual(self.archive.read_bytes(), before)  # nothing written back into Rose
        with zipfile.ZipFile(FakeBridge.mod_storage / f"mod-{mod_id[:8]}.fantome") as repaired:
            self.assertEqual(repaired.read("WAD/Ahri.ko_KR.wad.client"), b"fixed")

    def test_busy_while_champion_select_stages(self):
        self.overlay._staging_open = True

        with self.assertRaises(LtkBusy):
            with self.library.session():
                self.fail("no session while staging")
        self.assertEqual(FakeBridge.created, [])

    def test_busy_while_a_game_holds_ltk_manager(self):
        self.process_manager.set_session_stopper(lambda: None)

        with self.assertRaises(LtkBusy):
            with self.library.session():
                self.fail("no session during a game")
        self.assertEqual(FakeBridge.created, [])

    def test_busy_while_an_injection_installs_before_its_session_is_registered(self):
        """mk_run_overlay installs under the stage lock, its connect done and
        its stopper not registered yet: a session's start-up cleanup would
        take the mods it just installed for an earlier session's leftovers"""
        installed = "0f0f0f0f-0000-4000-8000-000000000000"
        FakeBridge.initial_library = [{"id": installed, "name": "1001-EternalAspect", "enabled": True}]
        self.state_path.write_text(json.dumps({"installed": {installed: "1001-EternalAspect"}}), encoding="utf-8")
        self.assertTrue(self.overlay._stage_lock.acquire(blocking=False))
        self.addCleanup(self.overlay._stage_lock.release)

        with self.assertRaises(LtkBusy):
            with self.library.session():
                self.fail("no session while an injection installs")
        self.assertEqual(FakeBridge.created, [])
        self.assertEqual(list(self.state()["installed"]), [installed])

    def test_busy_at_once_while_another_session_connects(self):
        self.assertTrue(self.overlay._connect_lock.acquire(blocking=False))
        self.addCleanup(self.overlay._connect_lock.release)

        with self.assertRaises(LtkBusy):
            with self.library.session():
                self.fail("no session while another connects")

    def test_waiting_for_another_connect_when_asked(self):
        self.overlay._stage_lock.acquire()
        self.overlay._connect_lock.acquire()
        threading.Timer(0.05, self.overlay._stage_lock.release).start()
        threading.Timer(0.1, self.overlay._connect_lock.release).start()

        with self.library.session(wait=True) as session:
            self.assertEqual(session.library(), {})
        self.assertTrue(self.overlay._stage_lock.acquire(blocking=False))
        self.overlay._stage_lock.release()

    def test_unavailable_without_rose_s_bridge_files(self):
        (self.tools / "ltk_launcher.exe").unlink()

        with self.assertRaises(LtkUnavailable) as raised:
            with self.library.session():
                self.fail("no session without the bridge")
        self.assertEqual(str(raised.exception), LTF_MISSING_REASON)
        self.report_issue.assert_not_called()  # the caller says so, not Troubleshooting

    def test_unavailable_without_ltk_manager(self):
        with patch.object(ToolsManager, "detect_ltk_manager", return_value=None):
            with self.assertRaises(LtkUnavailable) as raised:
                with self.library.session():
                    self.fail("no session without LTK Manager")
        self.assertEqual(str(raised.exception), LTK_MANAGER_MISSING_REASON)

    def test_unavailable_while_the_user_has_ltk_manager_open(self):
        with patch.object(overlay_manager, "find_bridge", return_value=None), \
                patch.object(OverlayManager, "_ltk_manager_running", return_value=True):
            with self.assertRaises(LtkUnavailable) as raised:
                with self.library.session():
                    self.fail("no session beside the user's LTK Manager")
        self.assertEqual(str(raised.exception), ALREADY_OPEN_REASON)
        self.report_issue.assert_not_called()

    def test_an_ltk_manager_rose_started_is_closed_after(self):
        find_bridge, run = self.launched(pid=4242)
        with find_bridge, run:
            with self.library.session() as session:
                session.library()

        self.assertIn("kill", self.bridge.command_names())
        self.assertIn(4242, self.terminated)

    def test_a_failure_inside_still_ends_the_session(self):
        with self.assertRaises(RuntimeError):
            with self.library.session() as session:
                session.import_archive(self.archive, "VO Korean")
                raise RuntimeError("the caller failed")

        self.assertEqual(self.bridge.library_entries, [])
        for lock in (self.overlay._stage_lock, self.overlay._connect_lock):
            self.assertTrue(lock.acquire(blocking=False))
            lock.release()


class ModCheckTests(LtfSessionTestCase):
    """A mod the user adds moves into LTK Manager's library: LTK Manager
    checks it, repairs what it can in its own copy, and keeps it, turned off,
    unless the game would still reject it"""

    SKINHACK = {
        "rule": "bin/skinhack", "title": "Another skin's model",
        "description": "This base skin uses the mesh of another skin.",
        "severity": "error", "count": 1, "fixable": 0,
    }
    REPAIRABLE = {"health": "repairable", "fixable": 2, "counts": {"errors": 2}}
    HEALTHY = {"health": "healthy", "fixable": 0, "counts": {}}

    def setUp(self):
        super().setUp()
        FakeBridge.mod_storage = self.root / "ltk-mods"
        self.stored = self.root / "saved-mods" / "skins" / "89000" / "Leona.fantome"
        self.stored.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.stored, "w") as packed:
            packed.writestr("META/info.json", '{"Name": "Eternal Aspect Leona"}')
            packed.writestr("WAD/Leona.wad.client", b"wad")
        self.before = self.stored.read_bytes()
        self.recorded = []
        self.library = LtkLibrary(self.overlay)

    def record(self, ltk_id, stamp=None):
        """The manifest write: what it was given, and whether the entry was
        still Rose's to remove then (a crash before the keep removes it)"""
        self.recorded.append((ltk_id, stamp, ltk_id in self.state()["installed"]))
        return True

    def check(self, on_kept=None):
        return self.library.check_mod(self.stored, "Eternal Aspect Leona", on_kept or self.record)

    @staticmethod
    def ltk_archive(ltk_id):
        return FakeBridge.mod_storage / f"mod-{ltk_id[:8]}.fantome"

    def test_a_healthy_mod_is_recorded_then_kept_turned_off(self):
        FakeBridge.health_answers = [self.HEALTHY]

        result = self.check()

        ltk_id = result["ltkId"]
        self.assertEqual(result, {"health": "healthy", "repaired": 0, "problems": [], "ltkId": ltk_id})
        self.assertEqual(self.recorded, [(ltk_id, stamp_of(self.ltk_archive(ltk_id)), True)])
        self.assertIsNotNone(self.recorded[0][1])
        self.assertEqual([(e["id"], e["enabled"]) for e in self.bridge.library_entries], [(ltk_id, False)])
        self.assertNotIn(("uninstall", ltk_id), self.bridge.calls)
        self.assertEqual(self.state()["installed"], {})
        self.assertEqual(self.stored.read_bytes(), self.before)  # Rose's copy is the caller's to delete

    def test_a_repaired_mod_is_kept_with_ltk_managers_repair_and_no_stamp(self):
        FakeBridge.health_answers = [self.REPAIRABLE, self.HEALTHY]
        FakeBridge.repair_files = {"META/info.json": "{}", "WAD/Leona.wad.client": b"fixed"}

        result = self.check()

        self.assertEqual(result["repaired"], 2)
        self.assertEqual(self.recorded, [(result["ltkId"], None, True)])  # the next sync reads its facts again
        self.assertEqual(self.stored.read_bytes(), self.before)  # nothing written back into Rose
        self.assertEqual([p.name for p in self.stored.parent.iterdir()], ["Leona.fantome"])
        with zipfile.ZipFile(self.ltk_archive(result["ltkId"])) as repaired:
            self.assertEqual(repaired.read("WAD/Leona.wad.client"), b"fixed")

    def test_a_fix_one_pass_leaves_for_the_next_is_applied(self):
        """The Nasus mod: its type fixes rewrote skin0.bin, so the same pass
        skipped its skinhack fix ("skin0.bin changed since the check"); LTK
        Manager's second repair applied it and the mod passed in game"""
        FakeBridge.health_answers = [
            {"health": "repairable", "fixable": 2, "counts": {"fatals": 2}},
            {"health": "repairable", "fixable": 1, "counts": {"errors": 1}, "rules": [dict(self.SKINHACK, fixable=1)]},
            self.HEALTHY,
        ]
        FakeBridge.repair_files = {"META/info.json": "{}", "WAD/Leona.wad.client": b"fixed"}

        result = self.check()

        self.assertEqual(self.bridge.command_names().count("repair_mod"), 2)
        self.assertEqual((result["repaired"], result["problems"]), (4, []))
        self.assertIn("ltkId", result)

    def test_a_mod_the_game_will_reject_is_removed_and_not_recorded(self):
        """#440, #454: LTK Manager turns off a skin that uses another skin's model"""
        FakeBridge.health_answers = [{"health": "unrepairable", "fixable": 0, "counts": {"errors": 1},
                                      "rules": [self.SKINHACK, dict(self.SKINHACK, rule="x/warning",
                                                                     severity="warning")]}]

        result = self.check()

        self.assertEqual(result["problems"], [{"rule": "bin/skinhack", "title": "Another skin's model",
                                               "description": "This base skin uses the mesh of another skin."}])
        self.assertNotIn("ltkId", result)
        self.assertEqual(self.recorded, [])
        self.assertNotIn("repair_mod", self.bridge.command_names())
        self.assertEqual(self.bridge.library_entries, [])
        self.assertEqual(self.state()["installed"], {})

    def test_an_entry_rose_could_not_record_is_removed_again(self):
        result = self.check(on_kept=lambda ltk_id, stamp=None: False)

        self.assertEqual(result["health"], "healthy")
        self.assertNotIn("ltkId", result)
        self.assertEqual(self.bridge.library_entries, [])
        self.assertEqual(self.state()["installed"], {})

    def test_an_entry_no_longer_listed_after_its_check_is_not_recorded(self):
        with patch.object(LibrarySession, "confirm", return_value=None):
            result = self.check()

        self.assertNotIn("ltkId", result)
        self.assertEqual(self.recorded, [])

    def test_an_entry_ltk_manager_cannot_turn_off_is_still_kept(self):
        with patch.object(FakeBridge, "toggle", side_effect=BridgeCommandError("busy")):
            result = self.check()

        self.assertIn("ltkId", result)  # the next session start turns it off
        self.assertNotIn(("uninstall", result["ltkId"]), self.bridge.calls)
        self.assertEqual(self.state()["installed"], {})

    def test_a_check_that_fails_records_nothing_and_removes_the_entry(self):
        with patch.object(FakeBridge, "check_mod_health", side_effect=BridgeCommandError("CDP busy")):
            self.assertIsNone(self.check())

        self.assertEqual(self.recorded, [])
        self.assertEqual(self.bridge.library_entries, [])

    def test_nothing_is_checked_while_a_game_uses_ltk_manager(self):
        self.process_manager.set_session_stopper(lambda: None)

        self.assertIsNone(self.check())
        self.assertEqual(FakeBridge.created, [])

    def test_nothing_is_checked_while_champion_select_stages(self):
        self.overlay._staging_open = True

        self.assertIsNone(self.check())
        self.assertEqual(FakeBridge.created, [])

    def test_nothing_is_checked_for_a_mod_ltk_manager_holds_already(self):
        """The same mod added again: the saved one, whose file is gone"""
        self.stored.unlink()

        self.assertIsNone(self.check())
        self.assertEqual((FakeBridge.created, self.recorded), ([], []))

    def test_nothing_is_checked_without_ltk_manager_or_a_game_folder(self):
        with patch.object(ToolsManager, "detect_ltk_manager", return_value=None):
            self.assertIsNone(self.check())
        self.overlay.game_dir = None
        self.assertIsNone(self.check())

        self.assertEqual((FakeBridge.created, self.recorded), ([], []))


class RemoveRoseModsTests(LtfSessionTestCase):
    """Rose's uninstaller, the user's data not kept: every entry Rose added to
    LTK Manager's library goes, as nothing would name it after"""

    DELETED = "0f0f0f0f-0000-4000-8000-000000000001"
    KEPT = "0f0f0f0f-0000-4000-8000-000000000002"
    INSTALLED = "0f0f0f0f-0000-4000-8000-000000000003"
    USERS = "0f0f0f0f-0000-4000-8000-000000000004"
    USERS_OFF = "0f0f0f0f-0000-4000-8000-000000000005"

    def setUp(self):
        super().setUp()
        self.mods_root = self.overlay.saved_mods_root
        manifest = self.mods_root / "voiceover" / "rose_category_mods.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"version": 1, "mods": {
            "VO Korean": {"name": "VO Korean", "path": "VO Korean", "ltkId": VO_ID},
            "Lost": {"name": "Lost", "path": "Lost", "ltkId": AATROX_ID, "missing": True},
        }, "pendingRemovals": [self.DELETED]}), encoding="utf-8")
        source = self.mods_root / "maps" / "Rift.fantome"
        source.parent.mkdir()
        source.write_bytes(b"PK")

    def library(self, *entries):
        FakeBridge.initial_library = [{"id": mod_id, "name": mod_id[-4:], "enabled": enabled}
                                      for mod_id, enabled in entries]

    def remove(self):
        return ltk_library.remove_rose_mods(self.overlay)

    def test_every_entry_rose_added_goes_and_the_users_are_turned_back_on(self):
        self.library((VO_ID, True), (self.DELETED, False), (self.KEPT, False), (self.INSTALLED, True),
                     (self.USERS, True), (self.USERS_OFF, False))
        self.state_path.write_text(json.dumps({
            "installed": {self.INSTALLED: "1001-EternalAspect"},
            "disabled": [self.USERS_OFF],
            "kept": {self.KEPT: {"folder": "Rift", "fingerprint": "f" * 64,
                                 "source": str(self.mods_root / "maps" / "Rift.fantome")}},
        }), encoding="utf-8")

        self.assertEqual(self.remove(), 0)

        self.assertEqual(sorted((e["id"], e["enabled"]) for e in self.bridge.library_entries),
                         [(self.USERS, True), (self.USERS_OFF, True)])
        self.assertEqual((self.state()["installed"], self.state()["kept"], self.state()["disabled"]), ({}, {}, []))

    def test_an_entry_a_manifest_names_is_removed_though_a_game_left_it_installed(self):
        self.library((VO_ID, False))
        self.state_path.write_text(json.dumps({"installed": {VO_ID: "VO Korean"}}), encoding="utf-8")

        self.assertEqual(self.remove(), 0)

        self.assertEqual(self.bridge.library_entries, [])

    def test_nothing_rose_added_starts_no_ltk_manager(self):
        (self.mods_root / "voiceover" / "rose_category_mods.json").unlink()

        self.assertEqual(self.remove(), 0)

        self.assertEqual(FakeBridge.created, [])

    def test_without_ltk_manager_it_fails_and_the_uninstall_goes_on(self):
        with patch.object(ToolsManager, "detect_ltk_manager", return_value=None):
            self.assertEqual(self.remove(), 1)

        self.assertEqual(FakeBridge.created, [])

    def test_a_users_mod_that_stays_off_fails_it(self):
        """The session's start only logs a mod it could not turn back on, and
        the uninstaller deletes the record of it right after"""
        self.library((VO_ID, False), (self.USERS_OFF, False))
        self.state_path.write_text(json.dumps({"disabled": [self.USERS_OFF]}), encoding="utf-8")
        toggle = FakeBridge.toggle

        def refuse_turning_on(bridge, target, enabled=True):
            if target == self.USERS_OFF and enabled:
                raise BridgeCommandError("CDP busy")
            return toggle(bridge, target, enabled)

        with patch.object(FakeBridge, "toggle", refuse_turning_on):
            self.assertEqual(self.remove(), 1)

        self.assertEqual([(e["id"], e["enabled"]) for e in self.bridge.library_entries], [(self.USERS_OFF, False)])
        self.assertEqual(self.state()["disabled"], [self.USERS_OFF])

    def test_an_entry_ltk_manager_would_not_remove_fails_it(self):
        self.library((VO_ID, False))

        with patch.object(FakeBridge, "uninstall", side_effect=BridgeCommandError("busy")):
            self.assertEqual(self.remove(), 1)


if __name__ == "__main__":
    unittest.main()
