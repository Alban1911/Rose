import json
import zipfile
from unittest.mock import patch

from injection.overlay import ltk_library
from injection.overlay.ltk_library import LtkLibrary
from injection.tests.test_ltf_session import FakeBridge, LtfSessionTestCase
from injection.tools.bridge import BridgeCommandError

VO_ID = "5e9b2219-f49f-4cf1-bc7e-774fb43e1349"
USERS_ID = "799b6c82-8324-4394-a0cf-ddebcd16eba7"


class RoseProfileTests(LtfSessionTestCase):
    """Every session switches LTK Manager to Rose's profile, and back to the
    user's at its end: the user's profile is never changed"""

    def test_the_users_profile_is_recorded_while_rose_s_is_active(self):
        during = {}

        def stop():
            during.setdefault("state", self.state())
            during.setdefault("active", self.bridge.active_profile_id)
            return True

        self.overlay.mk_run_overlay([self.make_mod()], stop_callback=stop)

        self.assertEqual(during, {"state": dict(during["state"], users_profile="default-id"), "active": "rose-id"})
        self.assertIsNone(self.state()["users_profile"])

    def test_a_profile_named_rose_is_used_again(self):
        FakeBridge.initial_profiles = [{"id": "default-id", "name": "Default"}, {"id": "mine", "name": "Rose"}]

        self.overlay.mk_run_overlay([self.make_mod()], stop_callback=lambda: True)

        self.assertNotIn("create_profile", self.bridge.command_names())
        self.assertIn(("switch_profile", "mine"), self.bridge.calls)

    def test_a_session_that_cannot_switch_to_rose_s_profile_changes_nothing(self):
        FakeBridge.initial_library = [{"id": USERS_ID, "name": "Map", "enabled": True}]
        FakeBridge.profile_switch_fails = True

        self.assertEqual(self.overlay.mk_run_overlay([self.make_mod()], stop_callback=lambda: True), 1)

        self.assertNotIn("import", self.bridge.command_names())
        self.assertNotIn("toggle", self.bridge.command_names())
        self.assertEqual(self.bridge.enabled_in("Default"), {USERS_ID})

    def test_a_switch_back_that_fails_stays_recorded_for_the_next_session(self):
        switch = FakeBridge.switch_profile

        def refuse_the_users(bridge, profile_id):
            if profile_id == "default-id":
                raise BridgeCommandError("CDP busy")
            return switch(bridge, profile_id)

        with patch.object(FakeBridge, "switch_profile", refuse_the_users):
            self.overlay.mk_run_overlay([self.make_mod()], stop_callback=lambda: True)

        self.assertEqual(self.state()["users_profile"], "default-id")

    def test_a_users_profile_deleted_since_is_forgotten(self):
        self.crashed_in_roses_profile()
        self.state_path.write_text(json.dumps({"users_profile": "deleted-id"}), encoding="utf-8")

        self.overlay.start_patcher_early()
        self.overlay.discard_early_patcher()

        self.assertIsNone(self.state()["users_profile"])
        self.assertNotIn("switch_profile", self.bridge.command_names())


class StartRepairTests(LtfSessionTestCase):
    """A Rose that crashed in a game left LTK Manager in Rose's profile: the
    next start switches back"""

    def test_the_next_start_switches_back_to_the_users_profile(self):
        self.crashed_in_roses_profile()

        ltk_library.restore_users_profile(self.host)

        self.assertEqual(self.bridge.active_profile_id, "default-id")
        self.assertIsNone(self.state()["users_profile"])

    def test_a_start_after_a_clean_end_starts_no_ltk_manager(self):
        ltk_library.restore_users_profile(self.host)

        self.assertEqual(FakeBridge.created, [])


