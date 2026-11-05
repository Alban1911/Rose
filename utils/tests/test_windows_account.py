import sys
import unittest
from unittest.mock import patch

from injection.tests.test_ltf_diagnostics import summarize
from utils.system import windows_account
from utils.system.windows_account import (
    HINTS,
    LEAGUE_HINT,
    LEAGUE_MESSAGE,
    MESSAGES,
    ShellAccount,
    check_league_client,
    check_windows_account,
)


class WindowsAccountTests(unittest.TestCase):
    """LTK Manager runs with the Windows shell's rights and refuses to patch as
    administrator: Rose says so at startup (#425)"""

    def check(self, account):
        with patch.object(windows_account, "shell_account", return_value=account), \
                patch("utils.core.issue_reporter.report_issue") as report:
            check_windows_account()
        return report

    def test_the_built_in_administrator_is_reported(self):
        report = self.check(ShellAccount(elevated=True, builtin_administrator=True, uac_disabled=False))

        report.assert_called_once()
        code, severity, message = report.call_args.args
        self.assertEqual(code, "WINDOWS_ADMIN_SHELL")
        self.assertEqual(message, MESSAGES["builtin"])
        self.assertEqual(report.call_args.kwargs["hint"], HINTS["builtin"])

    def test_uac_turned_off_is_reported(self):
        report = self.check(ShellAccount(elevated=True, builtin_administrator=False, uac_disabled=True))

        self.assertEqual(report.call_args.args[2], MESSAGES["uac"])

    def test_a_regular_account_or_an_unknown_one_reports_nothing(self):
        self.check(ShellAccount(elevated=False, builtin_administrator=False, uac_disabled=False)).assert_not_called()
        self.check(None).assert_not_called()

    def test_troubleshooting_tells_each_reason_apart(self):
        for reason in ("builtin", "uac", "other"):
            with self.subTest(reason=reason):
                (summary,) = summarize((MESSAGES[reason], HINTS[reason]))
                self.assertEqual(summary["code"], "WINDOWS_ADMIN_SHELL")
                self.assertEqual(summary["cause"], reason)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_the_shell_of_this_session_can_be_read(self):
        account = windows_account.shell_account()
        if account is not None:  # no shell window on a service or CI session
            self.assertIsInstance(account.elevated, bool)


class LeagueClientTests(unittest.TestCase):
    """A League client started as administrator gets no skin and no error from
    LTK Manager: Rose says so when it connects to the client (#431)"""

    REGULAR_SHELL = ShellAccount(elevated=False, builtin_administrator=False, uac_disabled=False)

    def check(self, elevated, shell=REGULAR_SHELL):
        with patch.object(windows_account, "process_elevated", return_value=elevated),                 patch.object(windows_account, "shell_account", return_value=shell),                 patch("utils.core.issue_reporter.report_issue") as report,                 patch("utils.core.issue_reporter.remove_issues") as remove:
            result = check_league_client(1234)
        return result, report, remove

    def test_an_elevated_client_is_reported(self):
        result, report, remove = self.check(True)

        self.assertTrue(result)
        code, severity, message = report.call_args.args
        self.assertEqual((code, message), ("LEAGUE_ELEVATED", LEAGUE_MESSAGE))
        self.assertEqual(report.call_args.kwargs["hint"], LEAGUE_HINT)
        remove.assert_not_called()

    def test_a_client_started_normally_clears_the_warning(self):
        result, report, remove = self.check(False)

        self.assertFalse(result)
        report.assert_not_called()
        (should_remove,) = remove.call_args.args
        self.assertTrue(should_remove(f"Nov 05 06:40 | {LEAGUE_MESSAGE}", f"Fix: {LEAGUE_HINT}"))
        self.assertFalse(should_remove(f"Nov 05 06:40 | {MESSAGES['uac']}", f"Fix: {HINTS['uac']}"))

    def test_an_elevated_shell_is_left_to_the_startup_check(self):
        elevated_shell = ShellAccount(elevated=True, builtin_administrator=False, uac_disabled=True)
        _, report, _ = self.check(True, shell=elevated_shell)

        report.assert_not_called()

    def test_an_unreadable_client_reports_nothing(self):
        result, report, remove = self.check(None)

        self.assertIsNone(result)
        report.assert_not_called()
        remove.assert_not_called()

    def test_troubleshooting_tells_it_from_the_windows_account(self):
        (summary,) = summarize((LEAGUE_MESSAGE, LEAGUE_HINT))
        self.assertEqual(summary["code"], "LEAGUE_ELEVATED")

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_this_process_can_be_read(self):
        import os
        self.assertIsInstance(windows_account.process_elevated(os.getpid()), bool)


if __name__ == "__main__":
    unittest.main()
