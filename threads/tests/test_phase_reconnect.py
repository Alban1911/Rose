import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from threads.core import phase_thread


class PhaseReconnectTests(unittest.TestCase):
    def test_same_phase_is_restored_after_client_outage(self):
        state = SimpleNamespace(stop=False, phase='InProgress',is_swiftplay_mode=False, swiftplay_extracted_mods=[])
        lcu = SimpleNamespace(ok=True, phase=None, refresh_if_needed=lambda: None)
        phase_handler = MagicMock()
        with (
            patch.object(phase_thread, 'SwiftplayHandler'),
            patch.object(phase_thread, 'PhaseHandler', return_value=phase_handler),
            patch.object(phase_thread, 'LobbyProcessor'),
        ):
            worker = phase_thread.PhaseThread(lcu, state)
        worker.last_phase = 'InProgress'
        worker._last_raw_phase = 'InProgress'
        observed = []

        def advance(_):
            observed.append(state.phase)
            if len(observed) == 1:
                lcu.phase = 'InProgress'
            else:
                state.stop = True

        with patch.object(phase_thread.time, 'sleep', side_effect=advance):
            worker.run()

        self.assertEqual(observed, [None, 'InProgress'])
        phase_handler.handle_phase_change.assert_not_called()


if __name__ == '__main__':
    unittest.main()