class RoseFolderTests(LtfSessionTestCase):
    """The mods Rose added to LTK Manager's library sit in its folder named
    "Rose"; the user's own mods stay where they are"""

    def setUp(self):
        super().setUp()
        voiceover = self.host.saved_mods_root / "voiceover"
        voiceover.mkdir(parents=True)
        (voiceover / "rose_category_mods.json").write_text(json.dumps({"version": 1, "mods": {
            "VO Korean": {"name": "VO Korean", "path": "VO Korean", "ltkId": VO_ID},
        }}), encoding="utf-8")
        FakeBridge.initial_library = [{"id": VO_ID, "name": "VO", "enabled": False},
                                      {"id": USERS_ID, "name": "Map", "enabled": True}]

    def test_a_session_start_files_the_mods_an_earlier_rose_moved(self):
        self.overlay.start_patcher_early()

        self.assertEqual(self.bridge.in_folder("Rose"), {VO_ID})
        self.assertEqual(self.bridge.in_folder(""), {USERS_ID})

    def test_a_filed_mod_is_not_moved_again(self):
        FakeBridge.initial_folders = [{"id": "root", "name": ""}, {"id": "rose-folder", "name": "Rose"}]
        FakeBridge.initial_library[0]["folderId"] = "rose-folder"

        self.overlay.start_patcher_early()

        self.assertNotIn("move_to_folder", self.bridge.command_names())
        self.assertNotIn("create_folder", self.bridge.command_names())

    def test_folders_that_cannot_be_read_do_not_stop_the_session(self):
        with patch.object(FakeBridge, "folders", side_effect=BridgeCommandError("CDP busy")):
            self.assertEqual(self.overlay.mk_run_overlay([self.make_mod()], stop_callback=lambda: True), 0)

    def test_a_mod_added_in_rose_is_filed_when_ltk_manager_keeps_it(self):
        FakeBridge.initial_library = []
        stored = self.root / "saved-mods" / "maps" / "Rift.fantome"
        stored.parent.mkdir(parents=True)
        with zipfile.ZipFile(stored, "w") as packed:
            packed.writestr("META/info.json", '{"Name": "Rift"}')

        result = LtkLibrary(self.host, self.game).check_mod(stored, "Rift", lambda ltk_id, stamp=None: True)

        self.assertEqual(self.bridge.in_folder("Rose"), {result["ltkId"]})
        self.assertNotIn(result["ltkId"], self.bridge.enabled_in("Default"))


class UninstallTests(LtfSessionTestCase):
    """Without "Keep my data", the uninstaller removes Rose's profile and
    folder too, and the user's profile is the active one after"""

    def remove(self):
        return ltk_library.remove_rose_mods(self.host)

    def index_lists_rose_s_profile(self):
        """LTK Manager's index on disk lists Rose's profile, as the fake does."""
        index = json.loads((self.ltk_data / "library.json").read_text(encoding="utf-8"))
        index["profiles"].append({"id": "rose-id", "name": "Rose", "enabledMods": []})
        (self.ltk_data / "library.json").write_text(json.dumps(index), encoding="utf-8")
        FakeBridge.initial_profiles = [{"id": "default-id", "name": "Default"}, {"id": "rose-id", "name": "Rose"}]

    def test_rose_s_profile_and_folder_go_and_the_users_profile_is_active(self):
        self.index_lists_rose_s_profile()
        FakeBridge.initial_profiles = [{"id": "default-id", "name": "Default"}, {"id": "rose-id", "name": "Rose"}]
        FakeBridge.initial_folders = [{"id": "root", "name": ""}, {"id": "rose-folder", "name": "Rose"}]
        FakeBridge.initial_library = [{"id": USERS_ID, "name": "Map", "enabled": True, "folderId": "rose-folder"}]

        self.assertEqual(self.remove(), 0)

        self.assertEqual([p["name"] for p in self.bridge.profile_list], ["Default"])
        self.assertEqual([f["name"] for f in self.bridge.folder_list], [""])
        self.assertEqual(self.bridge.active_profile_id, "default-id")
        self.assertEqual(self.bridge.library_entries[0]["folderId"], "root", "a mod the user put there stays")
        self.assertEqual(self.bridge.enabled_in("Default"), {USERS_ID})

    def test_a_rose_profile_left_alone_is_removed_though_rose_added_no_mod(self):
        self.index_lists_rose_s_profile()

        self.assertEqual(self.remove(), 0)

        self.assertIn(("delete_profile", "rose-id"), self.bridge.calls)

    def test_a_rose_profile_that_cannot_be_deleted_fails_it(self):
        self.index_lists_rose_s_profile()

        with patch.object(FakeBridge, "delete_profile", side_effect=BridgeCommandError("busy")):
            self.assertEqual(self.remove(), 1)
