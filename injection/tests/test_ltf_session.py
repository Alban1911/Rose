import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from injection.overlay import overlay_manager
from injection.overlay.overlay_manager import OverlayManager, ltk_failure_cause
from injection.overlay.process_manager import ProcessManager
from injection.tools.bridge import BridgeCommandError, BridgeUnavailable
from injection.tools.tools_manager import ToolsManager


def status(running=True, phase="patching", **extra):
    value = {"running": running, "phase": phase, "session": {}, "changesAfterGame": False, **extra}
    return {"ok": True, "response": {"ok": True, "value": value}}


class FakeBridge:
    """Stands in for the bridge inside ltk-manager.exe"""

    created = []
    patcher_statuses = []  # answers to patcher_status, the last one repeats
    initial_library = []
    # Answer an install with the whole entry it created (id, names, enabled),
    # not its id alone
    full_install_answer = False
    # The health_check_off answer; None: a bridge older than the command
    health_check_answer = {"ok": True, "changed": False}
    # Library entries LTK Manager cannot read, logged to broken_log at each read
    broken_ids = []
    broken_log = None
    # LTK Manager's mod storage (modDir per entry) and its health answers
    mod_storage = None
    health_answers = []  # verdicts check_mod_health returns, the last one repeats
    repair_files = None  # {path in archive: bytes} repair_mod writes into the entry's archive

    def __init__(self, port=None, pid=None):
        self.port = port
        self.pid = pid
        self.library_entries = [dict(entry) for entry in FakeBridge.initial_library]
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

    def _install(self, file_name, name):
        mod_id = str(uuid.uuid4())
        entry = {
            "id": mod_id,
            "name": Path(file_name).stem,
            "displayName": name or Path(file_name).stem,
            "enabled": True,
        }
        if FakeBridge.mod_storage is not None:
            entry.update({"modDir": str(FakeBridge.mod_storage / f"mod-{mod_id[:8]}"), "storage": "archive",
                          "format": "fantome"})
        self.library_entries.append(entry)
        value = dict(entry) if FakeBridge.full_install_answer else {"id": mod_id}
        return {"ok": True, "response": {"ok": True, "value": value}}

    def import_fantome(self, path, name=None):
        self.calls.append(("import", path, name))
        return self._install(path, name)

    def import_fantome_bytes(self, data, name):
        self.calls.append(("import_bytes", len(data), name))
        return self._install(name, name)

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

        FakeBridge.reset()
        self.state_path = self.root / "injection" / "ltf_installed.json"
        self.terminated = []
        self.ltk_logs = self.root / "ltk-logs"
        self.ltk_logs.mkdir()

        for patcher in (
            patch.object(overlay_manager, "LtkBridge", FakeBridge),
            patch.object(overlay_manager, "find_bridge", return_value=(46321, {"pid": 777})),
            patch.object(ToolsManager, "detect_ltk_manager", return_value=self.root / "ltk-manager.exe"),
            patch.object(overlay_manager, "report_issue"),
            patch.object(OverlayManager, "_running_game", return_value=None),
            patch.object(OverlayManager, "_ltk_manager_running", return_value=False),
            patch.object(OverlayManager, "_process_created", return_value=None),
            patch.object(OverlayManager, "_terminate_manager",
                         lambda _self, pid, grace_s=0.0: self.terminated.append(pid)),
            patch.object(overlay_manager, "PROCESS_MONITOR_SLEEP_S", 0.01),
            patch.object(overlay_manager, "PATCHER_STATUS_POLL_TICKS", 1),
            patch.object(overlay_manager, "PATCHER_READY_POLL_S", 0.01),
            patch.object(overlay_manager, "PATCHER_IDLE_GRACE_S", 0.05),
            patch.object(overlay_manager, "CDP_READY_POLL_S", 0.01),
            patch.object(overlay_manager, "CDP_READY_TIMEOUT_S", 0.05),
            patch.object(overlay_manager, "PATCHER_STOP_WAIT_S", 0.5),
            # Never this PC's game or client: RestartMissedGameTests turn it on with fakes
            patch.object(overlay_manager, "RESTART_MISSED_GAME", False),
            # Never this PC's own LTK Manager log
            patch.object(overlay_manager.LtkLogTail, "log_dir", staticmethod(lambda: self.ltk_logs)),
            # Nor its LTF logs
            patch.object(overlay_manager, "ltk_logs_dir", lambda: self.root / "logs" / "ltk"),
            patch.object(overlay_manager, "launcher_log_paths",
                         lambda: (self.root / "logs" / "ltk" / "ltk_launcher.log",
                                  self.root / "Public" / "ltk_launcher.log",
                                  self.root / "Temp" / "ltk_launcher.log")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        self.report_issue = overlay_manager.report_issue

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
            patch.object(overlay_manager, "find_bridge", return_value=None),
            patch.object(overlay_manager.subprocess, "run",
                         return_value=MagicMock(returncode=0, stdout=f"LTK_MANAGER_PID={pid}\n")),
        )

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def reported_codes(self):
        return [call.args[0] for call in self.report_issue.call_args_list]

    def reported_causes(self):
        return [
            call.kwargs["details"]["cause"]
            for call in self.report_issue.call_args_list
            if call.args[0] == "LTF_FAILED"
        ]


class InjectionSessionTests(LtfSessionTestCase):
    def test_injection_installs_the_mod_runs_the_patcher_and_cleans_up(self):
        mod = self.make_mod()

        result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 0)
        names = self.bridge.command_names()
        self.assertIn("import", names)
        self.assertIn("start_patcher", names)
        self.assertIn("stop_patcher", names)
        self.assertNotIn("kill", names)  # Rose did not start this LTK Manager
        self.assertEqual(self.bridge.library_entries, [])  # Rose's mod was removed
        self.assertEqual(self.reported_codes(), [])
        self.assertEqual(self.state()["installed"], {})
        self.assertIn("import_duration", self.overlay.last_injection_timing)

    def test_the_archive_is_staged_where_ltk_manager_can_read_it(self):
        mod = self.make_mod()

        self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        path = Path([call for call in self.bridge.calls if call[0] == "import"][0][1])
        self.assertEqual(path.parent.parent, self.root / "injection" / "ltf_staging")
        self.assertFalse(path.exists())  # removed once imported

    def test_an_archive_ltk_manager_cannot_read_is_sent_as_bytes(self):
        mod = self.make_mod()

        def unreadable(bridge_self, path, name=None):
            bridge_self.calls.append(("import", path, name))
            raise BridgeCommandError(f"import failed: not found: {path}")

        with patch.object(FakeBridge, "import_fantome", unreadable):
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 0)
        bytes_calls = [call for call in self.bridge.calls if call[0] == "import_bytes"]
        self.assertEqual(len(bytes_calls), 1)
        self.assertEqual(bytes_calls[0][2], f"{mod}.fantome")
        self.assertEqual(self.reported_codes(), [])

    def test_a_large_unreadable_archive_is_not_sent_as_bytes(self):
        mod = self.make_mod()

        def unreadable(bridge_self, path, name=None):
            raise BridgeCommandError(f"import failed: not found: {path}")

        with patch.object(FakeBridge, "import_fantome", unreadable), \
                patch.object(overlay_manager, "BYTES_IMPORT_LIMIT", 1):
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        self.assertNotIn("import_bytes", self.bridge.command_names())
        self.assertIn("LTF_IMPORT_FAILED", self.reported_codes())

    def test_a_patcher_that_never_starts_fails(self):
        mod = self.make_mod()
        FakeBridge.patcher_statuses = [status(running=False, phase="idle")]

        result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        self.assertIn("LTF_FAILED", self.reported_codes())
        self.assertEqual(self.bridge.library_entries, [])

    def test_a_disabled_import_is_toggled_on(self):
        mod = self.make_mod()
        original = FakeBridge.import_fantome

        def import_disabled(bridge_self, path, name=None):
            response = original(bridge_self, path, name=name)
            bridge_self.library_entries[-1]["enabled"] = False
            return response

        with patch.object(FakeBridge, "import_fantome", import_disabled):
            self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual([call for call in self.bridge.calls if call[0] == "toggle"][0][2], True)

    def test_an_import_answered_with_its_entry_is_not_looked_up_again(self):
        FakeBridge.full_install_answer = True
        FakeBridge.initial_library = [{"id": "user-mod", "name": "Map", "displayName": "Map", "enabled": True}]
        mods = [self.make_mod(), self.make_mod("ROSE-LoadingName", "Loading screen name")]

        self.overlay.mk_run_overlay(mods, stop_callback=lambda: True)

        # One read for both imports and for turning the user's mod off
        self.assertEqual(self.bridge.library_reads, 1)
        self.assertEqual(self.bridge.command_names().count("import"), 2)
        self.assertIn(("toggle", "user-mod", False), self.bridge.calls)
        self.assertEqual(self.bridge.library_entries,
                         [{"id": "user-mod", "name": "Map", "displayName": "Map", "enabled": True}])

    def test_an_import_answered_with_a_disabled_entry_is_toggled_on(self):
        FakeBridge.full_install_answer = True
        original = FakeBridge.import_fantome

        def import_disabled(bridge_self, path, name=None):
            response = original(bridge_self, path, name=name)
            bridge_self.library_entries[-1]["enabled"] = False
            response["response"]["value"]["enabled"] = False
            return response

        with patch.object(FakeBridge, "import_fantome", import_disabled):
            self.overlay.mk_run_overlay([self.make_mod()], stop_callback=lambda: True)

        self.assertEqual([call for call in self.bridge.calls if call[0] == "toggle"][0][2], True)

    def test_an_answer_naming_a_mod_the_user_had_is_not_taken_for_the_import(self):
        FakeBridge.initial_library = [{"id": "user-mod", "name": "Map", "displayName": "Map", "enabled": False}]
        original = FakeBridge.import_fantome

        def answer_with_users_mod(bridge_self, path, name=None):
            response = original(bridge_self, path, name=name)
            response["response"]["value"] = {"id": "user-mod", "enabled": False}
            return response

        with patch.object(FakeBridge, "import_fantome", answer_with_users_mod):
            self.overlay.mk_run_overlay([self.make_mod()], stop_callback=lambda: True)

        # The user's mod is never removed with Rose's
        self.assertNotIn(("uninstall", "user-mod"), self.bridge.calls)
        self.assertEqual([e["id"] for e in self.bridge.library_entries], ["user-mod"])

    def test_a_failed_import_reports_and_ends_the_session(self):
        mod = self.make_mod()

        def refuse(bridge_self, path, name=None):
            raise BridgeCommandError("import failed: bad archive")

        with patch.object(FakeBridge, "import_fantome", refuse):
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        self.assertIn("LTF_IMPORT_FAILED", self.reported_codes())
        names = self.bridge.command_names()
        self.assertNotIn("start_patcher", names)
        self.assertNotIn("kill", names)  # a reused manager belongs to the user

    def test_an_ltk_manager_refusing_the_commands_is_reported_as_outdated(self):
        """#473: an LTK Manager without the library plugin rejected the
        library read, and Troubleshooting told the user to free disk space"""
        def refuse(bridge_self):
            raise BridgeCommandError(
                'list failed: {"ok": false, "raw": {"ok": false, "error": '
                '"Command plugin:library|get_installed_mods not allowed by ACL"}}'
            )

        with patch.object(FakeBridge, "library", refuse):
            result = self.overlay.mk_run_overlay([self.make_mod()], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        self.assertEqual(self.reported_codes(), ["LTF_FAILED"])
        self.assertEqual(self.reported_causes(), ["outdated"])
        self.assertNotIn("start_patcher", self.bridge.command_names())

    def test_a_missing_bridge_reports_ltf_missing(self):
        (self.tools / "ltk_launcher.exe").unlink()
        mod = self.make_mod()

        result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        self.assertIn("LTF_MISSING", self.reported_codes())

    def test_a_missing_ltk_manager_reports_it(self):
        mod = self.make_mod()

        with patch.object(ToolsManager, "detect_ltk_manager", return_value=None):
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        self.assertIn("LTK_MANAGER_MISSING", self.reported_codes())

    def test_the_early_session_reports_nothing_itself(self):
        with patch.object(ToolsManager, "detect_ltk_manager", return_value=None):
            self.overlay.start_patcher_early()

        self.assertEqual(self.reported_codes(), [])

    def test_launching_the_manager_kills_it_after_the_game(self):
        mod = self.make_mod()
        no_bridge, run = self.launched(pid=4242)
        with no_bridge, run as launcher:
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 0)
        self.assertIn("--quiet", launcher.call_args.args[0])
        self.assertIn(("wait_for_bridge", 4242), FakeBridge.created[0].calls)
        self.assertIn("kill", self.bridge.command_names())
        self.assertEqual(self.process_manager.ltk_manager_process, (4242, None))
        self.assertEqual(self.state()["manager"]["pid"], 4242)

    def test_a_reused_manager_rose_started_earlier_is_closed_after_the_game(self):
        self.state_path.write_text(json.dumps({"manager": {"pid": 777, "created": None}}), encoding="utf-8")
        mod = self.make_mod()

        self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertIn("kill", self.bridge.command_names())

    def test_an_open_ltk_manager_is_left_alone_and_reported(self):
        mod = self.make_mod()
        no_bridge, run = self.launched()
        with no_bridge, run as launcher, \
                patch.object(OverlayManager, "_ltk_manager_running", return_value=True):
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        launcher.assert_not_called()
        self.assertEqual(self.reported_causes(), ["running"])

    def test_the_launcher_refusing_an_open_ltk_manager_is_reported(self):
        mod = self.make_mod()
        with patch.object(overlay_manager, "find_bridge", return_value=None), \
                patch.object(overlay_manager.subprocess, "run", return_value=MagicMock(returncode=5, stdout="")):
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        self.assertEqual(self.reported_causes(), ["running"])

    def test_the_launchers_own_log_of_a_start_goes_into_roses_log(self):
        """#478: why the launcher could not make explorer.exe LTK Manager's
        parent was only in ltk_launcher.log, which the user could not find"""
        rose_log, public_log, temp_log = overlay_manager.launcher_log_paths()
        rose_log.parent.mkdir(parents=True)
        rose_log.write_text("[launch] an earlier start, parent pid = 1 (explorer.exe)\r\n", encoding="utf-8")

        def launch(*args, **kwargs):
            with open(rose_log, "a", encoding="utf-8") as handle:
                handle.write("========== ltk_launcher ==========\r\n"
                             "[warn] spawn with explorer.exe as the parent failed (err=87) - starting it as a child\r\n"
                             "[launch] spawned pid = 4242 (suspended), parent pid = 99 (not explorer.exe)\r\n")
            return MagicMock(returncode=0, stdout="LTK_MANAGER_PID=4242\n")

        mod = self.make_mod()
        with patch.object(overlay_manager, "find_bridge", return_value=None), \
                patch.object(overlay_manager.subprocess, "run", side_effect=launch), \
                self.assertLogs(overlay_manager.log.name, level="DEBUG") as logs:
            self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        launcher_lines = [line for line in logs.output if "ltk_launcher:" in line]
        self.assertEqual(len(launcher_lines), 2)  # this start's lines only, without its banner
        self.assertIn("WARNING", launcher_lines[0])
        self.assertIn("starting it as a child", launcher_lines[0])
        self.assertEqual(self.overlay._launcher_parent, "not explorer.exe")
        self.assertFalse(public_log.exists())
        self.assertFalse(temp_log.exists())

    def test_the_launcher_logs_into_roses_logs_folder(self):
        """The LTF logs go to Rose's logs\\ltk folder (Open Logs folder), not
        C:\\Users\\Public where users could not find them"""
        mod = self.make_mod()
        no_bridge, run = self.launched()
        with no_bridge, run as launcher:
            self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        command = launcher.call_args.args[0]
        log_dir = self.root / "logs" / "ltk"
        self.assertEqual(command[command.index("--log-dir") + 1], str(log_dir))
        self.assertTrue(log_dir.is_dir())

    def test_ltk_managers_automatic_mod_check_is_turned_off_before_any_install(self):
        """#481: LTK Manager checked Rose's skin anew every game, for minutes
        on a hard drive while the game loaded"""
        FakeBridge.health_check_answer = {"ok": True, "changed": True}
        mod = self.make_mod()

        with self.assertLogs(overlay_manager.log.name, level="INFO") as logs:
            self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        names = self.bridge.command_names()
        self.assertIn("health_check_off", names)
        self.assertLess(names.index("health_check_off"), names.index("import"))
        self.assertTrue(any("Turned off LTK Manager's automatic mod check" in line for line in logs.output))

    def test_mods_ltk_manager_cannot_read_are_turned_off_for_good(self):
        """#479: an enabled library entry with an empty metadata file failed
        every overlay build; LTK Manager's library leaves it out, so Rose
        never turned it off"""
        broken = "0bb265aa-2b0c-44ff-9cfd-91935223a297"
        FakeBridge.broken_ids = [broken]
        FakeBridge.broken_log = self.ltk_logs / "ltk-manager.2026-11-07.log"
        mod = self.make_mod()

        self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        toggles = [call for call in self.bridge.calls if call[0] == "toggle" and call[1] == broken]
        self.assertEqual(toggles, [("toggle", broken, False)])  # once, and never back on
        names = self.bridge.command_names()
        self.assertLess(names.index("toggle"), names.index("start_patcher"))

    def test_a_bridge_without_the_command_still_injects(self):
        FakeBridge.health_check_answer = None  # an LTF bridge older than it
        mod = self.make_mod()

        result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 0)
        self.assertIn("import", self.bridge.command_names())

    def test_a_large_launcher_log_is_kept_as_old(self):
        rose_log = overlay_manager.launcher_log_paths()[0]
        rose_log.parent.mkdir(parents=True)
        rose_log.write_bytes(b"x" * (overlay_manager.LAUNCHER_LOG_MAX_BYTES + 1))

        mod = self.make_mod()
        no_bridge, run = self.launched()
        with no_bridge, run:
            self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertFalse(rose_log.exists())
        self.assertEqual((rose_log.parent / "ltk_launcher.old.log").stat().st_size,
                         overlay_manager.LAUNCHER_LOG_MAX_BYTES + 1)

    def test_a_failed_launcher_reports_start_failure(self):
        mod = self.make_mod()
        with patch.object(overlay_manager, "find_bridge", return_value=None), \
                patch.object(overlay_manager.subprocess, "run", return_value=MagicMock(returncode=3, stdout="")):
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        self.assertIn("LTF_FAILED", self.reported_codes())
        self.assertEqual(self.reported_causes(), ["start"])

    def test_a_bridge_that_never_comes_up_closes_the_launched_manager(self):
        mod = self.make_mod()
        no_bridge, run = self.launched(pid=4242)

        def never(timeout=30.0, expected_pid=None, cancelled=None):
            raise BridgeUnavailable("did not come up")

        with no_bridge, run, patch.object(FakeBridge, "wait_for_bridge", never):
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        self.assertEqual(self.terminated, [4242])
        self.assertEqual(self.reported_causes(), ["bridge"])

    def test_stopping_the_injection_is_not_reported_as_a_failure(self):
        mod = self.make_mod()
        calls = {"count": 0}

        def stop():
            calls["count"] += 1
            if calls["count"] == 1:
                self.process_manager.stop_injection_by_user()
            return False

        result = self.overlay.mk_run_overlay([mod], stop_callback=stop)

        self.assertEqual(result, 0)
        self.assertEqual(self.reported_codes(), [])
        self.assertIn("stop_patcher", self.bridge.command_names())

    def test_a_stop_while_ltk_manager_starts_is_honoured(self):
        mod = self.make_mod()

        def connect_then_stop(expected_pid=None):
            self.process_manager.stop_injection_by_user()
            return 46321, {"pid": 777}

        with patch.object(overlay_manager, "find_bridge", connect_then_stop):
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 0)
        names = self.bridge.command_names()
        self.assertNotIn("import", names)
        self.assertNotIn("start_patcher", names)

    def test_a_stop_between_imports_installs_nothing_more(self):
        first, second = self.make_mod("1001-A", "Skin A"), self.make_mod("1002-B", "Skin B")
        original = FakeBridge.import_fantome

        def import_then_stop(bridge_self, path, name=None):
            response = original(bridge_self, path, name=name)
            self.process_manager.stopped_by_user = True
            return response

        with patch.object(FakeBridge, "import_fantome", import_then_stop):
            result = self.overlay.mk_run_overlay([first, second], stop_callback=lambda: True)

        self.assertEqual(result, 0)
        self.assertEqual(self.bridge.command_names().count("import"), 1)
        self.assertNotIn("start_patcher", self.bridge.command_names())
        self.assertEqual(self.bridge.library_entries, [])  # the one import was removed again
        self.assertEqual(self.reported_codes(), [])

    def test_a_patchers_status_failure_ends_the_session_with_a_report(self):
        mod = self.make_mod()
        FakeBridge.patcher_statuses = [{"ok": True, "response": {"ok": False, "error": "refused by the game build"}}]

        result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: False)

        self.assertEqual(result, 1)
        self.assertIn("LTF_FAILED", self.reported_codes())
        self.assertEqual(self.reported_causes(), ["unknown"])

    def test_a_dead_bridge_ends_the_session_with_a_report(self):
        mod = self.make_mod()

        def stop():
            self.bridge.is_alive = False
            return False

        result = self.overlay.mk_run_overlay([mod], stop_callback=stop)

        self.assertEqual(result, 1)
        self.assertIn("LTF_FAILED", self.reported_codes())
        self.assertIn("bridge", self.reported_causes())
        # Nothing answered to remove the mod: the next session does it
        self.assertEqual(len(self.state()["installed"]), 1)

    def test_no_game_directory_refuses_the_injection(self):
        overlay = OverlayManager(self.tools, self.mods, None, self.process_manager)

        self.assertEqual(overlay.mk_run_overlay(["mod"], stop_callback=lambda: True), 127)


