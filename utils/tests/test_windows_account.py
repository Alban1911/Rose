import sys
import unittest
from unittest.mock import MagicMock, patch

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

    def test_ltk_managers_programs_set_to_run_as_administrator_are_found(self):
        """#468, #456: Windows refused to start them unelevated (error 740)"""
        import winreg

        values = {
            winreg.HKEY_CURRENT_USER: [
                (r"C:\Users\x\AppData\Roaming\dev.leaguetoolkit.manager\patcher\5fb1\ltk_patcher_host.exe",
                 "~ RUNASADMIN"),
                (r"C:\Riot Games\League of Legends\LeagueClient.exe", "~ RUNASADMIN"),
            ],
            winreg.HKEY_LOCAL_MACHINE: [
                (r"C:\Program Files\LTK Manager\ltk-manager.exe", "$ RUNASADMIN"),
                (r"C:\Program Files\LTK Manager\uninstall.exe", "$ RUNASADMIN"),
            ],
        }

        def open_key(root, *args):
            key = MagicMock()
            key.__enter__.return_value = key
            key.values = values[root]
            return key

        def enum_value(key, index):
            if index >= len(key.values):
                raise OSError("no more data")
            name, data = key.values[index]
            return name, data, winreg.REG_SZ

        with patch.object(winreg, "OpenKey", side_effect=open_key), \
                patch.object(winreg, "EnumValue", side_effect=enum_value):
            entries = windows_account.ltk_run_as_admin_entries()

        self.assertEqual(entries, [
            ("HKCU", r"C:\Users\x\AppData\Roaming\dev.leaguetoolkit.manager\patcher\5fb1\ltk_patcher_host.exe"),
            ("HKLM", r"C:\Program Files\LTK Manager\ltk-manager.exe"),
        ])

    def test_troubleshooting_names_ltk_manager_set_to_run_as_administrator(self):
        entries = [("HKLM", r"C:\Program Files\LTK Manager\ltk-manager.exe")]
        with patch.object(windows_account, "ltk_run_as_admin_entries", return_value=entries), \
                patch("utils.core.issue_reporter.report_issue") as report, \
                patch("utils.core.issue_reporter.remove_issues"):
            self.assertTrue(windows_account.check_ltk_settings())

        message = report.call_args.args[2]
        (summary,) = summarize((message, report.call_args.kwargs["hint"]))
        self.assertEqual(summary["code"], "LTK_ELEVATED")
        self.assertEqual(summary["detail"], r"C:\Program Files\LTK Manager\ltk-manager.exe [all users]")

    def test_no_ltk_program_set_to_run_as_administrator_clears_the_warning(self):
        with patch.object(windows_account, "ltk_run_as_admin_entries", return_value=[]), \
                patch("utils.core.issue_reporter.report_issue") as report, \
                patch("utils.core.issue_reporter.remove_issues") as remove:
            self.assertFalse(windows_account.check_ltk_settings())

        report.assert_not_called()
        remove.assert_called_once()

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_this_process_and_the_compatibility_settings_can_be_read(self):
        import os
        self.assertIsInstance(windows_account.process_elevated(os.getpid()), bool)
        self.assertIsInstance(windows_account.league_run_as_admin_entries(), list)


class FakeRegistry:
    """Windows' compatibility settings keys, as winreg reads and writes them.
    *values* maps (root, subkey) to {program path: layers}; *read_only*
    lists the (root, subkey) keys Rose may only read."""

    def __init__(self, values, read_only=()):
        self.values = {where: dict(entries) for where, entries in values.items()}
        self.read_only = set(read_only)
        self.opened = []

    def open_key(self, root, subkey, reserved=0, access=0):
        import winreg
        where = (root, subkey)
        self.opened.append(where)
        if where not in self.values:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        if where in self.read_only and access & winreg.KEY_SET_VALUE:
            raise PermissionError(5, "Access is denied")
        key = MagicMock()
        key.where = where
        key.__enter__.return_value = key
        return key

    def enum_value(self, key, index):
        import winreg
        entries = list(self.values[key.where].items())
        if index >= len(entries):
            raise OSError("no more data")
        name, data = entries[index]
        return name, data, winreg.REG_SZ

    def delete_value(self, key, name):
        del self.values[key.where][name]

    def set_value(self, key, name, reserved, kind, data):
        self.values[key.where][name] = data

    def patched(self):
        import winreg
        return (
            patch.object(winreg, "OpenKey", side_effect=self.open_key),
            patch.object(winreg, "EnumValue", side_effect=self.enum_value),
            patch.object(winreg, "DeleteValue", side_effect=self.delete_value),
            patch.object(winreg, "SetValueEx", side_effect=self.set_value),
        )


