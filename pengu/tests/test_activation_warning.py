import ctypes
import sys
import unittest
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main()
