import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from utils.integration import startup_verifier as verifier


class StartupVerifierTests(unittest.TestCase):
    def setUp(self):
        self.bridge = SimpleNamespace(
            ready_event=threading.Event(), plugin_ready_event=threading.Event(), connections=set(),
            client_seen_event=threading.Event(), is_responsive=True,
        )
        self.bridge.ready_event.set()
        self.state = SimpleNamespace(stop=False)
        self.warn = Mock()
        self.lcu = Mock()
        self.lcu.get.return_value = 'Lobby'
        self.monitor = verifier.StartupInjectionVerifier(self.lcu, self.state, self.bridge, self.warn)
        self.absent = verifier.ClientSample((42, 100.0), False)
        self.loaded = verifier.ClientSample((42, 100.0), True)
        probe = patch.object(verifier, 'sample_client', return_value=self.absent)
        self.probe = probe.start()
        self.addCleanup(probe.stop)
        owner = patch.object(verifier, 'client_matches_lcu', return_value=True)
        self.owner = owner.start()
        self.addCleanup(owner.stop)

    def tick(self, start, stop):
        for now in range(start, stop + 1, 5):
            self.monitor.check_once(now)

    def test_confirmed_absence_waits_for_grace_and_three_samples_then_warns_once(self):
        self.tick(0, 65)
        self.warn.assert_not_called()
        self.monitor.check_once(70)
        self.warn.assert_called_once_with(42)
        self.tick(75, 150)
        self.warn.assert_called_once()

    def test_loaded_core_without_bridge_never_warns(self):
        self.probe.return_value = self.loaded
        self.tick(0, 120)
        self.warn.assert_not_called()
        self.assertTrue(self.monitor.finished)

    def test_plugin_readiness_suppresses_late_failure_and_disconnects(self):
        self.tick(0, 65)
        self.bridge.plugin_ready_event.set()
        self.tick(70, 150)
        self.warn.assert_not_called()
        self.assertTrue(self.monitor.finished)

    def test_late_core_load_on_final_recheck_suppresses_warning(self):
        self.tick(0, 65)
        self.probe.side_effect = [self.absent, self.loaded]
        self.monitor.check_once(70)
        self.warn.assert_not_called()
        self.assertTrue(self.monitor.finished)
        self.probe.side_effect = None
        self.probe.return_value = self.absent
        self.tick(75, 150)
        self.warn.assert_not_called()

    def test_plugin_reports_ready_during_final_inspection(self):
        self.tick(0, 65)
        def late_ready(lcu):
            self.bridge.plugin_ready_event.set()
            return self.absent
        self.probe.side_effect = late_ready
        self.monitor.check_once(70)
        self.warn.assert_not_called()

    def test_unknown_inspection_and_pending_restart_reset_the_grace_period(self):
        self.tick(0, 65)
        self.probe.return_value = None
        self.tick(70, 150)
        self.probe.return_value = self.absent
        self.tick(155, 220)
        self.warn.assert_not_called()
        self.monitor.check_once(225)
        self.warn.assert_called_once()

    def test_client_restart_or_pid_reuse_restarts_grace_period(self):
        self.tick(0, 65)
        self.probe.return_value = verifier.ClientSample((42, 200.0), False)
        self.tick(70, 135)
        self.warn.assert_not_called()
        self.monitor.check_once(140)
        self.warn.assert_called_once()

    def test_sleep_resume_is_not_treated_as_ready_time(self):
        self.tick(0, 65)
        self.tick(1000, 1065)
        self.warn.assert_not_called()

    def test_live_bridge_connection_suppresses_warning_even_for_older_plugins(self):
        self.tick(0, 65)
        self.bridge.connections.add(object())
        self.tick(70, 150)
        self.warn.assert_not_called()

    def test_shutdown_suppresses_warning(self):
        self.tick(0, 65)
        self.state.stop = True
        self.monitor.check_once(70)
        self.warn.assert_not_called()

    def test_brief_legacy_connection_between_polls_permanently_suppresses_warning(self):
        self.tick(0, 65)
        # It has already disconnected: the active connections set is empty.
        self.bridge.client_seen_event.set()
        self.tick(70, 200)
        self.warn.assert_not_called()
        self.assertTrue(self.monitor.finished)

    def test_no_warning_after_a_previously_observed_connection_disconnects(self):
        self.bridge.connections.add(object())
        self.monitor.check_once(0)
        self.bridge.connections.clear()
        self.tick(5, 200)
        self.warn.assert_not_called()

    def test_blocked_or_stopped_bridge_defers_failure(self):
        self.tick(0, 65)
        self.bridge.is_responsive = False
        self.tick(70, 200)
        self.warn.assert_not_called()

    def test_unrelated_or_unreadable_lcu_owner_suppresses_failure(self):
        self.owner.return_value = False
        self.tick(0, 200)
        self.warn.assert_not_called()

    def test_late_phase_change_into_game_suppresses_failure(self):
        self.tick(0, 65)
        self.lcu.get.return_value = 'InProgress'
        self.monitor.check_once(70)
        self.warn.assert_not_called()
        self.lcu.get.assert_called_with('/lol-gameflow/v1/gameflow-phase', timeout=2, use_cache=False)

    def test_connection_arrives_during_final_status_request(self):
        self.tick(0, 65)
        def connected(*args, **kwargs):
            self.bridge.client_seen_event.set()
            return 'Lobby'
        self.lcu.get.side_effect = connected
        self.monitor.check_once(70)
        self.warn.assert_not_called()
        self.assertTrue(self.monitor.finished)


