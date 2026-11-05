import sys
import unittest
from unittest.mock import patch

from injection.tests.test_ltf_diagnostics import summarize
from utils.system import windows_account
from utils.system.windows_account import HINTS, MESSAGES, ShellAccount, check_windows_account


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


if __name__ == "__main__":
    unittest.main()
