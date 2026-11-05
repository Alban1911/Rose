import sys
import unittest
from unittest.mock import patch

from injection.tests.test_ltf_diagnostics import summarize
from utils.system import windows_account
from utils.system.windows_account import (
    HINTS,
    LEAGUE_HINT,
    LEAGUE_MESSAGE,
    LEAGUE_SETTING_HINT,
    LEAGUE_SETTING_MESSAGE,
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
    """League set to run as administrator, or a client started so, gets no
    skin: Rose says so when it connects to the client (#430, #431)"""

    REGULAR_SHELL = ShellAccount(elevated=False, builtin_administrator=False, uac_disabled=False)

    def check(self, elevated, shell=REGULAR_SHELL, entries=()):
        with patch.object(windows_account, "process_elevated", return_value=elevated), \
                patch.object(windows_account, "shell_account", return_value=shell), \
                patch.object(windows_account, "league_run_as_admin_entries", return_value=list(entries)), \
                patch("utils.core.issue_reporter.report_issue") as report, \
                patch("utils.core.issue_reporter.remove_issues") as remove:
            result = check_league_client(1234)
        return result, report, remove

    @staticmethod
    def removed(remove, line):
        """Whether one of the remove_issues calls drops this report line."""
        return any(call.args[0](f"Nov 05 06:40 | {line}", "") for call in remove.call_args_list)

    def test_an_elevated_client_is_reported(self):
        result, report, remove = self.check(True)

        self.assertTrue(result)
        code, severity, message = report.call_args.args
        self.assertEqual((code, message), ("LEAGUE_ELEVATED", LEAGUE_MESSAGE))
        self.assertEqual(report.call_args.kwargs["hint"], LEAGUE_HINT)
        self.assertFalse(self.removed(remove, LEAGUE_MESSAGE))
        self.assertTrue(self.removed(remove, LEAGUE_SETTING_MESSAGE + " (C:\\old\\LeagueClient.exe)."))

    def test_a_client_started_normally_clears_the_warnings(self):
        result, report, remove = self.check(False)

        self.assertFalse(result)
        report.assert_not_called()
        self.assertTrue(self.removed(remove, LEAGUE_MESSAGE))
        self.assertTrue(self.removed(remove, LEAGUE_SETTING_MESSAGE + " (C:\\old\\LeagueClient.exe)."))
        self.assertFalse(self.removed(remove, MESSAGES["uac"]))

    def test_programs_set_to_run_as_administrator_are_named(self):
        entries = [
            ("HKCU", r"C:\Riot Games\League of Legends\LeagueClient.exe"),
            ("HKLM", r"D:\Old\Riot Client\RiotClientServices.exe"),
        ]
        result, report, _ = self.check(False, entries=entries)

        self.assertTrue(result)
        code, _, message = report.call_args.args
        self.assertEqual(code, "LEAGUE_ELEVATED")
        self.assertEqual(message, (
            f"{LEAGUE_SETTING_MESSAGE} (C:\\Riot Games\\League of Legends\\LeagueClient.exe, "
            "D:\\Old\\Riot Client\\RiotClientServices.exe [all users])."
        ))
        self.assertEqual(report.call_args.kwargs["hint"], LEAGUE_SETTING_HINT)

    def test_an_elevated_shell_is_left_to_the_startup_check(self):
        elevated_shell = ShellAccount(elevated=True, builtin_administrator=False, uac_disabled=True)
        _, report, _ = self.check(True, shell=elevated_shell)

        report.assert_not_called()

    def test_an_unreadable_client_reports_nothing(self):
        result, report, remove = self.check(None)

        self.assertIsNone(result)
        report.assert_not_called()
        self.assertFalse(self.removed(remove, LEAGUE_MESSAGE))

    def test_troubleshooting_tells_both_from_the_windows_account(self):
        (running,) = summarize((LEAGUE_MESSAGE, LEAGUE_HINT))
        self.assertEqual((running["code"], running["cause"]), ("LEAGUE_ELEVATED", "running"))

        message = f"{LEAGUE_SETTING_MESSAGE} (C:\\Riot\\LeagueClient.exe, D:\\Riot\\RiotClientServices.exe [all users])."
        (setting,) = summarize((message, LEAGUE_SETTING_HINT))
        self.assertEqual((setting["code"], setting["cause"]), ("LEAGUE_ELEVATED", "setting"))
        self.assertEqual(setting["detail"], "C:\\Riot\\LeagueClient.exe, D:\\Riot\\RiotClientServices.exe [all users]")

    def test_only_league_and_riot_programs_set_to_run_as_administrator_count(self):
        """The rule LTK Manager applies: a League* or Riot* file name, a RUNASADMIN layer"""
        import winreg

        values = {
            winreg.HKEY_CURRENT_USER: [
                (r"C:\Riot Games\League of Legends\LeagueClient.exe", "~ RUNASADMIN"),
                (r"C:\Riot Games\League of Legends\Game\League of Legends.exe", "~ HIGHDPIAWARE"),
                (r"C:\Games\Steam\steam.exe", "~ RUNASADMIN"),
            ],
            winreg.HKEY_LOCAL_MACHINE: [(r"D:\Old\Riot Client\RiotClientServices.exe", "$ runasadmin WIN8RTM")],
        }

        class Key:
            def __init__(self, root):
                self.values = values[root]

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def enum_value(key, index):
            if index >= len(key.values):
                raise OSError("no more data")
            name, data = key.values[index]
            return name, data, winreg.REG_SZ

        with patch.object(winreg, "OpenKey", side_effect=lambda root, *args: Key(root)), \
                patch.object(winreg, "EnumValue", side_effect=enum_value):
            entries = windows_account.league_run_as_admin_entries()

        self.assertEqual(entries, [
            ("HKCU", r"C:\Riot Games\League of Legends\LeagueClient.exe"),
            ("HKLM", r"D:\Old\Riot Client\RiotClientServices.exe"),
        ])

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_this_process_and_the_compatibility_settings_can_be_read(self):
        import os
        self.assertIsInstance(windows_account.process_elevated(os.getpid()), bool)
        self.assertIsInstance(windows_account.league_run_as_admin_entries(), list)


if __name__ == "__main__":
    unittest.main()