class LibraryOwnershipTests(LtfSessionTestCase):
    """Rose only ever removes or keeps off what it changed itself"""

    user_mod = {"id": "user-mod", "name": "Eternal Aspect Leona", "displayName": "Eternal Aspect Leona", "enabled": True}

    def test_a_user_mod_with_the_same_name_is_never_taken_for_roses(self):
        FakeBridge.initial_library = [dict(self.user_mod)]
        mod = self.make_mod(display="Eternal Aspect Leona")

        self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertNotIn(("uninstall", "user-mod"), self.bridge.calls)
        self.assertEqual([e["id"] for e in self.bridge.library_entries], ["user-mod"])

    def test_an_unreadable_library_fails_the_import_instead_of_guessing(self):
        FakeBridge.initial_library = [dict(self.user_mod)]
        mod = self.make_mod()

        def connect(expected_pid=None):
            return 46321, {"pid": 777}

        with patch.object(overlay_manager, "find_bridge", connect):
            original_init = FakeBridge.__init__

            def failing_init(bridge_self, port=None, pid=None):
                original_init(bridge_self, port, pid)
                bridge_self.library_fails = True

            with patch.object(FakeBridge, "__init__", failing_init):
                result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        self.assertNotIn("import", self.bridge.command_names())
        self.assertNotIn(("uninstall", "user-mod"), self.bridge.calls)

    def test_the_users_enabled_mods_are_off_during_the_game_and_back_on_after(self):
        FakeBridge.initial_library = [dict(self.user_mod, id="user-map", name="Map", displayName="Map")]
        mod = self.make_mod()
        during = {}

        def stop():
            during.setdefault("enabled", {e["id"]: e["enabled"] for e in self.bridge.library_entries})
            return True

        self.overlay.mk_run_overlay([mod], stop_callback=stop)

        self.assertFalse(during["enabled"]["user-map"])
        self.assertEqual(self.bridge.library_entries, [dict(self.user_mod, id="user-map", name="Map", displayName="Map")])
        self.assertEqual(self.state()["disabled"], [])

    def test_a_crash_with_user_mods_off_turns_them_back_on_next_session(self):
        FakeBridge.initial_library = [dict(self.user_mod, enabled=False)]
        self.state_path.write_text(json.dumps({"installed": {}, "disabled": ["user-mod"]}), encoding="utf-8")

        self.overlay.start_patcher_early()

        self.assertIn(("toggle", "user-mod", True), self.bridge.calls)
        self.assertEqual(self.state()["disabled"], [])

    def test_an_import_that_fails_but_installs_is_still_removed(self):
        mod = self.make_mod()
        original = FakeBridge.import_fantome

        def install_then_time_out(bridge_self, path, name=None):
            original(bridge_self, path, name=name)
            raise BridgeUnavailable("LTKBridge request failed: timed out")

        with patch.object(FakeBridge, "import_fantome", install_then_time_out):
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        self.assertEqual(self.bridge.library_entries, [])
        self.assertEqual(self.state()["installed"], {})


