import shutil
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from injection.core import manager as manager_module
from injection.core import stage_plan as stage_plan_module
from injection.core.manager import InjectionManager
from injection.core.stage_plan import (
    PARTY_SKINS_LABEL,
    CarrierStep,
    LoadingNameStep,
    ModStep,
    PartyStep,
    StagePlan,
    prepare_plan,
    skin_plan,
)
from injection.mods.fingerprint import mod_fingerprint
from injection.overlay import overlay_manager
from injection.overlay.overlay_manager import LtkLogTail
from injection.tests.test_ltf_session import FakeBridge, LtfSessionTestCase, status
from threads.handlers.injection_trigger import InjectionTrigger
from utils.core.junction import link_or_extract


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)

    def folder(self, name, files):
        folder = self.root / name
        for relative, data in files.items():
            (folder / relative).parent.mkdir(parents=True, exist_ok=True)
            (folder / relative).write_bytes(data)
        return folder

    def test_the_same_files_anywhere_give_the_same_digest(self):
        files = {"META/info.json": b"{}", "WAD/Aatrox.wad.client": b"wad"}

        self.assertEqual(mod_fingerprint(self.folder("a", files)), mod_fingerprint(self.folder("b", files)))

    def test_other_content_or_names_give_another_digest(self):
        base = mod_fingerprint(self.folder("a", {"WAD/Aatrox.wad.client": b"wad"}))

        self.assertNotEqual(base, mod_fingerprint(self.folder("b", {"WAD/Aatrox.wad.client": b"other"})))
        self.assertNotEqual(base, mod_fingerprint(self.folder("c", {"WAD/Ahri.wad.client": b"wad"})))

    def test_a_large_file_is_told_apart_by_its_ends(self):
        size = 6 * 1024 * 1024
        first = bytearray(size)
        second = bytearray(size)
        second[-1] = 1

        self.assertNotEqual(
            mod_fingerprint(self.folder("a", {"WAD/Map11.wad.client": bytes(first)})),
            mod_fingerprint(self.folder("b", {"WAD/Map11.wad.client": bytes(second)})),
        )


