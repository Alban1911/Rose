import re
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'installer.iss'


class InstallerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.script = SCRIPT.read_text(encoding='utf-8-sig')

    def test_uninstall_never_recursively_deletes_the_install_root(self):
        self.assertNotRegex(self.script, r"(?is)DelTree\s*\(\s*ExpandConstant\s*\(\s*'\{app\}[\\/]?'\s*\)")
        self.assertNotRegex(self.script, r'(?im)^\s*Type:\s*filesandordirs\s*;\s*Name:\s*"\{app\}[\\/]?"')
        self.assertRegex(self.script, r"RemoveDir\s*\(\s*ExpandConstant\s*\(\s*'\{app\}'\s*\)\s*\)")

    def test_installed_files_and_existing_hook_cleanup_remain_registered(self):
        for entry in ('recursesubdirs createallsubdirs', 'injection\\overlay',
                      'injection\\mods', '--uninstall --silent', '/Delete /TN Rose /F',
                      '_CleanupStartupRegistry();', '_RemoveDeadPenguIfeo();'):
            self.assertIn(entry, self.script)
        self.assertRegex(self.script, r'(?m)^AppId=\{\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890\}\}')

    def test_inno_owns_the_apps_entry_and_legacy_cleanup_is_guarded(self):
        self.assertNotRegex(self.script, r'(?i)RegWrite(?:String|DWord)Value\s*\(')
        match = re.search(r'(?s)procedure _CleanupLegacyUninstallEntry\(\);(.*?)(?=\nprocedure |\Z)', self.script)
        self.assertIsNotNone(match, 'legacy duplicate entry needs an ownership-checked migration')
        body = match.group(1)
        for value in ("'InstallLocation'", "'DisplayName'", "'Publisher'"):
            self.assertIn(value, body)
        self.assertRegex(body, r'(?s)if .*?then\s+begin\s+RegDeleteKeyIncludingSubkeys\(HKLM, LegacyUninstallKey\)')
        self.assertIn("ExpandConstant('{app}')", body)
        self.assertEqual(self.script.count('_CleanupLegacyUninstallEntry();'), 3)

    def test_roses_ltk_mods_are_removed_before_its_files_unless_the_data_is_kept(self):
        """[UninstallRun]'s Check: is evaluated at install time, before the
        user answers the keep-data checkbox: the cleanup runs from [Code]"""
        match = re.search(r'(?s)procedure CurUninstallStepChanged\(.*?\nend;', self.script)
        self.assertIsNotNone(match)
        step = re.search(r'(?s)if CurUninstallStep = usUninstall then\s+begin(.*?)\n  end;', match.group(0))
        self.assertIsNotNone(step, 'the cleanup runs under usUninstall, before the files are deleted')
        self.assertRegex(
            step.group(1),
            r"(?s)if not _KeepUserData then\s+begin\s+Exec\(ExpandConstant\('\{app\}\\\{#MyAppExeName\}'\), "
            r"'--remove-ltk-mods', '', SW_HIDE, ewWaitUntilTerminated, ResultCode\);",
        )
        self.assertEqual(self.script.count('--remove-ltk-mods'), 1)
        uninstall_run = re.search(r'(?s)\n\[UninstallRun\](.*?)\n\[', self.script)
        self.assertNotIn('remove-ltk-mods', uninstall_run.group(1))

    def test_a_cleanup_that_failed_tells_the_user_their_mods_may_be_off(self):
        """Rose's record of the user's LTK Manager mods it turned off goes
        with its data: a failed cleanup says so, unless nobody is watching"""
        step = re.search(r"(?s)if not _KeepUserData then\s+begin(.*?)\n    end;", self.script)
        self.assertIsNotNone(step)
        self.assertRegex(
            step.group(1),
            r"(?s)'--remove-ltk-mods'.*?;\s+(?:\{[^}]*\}\s+)?if \(ResultCode <> 0\) and not UninstallSilent then\s+"
            r"MsgBox\(.*?turn them back on in LTK Manager.*?MB_OK\s*\);",
        )
