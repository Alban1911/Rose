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
        return [dict(entry) for entry in self.library_entries]

    def _install(self, file_name, name):
        mod_id = str(uuid.uuid4())
        entry = {
            "id": mod_id,
            "name": Path(file_name).stem,
            "displayName": name or Path(file_name).stem,
            "enabled": True,
        }
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
            # Never this PC's own LTK Manager log
            patch.object(overlay_manager.LtkLogTail, "log_dir", staticmethod(lambda: self.ltk_logs)),
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

        result = self.overlay.mk_run_overlay(
            [mod],
            stop_callback=lambda: True,
            injection_manager=MagicMock(),
        )

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

    def test_the_game_is_resumed_once_the_mods_are_installed(self):
        mod = self.make_mod()
        injection_manager = MagicMock()

        self.overlay.mk_run_overlay([mod], stop_callback=lambda: True, injection_manager=injection_manager)

        injection_manager.resume_game.assert_called_once()

    def test_the_game_is_resumed_only_once_the_patcher_is_scanning(self):
        mod = self.make_mod()
        FakeBridge.patcher_statuses = [
            status(running=True, phase="building"),
            status(running=True, phase="building"),
            status(running=True, phase="patching"),
        ]
        seen = {}
        injection_manager = MagicMock()
        injection_manager.resume_game.side_effect = lambda: seen.setdefault(
            "polls", self.bridge.command_names().count("patcher_status")
        )

        self.overlay.mk_run_overlay([mod], stop_callback=lambda: True, injection_manager=injection_manager)

        self.assertEqual(seen["polls"], 3)  # resumed after the third poll said patching

    def test_a_patcher_that_never_starts_fails_without_resuming(self):
        mod = self.make_mod()
        FakeBridge.patcher_statuses = [status(running=False, phase="idle")]
        injection_manager = MagicMock()

        result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True, injection_manager=injection_manager)

        self.assertEqual(result, 1)
        injection_manager.resume_game.assert_not_called()
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