class OverlayStagingTests(LtfSessionTestCase):
    """The countdown stages the mods; the injection reuses them as they are"""

    def setUp(self):
        super().setUp()
        self.stage_dir = self.root / "injection" / "stage"
        self.stage_dir.mkdir(parents=True)
        self.overlay.open_staging()

    def stage(self, name="1001-EternalAspect", display="Eternal Aspect Leona", wad=b"wad"):
        # The stager empties its folder before preparing each selection
        shutil.rmtree(self.stage_dir / name, ignore_errors=True)
        mod = self.make_mod(name, display, where=self.stage_dir, wad=wad)
        return mod, self.overlay.stage_mods(self.stage_dir, [mod])

    def test_staging_installs_the_mods_and_starts_the_patcher(self):
        _, staged = self.stage()

        self.assertTrue(staged)
        names = self.bridge.command_names()
        self.assertIn("import", names)
        self.assertEqual(names.count("start_patcher"), 1)
        self.assertEqual(len(self.state()["installed"]), 1)

    def test_an_injection_of_the_staged_mods_leaves_the_library_and_the_scan_alone(self):
        self.stage()
        before = list(self.bridge.calls)
        mod = self.make_mod()  # the same skin, extracted again by the injection

        result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 0)
        during = [call[0] for call in self.bridge.calls[len(before):]]
        self.assertNotIn("import", during)
        self.assertNotIn("start_patcher", during)
        self.assertEqual(self.bridge.library_entries, [])  # removed after the game
        self.assertEqual(self.reported_codes(), [])

    def test_an_injection_reuses_staged_mods_linked_from_the_cache(self):
        cache = self.root / "injection" / ".extract_cache"
        self.make_mod("Rift", "Rift", where=cache, wad=b"map")
        skin = self.make_mod(where=self.stage_dir)
        link_or_extract(cache / "Rift", self.stage_dir / "Rift", cache_dir=cache)
        self.assertTrue(self.overlay.stage_mods(self.stage_dir, [skin, "Rift"]))
        before = list(self.bridge.calls)
        self.make_mod()  # the injection extracts the skin and links the map again
        link_or_extract(cache / "Rift", self.mods / "Rift", cache_dir=cache)

        result = self.overlay.mk_run_overlay([skin, "Rift"], stop_callback=lambda: True)

        self.assertEqual(result, 0)
        during = [call[0] for call in self.bridge.calls[len(before):]]
        self.assertNotIn("import", during)
        self.assertNotIn("start_patcher", during)
        self.assertEqual((cache / "Rift" / "WAD" / "Aatrox.wad.client").read_bytes(), b"map")

    def test_an_injection_of_other_mods_swaps_them_and_restarts_the_patcher(self):
        self.stage(wad=b"staged skin")
        mod = self.make_mod(wad=b"final skin")

        result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 0)
        names = self.bridge.command_names()
        self.assertEqual(names.count("import"), 2)
        self.assertEqual(names.count("start_patcher"), 2)
        first_restart = names.index("stop_patcher")
        self.assertLess(first_restart, names.index("uninstall"))  # stopped before the library changed
        self.assertEqual(self.bridge.library_entries, [])

    def test_a_new_selection_replaces_the_staged_skin(self):
        self.stage(wad=b"first")
        first_id = self.bridge.library_entries[0]["id"]

        _, staged = self.stage(wad=b"second")

        self.assertTrue(staged)
        self.assertIn(("uninstall", first_id), self.bridge.calls)
        self.assertEqual(len(self.bridge.library_entries), 1)

    def test_staging_stops_when_the_selection_moves_on(self):
        mod = self.make_mod(where=self.stage_dir)

        staged = self.overlay.stage_mods(self.stage_dir, [mod], still_wanted=lambda: False)

        self.assertFalse(staged)
        self.assertEqual(FakeBridge.created, [])

    def test_nothing_is_staged_once_staging_is_closed(self):
        self.overlay.close_staging()
        mod = self.make_mod(where=self.stage_dir)

        self.assertFalse(self.overlay.stage_mods(self.stage_dir, [mod]))
        self.assertEqual(FakeBridge.created, [])

    def test_an_install_running_when_staging_closes_finishes_if_still_wanted(self):
        mods = [self.make_mod(where=self.stage_dir),
                self.make_mod("ROSE-LoadingName", "Loading screen name", where=self.stage_dir)]
        original = FakeBridge.import_fantome

        def import_then_close(bridge_self, path, name=None):
            self.overlay.close_staging()  # the injection takes over mid-install
            return original(bridge_self, path, name=name)

        with patch.object(FakeBridge, "import_fantome", import_then_close):
            staged = self.overlay.stage_mods(self.stage_dir, mods)

        self.assertTrue(staged)
        self.assertEqual(self.bridge.command_names().count("import"), 2)
        self.assertIn("start_patcher", self.bridge.command_names())

    def test_an_install_no_longer_wanted_stops(self):
        mods = [self.make_mod(where=self.stage_dir),
                self.make_mod("ROSE-LoadingName", "Loading screen name", where=self.stage_dir)]
        wanted = {"value": True}
        original = FakeBridge.import_fantome

        def import_then_move_on(bridge_self, path, name=None):
            wanted["value"] = False  # another skin is picked mid-install
            return original(bridge_self, path, name=name)

        with patch.object(FakeBridge, "import_fantome", import_then_move_on):
            staged = self.overlay.stage_mods(self.stage_dir, mods, still_wanted=lambda: wanted["value"])

        self.assertFalse(staged)
        self.assertEqual(self.bridge.command_names().count("import"), 1)
        self.assertNotIn("start_patcher", self.bridge.command_names())

    def test_the_users_mods_are_off_while_staged_and_back_on_after_a_discard(self):
        FakeBridge.initial_library = [{"id": "user-mod", "name": "Map", "displayName": "Map", "enabled": True}]
        self.stage()
        self.assertFalse(next(e for e in self.bridge.library_entries if e["id"] == "user-mod")["enabled"])

        self.overlay.discard_early_patcher()

        self.assertEqual(self.bridge.library_entries, [{"id": "user-mod", "name": "Map", "displayName": "Map", "enabled": True}])
        self.assertEqual(self.state()["installed"], {})
        self.assertEqual(self.state()["disabled"], [])

    def test_a_failed_staging_reports_nothing(self):
        mod = self.make_mod(where=self.stage_dir)

        def refuse(bridge_self, path, name=None):
            raise overlay_manager.BridgeCommandError("import failed: bad archive")

        with patch.object(FakeBridge, "import_fantome", refuse):
            self.assertFalse(self.overlay.stage_mods(self.stage_dir, [mod]))

        self.assertEqual(self.reported_codes(), [])

    def test_an_install_ltk_managers_browser_does_not_answer_says_so(self):
        mod = self.make_mod()

        def no_cdp(bridge_self):
            raise overlay_manager.BridgeCommandError(
                'list failed: {"ok": false, "raw": {"ok": false, "error": "CDP unavailable or timed out"}}'
            )

        with patch.object(FakeBridge, "library", no_cdp):
            self.assertEqual(self.overlay.mk_run_overlay([mod], stop_callback=lambda: True), 1)

        self.assertEqual(self.reported_codes(), ["LTF_FAILED"])
        self.assertEqual(self.reported_causes(), ["cdp"])

    def test_an_account_running_everything_as_administrator_is_named_in_it(self):
        from utils.system.windows_account import ShellAccount
        mod = self.make_mod()

        def no_cdp(bridge_self):
            raise overlay_manager.BridgeCommandError("list failed: CDP unavailable or timed out")

        elevated = ShellAccount(elevated=True, builtin_administrator=False, uac_disabled=True)
        with patch.object(FakeBridge, "library", no_cdp),                 patch("utils.system.windows_account.shell_account", return_value=elevated):
            self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        reason = next(call.kwargs["details"]["reason"] for call in self.report_issue.call_args_list
                      if call.args[0] == "LTF_FAILED")
        self.assertIn("as administrator", reason)
        self.assertEqual(self.reported_causes(), ["cdp"])

    def test_mods_packed_ahead_are_imported_as_they_are(self):
        mod = self.make_mod(where=self.stage_dir)
        archives = self.overlay.pack_mods(self.stage_dir, [mod])

        self.assertEqual(archives, {mod: self.stage_dir / f"{mod}.fantome"})
        with patch.object(overlay_manager, "write_fantome_zip") as pack:
            self.assertTrue(self.overlay.stage_mods(self.stage_dir, [mod], archives=archives))

        pack.assert_not_called()  # nothing left to pack on the way to the scan
        imported = [call[1] for call in self.bridge.calls if call[0] == "import"]
        self.assertEqual(imported, [str(self.stage_dir / f"{mod}.fantome")])

    def test_a_mod_staged_for_an_earlier_pick_is_not_packed_again(self):
        skin = self.make_mod(where=self.stage_dir)
        rift = self.make_mod("Rift", "Rift", where=self.stage_dir, wad=b"map")
        self.assertTrue(self.overlay.stage_mods(self.stage_dir, [skin, rift]))
        next_pick = self.root / "injection" / "stage-next"
        other = self.make_mod("1002-Other", "Other Leona", where=next_pick, wad=b"other")
        self.make_mod("Rift", "Rift", where=next_pick, wad=b"map")

        archives = self.overlay.pack_mods(next_pick, [other, rift])

        self.assertEqual(archives, {other: next_pick / f"{other}.fantome"})
        self.assertTrue(self.overlay.stage_mods(next_pick, [other, rift], archives=archives))
        imported = [call[1] for call in self.bridge.calls if call[0] == "import"]
        self.assertEqual(imported[2:], [str(next_pick / f"{other}.fantome")])  # the map stays as it is

    def test_a_missing_packed_archive_is_packed_by_the_install(self):
        mod = self.make_mod(where=self.stage_dir)

        staged = self.overlay.stage_mods(self.stage_dir, [mod], archives={mod: self.stage_dir / "gone.fantome"})

        self.assertTrue(staged)
        imported = Path([call[1] for call in self.bridge.calls if call[0] == "import"][0])
        self.assertEqual(imported.parent.parent, self.root / "injection" / "ltf_staging")

    def test_the_time_from_the_pick_is_kept_for_a_late_join(self):
        mod = self.make_mod(where=self.stage_dir)

        self.overlay.stage_mods(self.stage_dir, [mod], selected_at=time.monotonic() - 2.0)

        session = self.overlay._early_session
        self.assertGreaterEqual(session["staged_after_s"], 2.0)


