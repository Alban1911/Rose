import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from utils.core import issue_reporter
from utils.core.issue_reporter import parse_stamp, read_issues_tail, report_issue, start_session

DAY = 24 * 3600


def stamp(seconds_ago: float, code: str) -> str:
    when = time.localtime(time.time() - seconds_ago)
    return f"{time.strftime('%Y-%m-%d %H:%M:%S', when)} [{code}]"


class IssueFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "rose_diagnostics.txt"
        patcher = patch.object(issue_reporter, "_issues_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        start = patch.object(issue_reporter, "SESSION_START", issue_reporter.SESSION_START)
        start.start()
        self.addCleanup(start.stop)

    def test_a_report_holds_its_year_and_code(self):
        report_issue("LTF_FAILED", "error", "Injection failed: boom", hint="Retry.", dedupe_window_s=0)

        line, fix = read_issues_tail()
        when, code = parse_stamp(line.split(" | ", 1)[0])
        self.assertEqual(code, "LTF_FAILED")
        self.assertAlmostEqual(when, time.time(), delta=5)
        self.assertTrue(line.endswith(" | Injection failed: boom"))
        self.assertEqual(fix, "Fix: Retry.")

    def test_a_new_session_drops_old_setup_and_stale_reports(self):
        self.path.write_text("\n".join([
            f"{stamp(3600, 'WINDOWS_ADMIN_SHELL')} | LTK Manager can't apply skins: UAC is off.",
            "Fix: Turn UAC back on.",
            f"{stamp(8 * DAY, 'LTF_FAILED')} | Injection failed: a week ago",
            f"{stamp(2 * DAY, 'LTF_FAILED')} | Injection failed: two days ago",
            "Fix: Retry.",
        ]) + "\n", encoding="utf-8")

        start_session()

        self.assertEqual(read_issues_tail(), [
            f"{stamp(2 * DAY, 'LTF_FAILED')} | Injection failed: two days ago",
            "Fix: Retry.",
        ])

    def test_a_report_is_this_sessions_only_from_its_start(self):
        report_issue("LTF_FAILED", "error", "earlier", dedupe_window_s=0)
        issue_reporter.SESSION_START = time.time() + 2
        when, _ = parse_stamp(read_issues_tail()[0].split(" | ", 1)[0])

        self.assertFalse(issue_reporter.in_this_session(when))
        self.assertTrue(issue_reporter.in_this_session(issue_reporter.SESSION_START))


class OlderStampTests(unittest.TestCase):
    def test_an_older_report_gets_the_latest_year_not_in_the_future(self):
        now = datetime(2027, 1, 5, 12, 0).timestamp()

        december, code = parse_stamp("Dec 15 00:39", now)
        january, _ = parse_stamp("Jan 04 08:00", now)

        self.assertEqual(datetime.fromtimestamp(december), datetime(2026, 12, 15, 0, 39))
        self.assertEqual(datetime.fromtimestamp(january), datetime(2027, 1, 4, 8, 0))
        self.assertEqual(code, "")

    def test_an_unreadable_stamp_has_no_time(self):
        self.assertEqual(parse_stamp("yesterday"), (None, ""))


if __name__ == "__main__":
    unittest.main()
