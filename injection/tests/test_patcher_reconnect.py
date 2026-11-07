import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from injection.game.game_monitor import make_game_ended_callback
from injection.overlay import overlay_manager
from injection.overlay.overlay_manager import OverlayManager


class PatcherReconnectTests(unittest.TestCase):
    def test_game_crash_and_client_outage_keep_overlay_until_match_ends(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            overlay_dir = root / 'overlay'
            overlay_dir.mkdir()
            skin = overlay_dir / 'skin.wad.client'
            skin.write_bytes(b'prepared skin')
            overlay = OverlayManager(root / 'tools', root / 'mods', root / 'game')
            state = SimpleNamespace(phase='InProgress', stop=False)
            phases = iter([None, 'None', 'Reconnect', 'GameStart', 'InProgress', 'EndOfGame'])
            proc = MagicMock(returncode=0)
            proc.poll.return_value = None
            session = {'proc': proc, 'reader': MagicMock(), 'log': None,
                       'session': {'state': 'exited', 'error': None, 'eol': False}}
            observed = []

            def advance(_):
                self.assertTrue(skin.is_file(), 'Overlay deleted before reconnect')
                observed.append(state.phase)
                state.phase = next(phases)

            with (
                patch.object(overlay_manager.time, 'sleep', side_effect=advance),
                patch.object(overlay, '_running_game', return_value=None),
                patch.object(overlay, '_stop_ltk_patcher') as stop,
                patch.object(overlay, '_report_ltk_patcher_failure') as failure,
            ):
                code = overlay._run_ltk_patcher(
                    session, overlay_dir, make_game_ended_callback(state))

            self.assertEqual(code, 0)
            self.assertEqual(observed, ['InProgress', None, 'None', 'Reconnect',
                                        'GameStart', 'InProgress'])
            stop.assert_called_once_with(proc)
            failure.assert_not_called()
            self.assertFalse(skin.exists(), 'Overlay kept after confirmed match end')


if __name__ == '__main__':
    unittest.main()
