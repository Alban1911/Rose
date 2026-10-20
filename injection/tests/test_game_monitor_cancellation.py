import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from injection.game import game_monitor


class MonitorCancellationTests(unittest.TestCase):
    def run_cancellation(self, path, action, stage, stopped=False):
        entered, proceed = threading.Event(), threading.Event()
        suspended = [stopped]
        proc = Mock(pid=123)
        proc.info = {'name': 'test-game.exe', 'pid': 123}

        def barrier():
            entered.set()
            if not proceed.wait(3):
                raise AssertionError('test did not release process operation')

        def status():
            if stage == 'status':
                barrier()
            return game_monitor.STATUS_STOPPED if suspended[0] else 'running'

        def suspend():
            suspended[0] = True
            if stage == 'suspend':
                barrier()

        proc.status.side_effect = status
        proc.suspend.side_effect = suspend
        proc.resume.side_effect = lambda: suspended.__setitem__(0, False)
        calls = [0]

        def processes(*args):
            calls[0] += 1
            return [] if path == 'regular' and calls[0] <= 10 else [proc]

        fake = SimpleNamespace(process_iter=processes, Process=lambda pid: proc)
        monitor = game_monitor.GameMonitor(lambda: 60)
        self.addCleanup(monitor.stop)
        with patch.object(game_monitor, 'psutil', fake), \
                patch.object(game_monitor, '_GAME_PROCESS_NAMES', {'test-game.exe'}), \
                patch.object(game_monitor, 'PSUTIL_AVAILABLE', True):
            monitor.start()
            try:
                self.assertTrue(entered.wait(3), 'worker never reached process operation')
                getattr(monitor, action)()
            finally:
                proceed.set()
                monitor._monitor_thread.join(3)
            self.assertFalse(monitor._monitor_thread.is_alive())
            self.assertFalse(suspended[0], 'cancellation left the process suspended')
            self.assertIsNone(monitor.get_suspended_game_process())
            self.assertFalse(monitor.is_active)

    def test_cancellation_before_suspension(self):
        for path in ('immediate', 'regular'):
            for action in ('stop', 'resume_game', 'resume_if_suspended'):
                with self.subTest(path=path, action=action):
                    self.run_cancellation(path, action, 'status')

    def test_cancellation_during_suspension(self):
        for path in ('immediate', 'regular'):
            for action in ('stop', 'resume_game', 'resume_if_suspended'):
                with self.subTest(path=path, action=action):
                    self.run_cancellation(path, action, 'suspend')

    def test_cancellation_while_tracking_stopped_process(self):
        for path in ('immediate', 'regular'):
            for action in ('stop', 'resume_game', 'resume_if_suspended'):
                with self.subTest(path=path, action=action):
                    self.run_cancellation(path, action, 'status', stopped=True)

    def test_timeout_callback_error_releases_acquired_process(self):
        for path in ('immediate', 'regular'):
            with self.subTest(path=path):
                suspended = [False]
                proc = Mock(pid=123)
                proc.info = {'name': 'test-game.exe', 'pid': 123}
                proc.status.side_effect = lambda: game_monitor.STATUS_STOPPED if suspended[0] else 'running'
                proc.suspend.side_effect = lambda: suspended.__setitem__(0, True)
                proc.resume.side_effect = lambda: suspended.__setitem__(0, False)
                calls = [0]

                def processes(*args):
                    calls[0] += 1
                    return [] if path == 'regular' and calls[0] <= 10 else [proc]

                monitor = game_monitor.GameMonitor(Mock(side_effect=ValueError('invalid timeout')))
                fake = SimpleNamespace(process_iter=processes, Process=lambda pid: proc)
                with patch.object(game_monitor, 'psutil', fake), \
                        patch.object(game_monitor, '_GAME_PROCESS_NAMES', {'test-game.exe'}):
                    monitor.start()
                    monitor._monitor_thread.join(3)
                    try:
                        self.assertFalse(monitor._monitor_thread.is_alive())
                        self.assertFalse(suspended[0])
                        self.assertIsNone(monitor.get_suspended_game_process())
                    finally:
                        monitor.stop()

    def test_restart_waits_for_cancelled_acquisition_before_starting_new_worker(self):
        entered, proceed = threading.Event(), threading.Event()
        suspended = [False]
        proc = Mock(pid=123)
        proc.status.side_effect = lambda: game_monitor.STATUS_STOPPED if suspended[0] else 'running'

        def suspend():
            suspended[0] = True
            entered.set()
            if not proceed.wait(3):
                raise AssertionError('acquisition not released')

        proc.suspend.side_effect = suspend
        proc.resume.side_effect = lambda: suspended.__setitem__(0, False)
        monitor = game_monitor.GameMonitor(lambda: 60)
        monitor._monitor_active = True
        previous = threading.Thread(target=lambda: monitor._acquire_game_process(proc), daemon=True)
        monitor._monitor_thread = previous
        previous.start()
        try:
            self.assertTrue(entered.wait(3))
            with patch.object(game_monitor, 'MONITOR_THREAD_JOIN_TIMEOUT_S', 0.01):
                monitor.start()
            self.assertIs(monitor._monitor_thread, previous)
            self.assertFalse(monitor.is_active)
        finally:
            proceed.set()
            previous.join(3)
        self.assertFalse(previous.is_alive())
        self.assertFalse(suspended[0])
        with patch.object(game_monitor, 'psutil', SimpleNamespace(process_iter=lambda *args: [])):
            monitor.start()
            try:
                self.assertIsNot(monitor._monitor_thread, previous)
                self.assertTrue(monitor.is_active)
            finally:
                monitor.stop()
                monitor._monitor_thread.join(3)
        self.assertIsNone(monitor.get_suspended_game_process())

    def test_old_resume_does_not_clear_a_restarted_monitor(self):
        entered, proceed = threading.Event(), threading.Event()
        old = Mock(pid=123)
        old.status.return_value = game_monitor.STATUS_STOPPED

        def resume():
            entered.set()
            if not proceed.wait(3):
                raise AssertionError('resume not released')
            old.status.return_value = 'running'

        old.resume.side_effect = resume
        monitor = game_monitor.GameMonitor(lambda: 60)
        monitor._suspended_game_process = old
        resumer = threading.Thread(target=monitor.resume_game, daemon=True)
        resumer.start()
        replacement = Mock(pid=456)
        acquired = threading.Event()

        def timeout():
            acquired.set()
            return 60

        replacement.info = {'name': 'test-game.exe', 'pid': 456}
        replacement.status.return_value = 'running'
        fake = SimpleNamespace(process_iter=lambda *args: [replacement], Process=lambda pid: replacement)
        try:
            self.assertTrue(entered.wait(3))
            monitor._get_auto_resume_timeout = timeout
            with patch.object(game_monitor, 'psutil', fake), \
                    patch.object(game_monitor, '_GAME_PROCESS_NAMES', {'test-game.exe'}):
                monitor.start()
                try:
                    self.assertTrue(acquired.wait(3))
                    proceed.set()
                    resumer.join(3)
                    self.assertFalse(resumer.is_alive())
                    self.assertIs(monitor.get_suspended_game_process(), replacement)
                    self.assertTrue(monitor.is_active)
                finally:
                    monitor.stop()
                    monitor._monitor_thread.join(3)
        finally:
            proceed.set()
            resumer.join(3)

    def test_cancelled_acquisition_retries_failed_resume_during_cleanup(self):
        monitor = game_monitor.GameMonitor(lambda: 60)
        monitor._monitor_active = True
        proc = Mock(pid=123)
        proc.status.return_value = game_monitor.STATUS_STOPPED

        def status():
            monitor.stop()
            return game_monitor.STATUS_STOPPED

        proc.status.side_effect = status
        proc.resume.side_effect = [game_monitor.AccessDenied(123), None]
        with self.assertRaises(game_monitor.AccessDenied):
            monitor._acquire_game_process(proc)
        self.assertIs(monitor.get_suspended_game_process(), proc)
        proc.status.side_effect = None
        monitor.stop()
        self.assertEqual(proc.resume.call_count, 2)
        self.assertIsNone(monitor.get_suspended_game_process())

    def test_process_exiting_before_suspension_does_not_stop_monitor(self):
        for path in ('immediate', 'regular'):
            with self.subTest(path=path):
                gone = Mock(pid=456)
                gone.info = {'name': 'test-game.exe', 'pid': 456}
                gone.status.side_effect = game_monitor.NoSuchProcess(456)
                suspended = [False]
                game = Mock(pid=123)
                game.info = {'name': 'test-game.exe', 'pid': 123}
                game.status.side_effect = lambda: game_monitor.STATUS_STOPPED if suspended[0] else 'running'
                game.suspend.side_effect = lambda: suspended.__setitem__(0, True)
                game.resume.side_effect = lambda: suspended.__setitem__(0, False)
                calls = [0]

                def processes(*args):
                    calls[0] += 1
                    return [] if path == 'regular' and calls[0] <= 10 else [gone, game]

                fake = SimpleNamespace(process_iter=processes, Process=lambda pid: gone if pid == 456 else game)
                monitor = game_monitor.GameMonitor(lambda: 60)
                self.addCleanup(monitor.stop)
                with patch.object(game_monitor, 'psutil', fake), \
                        patch.object(game_monitor, '_GAME_PROCESS_NAMES', {'test-game.exe'}), \
                        patch.object(game_monitor, 'PSUTIL_AVAILABLE', True):
                    monitor.start()
                    acquired = threading.Event()
                    for _ in range(300):
                        if monitor.get_suspended_game_process() is game:
                            acquired.set()
                            break
                        acquired.wait(0.01)
                    try:
                        self.assertTrue(acquired.is_set(), 'monitor stopped instead of suspending the game')
                        self.assertTrue(monitor.is_active)
                        self.assertEqual(game.suspend.call_count, 1)
                    finally:
                        monitor.stop()
                        monitor._monitor_thread.join(3)
                    self.assertFalse(suspended[0])
