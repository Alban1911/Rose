"""What the LTF session tests share: a fake of the bridge inside LTK
Manager, and a temp Rose tree that never reaches this PC's."""

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from injection.overlay import ltf_report, ltf_session, ltk_data, overlay_manager
from injection.overlay.ltf_session import LtfHost
from injection.overlay.overlay_manager import OverlayManager
from injection.overlay.process_manager import ProcessManager
from injection.tools.bridge import BridgeCommandError, BridgeUnavailable
from injection.tools.tools_manager import ToolsManager


def status(running=True, phase="patching", **extra):
    value = {"running": running, "phase": phase, "session": {}, "changesAfterGame": False, **extra}
    return {"ok": True, "response": {"ok": True, "value": value}}


class FakeBridge:

    created = []
    patcher_statuses = []
    initial_library = []
    full_install_answer = False
    health_check_answer = {"ok": True, "changed": False}
    # Library entries LTK Manager cannot read, logged to broken_log at each read
    broken_ids = []
    broken_log = None
    mod_storage = None
    health_answers = []
    repair_files = None
    # LTK Manager's profiles: an entry's "enabled" is the active profile's,
    # and each other profile keeps its own (enabled_by_profile)
    initial_profiles = None
    initial_active_profile = None
    initial_folders = None
    profile_switch_fails = False

    def __init__(self, port=None, pid=None):
        self.port = port
        self.pid = pid
        self.library_entries = [dict(entry) for entry in FakeBridge.initial_library]
        for entry in self.library_entries:
            entry.setdefault("folderId", "root")
        self.profile_list = [dict(p) for p in FakeBridge.initial_profiles or [{"id": "default-id", "name": "Default"}]]
        self.active_profile_id = FakeBridge.initial_active_profile or self.profile_list[0]["id"]
        self.enabled_by_profile = {}
        self.folder_list = [dict(f) for f in FakeBridge.initial_folders or [{"id": "root", "name": ""}]]
        self.calls = []
        self.is_alive = True
        self.library_fails = False
        self.library_reads = 0
        FakeBridge.created.append(self)

    @classmethod
    def reset(cls):
        cls.created = []
        cls.patcher_statuses = []
        cls.initial_library = []
        cls.full_install_answer = False
        cls.health_check_answer = {"ok": True, "changed": False}
        cls.broken_ids = []
        cls.broken_log = None
        cls.mod_storage = None
        cls.health_answers = []
        cls.repair_files = None
        cls.initial_profiles = None
        cls.initial_active_profile = None
        cls.initial_folders = None
        cls.profile_switch_fails = False

    @classmethod
    def wait_for_bridge(cls, timeout=30.0, expected_pid=None, cancelled=None):
        bridge = cls(port=46321, pid=expected_pid)
        bridge.calls.append(("wait_for_bridge", expected_pid))
        return bridge

    def hello(self):
        return {"ok": True, "service": "LTKBridge", "pid": self.pid}

    def ping(self):
        if not self.is_alive:
            raise BridgeUnavailable("gone")
        return {"ok": True, "pong": 1}

    def alive(self):
        return self.is_alive

    def library(self):
        self.library_reads += 1
        if self.library_fails:
            raise BridgeCommandError("list failed: CDP busy (another eval in progress)")
        # LTK Manager logs, at each read, the entries it cannot read and leaves out
        if FakeBridge.broken_log is not None:
            with open(FakeBridge.broken_log, "a", encoding="utf-8") as handle:
                for mod_id in FakeBridge.broken_ids:
                    handle.write("2026-11-07T23:20:47.381184Z  WARN ltk_manager_library::mods::library: Skipping "
                                 f"broken mod entry {mod_id}: Serialization error: expected value at line 1 column 1\n")
        return [dict(entry) for entry in self.library_entries]

    def _install(self, file_name, name, data):
        mod_id = str(uuid.uuid4())
        entry = {
            "id": mod_id,
            "name": Path(file_name).stem,
            "displayName": name or Path(file_name).stem,
            "enabled": True,
            "folderId": "root",
        }
        if FakeBridge.mod_storage is not None:
            mod_dir = FakeBridge.mod_storage / f"mod-{mod_id[:8]}"
            mod_dir.parent.mkdir(parents=True, exist_ok=True)
            mod_dir.with_name(f"{mod_dir.name}.fantome").write_bytes(data)
            entry.update({"modDir": str(mod_dir), "storage": "archive", "format": "fantome"})
        self.library_entries.append(entry)
        value = dict(entry) if FakeBridge.full_install_answer else {"id": mod_id}
        return {"ok": True, "response": {"ok": True, "value": value}}

    def import_fantome(self, path, name=None):
        self.calls.append(("import", path, name))
        return self._install(path, name, Path(path).read_bytes() if FakeBridge.mod_storage is not None else b"")

    def import_fantome_bytes(self, data, name):
        self.calls.append(("import_bytes", len(data), name))
        return self._install(name, name, data)

    def toggle(self, target, enabled=True):
        self.calls.append(("toggle", target, enabled))
        for entry in self.library_entries:
            if entry["id"] == target:
                entry["enabled"] = enabled
        return {"ok": True}

    def uninstall(self, target):
        self.calls.append(("uninstall", target))
        remaining = [e for e in self.library_entries if e["id"] != target]
        if len(remaining) == len(self.library_entries):
            raise BridgeCommandError(f"unknown mod {target}")
        self.library_entries = remaining
        return {"ok": True}

    def check_mod_health(self, mod_id):
        self.calls.append(("check_mod_health", mod_id))
        answers = FakeBridge.health_answers
        verdict = answers.pop(0) if len(answers) > 1 else (answers[0] if answers else {"health": "healthy"})
        return {"ok": True, "response": {"ok": True, "value": dict(verdict, modId=mod_id)}}

    def repair_mod(self, mod_id):
        self.calls.append(("repair_mod", mod_id))
        files = FakeBridge.repair_files or {}
        entry = next(e for e in self.library_entries if e["id"] == mod_id)
        archive = Path(entry["modDir"] + ".fantome")
        archive.parent.mkdir(parents=True, exist_ok=True)
        import zipfile
        with zipfile.ZipFile(archive, "w") as packed:
            for name, data in files.items():
                packed.writestr(name, data)
        return {"ok": True, "response": {"ok": True, "value": {"applied": len(files), "skipped": 0,
                                                               "remaining": [], "failed": []}}}

    def health_check_off(self):
        self.calls.append(("health_check_off",))
        if FakeBridge.health_check_answer is None:
            raise BridgeCommandError("unknown: health_check_off")
        return FakeBridge.health_check_answer

    def start_patcher(self):
        self.calls.append(("start_patcher",))
        return {"ok": True, "response": {"ok": True, "value": None}}

    def stop_patcher(self):
        self.calls.append(("stop_patcher",))
        return {"ok": True, "response": {"ok": True, "value": None}}

    def patcher_status(self):
        self.calls.append(("patcher_status",))
        if not FakeBridge.patcher_statuses:
            return status()
        if len(FakeBridge.patcher_statuses) > 1:
            return FakeBridge.patcher_statuses.pop(0)
        return FakeBridge.patcher_statuses[0]

    def kill(self):
        self.calls.append(("kill",))
        self.is_alive = False
        return {"ok": True}

    def profiles(self):
        self.calls.append(("profiles",))
        return [dict(profile) for profile in self.profile_list]

    def active_profile(self):
        self.calls.append(("active_profile",))
        return dict(next(p for p in self.profile_list if p["id"] == self.active_profile_id))

    def create_profile(self, name):
        self.calls.append(("create_profile", name))
        profile = {"id": f"{name.lower()}-id", "name": name}
        self.profile_list.append(profile)
        return dict(profile)

    def switch_profile(self, profile_id):
        self.calls.append(("switch_profile", profile_id))
        if FakeBridge.profile_switch_fails or all(p["id"] != profile_id for p in self.profile_list):
            raise BridgeCommandError(f"switch_profile failed: Profile {profile_id} not found")
        self.enabled_by_profile[self.active_profile_id] = {e["id"] for e in self.library_entries if e.get("enabled")}
        enabled = self.enabled_by_profile.get(profile_id, set())
        for entry in self.library_entries:
            entry["enabled"] = entry["id"] in enabled
        self.active_profile_id = profile_id

    def delete_profile(self, profile_id):
        self.calls.append(("delete_profile", profile_id))
        if profile_id == self.active_profile_id:
            raise BridgeCommandError("Cannot delete active profile")
        self.profile_list = [p for p in self.profile_list if p["id"] != profile_id]

    def enabled_in(self, profile_name):
        profile_id = next(p["id"] for p in self.profile_list if p["name"] == profile_name)
        if profile_id == self.active_profile_id:
            return {e["id"] for e in self.library_entries if e.get("enabled")}
        return set(self.enabled_by_profile.get(profile_id, set()))

    def folders(self):
        self.calls.append(("folders",))
        return [dict(folder, modIds=[e["id"] for e in self.library_entries if e.get("folderId") == folder["id"]])
                for folder in self.folder_list]

    def create_folder(self, name):
        self.calls.append(("create_folder", name))
        folder = {"id": f"{name.lower()}-folder", "name": name}
        self.folder_list.append(folder)
        return dict(folder, modIds=[])

    def move_to_folder(self, mod_id, folder_id):
        self.calls.append(("move_to_folder", mod_id, folder_id))
        entry = next((e for e in self.library_entries if e["id"] == mod_id), None)
        if entry is None or entry.get("folderId") == folder_id:
            raise BridgeCommandError("move_to_folder failed: not found or already in the target folder")
        entry["folderId"] = folder_id

    def delete_folder(self, folder_id):
        self.calls.append(("delete_folder", folder_id))
        for entry in self.library_entries:
            if entry.get("folderId") == folder_id:
                entry["folderId"] = "root"
        self.folder_list = [f for f in self.folder_list if f["id"] != folder_id]

    def in_folder(self, folder_name):
        folder = next((f for f in self.folder_list if f["name"] == folder_name), None)
        return {e["id"] for e in self.library_entries if folder is not None and e.get("folderId") == folder["id"]}

    def command_names(self):
        return [call[0] for call in self.calls]


