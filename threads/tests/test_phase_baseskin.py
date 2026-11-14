import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from injection.baseskin import library
from threads.core import phase_thread


class PhaseBaseSkinPassTests(unittest.TestCase):
    def run_polls(self, raw_phases, last_phase):
        state = SimpleNamespace(stop=False, phase=last_phase, is_swiftplay_mode=False, swiftplay_extracted_mods=[])
        lcu = SimpleNamespace(ok=True, phase=raw_phases[0], refresh_if_needed=lambda: None)
        manager = MagicMock()
        with (
            patch.object(phase_thread, 'SwiftplayHandler'),
            patch.object(phase_thread, 'PhaseHandler', return_value=MagicMock()),
            patch.object(phase_thread, 'LobbyProcessor'),
        ):
            worker = phase_thread.PhaseThread(lcu, state, injection_manager=manager)
        worker.last_phase = last_phase
        worker._last_raw_phase = last_phase
        polls = iter(raw_phases[1:])
        seen = []

        def on_phase(phase, injection_manager, shared):
            seen.append((phase, injection_manager, shared.phase))

        def advance(_):
            try:
                lcu.phase = next(polls)
            except StopIteration:
                state.stop = True

        with (
            patch.object(library, 'on_phase', side_effect=on_phase),
            patch('utils.integration.pengu_loader.retry_deferred_restart'),
            patch.object(phase_thread.time, 'sleep', side_effect=advance),
        ):
            worker.run()
        return seen, manager

    def test_the_home_screen_starts_the_pass(self):
        seen, manager = self.run_polls(['None', 'None'], 'EndOfGame')
        # Once, with the home screen already in the shared phase the pass checks
        self.assertEqual(seen, [('None', manager, None)])

    def test_an_unreadable_client_does_not(self):
        seen, _ = self.run_polls([None, None], 'Lobby')
        self.assertEqual(seen, [])


if __name__ == '__main__':
    unittest.main()
