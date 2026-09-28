import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from injection.core.manager import InjectionManager
from injection.overlay import overlay_manager
from injection.overlay.overlay_manager import OverlayManager
from injection.tools.tools_manager import ToolsManager


class EarlyPatcherTests(unittest.TestCase):
    """The LTK patcher starts with the game monitor, before the mods are prepared:
    the DLL only overlays games launched after the host started scanning"""

    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        self.overlay = OverlayManager(root / 'tools', root / 'mods', root / 'game')

        self.host = root / 'tools' / 'ltk_patcher_host.exe'
        patches = [
            patch.object(ToolsManager, 'detect_ltk_patcher', side_effect=lambda: self.host),
            patch.object(overlay_manager, 'check_ltk_patcher', return_value=SimpleNamespace(expired=False)),
            patch.object(OverlayManager, '_start_ltk_patcher', side_effect=self._fake_session),
            patch.object(OverlayManager, '_abort_ltk_patcher'),
        ]
        self.detect, _, self.start, self.abort = (p.start() for p in patches)
        for p in patches:
            self.addCleanup(p.stop)
        self.running = True

    def _fake_session(self, host_exe, overlay_dir):
        proc = MagicMock()
        proc.poll.side_effect = lambda: None if self.running else 1
        return {'proc': proc, 'session': {}, 'reader': None, 'log': None}

    def test_the_overlay_takes_over_the_early_patcher(self):
        self.overlay.start_patcher_early()
        self.overlay.start_patcher_early()  # once per injection
        self.start.assert_called_once()
        self.assertTrue((self.overlay.mods_dir.parent / 'overlay').is_dir())

        session = self.overlay._take_early_patcher()
        self.assertIs(session['proc'].poll(), None)
        self.assertIsNone(self.overlay._take_early_patcher())
        self.abort.assert_not_called()

    def test_a_patcher_that_died_is_not_taken_over(self):
        self.overlay.start_patcher_early()
        self.running = False
        self.assertIsNone(self.overlay._take_early_patcher())
        self.abort.assert_called_once()

    def test_an_injection_that_gave_up_stops_its_patcher(self):
        self.overlay.start_patcher_early()
        self.overlay.discard_early_patcher()
        self.abort.assert_called_once()
        self.assertIsNone(self.overlay._take_early_patcher())

    def test_nothing_starts_without_a_usable_patcher(self):
        self.host = None
        self.overlay.start_patcher_early()
        self.start.assert_not_called()


class MonitorStartsThePatcherTests(unittest.TestCase):
    def test_the_patcher_starts_and_stops_with_the_game_monitor(self):
        manager = InjectionManager.__new__(InjectionManager)
        manager.game_monitor = MagicMock()
        manager.injector = MagicMock()

        manager._start_monitor()
        manager.injector.overlay_manager.start_patcher_early.assert_called_once()
        manager._stop_monitor()
        manager.injector.overlay_manager.discard_early_patcher.assert_called_once()

    def test_no_injector_yet(self):
        manager = InjectionManager.__new__(InjectionManager)
        manager.game_monitor = MagicMock()
        manager.injector = None
        manager._start_monitor()
        manager._stop_monitor()
        manager.game_monitor.start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