class StaleCleanupTests(LtfSessionTestCase):
    def test_leftover_mods_from_a_crashed_session_are_removed_at_start(self):
        FakeBridge.initial_library = [{"id": "old-id", "name": "SomeFolder", "enabled": True}]
        # The layout the first LTF build wrote
        self.state_path.write_text(json.dumps({"old-id": "SomeFolder"}), encoding="utf-8")

        self.overlay.start_patcher_early()

        self.assertIn(("uninstall", "old-id"), self.bridge.calls)
        self.assertEqual(self.state()["installed"], {})

    def test_a_leftover_that_cannot_be_removed_is_kept_for_next_time(self):
        FakeBridge.initial_library = [{"id": "old-id", "name": "SomeFolder", "enabled": True}]
        self.state_path.write_text(json.dumps({"installed": {"old-id": "SomeFolder"}}), encoding="utf-8")

        def refuse(bridge_self, target):
            raise BridgeCommandError("uninstall failed: CDP busy")

        with patch.object(FakeBridge, "uninstall", refuse):
            self.overlay.start_patcher_early()

        self.assertEqual(self.state()["installed"], {"old-id": "SomeFolder"})

    def test_a_leftover_already_gone_is_forgotten(self):
        self.state_path.write_text(json.dumps({"installed": {"gone-id": "SomeFolder"}}), encoding="utf-8")

        self.overlay.start_patcher_early()

        self.assertNotIn(("uninstall", "gone-id"), self.bridge.calls)
        self.assertEqual(self.state()["installed"], {})


class EarlySessionTests(LtfSessionTestCase):
    def test_the_early_session_is_reused_by_the_injection(self):
        self.overlay.start_patcher_early()
        self.assertEqual(len(FakeBridge.created), 1)
        mod = self.make_mod()

        result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 0)
        self.assertEqual(len(FakeBridge.created), 1)  # connected, not relaunched

    def test_a_repeated_early_start_connects_once(self):
        self.overlay.start_patcher_early()
        self.overlay.start_patcher_early()

        self.assertEqual(len(FakeBridge.created), 1)

    def test_a_dead_early_session_is_replaced(self):
        self.overlay.start_patcher_early()
        self.bridge.is_alive = False

        self.overlay.start_patcher_early()

        self.assertEqual(len(FakeBridge.created), 2)

    def test_discard_stops_a_session_that_never_injected(self):
        self.overlay.start_patcher_early()

        self.overlay.discard_early_patcher()

        names = self.bridge.command_names()
        self.assertIn("stop_patcher", names)
        self.assertNotIn("kill", names)  # a manager Rose merely attached to stays up

    def test_discard_closes_a_manager_rose_launched(self):
        no_bridge, run = self.launched()
        with no_bridge, run:
            self.overlay.start_patcher_early()

        self.overlay.discard_early_patcher()

        self.assertIn("kill", self.bridge.command_names())

    def test_an_injection_after_a_discard_starts_fresh(self):
        self.overlay.start_patcher_early()
        self.overlay.discard_early_patcher()
        mod = self.make_mod()

        result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 0)
        self.assertEqual(len(FakeBridge.created), 2)

    def test_a_discard_does_not_wait_for_ltk_manager_to_start(self):
        release = threading.Event()
        entered = threading.Event()

        def slow_bridge(timeout=30.0, expected_pid=None, cancelled=None):
            entered.set()
            release.wait(5)
            return FakeBridge(port=46321, pid=expected_pid)

        no_bridge, run = self.launched()
        with no_bridge, run, patch.object(FakeBridge, "wait_for_bridge", slow_bridge):
            starter = threading.Thread(target=self.overlay.start_patcher_early)
            starter.start()
            self.assertTrue(entered.wait(5))

            began = time.monotonic()
            self.overlay.discard_early_patcher()
            discard_took = time.monotonic() - began

            release.set()
            starter.join(5)

        self.assertLess(discard_took, 0.5)
        self.assertIsNone(self.overlay._early_session)
        self.assertIn("kill", self.bridge.command_names())  # dropped when its connect completed

    def test_an_injection_waits_for_the_early_connect_instead_of_launching_twice(self):
        release = threading.Event()
        entered = threading.Event()
        original = FakeBridge.wait_for_bridge.__func__

        def slow_bridge(timeout=30.0, expected_pid=None, cancelled=None):
            entered.set()
            release.wait(5)
            return original(FakeBridge, timeout, expected_pid, cancelled)

        mod = self.make_mod()
        no_bridge, run = self.launched()
        with no_bridge, run as launcher, patch.object(FakeBridge, "wait_for_bridge", slow_bridge):
            starter = threading.Thread(target=self.overlay.start_patcher_early)
            starter.start()
            self.assertTrue(entered.wait(5))
            results = []
            injector = threading.Thread(
                target=lambda: results.append(self.overlay.mk_run_overlay([mod], stop_callback=lambda: True))
            )
            injector.start()
            time.sleep(0.1)
            release.set()
            starter.join(5)
            injector.join(5)

        self.assertEqual(results, [0])
        self.assertEqual(launcher.call_count, 1)


