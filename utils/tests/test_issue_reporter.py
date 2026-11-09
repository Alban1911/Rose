import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from utils.core import issue_reporter
from utils.core.issue_reporter import (
    Stamp,
    in_this_session,
    parse_stamp,
    read_issues_tail,
    remove_issues,
    report_issue,
    resolve_issue,
    start_session,
)

DAY = 24 * 3600
EARLIER = "0e0e0e0e"  # an earlier session's id


def stamp(seconds_ago: float, code: str, session: str = EARLIER) -> str:
    when = time.localtime(time.time() - seconds_ago)
    return f"{time.strftime('%Y-%m-%d %H:%M:%S', when)} [{code}] #{session}"


class IssueFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "rose_diagnostics.txt"
        patcher = patch.object(issue_reporter, "_issues_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        for name in ("SESSION_START", "SESSION_ID"):
            kept = patch.object(issue_reporter, name, getattr(issue_reporter, name))
            kept.start()
            self.addCleanup(kept.stop)

    def write(self, *lines):
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def stamps(self):
        return [parse_stamp(line.split(" | ", 1)[0]) for line in read_issues_tail() if " | " in line]

    def test_a_report_holds_its_year_code_and_session(self):
        report_issue("LTF_FAILED", "error", "Injection failed: boom", hint="Retry.", dedupe_window_s=0)

        line, fix = read_issues_tail()
        written = parse_stamp(line.split(" | ", 1)[0])
        self.assertEqual((written.code, written.session), ("LTF_FAILED", issue_reporter.SESSION_ID))
        self.assertAlmostEqual(written.when, time.time(), delta=5)
        self.assertTrue(line.endswith(" | Injection failed: boom"))
        self.assertEqual(fix, "Fix: Retry.")

    def test_a_new_session_drops_old_setup_and_stale_reports(self):
        two_days_ago = stamp(2 * DAY, "LTF_FAILED")
        self.write(
            f"{stamp(3600, 'WINDOWS_ADMIN_SHELL')} | LTK Manager can't apply skins: UAC is off.",
            "Fix: Turn UAC back on.",
            f"{stamp(8 * DAY, 'LTF_FAILED')} | Injection failed: a week ago",
            f"{two_days_ago} | Injection failed: two days ago",
            "Fix: Retry.",
        )

        start_session()

        self.assertEqual(read_issues_tail(), [f"{two_days_ago} | Injection failed: two days ago", "Fix: Retry."])

    def test_a_report_is_this_sessions_whatever_the_clock_did(self):
        """A daylight saving change, or a clock set right after a boot, put
        reports in the wrong session while sessions were told by the time"""
        report_issue("LTF_FAILED", "error", "the last session's", dedupe_window_s=0)
        clock_set_back = time.time() - 2 * 3600
        with patch.object(issue_reporter.time, "time", return_value=clock_set_back):
            start_session()
            report_issue("LTF_FAILED", "error", "this session's", dedupe_window_s=0)

        earlier, current = self.stamps()
        self.assertGreater(earlier.when, current.when, "the clock went back")
        self.assertEqual((in_this_session(earlier), in_this_session(current)), (False, True))

    def test_a_setup_problem_ltk_manager_checks_again_stays_current_until_then(self):
        """LTK Manager set to run as administrator: Rose checks it again only as
        LTK Manager starts. Dropped at Rose's start, Troubleshooting said
        "No recent errors" until a game's injection failed"""
        reported = f"{stamp(9 * DAY, 'LTK_ELEVATED')} | LTK Manager is set to run as administrator"
        self.write(reported, "Fix: Turn it off.")

        start_session()

        (kept,) = self.stamps()
        self.assertEqual(read_issues_tail(), [reported, "Fix: Turn it off."])
        self.assertTrue(in_this_session(kept))

    def test_a_setup_problem_reported_again_replaces_its_earlier_copy(self):
        self.write(f"{stamp(DAY, 'LTF_MISSING')} | Injection failed: Rose's LTF bridge files are missing.")

        report_issue("LTF_MISSING", "error", "Injection failed: Rose's LTF bridge files are missing.",
                     dedupe_window_s=0)

        (current,) = self.stamps()
        self.assertEqual(current.session, issue_reporter.SESSION_ID)

    def test_a_problem_gone_has_its_reports_removed_older_ones_too(self):
        self.write(
            f"{stamp(DAY, 'LTK_MANAGER_MISSING')} | Injection failed: LTK Manager is not installed.",
            "Nov 08 14:02 | Injection failed: LTK Manager is not installed.",
            f"{stamp(60, 'LTF_FAILED')} | Injection failed: boom",
        )

        resolve_issue("LTK_MANAGER_MISSING", "LTK Manager is not installed")

        self.assertEqual([found.code for found in self.stamps()], ["LTF_FAILED"])

    def test_nothing_is_written_when_no_report_goes(self):
        """Rose's start rewrote the whole file (up to 1.5 MB) for nothing"""
        self.write(f"{stamp(60, 'LTF_FAILED')} | Injection failed: boom")

        with patch.object(Path, "write_text", side_effect=AssertionError("written")):
            self.assertTrue(remove_issues(lambda line, fix: False))
            start_session()


class StampTests(unittest.TestCase):
    def test_an_older_report_gets_the_latest_year_not_in_the_future(self):
        now = datetime(2027, 1, 5, 12, 0).timestamp()

        december = parse_stamp("Dec 15 00:39", now)
        january = parse_stamp("Jan 04 08:00", now)

        self.assertEqual(datetime.fromtimestamp(december.when), datetime(2026, 12, 15, 0, 39))
        self.assertEqual(datetime.fromtimestamp(january.when), datetime(2027, 1, 4, 8, 0))
        self.assertEqual((december.code, december.session), ("", ""))

    def test_a_report_from_before_stamps_held_their_session_is_an_earlier_sessions(self):
        before = parse_stamp("2026-11-08 14:02:31 [LTF_FAILED]")

        self.assertEqual((before.code, before.session), ("LTF_FAILED", ""))
        self.assertFalse(in_this_session(before))

    def test_any_code_is_read(self):
        """A code with a digit made the whole stamp unreadable: never this session's, never cleaned up"""
        self.assertEqual(parse_stamp("2026-11-08 14:02:31 [LTK_V2_FAILED] #3f9a0c21")[1:],
                         ("LTK_V2_FAILED", "3f9a0c21"))

    def test_an_unreadable_stamp_has_no_time(self):
        self.assertEqual(parse_stamp("yesterday"), Stamp(None, "", ""))


if __name__ == "__main__":
    unittest.main()
