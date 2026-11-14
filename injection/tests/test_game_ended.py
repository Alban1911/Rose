import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from injection.core import manager as manager_module
from injection.core.manager import InjectionManager
from injection.game import game_monitor
from injection.game.game_monitor import make_game_ended_callback
from injection.tests.test_ltf_session import LtfSessionTestCase


class GameEndedCallbackTests(unittest.TestCase):
    @staticmethod
    def _run(phases):
        state = SimpleNamespace(phase=None)
        callback = make_game_ended_callback(state)
        results = []
        for phase in phases:
            state.phase = phase
            results.append(callback())
        return results

    def test_ends_once_the_game_is_over(self):
        self.assertEqual(
            self._run(['ChampSelect', 'GameStart', 'InProgress', 'WaitingForStats']),
            [False, False, False, True],
        )

    def test_reconnect_is_not_the_end(self):
        self.assertEqual(
            self._run(['InProgress', 'Reconnect', 'GameStart', 'InProgress', 'EndOfGame']),
            [False, False, False, False, True],
        )

    def test_champ_select_ended_without_a_game_ends_it(self):
        # A dodge: the client may requeue at once, with no lobby cleanup between
        for phase in ('Lobby', 'Matchmaking', 'ReadyCheck', 'EndOfGame'):
            for champ_select in ('ChampSelect', 'FINALIZATION'):
                with self.subTest(phase=phase, champ_select=champ_select):
                    self.assertEqual(self._run([champ_select, phase]), [False, True])

    def test_a_callback_made_in_champ_select_ends_on_a_dodge_it_did_not_see(self):
        state = SimpleNamespace(phase='FINALIZATION')
        callback = make_game_ended_callback(state)
        state.phase = 'Lobby'
        self.assertTrue(callback())

    def test_a_client_closed_in_champ_select_ends_it(self):
        state = SimpleNamespace(phase='ChampSelect')
        now = [0.0]
        callback = make_game_ended_callback(state, clock=lambda: now[0])
        self.assertFalse(callback())
        state.phase = None
        self.assertFalse(callback())
        now[0] = game_monitor.CHAMP_SELECT_OUTAGE_GRACE_S - 1
        self.assertFalse(callback())
        now[0] = game_monitor.CHAMP_SELECT_OUTAGE_GRACE_S
        self.assertTrue(callback())

    def test_a_brief_gap_before_the_game_is_not_the_end(self):
        self.assertEqual(
            self._run(['ChampSelect', None, 'GameStart', None, 'InProgress', 'EndOfGame']),
            [False, False, False, False, False, True],
        )

    def test_never_ends_before_a_game_it_was_not_in_champ_select_for(self):
        # Swiftplay: its overlay may run with no champ select before the game
        self.assertEqual(
            self._run(['Lobby', 'Matchmaking', 'ReadyCheck', 'Lobby', None,
                       'GameStart', 'InProgress', 'WaitingForStats']),
            [False, False, False, False, False, False, False, True],
        )

    def test_client_outage_during_reconnect_keeps_the_match(self):
        self.assertEqual(
            # the phase thread reads the client's "None" as None
            self._run(['InProgress', None, None, None, 'Reconnect',
                       'GameStart', 'InProgress', 'WaitingForStats']),
            [False, False, False, False, False, False, False, True],
        )

    def test_a_phase_after_the_outage_ends_the_match(self):
        for phase in ('WaitingForStats', 'PreEndOfGame', 'EndOfGame', 'TerminatedInError',
                      'Lobby', 'Matchmaking', 'ReadyCheck', 'ChampSelect'):
            with self.subTest(phase=phase):
                self.assertEqual(self._run(['InProgress', None, phase]),
                                 [False, False, True])

    def test_a_client_gone_past_the_grace_ends_the_match(self):
        """The client closed for good, or reopened on its home screen (no phase either)."""
        state = SimpleNamespace(phase='InProgress')
        now = [0.0]
        callback = make_game_ended_callback(state, clock=lambda: now[0])
        self.assertFalse(callback())
        state.phase = None
        self.assertFalse(callback())
        now[0] = game_monitor.CLIENT_OUTAGE_GRACE_S - 1
        self.assertFalse(callback())
        now[0] = game_monitor.CLIENT_OUTAGE_GRACE_S
        self.assertTrue(callback())

    def test_the_grace_restarts_with_each_outage(self):
        state = SimpleNamespace(phase='InProgress')
        now = [0.0]
        callback = make_game_ended_callback(state, clock=lambda: now[0])
        callback()
        state.phase = None
        callback()
        now[0] = game_monitor.CLIENT_OUTAGE_GRACE_S - 1
        state.phase = 'InProgress'  # back in the game
        self.assertFalse(callback())
        state.phase = None
        self.assertFalse(callback())
        now[0] += game_monitor.CLIENT_OUTAGE_GRACE_S - 1
        self.assertFalse(callback())

    def test_closing_rose_stops_waiting_for_reconnect(self):
        state = SimpleNamespace(phase='InProgress', stop=False)
        callback = make_game_ended_callback(state)
        self.assertFalse(callback())
        state.phase = None
        self.assertFalse(callback())
        state.stop = True
        self.assertTrue(callback())

    def test_each_injection_tracks_its_own_game(self):
        state = SimpleNamespace(phase='InProgress')
        first = make_game_ended_callback(state)
        first()
        state.phase = 'EndOfGame'
        second = make_game_ended_callback(state)
        self.assertTrue(first())
        self.assertFalse(second())



def wait_until(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class DodgeSessionTests(LtfSessionTestCase):
    """The injection's session ends when its champ select ends without a game"""

    def setUp(self):
        super().setUp()
        self.state = SimpleNamespace(phase='ChampSelect')
        self.manager = InjectionManager(shared_state=None)
        self.manager._initialized = True
        self.manager.injector = SimpleNamespace(game_dir=self.game, overlay_manager=self.overlay,
                                                mods_dir=self.mods)
        self.manager.start_patcher_in_background = lambda: None
        self.manager.refresh_injection_threshold = lambda: 0.0
        self.manager.injection_threshold = 0.0
        patcher = patch.object(manager_module, 'report_issue')
        patcher.start()
        self.addCleanup(patcher.stop)

    def start_injection(self, stop_callback):
        mod = self.make_mod()
        thread = threading.Thread(
            target=self.manager._run_injection,
            args=('Skin A', lambda _extra: self.overlay.mk_run_overlay([mod], stop_callback=stop_callback) == 0),
            daemon=True,
        )
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(self.process_manager.kill_all_runoverlay_processes)
        return thread

    def test_a_dodge_straight_back_to_matchmaking_frees_the_next_injection(self):
        thread = self.start_injection(make_game_ended_callback(self.state))
        self.assertTrue(wait_until(self.process_manager.session_active))

        # Another player dodges: the client requeues, no lobby in between
        self.state.phase = 'Matchmaking'
        self.manager.discard_early_patcher()  # what the WS handler does

        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertIn('stop_patcher', self.bridge.command_names())
        self.assertTrue(self.manager._run_injection('Skin B', lambda _extra: True))

    def test_a_dodge_before_the_session_starts_ends_it(self):
        stop_callback = make_game_ended_callback(self.state)  # made at the trigger
        # The lobby cleanup runs while the skin is still prepared
        self.state.phase = 'Lobby'
        self.process_manager.kill_all_runoverlay_processes()

        thread = self.start_injection(stop_callback)

        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(self.process_manager.session_active())


if __name__ == '__main__':
    unittest.main()