class OverlayOnlyTests(LtfSessionTestCase):
    def test_the_mod_is_installed_without_a_patcher(self):
        mod = self.make_mod()

        result = self.overlay.mk_overlay_only([mod])

        self.assertEqual(result, 0)
        names = self.bridge.command_names()
        self.assertIn("import", names)
        self.assertNotIn("start_patcher", names)
        self.assertNotIn("kill", names)
        self.assertEqual(len(self.state()["installed"]), 1)
        self.assertIn("import_duration", self.overlay.last_injection_timing)


class PatcherStatusParsingTests(LtfSessionTestCase):
    def _session(self):
        self.overlay.start_patcher_early()
        return self.overlay._new_session(self.bridge, False)

    def test_a_running_patcher_records_its_phase(self):
        session = self._session()

        self.overlay._poll_patcher_status(session)

        self.assertEqual(session["state"], "patching")
        self.assertIsNone(session["error"])
        self.assertFalse(session["done"])

    def test_a_failed_phase_ends_the_session(self):
        session = self._session()
        FakeBridge.patcher_statuses = [status(running=False, phase="failed")]

        self.overlay._poll_patcher_status(session)

        self.assertIsNotNone(session["error"])

    def test_one_unanswered_poll_does_not_end_the_session(self):
        session = self._session()
        FakeBridge.patcher_statuses = [
            {"ok": False, "error": "CDP busy (another eval in progress)"},
            {"ok": False, "error": "CDP unavailable or timed out"},
            status(),
        ]

        for _ in range(3):
            self.overlay._poll_patcher_status(session)

        self.assertIsNone(session["error"])
        self.assertEqual(session["status_failures"], 0)

    def test_a_patcher_that_keeps_not_answering_ends_the_session(self):
        session = self._session()
        FakeBridge.patcher_statuses = [{"ok": False, "error": "CDP unavailable or timed out"}]

        for _ in range(overlay_manager.STATUS_FAILURE_LIMIT):
            self.overlay._poll_patcher_status(session)

        self.assertIn("CDP unavailable", session["error"])

    def test_a_stopped_patcher_after_the_game_ends_the_session_normally(self):
        session = self._session()
        with patch.object(OverlayManager, "_running_game", return_value=MagicMock()):
            self.overlay._poll_patcher_status(session)
        FakeBridge.patcher_statuses = [status(running=False, phase="idle")]

        self.overlay._poll_patcher_status(session)

        self.assertTrue(session["done"])
        self.assertIsNone(session["error"])

    def test_a_stopped_patcher_before_the_game_appears_keeps_waiting(self):
        session = self._session()
        FakeBridge.patcher_statuses = [status(running=False, phase="idle")]

        self.overlay._poll_patcher_status(session)

        self.assertFalse(session["done"])
        self.assertIsNone(session["error"])

    def test_a_stopped_patcher_with_a_running_game_is_only_logged(self):
        session = self._session()
        FakeBridge.patcher_statuses = [status(running=False, phase="idle")]

        with patch.object(OverlayManager, "_running_game", return_value=MagicMock()):
            self.overlay._poll_patcher_status(session)

        self.assertIsNone(session["error"])
        self.assertFalse(session["done"])

    def test_a_late_join_is_reported_once(self):
        session = self._session()
        FakeBridge.patcher_statuses = [status(session={"verdict": "The DLL joined too late and stayed inert"})]

        self.overlay._poll_patcher_status(session)
        self.overlay._poll_patcher_status(session)

        self.assertEqual(self.reported_causes(), ["late"])
        self.assertIsNone(session["error"])


    def test_an_overlay_disabled_by_the_integrity_check_is_reported_once(self):
        """#432: LTK Manager turned the overlay off for a custom skin made of
        another skin's files, while Rose logged the injection as completed"""
        session = self._session()
        FakeBridge.patcher_statuses = [status(session={"log": '2026-11-05T07:07:34.554873Z  INFO ltk_manager_runtime::patcher::injector: [ltk-dll pid=19852 tid=9656 ERROR] ltk_patcher_dll::verify: overlay verification failed, disabling overlay: wad data/final/champions/zed.wad.client: base-skin check: skin0 is another skin: SkinAudioProperties.BankUnits.Name names zedSkin<n>' + "\n" + '2026-11-05T07:07:35.337701Z  INFO ltk_manager_core::patching::pipeline: Incident recorded: Skinhack Detection id=2026-11-05T10-07-32 verdict=SkinhackDetected'})]

        self.overlay._poll_patcher_status(session)
        self.overlay._poll_patcher_status(session)

        self.assertEqual(self.reported_causes(), ["disabled"])  # its incident only repeats it
        (reason,) = [call.args[2] for call in self.report_issue.call_args_list if call.args[0] == "LTF_FAILED"]
        self.assertIn("zed.wad.client: base-skin check: skin0 is another skin", reason)

    # What LTK Manager logged for #475: its host found the game, the DLL never
    # loaded, and the incident it filed is titled "Unexplained Game Exit"
    NOT_ATTACHED_LOG = (
        "2026-11-07T16:12:27.302329Z  WARN ltk_manager_runtime::patcher::host::persistent: [ltk-host stderr]   "
        "60.000000000s ERROR ltk_patcher_host::worker: failed: DLL never attached after 60s -- if the game is "
        "elevated, run the host elevated\n"
        "2026-11-07T16:12:35.791000Z  INFO ltk_manager_core::patching::pipeline: Incident recorded: Unexplained "
        "Game Exit id=2026-11-08T00-10-46 verdict=EndedWithoutReason"
    )

    def test_a_dll_that_never_got_into_the_game_is_reported_once(self):
        """#475: Troubleshooting only showed the incident's "Unexplained Game
        Exit", not that the patcher never got into the game"""
        session = self._session()
        FakeBridge.patcher_statuses = [status(session={"log": self.NOT_ATTACHED_LOG})]

        self.overlay._poll_patcher_status(session)
        self.overlay._poll_patcher_status(session)

        self.assertEqual(self.reported_causes(), ["not_attached"])  # its incident only repeats it
        (reason,) = [call.args[2] for call in self.report_issue.call_args_list if call.args[0] == "LTF_FAILED"]
        self.assertIn("never got into the game (DLL never attached after 60s)", reason)

    def test_a_dll_that_got_into_the_relaunched_game_is_not_reported(self):
        session = self._session()
        FakeBridge.patcher_statuses = [status(session={"log": self.NOT_ATTACHED_LOG.split("\n")[0] + "\n"
                                                       "2026-11-07T16:13:01.000000Z  INFO x: [ltk-host stderr] "
                                                       "INFO ltk_patcher_host::worker: dll attached pid=9616"})]

        self.overlay._poll_patcher_status(session)

        self.assertEqual(self.reported_causes(), [])

    def test_a_refusal_names_a_manager_not_started_under_explorer(self):
        """#478: LTK Manager's log showed parent ltk_launcher.exe; the reason
        the launcher fell back was only in ltk_launcher.log"""
        session = self._session()
        self.overlay._launcher_parent = "not explorer.exe"
        FakeBridge.patcher_statuses = [status(session={"log": (
            "2026-11-07T20:56:40.028528Z  INFO ltk_manager_runtime::patcher::injector: [ltk-dll pid=19048 "
            "tid=14596 ERROR] ltk_patcher_dll::verify: host verification failed, refusing overlay: "
            "[VRF00000007] (18776)")})]

        self.overlay._poll_patcher_status(session)

        self.assertEqual(self.reported_causes(), ["refused"])
        (reason,) = [call.args[2] for call in self.report_issue.call_args_list if call.args[0] == "LTF_FAILED"]
        self.assertIn("LTK Manager's patcher refused the overlay (host verification failed: VRF00000007 (18776); "
                      "LTK Manager's parent was not explorer.exe (not explorer.exe))", reason)

    def test_a_refusal_with_a_manager_under_explorer_names_no_parent(self):
        session = self._session()
        self.overlay._launcher_parent = "explorer.exe"
        FakeBridge.patcher_statuses = [status(session={"log": "ERROR] ltk_patcher_dll::verify: host verification "
                                                              "failed, refusing overlay: [VRF00000008] (1, x)"})]

        self.overlay._poll_patcher_status(session)

        (reason,) = [call.args[2] for call in self.report_issue.call_args_list if call.args[0] == "LTF_FAILED"]
        self.assertNotIn("parent", reason)

    def test_a_slow_automatic_mod_check_is_reported_once(self):
        """#481: LTK Manager's check of the skin Rose installed took 4 to 6
        minutes on a slow drive, while the game sat on a black loading screen"""
        session = self._session()
        FakeBridge.patcher_statuses = [status(session={"log": (
            "2026-11-07T20:03:50.541496Z  INFO ltk_manager_library::mods::health::sweep: Swept mod health in "
            "263.0511754s: 1 of 1 checked, 0 repairable, 0 unrepairable\n"
            "2026-11-07T20:03:50.559942Z  INFO ltk_manager_library::mods::health::sweep: Swept mod health in "
            "16.5453ms: 1 of 1 checked, 0 repairable, 0 unrepairable")})]

        self.overlay._poll_patcher_status(session)
        self.overlay._poll_patcher_status(session)

        (call,) = [c for c in self.report_issue.call_args_list if c.args[0] == "LTK_SLOW_MOD_CHECK"]
        self.assertEqual(call.args[1], "warning")
        self.assertIn("took 263s on this PC", call.args[2])
        self.assertIn("Automatically check mods", call.kwargs["hint"])
        self.assertEqual(self.reported_causes(), [])  # no failed session

    def test_a_mod_check_of_a_few_seconds_is_not_reported(self):
        session = self._session()
        FakeBridge.patcher_statuses = [status(session={"log": (
            "2026-11-07T20:40:38.929013Z  INFO ltk_manager_library::mods::health::sweep: Swept mod health in "
            "4.0536767s: 1 of 1 checked, 1 repairable, 0 unrepairable")})]

        self.overlay._poll_patcher_status(session)

        self.assertNotIn("LTK_SLOW_MOD_CHECK", self.reported_codes())

    def test_an_incident_after_the_game_is_reported(self):
        """#432: League could not mount a WAD of the overlay and closed"""
        session = self._session()
        FakeBridge.patcher_statuses = [status(session={"log": '2026-11-05T07:04:55.164706Z  INFO ltk_manager_core::patching::pipeline: Incident recorded: WAD Mount Failure id=2026-11-05T10-04-52 verdict=CorruptArchive'})]

        self.overlay._poll_patcher_status(session)

        self.assertEqual(self.reported_causes(), ["corrupt"])
        (reason,) = [call.args[2] for call in self.report_issue.call_args_list if call.args[0] == "LTF_FAILED"]
        self.assertIn("WAD Mount Failure (CorruptArchive", reason)
        self.assertIn("incidents\\2026-11-05T10-04-52.json", reason)


    def test_a_start_while_the_last_patcher_still_builds_waits_for_it(self):
        """#437: LTK Manager stops a patcher only after the overlay build it is
        in (62s with map mods); the restart in between was refused as
        ALREADY_RUNNING and the injection gave up"""
        session = self._session()
        starts = {"count": 0}

        def start_patcher(bridge_self):
            bridge_self.calls.append(("start_patcher",))
            starts["count"] += 1
            if starts["count"] == 1:
                raise overlay_manager.BridgeCommandError(
                    "start_patcher failed: PATCHER ALREADY_RUNNING: The patcher is already running"
                )
            return {"ok": True, "response": {"ok": True, "value": None}}

        FakeBridge.patcher_statuses = [status(running=True, phase="building"),
                                       status(running=True, phase="building"),
                                       status(running=False, phase="idle")]
        with patch.object(FakeBridge, "start_patcher", start_patcher):
            self.assertTrue(self.overlay._start_patcher(session))

        names = self.bridge.command_names()
        self.assertEqual(names.count("start_patcher"), 2)
        self.assertLess(names.index("stop_patcher"), len(names) - 1 - names[::-1].index("start_patcher"))
        self.assertEqual(self.reported_codes(), [])

    def test_a_patcher_that_never_stops_still_fails_the_start(self):
        session = self._session()

        def start_patcher(bridge_self):
            raise overlay_manager.BridgeCommandError(
                "start_patcher failed: PATCHER ALREADY_RUNNING: The patcher is already running"
            )

        FakeBridge.patcher_statuses = [status(running=True, phase="building")]
        with patch.object(FakeBridge, "start_patcher", start_patcher):
            self.assertFalse(self.overlay._start_patcher(session))

        self.assertEqual(self.reported_codes(), ["LTF_FAILED"])

    def test_the_session_waits_for_ltk_managers_browser(self):
        """#431: the bridge answers seconds before LTK Manager's browser does;
        the countdown's staging tried at once, failed with "CDP unavailable"
        and the skin was only installed when the game had started"""
        mod = self.make_mod()
        answers = iter([False, False, True])
        real_library = FakeBridge.library

        def library(bridge_self):
            if not next(answers, True):
                raise overlay_manager.BridgeCommandError(
                    'list failed: {"ok": false, "raw": {"ok": false, "error": "CDP unavailable or timed out"}}'
                )
            return real_library(bridge_self)

        self.overlay.open_staging()
        no_bridge, run = self.launched()  # a freshly started LTK Manager
        with no_bridge, run, patch.object(FakeBridge, "library", library), \
                patch.object(overlay_manager, "CDP_READY_TIMEOUT_S", 5.0):
            self.overlay.start_patcher_early()
            self.assertTrue(self.overlay.stage_mods(self.mods, [mod]))

        self.assertEqual(self.reported_codes(), [])
        self.assertIn("import", [call[0] for call in self.bridge.calls])

    def test_a_page_without_tauri_yet_is_waited_for_too(self):
        """#441: the page answered before Tauri's IPC was set up"""
        mod = self.make_mod()
        answers = iter([False, True])
        real_library = FakeBridge.library

        def library(bridge_self):
            if not next(answers, True):
                raise overlay_manager.BridgeCommandError(
                    'list failed: {"ok": false, "raw": {"ok": false, '
                    '"error": "Cannot read properties of undefined (reading \'invoke\')"}}'
                )
            return real_library(bridge_self)

        self.overlay.open_staging()
        no_bridge, run = self.launched()
        with no_bridge, run, patch.object(FakeBridge, "library", library), \
                patch.object(overlay_manager, "CDP_READY_TIMEOUT_S", 5.0):
            self.overlay.start_patcher_early()
            self.assertTrue(self.overlay.stage_mods(self.mods, [mod]))

        self.assertEqual(self.reported_codes(), [])

    def test_built_in_mods_holding_every_champion_are_reported(self):
        """#441: LTK Manager's "Base skins: Every champion" put 176 archives
        (16 GB) in the overlay: a 258s build, and the game started first"""
        (self.ltk_logs.parent / "settings.json").write_text(json.dumps({
            "builtinMods": {"baseSkins": "allChampions", "characterInking": {"enabled": True}},
        }), encoding="utf-8")

        self.overlay.start_patcher_early()

        (call,) = [c for c in self.report_issue.call_args_list if c.args[0] == "LTK_HEAVY_BUILTINS"]
        self.assertIn("Base skins: Every champion", call.args[2])
        self.assertIn("Character inking: every champion", call.args[2])

    def test_light_built_in_mods_are_left_alone(self):
        for builtins in ({}, {"baseSkins": "moddedChampions"}, {"baseSkins": "off"},
                         {"characterInking": {"enabled": True, "scope": "chosen"}},
                         {"characterInking": {"enabled": False, "scope": "all"}}):
            with self.subTest(builtins=builtins):
                self.assertEqual(overlay_manager.heavy_builtin_mods({"builtinMods": builtins}), [])
        self.assertEqual(overlay_manager.heavy_builtin_mods({}), [])
        self.assertEqual(overlay_manager.heavy_builtin_mods("not a dict"), [])

    def test_unreadable_ltk_settings_report_nothing(self):
        (self.ltk_logs.parent / "settings.json").write_text("{not json", encoding="utf-8")

        self.overlay.start_patcher_early()

        self.assertNotIn("LTK_HEAVY_BUILTINS", self.reported_codes())

    def test_a_browser_that_never_answers_is_still_reported(self):
        mod = self.make_mod()

        def no_cdp(bridge_self):
            raise overlay_manager.BridgeCommandError("list failed: CDP unavailable or timed out")

        no_bridge, run = self.launched()
        with no_bridge, run, patch.object(FakeBridge, "library", no_cdp):
            self.assertEqual(self.overlay.mk_run_overlay([mod], stop_callback=lambda: True), 1)

        self.assertEqual(self.reported_causes(), ["cdp"])