class LtfSessionTestCase(unittest.TestCase):
    """Shared setup: a temp Rose tree and a faked bridge/launcher"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.tools = self.root / "tools"
        self.tools.mkdir()
        (self.tools / "ltk_launcher.exe").write_bytes(b"launcher")
        (self.tools / "LeagueToolFlop.dll").write_bytes(b"dll")
        self.mods = self.root / "injection" / "mods"
        self.mods.mkdir(parents=True)
        self.game = self.root / "game"
        self.game.mkdir()
        self.process_manager = ProcessManager()
        self.overlay = OverlayManager(self.tools, self.mods, self.game, self.process_manager)
        self.host = self.overlay.host

        FakeBridge.reset()
        self.state_path = self.root / "injection" / "ltf_installed.json"
        self.terminated = []
        self.ltk_logs = self.root / "ltk-logs"
        self.ltk_logs.mkdir()
        self.report_issue = MagicMock()
        self.resolve_issue = MagicMock()

        for patcher in (
            patch.object(ltf_session, "LtkBridge", FakeBridge),
            patch.object(ltf_session, "find_bridge", return_value=(46321, {"pid": 777})),
            patch.object(ToolsManager, "detect_ltk_manager", return_value=self.root / "ltk-manager.exe"),
            patch.object(overlay_manager, "report_issue", self.report_issue),
            patch.object(ltf_session, "report_issue", self.report_issue),
            patch.object(ltf_session, "resolve_issue", self.resolve_issue),
            patch.object(ltf_report, "report_issue", self.report_issue),
            patch.object(OverlayManager, "_running_game", return_value=None),
            patch.object(LtfHost, "_ltk_manager_running", return_value=False),
            patch.object(LtfHost, "_process_created", return_value=None),
            patch.object(LtfHost, "_terminate_manager",
                         lambda _self, pid, grace_s=0.0: self.terminated.append(pid)),
            patch.object(overlay_manager, "PROCESS_MONITOR_SLEEP_S", 0.01),
            patch.object(overlay_manager, "PATCHER_STATUS_POLL_TICKS", 1),
            patch.object(overlay_manager, "PATCHER_READY_POLL_S", 0.01),
            patch.object(overlay_manager, "PATCHER_IDLE_GRACE_S", 0.05),
            patch.object(ltf_session, "CDP_READY_POLL_S", 0.01),
            patch.object(ltf_session, "CDP_READY_TIMEOUT_S", 0.05),
            patch.object(overlay_manager, "PATCHER_STOP_WAIT_S", 0.5),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.isolate_from_this_pc()

    def isolate_from_this_pc(self):
        """Never this PC's saved mods, LTK Manager data and log, LTF logs,
        registry or Rose's diagnostics file: the test's folders instead. Nor
        its game or client: a test that restarts a missed game fakes them."""
        self.host.saved_mods_root = self.root / "saved-mods"
        self.ltk_data = self.root / "ltk-data"
        self.ltk_data.mkdir(exist_ok=True)
        (self.ltk_data / "library.json").write_text(json.dumps({
            "version": 2, "mods": [], "activeProfileId": "default-id",
            "profiles": [{"id": "default-id", "name": "Default", "enabledMods": []}],
            "folders": [{"id": "root", "name": "", "modIds": []}], "folderOrder": ["root"],
        }), encoding="utf-8")
        for patcher in (
            patch.object(ltk_data, "ltk_data_dir", return_value=self.ltk_data),
            patch.object(ltk_data.LtkLogTail, "log_dir", staticmethod(lambda: self.ltk_logs)),
            patch.object(ltf_session, "ltk_logs_dir", lambda: self.root / "logs" / "ltk"),
            patch("utils.system.windows_account.check_ltk_settings", return_value=False),
            patch.object(overlay_manager, "RESTART_MISSED_GAME", False),
            patch.object(ltf_session, "launcher_log_paths",
                         lambda: (self.root / "logs" / "ltk" / "ltk_launcher.log",
                                  self.root / "Public" / "ltk_launcher.log",
                                  self.root / "Temp" / "ltk_launcher.log")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    @property
    def bridge(self):
        self.assertTrue(FakeBridge.created, "no bridge was created")
        return FakeBridge.created[-1]

    def make_mod(self, name="1001-EternalAspect", display="Eternal Aspect Leona", where=None, wad=b"wad"):
        folder = (where or self.mods) / name
        (folder / "META").mkdir(parents=True)
        (folder / "META" / "info.json").write_text(
            json.dumps({"Name": display, "Author": "Tester", "Version": "1.0.0"}),
            encoding="utf-8",
        )
        (folder / "WAD").mkdir()
        (folder / "WAD" / "Aatrox.wad.client").write_bytes(wad)
        return name

    def launched(self, pid=4242):
        """Patches for an LTK Manager Rose starts through the launcher."""
        return (
            patch.object(ltf_session, "find_bridge", return_value=None),
            patch.object(ltf_session.subprocess, "run",
                         return_value=MagicMock(returncode=0, stdout=f"LTK_MANAGER_PID={pid}\n")),
        )

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def crashed_in_roses_profile(self, **state):
        """LTK Manager as a Rose that crashed in a game left it: Rose's
        profile active (what initial_library enables is on there), and the
        journal recording the user's profile to switch back to."""
        FakeBridge.initial_profiles = [{"id": "default-id", "name": "Default"}, {"id": "rose-id", "name": "Rose"}]
        FakeBridge.initial_active_profile = "rose-id"
        self.state_path.write_text(json.dumps({"users_profile": "default-id", **state}), encoding="utf-8")

    def reported_codes(self):
        return [call.args[0] for call in self.report_issue.call_args_list]

    def reported_causes(self):
        return [
            call.kwargs["details"]["cause"]
            for call in self.report_issue.call_args_list
            if call.args[0] == "LTF_FAILED"
        ]
