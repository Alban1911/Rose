import json
import time
import unittest
from unittest.mock import patch

from pengu.communication import message_handler
from utils.core import issue_reporter


def stamp(seconds_ago: float, code: str) -> str:
    when = time.localtime(time.time() - seconds_ago)
    return f"{time.strftime('%Y-%m-%d %H:%M:%S', when)} [{code}]"


LINES = [
    f"{stamp(2 * 24 * 3600, 'LOW_DISK_SPACE')} | Injection failed: not enough disk space",
    f"{stamp(60, 'LTF_FAILED')} | Injection failed: LTK Manager is already open without Rose's bridge",
    "Fix: Close LTK Manager, then retry.",
]


class DiagnosticsSessionTests(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(message_handler.MessageHandler)
        for patcher in (
            patch.object(message_handler, "read_issues_tail", return_value=LINES),
            patch.object(issue_reporter, "SESSION_START", time.time() - 3600),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_errors_say_whether_they_are_from_this_session_most_recent_first(self):
        errors = self.handler._compute_diagnostics_errors()

        self.assertEqual([(e["code"], e["thisSession"]) for e in errors],
                         [("LTF_FAILED", True), ("LOW_DISK_SPACE", False)])

    def test_only_this_sessions_errors_light_up_troubleshooting(self):
        sent = []
        self.handler._send_response = sent.append
        with patch.object(message_handler, "get_config_float", return_value=1.0), \
                patch.object(message_handler, "get_config_option", return_value=""), \
                patch.object(message_handler, "is_registered_for_autostart", return_value=False):
            self.handler._handle_settings_request({})

        payload = json.loads(sent[-1])
        self.assertTrue(payload["hasErrors"])
        self.assertEqual(payload["errorsCount"], 1)


if __name__ == "__main__":
    unittest.main()