class ModCheckTests(LtfSessionTestCase):
    """LTK Manager checks a mod the user adds, and repairs what it can"""

    SKINHACK = {
        "rule": "bin/skinhack", "title": "Another skin's model",
        "description": "This base skin uses the mesh of another skin.",
        "severity": "error", "count": 1, "fixable": 0,
    }

    def setUp(self):
        super().setUp()
        FakeBridge.mod_storage = self.root / "ltk-mods"
        self.folder = self.mods / self.make_mod()

    def test_a_healthy_mod_is_left_as_it_is_and_removed_from_ltk_manager(self):
        FakeBridge.health_answers = [{"health": "healthy", "fixable": 0, "counts": {}}]

        result = self.overlay.check_mod(self.folder, "Eternal Aspect Leona")

        self.assertEqual(result, {"health": "healthy", "repaired": 0, "problems": []})
        self.assertEqual((self.folder / "WAD" / "Aatrox.wad.client").read_bytes(), b"wad")
        self.assertIn("uninstall", self.bridge.command_names())
        self.assertNotIn("repair_mod", self.bridge.command_names())
        self.assertEqual(self.state()["installed"], {})

    def test_a_repairable_mod_is_repaired_and_rose_keeps_the_repaired_files(self):
        FakeBridge.health_answers = [
            {"health": "repairable", "fixable": 2, "counts": {"errors": 2}},
            {"health": "healthy", "fixable": 0, "counts": {}},
        ]
        FakeBridge.repair_files = {"META/info.json": '{"Name": "Eternal Aspect Leona"}',
                                   "WAD/Aatrox.wad.client": b"fixed"}

        result = self.overlay.check_mod(self.folder, "Eternal Aspect Leona")

        self.assertEqual(result, {"health": "repairable", "repaired": 2, "problems": []})
        self.assertEqual((self.folder / "WAD" / "Aatrox.wad.client").read_bytes(), b"fixed")
        self.assertEqual([p.name for p in self.mods.iterdir()], [self.folder.name])  # nothing left behind
        self.assertIn("uninstall", self.bridge.command_names())

    def test_a_fix_one_pass_leaves_for_the_next_is_applied(self):
        """The Nasus mod: its type fixes rewrote skin0.bin, so the same pass
        skipped its skinhack fix ("skin0.bin changed since the check"); LTK
        Manager's second repair applied it and the mod passed in game"""
        FakeBridge.health_answers = [
            {"health": "repairable", "fixable": 2, "counts": {"fatals": 2}},
            {"health": "repairable", "fixable": 1, "counts": {"errors": 1},
             "rules": [dict(self.SKINHACK, fixable=1)]},
            {"health": "healthy", "fixable": 0, "counts": {}},
        ]
        FakeBridge.repair_files = {"META/info.json": "{}", "WAD/Aatrox.wad.client": b"fixed"}

        result = self.overlay.check_mod(self.folder, "Eternal Aspect Leona")

        self.assertEqual(self.bridge.command_names().count("repair_mod"), 2)
        self.assertEqual(result, {"health": "repairable", "repaired": 4, "problems": []})

    def test_a_mod_the_game_will_reject_is_reported(self):
        """#440, #454: LTK Manager turns off a skin that uses another skin's model"""
        FakeBridge.health_answers = [{"health": "unrepairable", "fixable": 0, "counts": {"errors": 1},
                                      "rules": [self.SKINHACK, dict(self.SKINHACK, rule="x/warning",
                                                                     severity="warning")]}]

        result = self.overlay.check_mod(self.folder, "Eternal Aspect Leona")

        self.assertEqual(result["problems"], [{"rule": "bin/skinhack", "title": "Another skin's model",
                                               "description": "This base skin uses the mesh of another skin."}])
        self.assertNotIn("repair_mod", self.bridge.command_names())

    def test_nothing_is_checked_while_a_game_uses_ltk_manager(self):
        self.process_manager.set_session_stopper(lambda: None)

        self.assertIsNone(self.overlay.check_mod(self.folder, "Eternal Aspect Leona"))
        self.assertEqual(FakeBridge.created, [])

    def test_nothing_is_checked_while_champion_select_stages(self):
        self.overlay._staging_open = True

        self.assertIsNone(self.overlay.check_mod(self.folder, "Eternal Aspect Leona"))
        self.assertEqual(FakeBridge.created, [])


