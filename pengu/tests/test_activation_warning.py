import ctypes
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import main as rose_main


class _RunNow:
    """Stand-in for create_daemon_thread that runs the target on start()"""

    def __init__(self, target, name=None):
        self.target = target

    def start(self):
        self.target()


@unittest.skipUnless(sys.platform == 'win32', 'the warning is a Windows dialog')
class PenguActivationWarningTests(unittest.TestCase):
    """A failed Pengu activation used to be only a log line: Rose was simply
    missing from the client and the user had no idea why"""

    def test_the_user_is_told_and_the_issue_is_recorded(self):
        with (
            patch.object(rose_main, 'create_daemon_thread', _RunNow),
            patch.object(rose_main, 'report_issue') as report_issue,
            patch.object(ctypes.windll.user32, 'MessageBoxW', return_value=1) as message_box,
        ):
            rose_main._warn_pengu_activation_failed()

        self.assertEqual(report_issue.call_args[0][0], 'PENGU_ACTIVATION_FAILED')
        message_box.assert_called_once()
        self.assertIn('Pengu Loader', message_box.call_args[0][1])

    def test_a_dialog_error_is_logged_not_raised(self):
        with (
            patch.object(rose_main, 'create_daemon_thread', _RunNow),
            patch.object(rose_main, 'report_issue'),
            patch.object(ctypes.windll.user32, 'MessageBoxW', side_effect=OSError('no desktop')),
        ):
            rose_main._warn_pengu_activation_failed()

    def test_a_failed_activation_warns_at_once_not_as_an_injection_failure(self):
        """#350 first replaced this warning with a log line, leaving the user to the
        startup verifier's check a minute later"""
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
            patch.object(rose_main, '_warn_pengu_activation_failed') as activation,
            patch.object(rose_main, '_warn_pengu_injection_failed') as injection,
        ):
            rose_main._setup_pengu_and_injection(Mock(), Mock())
        activation.assert_called_once()
        injection.assert_not_called()


@unittest.skipUnless(sys.platform == 'win32', 'the warning is a Windows dialog')
class PenguInjectionWarningTests(unittest.TestCase):
    """The startup verifier's verdict: activated, but not loaded into the client."""

    def test_the_user_is_told_where_to_send_the_report(self):
        with (
            patch.object(rose_main, 'report_issue') as report_issue,
            patch.object(ctypes.windll.user32, 'MessageBoxW', return_value=1) as message_box,
        ):
            rose_main._warn_pengu_injection_failed(123)

        self.assertEqual(report_issue.call_args[0][0], 'PENGU_INJECTION_FAILED')
        self.assertEqual(report_issue.call_args.kwargs['details'], {'client_pid': 123})
        text = message_box.call_args[0][1]
        self.assertIn('Diagnose Rose startup', text)
        self.assertIn('discord.gg/roseskins', text)
        self.assertIn('github.com/Alban1911/Rose/issues', text)

    def test_a_dialog_error_is_logged_not_raised(self):
        with (
            patch.object(rose_main, 'report_issue'),
            patch.object(ctypes.windll.user32, 'MessageBoxW', side_effect=OSError('no desktop')),
        ):
            rose_main._warn_pengu_injection_failed(123)

    def test_the_issue_reaches_the_diagnostics_file(self):
        from utils.core import issue_reporter
        self.assertIn('PENGU_INJECTION_FAILED', issue_reporter._ALLOWED_CODES)


if __name__ == '__main__':
    unittest.main()
