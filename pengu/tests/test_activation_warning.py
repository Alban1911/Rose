import ctypes
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import main as rose_main


@unittest.skipUnless(sys.platform == 'win32', 'the warning is a Windows dialog')
class PenguActivationWarningTests(unittest.TestCase):
    """The verifier reports confirmed missing injection through a Windows dialog."""

    def test_the_user_is_told_and_the_issue_is_recorded(self):
        with (
            patch.object(rose_main, 'report_issue') as report_issue,
            patch.object(ctypes.windll.user32, 'MessageBoxW', return_value=1) as message_box,
        ):
            rose_main._warn_pengu_injection_failed(123)

        self.assertEqual(report_issue.call_args[0][0], 'PENGU_INJECTION_FAILED')
        self.assertEqual(report_issue.call_args.kwargs['details'], {'client_pid': 123})
        message_box.assert_called_once()
        self.assertIn('Pengu Loader', message_box.call_args[0][1])
        self.assertIn('Diagnose Rose startup', message_box.call_args[0][1])

    def test_a_dialog_error_is_logged_not_raised(self):
        with (
            patch.object(rose_main, 'report_issue'),
            patch.object(ctypes.windll.user32, 'MessageBoxW', side_effect=OSError('no desktop')),
        ):
            rose_main._warn_pengu_injection_failed(123)

    def test_failed_activation_command_does_not_show_an_injection_warning(self):
        path = Path('C:/League').resolve()
        config = Mock()
        config.load_league_path.return_value = path
        config.load_client_path.return_value = path
        detector = Mock()
        detector.detect_paths.return_value = (path, path)
        with (
            patch.object(rose_main, 'ConfigManager', return_value=config),
            patch.object(rose_main, 'GameDetector', return_value=detector),
            patch.object(rose_main.pengu_loader, 'activate_on_start', return_value=False),
            patch.object(rose_main, '_warn_pengu_injection_failed') as warn,
        ):
            rose_main._setup_pengu_and_injection(Mock(), Mock())
        warn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