class LtkLogReadingTests(LtfSessionTestCase):
    """What LTK Manager's log says about the overlay's build and the scan"""

    BUILD_AND_SCAN = (
        "2026-11-04T18:08:17.090475Z  INFO ltk_overlay::builder: Overlay build complete: 3 built, 0 reused in 4.2749041s\n"
        "2026-11-04T18:08:17.201030Z  WARN ltk_manager_runtime::patcher::host::persistent: [ltk-host stderr]"
        "    0.007079600s  INFO ltk_patcher_host::worker: session started: scanning for game\n"
    )
    SCAN_STARTED = 1793815697.20103  # 2026-11-04T18:08:17.201030Z

    def write_log(self, text):
        with open(self.ltk_logs / "ltk-manager.2026-11-04.log", "a", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def started_session(self):
        session = self.overlay._new_session(FakeBridge(), launched=False)
        self.assertTrue(self.overlay._start_patcher(session))
        return session

    def test_the_build_time_and_the_scan_start_are_read(self):
        self.write_log("before the start: Overlay build complete: 1 built, 0 reused in 9.0s\n")
        session = self.started_session()
        self.write_log(self.BUILD_AND_SCAN)

        self.overlay._read_ltk_log(session)

        self.assertAlmostEqual(session["overlay_build_s"], 4.2749041)
        self.assertAlmostEqual(session["scan_started_at"], self.SCAN_STARTED, places=4)

    NO_PATCHER_DLL = (
        "2026-11-05T02:54:37.120000Z ERROR ltk_manager::services::telemetry: upload failed\n"
        "2026-11-05T02:54:41.250000Z ERROR ltk_manager_core::patching::thread: Could not prepare the patcher host "
        "error=Patcher(DllUnavailable { reason: Network })\r\n"
        "2026-11-05T02:54:41.260000Z ERROR ltk_manager_core::patching::thread: Overlay build failed error=later\n"
    )

    def test_the_patchers_own_error_is_read(self):
        session = self.started_session()
        self.write_log(self.NO_PATCHER_DLL)

        self.overlay._read_ltk_log(session)

        self.assertEqual(
            session["ltk_error"],
            "Could not prepare the patcher host error=Patcher(DllUnavailable { reason: Network })",
        )

    def test_a_patcher_that_gave_up_reports_ltk_managers_reason(self):
        mod = self.make_mod()
        FakeBridge.patcher_statuses = [status(running=False, phase="idle")]
        original = FakeBridge.start_patcher

        def start_then_fail(bridge_self):
            answer = original(bridge_self)
            self.write_log(self.NO_PATCHER_DLL)  # LTK Manager gives up right after the start
            return answer

        with patch.object(FakeBridge, "start_patcher", start_then_fail):
            result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True)

        self.assertEqual(result, 1)
        reason = next(call.kwargs["details"]["reason"] for call in self.report_issue.call_args_list
                      if call.args[0] == "LTF_FAILED")
        self.assertEqual(
            reason,
            "the LTK patcher stopped before it was ready "
            "(LTK Manager: Could not prepare the patcher host error=Patcher(DllUnavailable { reason: Network }))",
        )

    def test_a_restart_forgets_the_last_error(self):
        session = self.started_session()
        self.write_log(self.NO_PATCHER_DLL)
        self.overlay._read_ltk_log(session)

        self.assertTrue(self.overlay._start_patcher(session))

        self.assertIsNone(session["ltk_error"])

    def test_a_build_in_milliseconds_is_read(self):
        session = self.started_session()
        self.write_log("2026-11-04T18:08:43.972577Z  INFO ltk_overlay::builder: "
                       "Overlay build complete: 2 built, 0 reused in 511.0956ms\n")

        self.overlay._read_ltk_log(session)

        self.assertAlmostEqual(session["overlay_build_s"], 0.5110956)

    def test_a_patcher_still_building_is_not_called_scanning(self):
        session = self.started_session()

        self.assertIn("still building the overlay", self.overlay._patcher_progress(session))

        self.write_log(self.BUILD_AND_SCAN)
        self.overlay._read_ltk_log(session)
        progress = self.overlay._patcher_progress(session)
        self.assertIn("has been scanning for", progress)
        self.assertIn("overlay built in 4.3s", progress)

    def test_a_late_join_says_what_took_the_time(self):
        session = self.started_session()
        session["staged_after_s"] = 2.2
        self.write_log(self.BUILD_AND_SCAN + "ltk_patcher_dll::entry: joined too late, not overlaying\n")
        game = MagicMock()
        game.create_time.return_value = self.SCAN_STARTED - 0.2

        with patch.object(overlay_manager.OverlayManager, "_running_game", return_value=game):
            self.overlay._check_patcher_verdict(session)

        reason = self.report_issue.call_args.kwargs["details"]["reason"]
        self.assertIn("its scan started 0.2s after the client created the game", reason)
        self.assertIn("LTK Manager took 4.3s to build the overlay", reason)
        self.assertIn("Rose started it 2.2s after the skin was picked", reason)
        self.assertEqual(self.reported_causes(), ["late"])

    def test_a_restart_forgets_the_previous_build(self):
        session = self.started_session()
        self.write_log(self.BUILD_AND_SCAN)
        self.overlay._read_ltk_log(session)

        self.overlay._start_patcher(session)

        self.assertIsNone(session["overlay_build_s"])
        self.assertIsNone(session["scan_started_at"])


