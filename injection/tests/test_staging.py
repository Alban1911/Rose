import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from injection.core import manager as manager_module
from injection.core.manager import InjectionManager
from injection.mods.fingerprint import mod_fingerprint
from injection.overlay import overlay_manager
from injection.overlay.overlay_manager import LtkLogTail
from injection.tests.test_ltf_session import FakeBridge, LtfSessionTestCase, status
from threads.handlers.injection_trigger import InjectionTrigger


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
        injection_manager = MagicMock()

        result = self.overlay.mk_run_overlay([mod], stop_callback=lambda: True, injection_manager=injection_manager)

        self.assertEqual(result, 0)
        during = [call[0] for call in self.bridge.calls[len(before):]]
        self.assertNotIn("import", during)
        self.assertNotIn("start_patcher", during)
        injection_manager.resume_game.assert_called_once()
        self.assertEqual(self.bridge.library_entries, [])  # removed after the game
        self.assertEqual(self.reported_codes(), [])

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

    def test_mods_packed_ahead_are_imported_as_they_are(self):
        mod = self.make_mod(where=self.stage_dir)
        archives = self.overlay.pack_mods(self.stage_dir, [mod])

        self.assertEqual(archives, {mod: self.stage_dir / f"{mod}.fantome"})
        with patch.object(overlay_manager, "write_fantome_zip") as pack:
            self.assertTrue(self.overlay.stage_mods(self.stage_dir, [mod], archives=archives))

        pack.assert_not_called()  # nothing left to pack on the way to the scan
        imported = [call[1] for call in self.bridge.calls if call[0] == "import"]
        self.assertEqual(imported, [str(self.stage_dir / f"{mod}.fantome")])

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


class StagingTargetTests(unittest.TestCase):
    """The countdown stages only what the injection would install alone"""

    def setUp(self):
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
        )
        self.trigger = InjectionTrigger(MagicMock(), self.state, MagicMock(), None)
        for patcher in (
            patch("utils.core.historic.get_historic_skin_for_champion", return_value=None),
            patch("utils.core.mod_historic.load_mod_historic", return_value={}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_an_unowned_skin_is_staged(self):
        self.assertTrue(self.trigger.staging_target("skin_1001"))

    def test_the_default_skin_is_not(self):
        self.state.last_hovered_skin_id = 1000

        self.assertFalse(self.trigger.staging_target("skin_1000"))

    def test_another_champions_skin_is_not(self):
        self.state.last_hovered_skin_id = 2001

        self.assertFalse(self.trigger.staging_target("skin_2001"))

    def test_a_custom_mod_is_not(self):
        self.state.selected_custom_mod = {"mod_name": "My mod"}

        self.assertFalse(self.trigger.staging_target("skin_1001"))

    def test_a_selected_or_saved_map_mod_is_not(self):
        self.state.selected_map_mod = {"mod_name": "Map"}
        self.assertFalse(self.trigger.staging_target("skin_1001"))

        self.state.selected_map_mod = None
        with patch("utils.core.mod_historic.load_mod_historic", return_value={"map": "maps/Summoner Rift.fantome"}):
            self.assertFalse(self.trigger.staging_target("skin_1001"))

    def test_friends_skins_are_not(self):
        with patch.object(InjectionTrigger, "_has_party_skins", return_value=True):
            self.assertFalse(self.trigger.staging_target("skin_1001"))


if __name__ == "__main__":
    unittest.main()