@unittest.skipUnless(sys.platform == 'win32', 'Windows process snapshots')
class WindowsProbeTests(unittest.TestCase):
    def setUp(self):
        self.lcu = Mock(ok=True)
        self.lcu.get.return_value = 'Lobby'
        self.process = Mock(pid=42, info={'name': 'LeagueClientUx.exe'})
        self.process.create_time.return_value = 100.0
        self.process.exe.return_value = r'C:\League\LeagueClientUx.exe'
        self.process.is_running.return_value = True
        self.paths = [Path(r'C:\League\LeagueClientUx.exe'), Path(r'C:\Windows\ntdll.dll'),
                      Path(r'C:\Windows\kernel32.dll')]
        patches = [
            patch.object(verifier.psutil, 'process_iter', return_value=[self.process]),
            patch.object(verifier, '_session_id', return_value=1),
            patch.object(verifier.pengu_loader, 'is_client_restart_pending', return_value=False),
            patch.object(verifier, '_module_paths', return_value=self.paths),
        ]
        self.processes, self.session, self.pending, self.modules = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        alias = patch.object(Path, 'lstat', side_effect=FileNotFoundError)
        self.alias = alias.start()
        self.addCleanup(alias.stop)

    def test_complete_absence_is_reported(self):
        self.assertEqual(verifier.sample_client(self.lcu), verifier.ClientSample((42, 100.0), False))
        self.lcu.get.assert_called_with('/lol-gameflow/v1/gameflow-phase', timeout=2, use_cache=False)

    def test_loaded_core_is_positive_evidence(self):
        self.paths.append(Path(r'C:\Another Pengu\core.dll'))
        self.assertTrue(verifier.sample_client(self.lcu).core_loaded)

    def test_partial_or_unreadable_snapshot_is_unknown(self):
        self.modules.return_value = self.paths[:1]
        self.assertIsNone(verifier.sample_client(self.lcu))
        self.modules.side_effect = PermissionError('access denied')
        self.assertIsNone(verifier.sample_client(self.lcu))

    def test_symlink_mode_is_not_misdiagnosed(self):
        self.paths.append(Path(r'C:\League\version.dll'))
        self.assertIsNone(verifier.sample_client(self.lcu))

    def test_no_client_or_multiple_clients_is_unknown(self):
        for processes in ([], [self.process, self.process]):
            self.processes.return_value = processes
            self.assertIsNone(verifier.sample_client(self.lcu))

    def test_other_session_client_is_ignored(self):
        self.session.side_effect = [1, 2]
        self.assertIsNone(verifier.sample_client(self.lcu))

    def test_pending_restart_defers_inspection(self):
        self.pending.return_value = True
        self.assertIsNone(verifier.sample_client(self.lcu))
        self.modules.assert_not_called()

    def test_game_or_unavailable_lcu_defers_inspection(self):
        for phase in (None, 'InProgress', 'ChampSelect', 'Reconnect', {}):
            self.lcu.get.return_value = phase
            self.assertIsNone(verifier.sample_client(self.lcu))
        self.modules.assert_not_called()

    def test_process_exit_during_snapshot_is_unknown(self):
        self.process.is_running.return_value = False
        self.assertIsNone(verifier.sample_client(self.lcu))

    def test_client_local_alias_on_disk_is_unknown_even_when_snapshot_uses_another_path(self):
        self.alias.side_effect = None
        self.alias.return_value = object()
        self.assertIsNone(verifier.sample_client(self.lcu))

    def test_inaccessible_client_alias_is_unknown(self):
        self.alias.side_effect = PermissionError('access denied')
        self.assertIsNone(verifier.sample_client(self.lcu))


class LcuOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.lcu = SimpleNamespace(port=12345)
        self.ux = Mock(pid=42)
        self.ux.name.return_value = 'LeagueClientUx.exe'
        self.ux.create_time.return_value = 100.0
        self.ux.is_running.return_value = True
        self.parent = Mock(pid=21)
        self.parent.name.return_value = 'LeagueClient.exe'
        self.ux.parents.return_value = [self.parent]
        self.listener = SimpleNamespace(pid=21, status=verifier.psutil.CONN_LISTEN,
                                       laddr=SimpleNamespace(port=12345, ip='127.0.0.1'))
        process = patch.object(verifier.psutil, 'Process', return_value=self.ux)
        process.start()
        self.addCleanup(process.stop)
        connections = patch.object(verifier.psutil, 'net_connections', return_value=[self.listener])
        self.connections = connections.start()
        self.addCleanup(connections.stop)

    def test_listener_belongs_to_the_selected_clients_parent(self):
        self.assertTrue(verifier.client_matches_lcu((42, 100.0), self.lcu))

    def test_listener_belongs_to_another_client(self):
        self.listener.pid = 99
        self.assertFalse(verifier.client_matches_lcu((42, 100.0), self.lcu))

    def test_connection_table_access_denied(self):
        self.connections.side_effect = verifier.psutil.AccessDenied()
        self.assertFalse(verifier.client_matches_lcu((42, 100.0), self.lcu))

    def test_pid_reuse_is_not_matching_client(self):
        self.ux.create_time.return_value = 200.0
        self.assertFalse(verifier.client_matches_lcu((42, 100.0), self.lcu))

    def test_missing_listener_is_unknown(self):
        self.connections.return_value = []
        self.assertFalse(verifier.client_matches_lcu((42, 100.0), self.lcu))

    def test_lcu_uncached_get_bypasses_the_shared_cache(self):
        from lcu.core.client import LCU
        lcu = LCU.__new__(LCU)
        lcu._api = Mock()
        lcu.get('/lol-gameflow/v1/gameflow-phase', timeout=2, use_cache=False)
        lcu._api.get.assert_called_once_with('/lol-gameflow/v1/gameflow-phase', 2, use_cache=False)


@unittest.skipUnless(sys.platform == 'win32', 'Windows process snapshots')
class NativeSnapshotTests(unittest.TestCase):
    def test_real_snapshot_of_this_process_contains_python_and_windows_modules(self):
        paths = verifier._module_paths(os.getpid())
        names = {p.name.lower() for p in paths}
        self.assertIn(Path(sys.executable).name.lower(), names)
        self.assertIn('ntdll.dll', names)
        self.assertIn('kernel32.dll', names)


if __name__ == '__main__':
    unittest.main()