class LtkLogTests(LtfSessionTestCase):
    def write_log(self, text):
        with open(self.ltk_logs / "ltk-manager.2026-11-02.log", "a", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def test_only_what_is_written_after_the_start_is_read(self):
        self.write_log("old: joined too late, not overlaying\n")
        tail = LtkLogTail(self.ltk_logs)

        self.write_log("new line\n")

        self.assertEqual(tail.read(), "new line\n")
        self.assertEqual(tail.read(), "")

    def test_a_late_join_in_ltk_managers_log_is_reported(self):
        self.write_log("before the session\n")
        mod = self.make_mod()
        polls = {"count": 0}

        def stop():
            polls["count"] += 1
            if polls["count"] == 2:
                self.write_log(
                    "[ltk-host] injected: dll attached\n"
                    "ltk_patcher_dll::entry: joined too late, not overlaying\n"
                )
            return polls["count"] > 4

        result = self.overlay.mk_run_overlay([mod], stop_callback=stop)

        self.assertEqual(result, 0)
        self.assertEqual(self.reported_causes(), ["late"])

    def test_a_host_verification_refusal_in_the_log_is_reported(self):
        mod = self.make_mod()
        polls = {"count": 0}

        def stop():
            polls["count"] += 1
            if polls["count"] == 2:
                self.write_log(
                    "[ltk-host] injected: dll attached\n"
                    "[ltk-dll pid=28800 tid=28356 ERROR] ltk_patcher_dll::verify: "
                    "host verification failed, refusing overlay: [VRF00000007] (27688)\n"
                )
            return polls["count"] > 4

        result = self.overlay.mk_run_overlay([mod], stop_callback=stop)

        self.assertEqual(result, 0)
        self.assertEqual(self.reported_causes(), ["refused"])

    def test_a_refusal_over_ltk_managers_own_signature_names_it(self):
        """#442: the chain's inner check was WinVerifyTrust's 0x80096010 on
        ltk-manager.exe: a damaged LTK Manager, fixed by reinstalling it"""
        mod = self.make_mod()
        polls = {"count": 0}

        def stop():
            polls["count"] += 1
            if polls["count"] == 2:
                self.write_log(
                    "[ltk-host] injected: dll attached\n"
                    "[ltk-dll pid=21108 tid=20400 ERROR] ltk_patcher_dll::verify: host verification failed, "
                    "refusing overlay: [VRF00000009] (3168) -> [VRF00000001] (80096010)\n"
                )
            return polls["count"] > 4

        self.overlay.mk_run_overlay([mod], stop_callback=stop)

        self.assertEqual(self.reported_causes(), ["signature"])
        (reason,) = [call.args[2] for call in self.report_issue.call_args_list if call.args[0] == "LTF_FAILED"]
        self.assertIn("VRF00000009 (3168)", reason)
        self.assertIn("0x80096010", reason)
        self.assertIn("Reinstall LTK Manager", overlay_manager.OverlayManager._ltk_failure_hint(reason))

    def test_an_attached_patcher_is_not_reported(self):
        mod = self.make_mod()
        polls = {"count": 0}

        def stop():
            polls["count"] += 1
            if polls["count"] == 2:
                self.write_log("[ltk-host] injected: dll attached\n")
            return polls["count"] > 4

        self.overlay.mk_run_overlay([mod], stop_callback=stop)

        self.assertEqual(self.reported_codes(), [])


class StageWorkerTests(unittest.TestCase):
    """InjectionManager stages the selection the player rests on"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        self.manager = InjectionManager(shared_state=SimpleNamespace(current_game_mode="CLASSIC"))
        self.manager._initialized = True
        self.staged = []
        self.stage_calls = []
        self.prepared = []
        self.done = threading.Event()
        self.stage_root = root / "injection" / "stage"
        injector = MagicMock()
        injector.mods_dir = root / "injection" / "mods"

        def prepare(name, target, **kwargs):
            self.prepared.append((name, time.monotonic()))
            return [name]

        injector.prepare_skin_mods.side_effect = prepare
        injector.overlay_manager.pack_mods.side_effect = lambda stage_dir, names: {
            name: Path(stage_dir) / f"{name}.fantome" for name in names
        }

        def stage_mods(stage_dir, names, still_wanted, **kwargs):
            self.staged.append(names[0])
            self.stage_calls.append({"stage_dir": stage_dir, "at": time.monotonic(), **kwargs})
            self.done.set()
            return True

        injector.overlay_manager.stage_mods.side_effect = stage_mods
        self.manager.injector = injector
        for patcher in (
            patch.object(manager_module, "STAGE_SETTLE_S", 0.05),
            patch.object(manager_module, "STAGE_WORKER_IDLE_S", 0.5),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        # First of the cleanups: no stager thread may still write in the
        # temporary folder when it is removed
        self.addCleanup(self.stop_stager)

    def stop_stager(self):
        threads = [self.manager._prepare_thread, self.manager._stage_thread]
        with patch.object(manager_module, "STAGE_WORKER_IDLE_S", 0.0):
            self.manager.cancel_staging()  # wakes them: idle at once, they exit
            for thread in threads:
                if thread is not None:
                    thread.join(2)
                    self.assertFalse(thread.is_alive())

    def test_only_the_selection_the_player_rests_on_is_staged(self):
        self.manager.stage_skin("skin_1001", champion_id=1)
        self.manager.stage_skin("skin_1002", champion_id=1)
        self.manager.stage_skin("skin_1003", champion_id=1)

        self.assertTrue(self.done.wait(2))
        time.sleep(0.2)
        self.assertEqual(self.staged, ["skin_1003"])

    def test_a_plan_with_mods_is_staged_whole(self):
        plan = StagePlan("skin_1001", (CarrierStep("skin_1001", "Leona", 1), ModStep("Rift", "C:/mods/maps/Rift")))
        with patch.object(manager_module, "prepare_plan", return_value=["1001", "Rift"]) as prepare:
            self.manager.stage_plan(plan)
            self.assertTrue(self.done.wait(2))

        self.assertEqual(prepare.call_args.args[1], plan)
        self.assertEqual(self.manager.injector.overlay_manager.stage_mods.call_args.args[1], ["1001", "Rift"])

    def test_the_same_selection_is_staged_once(self):
        self.manager.stage_skin("skin_1001", champion_id=1)
        self.assertTrue(self.done.wait(2))
        self.manager.stage_skin("skin_1001", champion_id=1)
        time.sleep(0.2)

        self.assertEqual(self.staged, ["skin_1001"])

    def test_a_cancelled_selection_is_not_staged(self):
        self.manager.stage_skin("skin_1001", champion_id=1)
        self.manager.cancel_staging()
        time.sleep(0.3)

        self.assertEqual(self.staged, [])
        self.manager.injector.overlay_manager.close_staging.assert_called()

    def test_the_injection_cancels_staging(self):
        self.manager.discard_early_patcher()

        self.manager.injector.overlay_manager.close_staging.assert_called()

    def test_a_pick_is_prepared_at_once_and_installed_once_it_rests(self):
        with patch.object(manager_module, "STAGE_SETTLE_S", 0.3):
            picked = time.monotonic()
            self.manager.stage_skin("skin_1001", champion_id=1)
            self.assertTrue(self.done.wait(2))

        self.assertLess(self.prepared[0][1] - picked, 0.2)  # while it settles
        self.assertGreaterEqual(self.stage_calls[0]["at"] - picked, 0.3)

    def test_the_install_imports_what_was_packed_and_cleans_up(self):
        self.manager.stage_skin("skin_1001", champion_id=1)
        self.assertTrue(self.done.wait(2))
        time.sleep(0.05)

        call = self.stage_calls[0]
        self.assertEqual(call["archives"], {"skin_1001": Path(call["stage_dir"]) / "skin_1001.fantome"})
        self.assertIsNotNone(call["selected_at"])
        self.assertEqual(Path(call["stage_dir"]).parent, self.stage_root)
        self.assertEqual(list(self.stage_root.iterdir()) if self.stage_root.exists() else [], [])

    def test_the_next_pick_is_prepared_while_another_one_installs(self):
        installing, release = threading.Event(), threading.Event()

        def stage_mods(stage_dir, names, still_wanted, **kwargs):
            self.staged.append(names[0])
            if names[0] == "skin_1001":
                installing.set()
                release.wait(2)  # an import LTK Manager is still answering
                return still_wanted()
            self.done.set()
            return True

        self.manager.injector.overlay_manager.stage_mods.side_effect = stage_mods
        self.manager.stage_skin("skin_1001", champion_id=1)
        self.assertTrue(installing.wait(2))
        self.manager.stage_skin("skin_1002", champion_id=1)

        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and "skin_1002" not in [name for name, _ in self.prepared]:
            time.sleep(0.01)
        self.assertIn("skin_1002", [name for name, _ in self.prepared])
        self.assertEqual(self.staged, ["skin_1001"])  # still installing the first one

        release.set()
        self.assertTrue(self.done.wait(2))
        self.assertEqual(self.staged, ["skin_1001", "skin_1002"])

    def test_a_pick_that_cannot_rest_before_the_threshold_is_installed_at_once(self):
        with patch.object(manager_module, "STAGE_SETTLE_S", 0.3):
            picked = time.monotonic()
            self.manager.stage_skin("skin_1001", champion_id=1, threshold_in_s=0.2)
            self.assertTrue(self.done.wait(2))

        self.assertLess(self.stage_calls[0]["at"] - picked, 0.2)

    def test_a_pick_well_before_the_threshold_still_rests(self):
        with patch.object(manager_module, "STAGE_SETTLE_S", 0.3):
            picked = time.monotonic()
            self.manager.stage_skin("skin_1001", champion_id=1, threshold_in_s=5.0)
            self.assertTrue(self.done.wait(2))

        self.assertGreaterEqual(self.stage_calls[0]["at"] - picked, 0.3)

    def test_the_injection_lets_the_staging_of_its_own_skin_finish(self):
        installing, release = threading.Event(), threading.Event()
        wanted_at_the_end = []

        def stage_mods(stage_dir, names, still_wanted, **kwargs):
            self.staged.append(names[0])
            installing.set()
            release.wait(2)
            wanted_at_the_end.append(still_wanted())
            self.done.set()
            return wanted_at_the_end[-1]

        self.manager.injector.overlay_manager.stage_mods.side_effect = stage_mods
        self.manager.stage_skin("skin_1001", champion_id=1)
        self.assertTrue(installing.wait(2))

        self.manager.cancel_staging(keep="skin_1001")  # the injection takes this skin
        release.set()

        self.assertTrue(self.done.wait(2))
        self.assertEqual(wanted_at_the_end, [True])
        self.manager.injector.overlay_manager.close_staging.assert_not_called()

    def test_the_injection_installs_its_own_skin_at_once_while_it_rests(self):
        with patch.object(manager_module, "STAGE_SETTLE_S", 5.0):
            picked = time.monotonic()
            self.manager.stage_skin("skin_1001", champion_id=1)
            time.sleep(0.1)
            self.manager.cancel_staging(keep="skin_1001")

            self.assertTrue(self.done.wait(2))

        self.assertLess(self.stage_calls[0]["at"] - picked, 1.0)

    def test_the_injection_of_another_skin_stops_the_staging(self):
        installing, release = threading.Event(), threading.Event()
        wanted_at_the_end = []

        def stage_mods(stage_dir, names, still_wanted, **kwargs):
            installing.set()
            release.wait(2)
            wanted_at_the_end.append(still_wanted())
            return False

        self.manager.injector.overlay_manager.stage_mods.side_effect = stage_mods
        self.manager.stage_skin("skin_1001", champion_id=1)
        self.assertTrue(installing.wait(2))

        self.manager.cancel_staging(keep="skin_1002")
        release.set()
        time.sleep(0.1)

        self.assertEqual(wanted_at_the_end, [False])
        self.manager.injector.overlay_manager.close_staging.assert_called()

    def test_a_pick_is_not_prepared_again_while_it_installs(self):
        installing, release = threading.Event(), threading.Event()

        def stage_mods(stage_dir, names, still_wanted, **kwargs):
            self.staged.append(names[0])
            installing.set()
            release.wait(2)
            self.done.set()
            return True

        self.manager.injector.overlay_manager.stage_mods.side_effect = stage_mods
        self.manager.stage_skin("skin_1001", champion_id=1)
        self.assertTrue(installing.wait(2))
        with self.manager._stage_cond:
            self.manager._stage_cond.notify_all()  # the preparer looks again
        time.sleep(0.2)
        release.set()
        self.assertTrue(self.done.wait(2))

        self.assertEqual([name for name, _ in self.prepared], ["skin_1001"])

    def test_coming_back_to_a_pick_given_up_mid_install_stages_it_again(self):
        release, gave_up = threading.Event(), threading.Event()
        calls = {"count": 0}

        def stage_mods(stage_dir, names, still_wanted, **kwargs):
            calls["count"] += 1
            self.staged.append(names[0])
            if calls["count"] == 1:
                release.wait(2)
                wanted = still_wanted()  # the player moved on meanwhile
                gave_up.set()
                return wanted
            self.done.set()
            return True

        self.manager.injector.overlay_manager.stage_mods.side_effect = stage_mods
        with patch.object(manager_module, "STAGE_SETTLE_S", 0.3):
            self.manager.stage_skin("skin_1001", champion_id=1)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not self.staged:
                time.sleep(0.01)
            self.manager.stage_skin("skin_1002", champion_id=1)
            release.set()
            self.assertTrue(gave_up.wait(2))
            self.manager.stage_skin("skin_1001", champion_id=1)  # back before 1002 rested

            self.assertTrue(self.done.wait(2))

        self.assertEqual(self.staged, ["skin_1001", "skin_1001"])


class FakeModStorage:
    """The mods storage, with the files of the listed mods in *root*"""

    CATEGORY_MAPS = "maps"
    CATEGORY_FONTS = "fonts"
    CATEGORY_ANNOUNCERS = "announcers"
    CATEGORY_UI = "ui"
    CATEGORY_VOICEOVER = "voiceover"
    CATEGORY_LOADING_SCREEN = "loading_screen"
    CATEGORY_VFX = "vfx"
    CATEGORY_SFX = "sfx"
    CATEGORY_OTHERS = "others"

    def __init__(self, root, entries=()):
        self.mods_root = Path(root)
        self.entries = list(entries)

    def list_mods_for_category(self, category):
        return [entry for entry in self.entries if entry["id"].split("/", 1)[0] == category]

    def list_mods_for_champion(self, champion_id):
        return []


class StagingPlanTests(unittest.TestCase):
    """The countdown stages what the injection installs: the skin, the
    custom and saved mods, friends' skins"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.mods_root = Path(temp_dir.name)
        self.state = SimpleNamespace(
            last_hovered_skin_id=1001,
            locked_champ_id=1,
            hovered_champ_id=None,
            historic_mode_active=False,
            historic_skin_id=None,
            random_mode_active=False,
            random_skin_id=None,
            selected_chroma_id=None,
            selected_custom_mod=None,
            selected_map_mod=None,
            selected_font_mod=None,
            selected_announcer_mod=None,
            selected_other_mods=None,
            selected_other_mod=None,
            party_manager=None,
            owned_skin_ids=set(),
            selected_skin_id=None,
        )
        self.trigger = InjectionTrigger(MagicMock(), self.state, MagicMock(), None)
        self.storage = FakeModStorage(self.mods_root)
        self.saved = {}
        for patcher in (
            patch("utils.core.historic.get_historic_skin_for_champion", return_value=None),
            patch("utils.core.mod_historic.load_mod_historic", side_effect=lambda: dict(self.saved)),
            patch("injection.mods.storage.ModStorageService", side_effect=lambda: self.storage),
            patch("threads.handlers.injection_trigger.get_injection_dir", return_value=self.mods_root / "injection"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def save_map(self, exists=True):
        """A map mod saved from an earlier game (mod_historic.json)"""
        path = self.mods_root / "maps" / "Rift.fantome"
        if exists:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"map")
        self.storage.entries.append({"id": "maps/Rift.fantome", "name": "Rift", "path": "maps/Rift.fantome"})
        self.saved["map"] = "maps/Rift.fantome"
        return path

    def custom_mod(self, **extra):
        return {
            "skin_id": 1001,
            "champion_id": 1,
            "mod_name": "My mod",
            "mod_path": str(self.mods_root / "skins" / "1000" / "My mod.fantome"),
            "mod_folder_name": "My mod",
            **extra,
        }

    def test_an_unowned_skin_is_staged_alone(self):
        self.assertEqual(self.trigger.staging_plan("skin_1001", "Leona"), skin_plan("skin_1001", "Leona", 1, False))

    def test_the_default_skin_is_not(self):
        self.state.last_hovered_skin_id = 1000

        self.assertIsNone(self.trigger.staging_plan("skin_1000"))

    def test_another_champions_skin_is_not(self):
        self.state.last_hovered_skin_id = 2001

        self.assertIsNone(self.trigger.staging_plan("skin_2001"))

    def test_a_custom_mod_is_staged_with_its_skin_as_carrier(self):
        self.state.selected_custom_mod = self.custom_mod()

        plan = self.trigger.staging_plan("skin_1001", "Leona")

        self.assertEqual(plan, StagePlan("skin_1001", (
            CarrierStep("skin_1001", "Leona", 1),
            ModStep("My mod", self.state.selected_custom_mod["mod_path"], required=True),
            LoadingNameStep(1001),
        )))

    def test_a_custom_mod_on_an_owned_skin_has_no_carrier(self):
        self.state.owned_skin_ids = {1001}
        self.state.selected_custom_mod = self.custom_mod()

        plan = self.trigger.staging_plan("skin_1001", "Leona")

        self.assertEqual(plan.steps, (
            ModStep("My mod", self.state.selected_custom_mod["mod_path"], required=True),
            LoadingNameStep(1001),
        ))

    def test_a_custom_mod_the_injection_cannot_extract_is_not_staged(self):
        self.state.selected_custom_mod = self.custom_mod(mod_path=None)

        self.assertIsNone(self.trigger.staging_plan("skin_1001", "Leona"))

    def test_a_saved_map_mod_is_staged_with_the_skin_as_carrier(self):
        path = self.save_map()

        plan = self.trigger.staging_plan("skin_1001", "Leona")

        self.assertEqual(plan, StagePlan("skin_1001", (
            CarrierStep("skin_1001", "Leona", 1),
            ModStep("Rift", str(path)),
            LoadingNameStep(1001),
        )))
        self.assertIsNone(self.state.selected_map_mod)  # staging selects nothing

    def test_a_selected_map_mod_on_the_default_skin_is_staged_alone(self):
        self.state.last_hovered_skin_id = 1000
        self.state.selected_map_mod = {"mod_name": "Rift", "mod_path": "C:/mods/maps/Rift", "mod_folder_name": "Rift"}

        plan = self.trigger.staging_plan("skin_1000", "Leona")

        self.assertEqual(plan.steps, (ModStep("Rift", "C:/mods/maps/Rift"), LoadingNameStep(1000)))

    def test_a_saved_mod_whose_file_is_gone_is_left_out(self):
        self.save_map(exists=False)

        self.assertEqual(self.trigger.staging_plan("skin_1001", "Leona"), skin_plan("skin_1001", "Leona", 1, False))

    def test_friends_skins_come_after_the_skin(self):
        friend = PartyStep(7, "Friend", 2, 2001, None, None, False)
        with patch.object(InjectionTrigger, "planned_party_skins", return_value=(friend,)):
            plan = self.trigger.staging_plan("skin_1001", "Leona")

        self.assertEqual(plan, skin_plan("skin_1001", "Leona", 1, False, (friend,)))

    def test_friends_skins_are_staged_alone_on_the_default_skin(self):
        self.state.last_hovered_skin_id = 1000
        friend = PartyStep(7, "Friend", 2, 2001, None, None, False)
        with patch.object(InjectionTrigger, "planned_party_skins", return_value=(friend,)):
            plan = self.trigger.staging_plan("skin_1000", "Leona")

        self.assertEqual(plan, StagePlan(PARTY_SKINS_LABEL, (friend,)))

    def test_the_injection_of_saved_mods_selects_what_was_staged(self):
        path = self.save_map()
        self.trigger.injection_manager.injector.mods_dir = self.mods_root / "injection" / "mods"
        self.trigger._inject_custom_mod = MagicMock()
        plan = self.trigger.staging_plan("skin_1001", "Leona")

        with patch("threads.handlers.injection_trigger.link_or_extract"):
            self.trigger.trigger_injection("skin_1001", ticker_id=1, cname="Leona")

        self.assertEqual(self.state.selected_map_mod["mod_path"], str(path))
        _, kwargs = self.trigger._inject_custom_mod.call_args
        self.assertEqual(kwargs["base_skin_name"], "skin_1001")
        self.trigger.injection_manager.cancel_staging.assert_called_with(keep=plan.label)


class PreparePlanTests(unittest.TestCase):
    """The stager prepares the plan's mods as the injection prepares them"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.target = self.root / "stage" / "1"
        self.target.mkdir(parents=True)
        self.injector = MagicMock()
        self.injector.game_dir = self.root / "game"
        cache = patch.object(stage_plan_module, "get_injection_dir", return_value=self.root / "injection")
        cache.start()
        self.addCleanup(cache.stop)

    def mod_folder(self, name, data=b"mod"):
        folder = self.root / "mods" / name
        (folder / "WAD").mkdir(parents=True)
        (folder / "WAD" / "Map11.wad.client").write_bytes(data)
        return folder

    def skin_archive(self, name="1001"):
        archive = self.root / "skins" / f"{name}.fantome"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("META/info.json", '{"Name": "Skin"}')
            zf.writestr("WAD/Leona.wad.client", b"skin")
        return archive

    def test_a_skin_is_prepared_like_the_injection_does(self):
        self.injector.prepare_skin_mods.return_value = ["1001", "ROSE-LoadingName"]

        names = prepare_plan(self.injector, skin_plan("skin_1001", "Leona", 1, True), self.target)

        self.assertEqual(names, ["1001", "ROSE-LoadingName"])
        self.injector.prepare_skin_mods.assert_called_once_with(
            "skin_1001", self.target, champion_name="Leona", champion_id=1, classic=True, report=False,
        )

    def test_a_carrier_a_custom_mod_and_a_map_are_prepared_in_order(self):
        self.injector._resolve_zip.return_value = self.skin_archive()
        custom = self.mod_folder("My mod", b"custom")
        rift = self.mod_folder("Rift", b"rift")
        plan = StagePlan("skin_1001", (
            CarrierStep("skin_1001", "Leona", 1),
            ModStep("My mod", str(custom), required=True),
            ModStep("Gone", str(self.root / "mods" / "Gone.fantome")),
            ModStep("Rift", str(rift)),
            LoadingNameStep(1001),
        ))

        with patch.object(stage_plan_module, "build_loading_name", return_value="ROSE-LoadingName") as loading_name:
            names = prepare_plan(self.injector, plan, self.target)

        self.assertEqual(names, ["1001", "My mod", "Rift", "ROSE-LoadingName"])
        self.assertEqual((self.target / "Rift" / "WAD" / "Map11.wad.client").read_bytes(), b"rift")
        self.assertEqual(mod_fingerprint(self.target / "Rift"), mod_fingerprint(rift))
        loading_name.assert_called_once_with(
            self.injector.game_dir, self.target, self.target / "My mod", 1001,
            other_mods=[self.target / "1001", self.target / "Rift"],  # a map or font may carry the text table
        )

    def test_the_loading_name_of_saved_mods_comes_from_the_carrier(self):
        self.injector._resolve_zip.return_value = self.skin_archive()
        plan = StagePlan("skin_1001", (CarrierStep("skin_1001", "Leona", 1), LoadingNameStep(1001)))

        with patch.object(stage_plan_module, "build_loading_name", return_value=None) as loading_name:
            names = prepare_plan(self.injector, plan, self.target)

        self.assertEqual(names, ["1001"])
        loading_name.assert_called_once_with(self.injector.game_dir, self.target, self.target / "1001", 1001, other_mods=[])

    def test_nothing_is_staged_without_the_custom_mod_or_the_carrier(self):
        missing_mod = StagePlan("skin_1001", (ModStep("My mod", str(self.root / "gone"), required=True),))
        self.injector._resolve_zip.return_value = None
        missing_carrier = StagePlan("skin_1001", (CarrierStep("skin_1001", "Leona", 1), ModStep("Rift", str(self.mod_folder("Rift")))))

        self.assertIsNone(prepare_plan(self.injector, missing_mod, self.target))
        self.assertIsNone(prepare_plan(self.injector, missing_carrier, self.target))

    def test_friends_skins_are_prepared_in_the_stage_folder(self):
        friend = PartyStep(7, "Friend", 2, 2001, 2003, None, False)

        with patch("party.integration.injection_hook.prepare_peer_skin", return_value="party_7") as prepare:
            names = prepare_plan(self.injector, StagePlan(PARTY_SKINS_LABEL, (friend,)), self.target)

        self.assertEqual(names, ["party_7"])
        skin_data = prepare.call_args.args[0]
        self.assertEqual((skin_data.summoner_id, skin_data.skin_id, skin_data.chroma_id), (7, 2001, 2003))
        self.assertEqual(prepare.call_args.kwargs["mods_dir"], self.target)


if __name__ == "__main__":
    unittest.main()