class LauncherSettingTests(unittest.TestCase):
    """Rose's ltk_launcher.exe set to run as administrator: Windows refused the
    copy of it that gives LTK Manager explorer.exe as its parent (error 740),
    and the patcher refused every overlay (VRF00000007). Rose takes the
    setting off itself"""

    LAUNCHER = r"C:\Program Files\Rose\_internal\injection\tools\ltk_launcher.exe"
    OLD_LAUNCHER = r"C:\Rose\_internal\injection\tools\ltk_launcher.exe"
    ROSE = r"C:\Program Files\Rose\Rose.exe"
    KEY = windows_account.COMPAT_LAYERS_KEY

    def clear(self, registry, desktop_sid=None):
        first, second, third, fourth = registry.patched()
        with first, second, third, fourth, \
                patch.object(windows_account, "desktop_user_sid", return_value=desktop_sid):
            return windows_account.clear_launcher_run_as_admin()

    def test_only_the_run_as_administrator_layer_goes(self):
        self.assertIsNone(windows_account.without_run_as_admin("~ RUNASADMIN"))
        self.assertIsNone(windows_account.without_run_as_admin("$ runasadmin"))
        self.assertEqual(windows_account.without_run_as_admin("$ RUNASADMIN WIN8RTM"), "$ WIN8RTM")
        self.assertEqual(windows_account.without_run_as_admin("~ HIGHDPIAWARE RUNASADMIN"), "~ HIGHDPIAWARE")

    def test_the_launchers_setting_is_taken_off_and_nothing_else(self):
        """The user's own settings stay: Rose.exe's, and LTK Manager's (Rose
        only names those, they are not its programs)"""
        import winreg
        hkcu, hklm = (winreg.HKEY_CURRENT_USER, self.KEY), (winreg.HKEY_LOCAL_MACHINE, self.KEY)
        ltk_manager = r"C:\Program Files\LTK Manager\ltk-manager.exe"
        registry = FakeRegistry({
            hkcu: {self.LAUNCHER: "~ RUNASADMIN", self.ROSE: "~ RUNASADMIN"},
            hklm: {self.OLD_LAUNCHER: "$ RUNASADMIN WIN8RTM", ltk_manager: "$ RUNASADMIN"},
        })

        cleared, left = self.clear(registry)

        self.assertEqual(cleared, [("HKCU", self.LAUNCHER), ("HKLM", self.OLD_LAUNCHER)])
        self.assertEqual(left, [])
        self.assertEqual(registry.values[hkcu], {self.ROSE: "~ RUNASADMIN"})
        self.assertEqual(registry.values[hklm], {self.OLD_LAUNCHER: "$ WIN8RTM", ltk_manager: "$ RUNASADMIN"})

    def test_the_desktop_users_setting_goes_when_rose_runs_as_another_account(self):
        """A standard account elevated with an administrator's password: Rose's
        HKEY_CURRENT_USER is the administrator's, the user's setting is in
        their own hive"""
        import winreg
        sid = "S-1-5-21-163208246-3233954084-627669836-1001"
        desktop = (winreg.HKEY_USERS, f"{sid}\\{self.KEY}")
        registry = FakeRegistry({desktop: {self.LAUNCHER: "~ RUNASADMIN"}})

        cleared, left = self.clear(registry, desktop_sid=sid)

        self.assertEqual(cleared, [("HKU", self.LAUNCHER)])
        self.assertEqual(registry.values[desktop], {})
        self.assertIn(desktop, registry.opened)

    def test_a_setting_rose_cannot_change_is_left_and_named(self):
        import winreg
        hklm = (winreg.HKEY_LOCAL_MACHINE, self.KEY)
        registry = FakeRegistry({hklm: {self.LAUNCHER: "$ RUNASADMIN"}}, read_only=[hklm])

        cleared, left = self.clear(registry)

        self.assertEqual((cleared, left), ([], [("HKLM", self.LAUNCHER)]))
        self.assertEqual(registry.values[hklm], {self.LAUNCHER: "$ RUNASADMIN"})

    def check(self, cleared, left):
        with patch.object(windows_account, "clear_launcher_run_as_admin", return_value=(cleared, left)), \
                patch("utils.core.issue_reporter.report_issue") as report, \
                patch("utils.core.issue_reporter.remove_issues") as remove:
            result = windows_account.check_launcher_settings()
        return result, report, remove

    def test_a_setting_taken_off_is_logged_and_clears_the_warning(self):
        with self.assertLogs(windows_account.log.name, level="INFO") as logs:
            result, report, remove = self.check([("HKCU", self.LAUNCHER)], [])

        self.assertFalse(result)
        report.assert_not_called()
        line = f"{windows_account.LAUNCHER_SETTING_MESSAGE} ({self.LAUNCHER})."
        self.assertTrue(remove.call_args.args[0](f"Nov 16 16:15 | {line}", ""))
        self.assertTrue(any("Took \"Run as administrator\" off" in entry and self.LAUNCHER in entry
                            for entry in logs.output))

    def test_troubleshooting_names_a_setting_rose_could_not_take_off(self):
        result, report, _ = self.check([], [("HKLM", self.LAUNCHER)])

        self.assertTrue(result)
        code, severity, message = report.call_args.args
        self.assertEqual((code, severity), ("LAUNCHER_ELEVATED", "error"))
        (summary,) = summarize((message, report.call_args.kwargs["hint"]))
        self.assertEqual(summary["code"], "LAUNCHER_ELEVATED")
        self.assertEqual(summary["detail"], f"{self.LAUNCHER} [all users]")

    def test_an_unreadable_registry_never_stops_rose(self):
        with patch.object(windows_account, "clear_launcher_run_as_admin", side_effect=OSError("no registry")), \
                patch("utils.core.issue_reporter.report_issue") as report:
            self.assertFalse(windows_account.check_launcher_settings())
        report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