class RestartMissedGameTests(LtfSessionTestCase):
    """The patcher cannot hook a frozen game nor one created before its scan:
    such a game is killed and the client reconnects to the match, launching
    it again while the patcher scans (instead of a lost game)"""

    LATE = status(session={"verdict": "The DLL joined too late and stayed inert"})

    def setUp(self):
        super().setUp()
        self.killed = []
        self.reconnects = []
        self.reconnect_result = True
        self.relaunches = []  # games the client launches again after a kill
        for target, value in (
            ("RESTART_MISSED_GAME", True),
            ("kill_game", self._kill),
            ("reconnect_to_game", lambda stopped=None: self.reconnects.append(stopped) or self.reconnect_result),
            ("restart_window_s", lambda: self.window),
        ):
            patcher = patch.object(overlay_manager, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = 60.0
        self.now = time.time()
        self.game = MagicMock()
        self.game.create_time.return_value = self.now - 5  # the game started seconds ago
        self.running = self.game
        game_patch = patch.object(OverlayManager, "_running_game", side_effect=lambda: self.running)
        game_patch.start()
        self.addCleanup(game_patch.stop)

    def _kill(self, game):
        self.killed.append(game)
        self.running = self.relaunches.pop(0) if self.relaunches else None
        return True

    def _session(self):
        self.overlay.start_patcher_early()
        return self.overlay._new_session(self.bridge, False)

    def test_a_late_join_restarts_the_game_instead_of_losing_it(self):
        session = self._session()
        FakeBridge.patcher_statuses = [self.LATE]

        self.overlay._poll_patcher_status(session)
        self.overlay._poll_patcher_status(session)  # the status still names the killed game

        self.assertEqual(self.killed, [self.game])
        self.assertEqual(len(self.reconnects), 1)
        self.assertEqual(self.reported_causes(), [])
        self.assertFalse(session["ltk_late"])
        self.assertEqual(session["reconnects"], 1)

    def test_the_relaunched_game_missed_too_is_reported(self):
        session = self._session()
        FakeBridge.patcher_statuses = [self.LATE]
        self.overlay._poll_patcher_status(session)

        # LTK Manager's log tells the relaunched game was missed as well
        self.overlay._note_ltk_text(session, "ltk_patcher_dll::entry: joined too late, not overlaying")
        self.overlay._check_patcher_verdict(session)

        self.assertEqual(len(self.killed), 1)  # once a session
        self.assertEqual(self.reported_causes(), ["late"])

    def test_a_client_that_does_not_reconnect_is_reported_once(self):
        self.reconnect_result = False
        session = self._session()
        FakeBridge.patcher_statuses = [self.LATE]

        self.overlay._poll_patcher_status(session)
        self.overlay._poll_patcher_status(session)

        reasons = [call.args[2] for call in self.report_issue.call_args_list if call.args[0] == "LTF_FAILED"]
        self.assertEqual(len(reasons), 1)
        self.assertIn("did not reconnect", reasons[0])

    def test_a_game_created_before_the_scan_is_restarted_before_it_loads(self):
        session = self._session()
        session["scan_started_at"] = self.now - 1
        self.game.create_time.return_value = self.now - 10

        self.overlay._restart_early_game(session)

        self.assertEqual(self.killed, [self.game])
        self.assertEqual(len(self.reconnects), 1)

    def test_a_game_created_under_the_scan_is_left_alone(self):
        session = self._session()
        session["scan_started_at"] = self.now - 10
        self.game.create_time.return_value = self.now - 5

        self.overlay._restart_early_game(session)

        self.assertEqual(self.killed, [])

    def test_an_unknown_scan_start_leaves_it_to_the_late_join_verdict(self):
        session = self._session()
        self.game.create_time.return_value = self.now - 10

        self.overlay._restart_early_game(session)

        self.assertEqual(self.killed, [])

    def test_a_game_past_the_auto_resume_timeout_is_left_running(self):
        """The player is in the match by then: no kill, and Troubleshooting
        suggests a longer Monitor Auto-Resume Timeout instead of a late join"""
        self.window = 20.0
        self.game.create_time.return_value = self.now - 45
        session = self._session()
        FakeBridge.patcher_statuses = [self.LATE]

        self.overlay._poll_patcher_status(session)
        self.overlay._poll_patcher_status(session)

        self.assertEqual(self.killed, [])
        self.assertEqual(self.reconnects, [])
        self.assertEqual(self.reported_causes(), [])  # no late join report on top
        skipped = [call for call in self.report_issue.call_args_list if call.args[0] == "AUTO_RESUME_TRIGGERED"]
        self.assertEqual(len(skipped), 1)
        message = skipped[0].args[2]
        self.assertIn(overlay_manager.RESTART_SKIPPED_MESSAGE, message)
        self.assertRegex(message, r"after 4[45]s")  # what Troubleshooting reads the timeout from
        self.assertIn("Monitor Auto-Resume Timeout (20s)", message)
        self.assertIn("Monitor Auto-Resume Timeout", skipped[0].kwargs["hint"])

    def test_an_early_game_past_the_auto_resume_timeout_is_left_running(self):
        self.window = 20.0
        session = self._session()
        session["scan_started_at"] = self.now - 1
        self.game.create_time.return_value = self.now - 30

        self.overlay._restart_early_game(session)

        self.assertEqual(self.killed, [])
        self.assertIn("AUTO_RESUME_TRIGGERED", self.reported_codes())

    def test_a_game_within_the_auto_resume_timeout_is_restarted(self):
        self.window = 20.0
        self.game.create_time.return_value = self.now - 15
        session = self._session()
        FakeBridge.patcher_statuses = [self.LATE]

        self.overlay._poll_patcher_status(session)

        self.assertEqual(self.killed, [self.game])
        self.assertNotIn("AUTO_RESUME_TRIGGERED", self.reported_codes())

    def test_an_unreadable_start_time_still_restarts(self):
        self.game.create_time.side_effect = overlay_manager.psutil.NoSuchProcess(123)
        session = self._session()
        FakeBridge.patcher_statuses = [self.LATE]

        self.overlay._poll_patcher_status(session)

        self.assertEqual(self.killed, [self.game])

    # -- a game created while the patcher still builds -------------------------
    BUILDING = status(running=True, phase="building")
    READY = status(running=True, phase="patching")

    def _game(self):
        game = MagicMock()
        game.is_running.return_value = True
        return game

    def test_a_game_created_while_the_patcher_builds_is_held_until_it_scans(self):
        """Closing it at once left the player on the reconnect screen while
        the overlay built (and the client relaunched it by itself, too early):
        it is suspended instead, then closed and reconnected to once the
        patcher scans, so only a short reconnect shows"""
        self.game = self.running = self._game()
        session = self._session()
        FakeBridge.patcher_statuses = [self.BUILDING, self.BUILDING, self.BUILDING, self.READY]

        self.assertTrue(self.overlay._wait_for_patcher(session))

        self.game.suspend.assert_called_once()
        self.assertEqual(self.killed, [self.game])  # once the patcher scans
        self.assertEqual(len(self.reconnects), 1)
        self.assertEqual(session["reconnects"], 1)
        self.assertIsNone(session.get("held_game"))
        self.assertNotIn("AUTO_RESUME_TRIGGERED", self.reported_codes())

    def test_the_auto_resume_timeout_resumes_the_held_game(self):
        self.window = 0.05
        self.game = self.running = self._game()
        session = self._session()
        FakeBridge.patcher_statuses = [self.BUILDING]  # never ready

        self.assertTrue(self.overlay._wait_for_patcher(session))

        self.game.suspend.assert_called_once()
        self.game.resume.assert_called_once()
        self.assertEqual(self.killed, [])
        self.assertEqual(self.reconnects, [])
        (report,) = [c for c in self.report_issue.call_args_list if c.args[0] == "AUTO_RESUME_TRIGGERED"]
        self.assertIn("Monitor Auto-Resume Timeout", report.args[2])
        self.assertIn("resumed the game", report.args[2])
        self.assertIn("Monitor Auto-Resume Timeout", report.kwargs["hint"])
        # The game plays on: no restart (nor a second report) once the patcher is ready
        self.assertFalse(self.overlay._restart_missed_game(session, self.game))
        self.assertEqual(self.killed, [])

    def test_a_held_game_that_died_is_replaced_by_the_relaunched_one(self):
        self.game = self.running = self._game()
        session = self._session()
        FakeBridge.patcher_statuses = [self.BUILDING, self.BUILDING, self.BUILDING, self.READY]
        relaunched = self._game()

        def died(*_):
            self.game.is_running.return_value = False
            self.running = relaunched
        self.game.suspend.side_effect = died

        self.assertTrue(self.overlay._wait_for_patcher(session))

        relaunched.suspend.assert_called_once()
        self.assertEqual(self.killed, [relaunched])
        self.assertEqual(len(self.reconnects), 1)

    def test_a_ready_patcher_leaves_the_game_alone(self):
        self.game = self.running = self._game()
        session = self._session()
        FakeBridge.patcher_statuses = [self.READY]

        self.assertTrue(self.overlay._wait_for_patcher(session))

        self.game.suspend.assert_not_called()
        self.assertEqual(self.killed, [])
        self.assertEqual(self.reconnects, [])

    def test_no_game_yet_holds_nothing(self):
        session = self._session()
        FakeBridge.patcher_statuses = [self.BUILDING, self.READY]

        with patch.object(OverlayManager, "_running_game", return_value=None):
            self.assertTrue(self.overlay._wait_for_patcher(session))

        self.assertEqual(self.killed, [])
        self.assertEqual(self.reconnects, [])

    def test_a_failing_patcher_resumes_the_held_game(self):
        self.game = self.running = self._game()
        session = self._session()
        FakeBridge.patcher_statuses = [self.BUILDING, status(running=False, phase="failed")]

        self.assertFalse(self.overlay._wait_for_patcher(session))

        self.game.resume.assert_called_once()
        self.assertEqual(self.killed, [])

    def test_a_stopped_session_resumes_the_held_game(self):
        self.game = self.running = self._game()
        session = self._session()
        FakeBridge.patcher_statuses = [self.BUILDING]
        calls = []

        def stopped(_session):
            calls.append(1)
            return len(calls) > 3

        with patch.object(OverlayManager, "_session_stopped", side_effect=stopped):
            self.assertFalse(self.overlay._wait_for_patcher(session))

        self.game.suspend.assert_called_once()
        self.game.resume.assert_called_once()
        self.assertEqual(self.killed, [])

    # -- the watcher: holds the game from the patcher's start ------------------
    def _watch(self, session):
        with patch.object(overlay_manager, "HOLD_WATCH", True), \
                patch.object(overlay_manager, "HOLD_WATCH_POLL_S", 0.001), \
                patch.object(overlay_manager, "HOLD_WATCH_HELD_POLL_S", 0.001):
            self.overlay._start_hold_watch(session)
        return session["hold_thread"]

    def _until(self, condition, timeout=2.0):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(condition())

    def test_the_watcher_holds_the_game_before_the_injection_waits(self):
        """The wait's own polling came ~1s after the game's start, when the
        game already refused to be suspended (access denied): the watcher
        runs from the patcher's start"""
        self.game = self.running = self._game()
        session = self._session()
        thread = self._watch(session)

        self._until(lambda: session.get("held_game") is self.game)
        FakeBridge.patcher_statuses = [self.READY]
        self.assertTrue(self.overlay._wait_for_patcher(session))
        thread.join(1)

        self.assertFalse(thread.is_alive())
        self.game.suspend.assert_called_once()
        self.assertEqual(self.killed, [self.game])  # created before the scan: restarted
        self.assertEqual(len(self.reconnects), 1)

    def test_the_watcher_resumes_the_game_at_the_auto_resume_timeout(self):
        self.window = 0.05
        self.game = self.running = self._game()
        session = self._session()
        thread = self._watch(session)

        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.game.suspend.assert_called_once()
        self.game.resume.assert_called_once()
        self.assertIn("AUTO_RESUME_TRIGGERED", self.reported_codes())
        self.assertTrue(session["hold_done"])

    def test_an_ended_session_resumes_the_game_the_watcher_held(self):
        self.game = self.running = self._game()
        session = self._session()
        thread = self._watch(session)
        self._until(lambda: session.get("held_game") is self.game)

        self.overlay._end_session(session)
        thread.join(1)

        self.assertFalse(thread.is_alive())
        self.game.resume.assert_called_once()
        self.assertEqual(self.killed, [])

    def test_a_game_created_under_the_scan_is_only_resumed(self):
        self.game = self.running = self._game()
        self.game.create_time.return_value = self.now
        session = self._session()
        session["scan_started_at"] = self.now - 1
        self.overlay._hold_early_game(session)
        FakeBridge.patcher_statuses = [self.READY]

        self.assertTrue(self.overlay._wait_for_patcher(session))

        self.game.resume.assert_called_once()
        self.assertEqual(self.killed, [])
        self.assertEqual(self.reconnects, [])

    def test_a_game_that_cannot_be_suspended_is_left_running(self):
        self.game = self.running = self._game()
        self.game.suspend.side_effect = overlay_manager.psutil.AccessDenied(123)
        session = self._session()
        FakeBridge.patcher_statuses = [self.BUILDING, self.BUILDING, self.READY]

        self.assertTrue(self.overlay._wait_for_patcher(session))

        self.game.suspend.assert_called_once()  # not retried every poll
        self.assertEqual(self.killed, [])


class RestartWindowTests(unittest.TestCase):
    """The Monitor Auto-Resume Timeout setting, read as the restart window"""

    def window(self, value=None, error=None):
        def read(section, key, default):
            self.assertEqual((section, key), ("General", "monitor_auto_resume_timeout"))
            if error:
                raise error
            return default if value is None else value

        with patch("config.get_config_float", side_effect=read):
            return overlay_manager.restart_window_s()

    def test_the_setting_is_the_window(self):
        self.assertEqual(self.window(90), 90.0)

    def test_the_default_is_a_minute(self):
        self.assertEqual(self.window(), 60.0)

    def test_it_is_clamped_to_the_settings_range(self):
        self.assertEqual(self.window(0), 1.0)
        self.assertEqual(self.window(999), 180.0)

    def test_an_unreadable_setting_falls_back_to_the_default(self):
        self.assertEqual(self.window(float("nan")), 60.0)
        self.assertEqual(self.window(error=ValueError("bad")), 60.0)


class FailureCauseTests(unittest.TestCase):
    def test_start_failures(self):
        self.assertEqual(ltk_failure_cause("could not start the LTF launcher (exit code 3)"), "start")
        self.assertEqual(ltk_failure_cause("could not start the LTK patcher (denied)"), "start")

    def test_patcher_refusals_over_administrator_rights(self):
        """#430: LTK refuses to patch League set to run as administrator, or
        from an elevated LTK Manager; neither is a missing launcher file"""
        league = ("could not start the LTK patcher (start_patcher failed: PATCHER LEAGUE_ELEVATED: League is set "
                  "to run as administrator. Turn that off, then start the patcher again)")
        manager = ("could not start the LTK patcher (start_patcher failed: PATCHER MANAGER_ELEVATED: LTK Manager is "
                   "running as administrator. Reopen it normally, or turn on User Account Control if it is off, to "
                   "start the patcher)")
        self.assertEqual(ltk_failure_cause(league), "league_admin")
        self.assertEqual(ltk_failure_cause(manager), "manager_admin")
        # LTK's own log line for it, without the kind
        self.assertEqual(ltk_failure_cause("Start patcher failed: League is set to run as administrator"), "league_admin")
        self.assertIn("Run this program as an administrator", OverlayManager._ltk_failure_hint(league))
        self.assertIn("User Account Control", OverlayManager._ltk_failure_hint(manager))
        # The CDP reason names administrator rights too, but stays a CDP failure
        self.assertEqual(ltk_failure_cause(
            overlay_manager.CDP_UNREACHABLE_REASON + "; Windows runs every program as administrator on this account"
        ), "cdp")

    def test_ltk_managers_missing_patcher_is_not_blamed_on_roses_files(self):
        """#431: LTK Manager's own ltk_patcher_host.exe was gone (an antivirus),
        and the hint sent the user to check Rose's launcher files"""
        reason = ("could not start the LTK patcher (start_patcher failed: UNKNOWN: ltk_patcher_host.exe not "
                  "found. Tried:\n - C:\\Program Files\\LTK Manager\\ltk_patcher_host.exe)")
        self.assertEqual(ltk_failure_cause(reason), "host_missing")
        self.assertIn("Reinstall LTK Manager", OverlayManager._ltk_failure_hint(reason))

    def test_commands_ltk_manager_does_not_declare_mean_it_is_outdated(self):
        """#473: Tauri refuses a command the app does not declare; the reason
        names an install, but the fix is updating LTK Manager, not disk space"""
        reason = ("LTK Manager refused Rose's commands (list failed: {\"error\": \"Command "
                  "plugin:library|get_installed_mods not allowed by ACL\"})")
        self.assertEqual(ltk_failure_cause(reason), "outdated")
        self.assertEqual(ltk_failure_cause(
            "could not start the LTK patcher (Command plugin:patcher|start_patcher not allowed by ACL)"
        ), "outdated")
        hint = OverlayManager._ltk_failure_hint(reason)
        self.assertIn("Update LTK Manager", hint)
        self.assertNotIn("disk space", hint)

    def test_ltk_manager_verdicts_on_the_game(self):
        self.assertEqual(ltk_failure_cause(
            "LTK Manager disabled the overlay (wad data/final/champions/zed.wad.client: base-skin check: skin0 "
            "skeleton is one of zed's other skins' meshes)"
        ), "disabled")
        self.assertEqual(ltk_failure_cause(
            "LTK Manager recorded an incident after the game: WAD Mount Failure (CorruptArchive; "
            "%APPDATA%\\dev.leaguetoolkit.manager\\incidents\\2026-11-05T10-04-52.json)"
        ), "corrupt")
        self.assertEqual(ltk_failure_cause(
            "LTK Manager recorded an incident after the game: Game Crash (Crash; x.json)"
        ), "incident")
        for cause in ("disabled", "corrupt", "incident"):
            self.assertIn("incident" if cause != "disabled" else "custom skin",
                          OverlayManager._ltk_failure_hint(
                              {"disabled": "LTK Manager disabled the overlay (x)",
                               "corrupt": "recorded an incident after the game: x (CorruptArchive; y)",
                               "incident": "LTK Manager recorded an incident after the game: x (Crash; y)"}[cause]))

    def test_ltk_programs_windows_will_not_start_unelevated(self):
        """#456: LTK Manager could not spawn its host, set to run as administrator"""
        reason = ("the LTK patcher stopped before it was ready (LTK Manager: Failed to spawn host "
                  "'ltk_patcher_host.exe': The requested operation requires elevation. (os error 740))")
        self.assertEqual(ltk_failure_cause(reason), "ltk_admin")
        self.assertIn("ltk_patcher_host.exe", OverlayManager._ltk_failure_hint(reason))

    def test_a_patcher_ltks_delivery_service_refused(self):
        """#482: LTK Manager could not download its patcher (429 rate_limited)"""
        reason = ("the LTK patcher stopped before it was ready (LTK Manager: No patcher DLL is available "
                  "error=the delivery service refused the request with status 429 rate_limited)")
        self.assertEqual(ltk_failure_cause(reason), "delivery")
        self.assertIn("delivery service", OverlayManager._ltk_failure_hint(reason))

    def test_a_refused_rose_package_is_sent_to_leagueskins(self):
        """#454: the refused WAD came from an official skin's chroma, and the
        hint said to use the official one"""
        hint = OverlayManager._ltk_failure_hint("LTK Manager disabled the overlay (wad x: base-skin check)")
        self.assertIn("LeagueSkins", hint)
        self.assertNotIn("or the official one", hint)

    def test_a_dll_that_never_got_into_the_game(self):
        reason = "LTK Manager's patcher never got into the game (DLL never attached after 60s)"
        self.assertEqual(ltk_failure_cause(reason), "not_attached")
        hint = OverlayManager._ltk_failure_hint(reason)
        self.assertIn("run as administrator", hint)
        self.assertIn("antivirus", hint)

    def test_bridge_and_import_failures(self):
        self.assertEqual(ltk_failure_cause("the LTF bridge went away during the game"), "bridge")
        self.assertEqual(ltk_failure_cause("the LTF bridge is unreachable (timeout)"), "bridge")
        self.assertEqual(ltk_failure_cause("import failed for My Skin (bad archive)"), "import")

    def test_an_open_ltk_manager_and_a_late_join(self):
        self.assertEqual(ltk_failure_cause(overlay_manager.ALREADY_OPEN_REASON), "running")
        self.assertEqual(
            ltk_failure_cause("the game started before the LTK patcher was scanning (joined too late)"), "late"
        )

    def test_a_refused_overlay(self):
        self.assertEqual(
            ltk_failure_cause(
                "LTK Manager's patcher refused the overlay (host verification VRF00000007 (27688))"
            ),
            "refused",
        )

    def test_process_exit_codes(self):
        killed = str(0x40010004)
        self.assertEqual(ltk_failure_cause(f"exited with code {killed}"), "killed")
        self.assertEqual(ltk_failure_cause("exited with code -1073741819 (0xC0000005)"), "crashed")
        self.assertEqual(ltk_failure_cause("exited with code 1"), "unknown")

    def test_anything_else_is_unknown(self):
        self.assertEqual(ltk_failure_cause("something unexpected"), "unknown")


class FakeProcess:
    def __init__(self, name, created=100.0):
        self._name = name
        self._created = created
        self.terminated = False

    def name(self):
        return self._name

    def create_time(self):
        return self._created

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


class ProcessManagerSessionTests(unittest.TestCase):
    def setUp(self):
        self.process_manager = ProcessManager()
        self.stopped = []
        self.process_manager.set_session_stopper(lambda: self.stopped.append("stopped"))

    def test_stopping_the_overlay_ends_the_session(self):
        self.process_manager.stop_overlay_process()

        self.assertEqual(self.stopped, ["stopped"])
        self.assertTrue(self.process_manager.stopped_by_rose)

    def test_a_user_stop_ends_the_session_and_is_flagged(self):
        self.process_manager.stop_injection_by_user()

        self.assertTrue(self.process_manager.stopped_by_user)
        self.assertEqual(self.stopped, ["stopped"])

    def test_the_champ_select_cleanup_ends_the_session(self):
        self.process_manager.kill_all_runoverlay_processes()

        self.assertEqual(self.stopped, ["stopped"])
        self.assertTrue(self.process_manager.stopped_by_rose)

    def test_a_stopping_session_without_a_stopper_does_not_raise(self):
        self.process_manager.set_session_stopper(None)

        self.process_manager.stop_overlay_process()

        self.assertTrue(self.process_manager.stopped_by_rose)

    def test_a_broken_stopper_is_swallowed(self):
        def boom():
            raise RuntimeError("bridge gone")

        self.process_manager.set_session_stopper(boom)

        self.process_manager.stop_overlay_process()

        self.assertTrue(self.process_manager.stopped_by_rose)

    def test_clearing_keeps_a_newer_sessions_stopper(self):
        newer = lambda: None
        self.process_manager.set_session_stopper(newer)

        self.process_manager.clear_session_stopper(lambda: None)

        self.assertIs(self.process_manager._session_stopper, newer)

    def _sweep(self, process, registered=(42, 100.0)):
        fake_psutil = MagicMock()
        fake_psutil.Process.return_value = process
        fake_psutil.TimeoutExpired = type("TimeoutExpired", (Exception,), {})
        fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        fake_psutil.Error = type("Error", (Exception,), {})
        self.process_manager.ltk_manager_process = registered
        with patch("injection.overlay.process_manager.psutil", fake_psutil), \
                patch("injection.overlay.process_manager.PSUTIL_AVAILABLE", True):
            self.process_manager.kill_all_modtools_processes()
        return fake_psutil

    def test_the_sweep_only_closes_the_ltk_manager_rose_started(self):
        process = FakeProcess("ltk-manager.exe")

        fake_psutil = self._sweep(process)

        fake_psutil.Process.assert_called_once_with(42)
        fake_psutil.process_iter.assert_not_called()  # no sweep by name
        self.assertTrue(process.terminated)
        self.assertIsNone(self.process_manager.ltk_manager_process)

    def test_the_mixed_case_executable_name_is_matched(self):
        process = FakeProcess("LTK Manager.exe")

        self._sweep(process)

        self.assertTrue(process.terminated)

    def test_a_reused_pid_is_not_closed(self):
        process = FakeProcess("ltk-manager.exe", created=999.0)

        self._sweep(process)

        self.assertFalse(process.terminated)

    def test_nothing_is_closed_when_rose_started_no_ltk_manager(self):
        fake_psutil = self._sweep(FakeProcess("ltk-manager.exe"), registered=None)

        fake_psutil.Process.assert_not_called()


class SessionStopperWiringTests(LtfSessionTestCase):
    def test_a_champ_select_cleanup_ends_a_running_session(self):
        mod = self.make_mod()
        seen = {"stopped": False}

        def stop():
            if not seen["stopped"]:
                seen["stopped"] = True
                self.process_manager.kill_all_runoverlay_processes()
            return False

        result = self.overlay.mk_run_overlay([mod], stop_callback=stop)

        self.assertEqual(result, 0)
        self.assertEqual(self.reported_codes(), [])
        self.assertIn("stop_patcher", self.bridge.command_names())

    def test_the_stopper_is_cleared_after_the_session(self):
        mod = self.make_mod()

        self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertIsNone(self.process_manager._session_stopper)


if __name__ == "__main__":
    unittest.main()
