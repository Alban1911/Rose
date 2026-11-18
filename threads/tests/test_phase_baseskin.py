import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from threads.core import phase_thread


class PhaseHomeScreenTests(unittest.TestCase):
    """The home screen never reaches the phase handler: the phase thread puts it in the shared state."""

    def run_polls(self, raw_phases, last_phase):
        state = SimpleNamespace(stop=False, phase=last_phase, is_swiftplay_mode=False, swiftplay_extracted_mods=[])
        lcu = SimpleNamespace(ok=True, phase=raw_phases[0], refresh_if_needed=lambda: None)
        with (
            patch.object(phase_thread, 'SwiftplayHandler'),
            patch.object(phase_thread, 'PhaseHandler', return_value=MagicMock()),
            patch.object(phase_thread, 'LobbyProcessor'),
        ):
            worker = phase_thread.PhaseThread(lcu, state, injection_manager=MagicMock())
        worker.last_phase = last_phase
        worker._last_raw_phase = last_phase
        polls = iter(raw_phases[1:])

        def advance(_):
            try:
                lcu.phase = next(polls)
            except StopIteration:
                state.stop = True

        with (
            patch('utils.integration.pengu_loader.retry_deferred_restart'),
            patch.object(phase_thread.time, 'sleep', side_effect=advance),
        ):
            worker.run()
        return state

    def test_the_home_screen_is_the_shared_phase(self):
        self.assertIsNone(self.run_polls(['None', 'None'], 'EndOfGame').phase)

    def test_an_unreadable_client_leaves_the_phase_as_it_was(self):
        self.assertEqual(self.run_polls([None, None], 'Lobby').phase, 'Lobby')


if __name__ == '__main__':
    unittest.main()
