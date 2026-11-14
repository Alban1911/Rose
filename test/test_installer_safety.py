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

    def test_uninstall_keeps_untracked_files_in_install_subdirectories(self):
        section = re.search(r'(?s)\n\[UninstallDelete\](.*?)\n\[', self.script).group(1)
        for directory in ('injection\\overlay', 'injection\\mods'):
            self.assertIn(f'Type: dirifempty; Name: "{{app}}\\{directory}"', section)
        # Only Rose's runtime, which an update replaces with files the uninstall log never saw
        self.assertEqual(re.findall(r'Type: filesandordirs; Name: "([^"]+)"', section), ['{app}\\_internal'])

    def test_installer_upgrades_replace_legacy_uninstall_actions(self):
        self.assertRegex(self.script, r'(?m)^UninstallLogMode=overwrite$')

    def test_installed_files_and_existing_hook_cleanup_remain_registered(self):
        for entry in ('recursesubdirs createallsubdirs', 'injection\\overlay',
                      'injection\\mods', '--uninstall --silent', '_RemoveRoseAutostartTask();',
                      '_CleanupStartupRegistry();', '_RemoveRosePenguIfeo(False);',
                      '_RemoveRosePenguIfeo(True);'):
            self.assertIn(entry, self.script)
        self.assertRegex(self.script, r'(?m)^AppId=\{\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890\}\}')

    def test_pengu_cleanup_checks_the_command_and_full_rose_dll_path(self):
        command = self._routine('_PenguCoreFromCommand')
        self.assertIn("CompareText(Launcher, 'rundll32')", command)
        self.assertIn("CompareText(Launcher, 'rundll32.exe')", command)
        self.assertIn("Trim(Copy(EntryPoint, 2, Length(EntryPoint))) = '#6000'", command)

        ownership = self._routine('_IsRosePenguCore')
        self.assertIn(r"CompareText(DllPath, ExpandConstant('{app}\_internal\Pengu Loader\core.dll'))", ownership)
        self.assertIn(r"CompareText(DllPath, _UserDataFolder() + '\Pengu Loader\core.dll')", ownership)
        self.assertIn(r"RegQueryStringValue(HKLM64, ProfileListKey + '\' + Profiles[I], 'ProfileImagePath'", ownership)
        self.assertIn(r"CompareText(DllPath, AddBackslash(ProfileDir) + 'AppData\Local\{#MyAppName}\Pengu Loader\core.dll')", ownership)
        self.assertNotIn('Pos(', ownership)
        self.assertRegex(
            self._routine('_RemoveRosePenguStartupValues'),
            r"(?s)DllPath := _PenguCoreFromCommand\(Val\);\s*if \(DllPath <> ''\) and _IsRosePenguCore\(DllPath\) then"
            r"\s*RegDeleteValue\(RootKey, SubKey, Names\[I\]\)",
        )

    def test_ifeo_cleanup_deletes_an_owned_or_dead_debugger_value(self):
        body = self._routine('_RemoveRosePenguIfeo')
        self.assertRegex(
            body,
            r"(?s)DllPath := _PenguCoreFromCommand\(Debugger\);\s*"
            r"if \(DllPath <> ''\) and\s*"
            r"\(\(not FileExists\(DllPath\)\) or \(\(not OnlyIfMissing\) and _IsRosePenguCore\(DllPath\)\)\) then\s*"
            r"RegDeleteValue\(HKLM64, IfeoKey, 'Debugger'\)",
        )
        self.assertNotRegex(self.script, r'(?i)RegDeleteKey\w*\([^,]+,\s*IfeoKey\)')

    def test_autostart_cleanup_checks_what_the_task_runs(self):
        body = self._routine('_RemoveRoseAutostartTask')
        self.assertIn('if Actions.Count <> 1 then', body)
        self.assertIn('ActionPath := Action.Path;', body)
        self.assertIn('Arguments := Action.Arguments;', body)
        self.assertIn('if not (VarIsNull(Arguments) or VarIsEmpty(Arguments)) then', body)
        self.assertRegex(
            body,
            r"(?s)if \(CompareText\(RemoveQuotes\(Trim\(ActionPath\)\), "
            r"ExpandConstant\('\{app\}\\\{#MyAppExeName\}'\)\) = 0\) and\s*"
            r"\(Trim\(ActionArguments\) = ''\) then\s*Folder.DeleteTask\('\{#MyAppName\}', 0\)",
        )
        self.assertNotIn('/Delete /TN Rose', self.script)

    def test_update_cleanup_requires_the_updater_marker_at_the_default_path(self):
        updater = (SCRIPT.parent / 'launcher' / 'update' / 'update_installer.py').read_text(encoding='utf-8')
        for updater_constant, installer_constant in (
            ('WORKSPACE_MARKER', 'UpdateMarkerName'),
            ('WORKSPACE_VERSION', 'UpdateMarkerVersion'),
        ):
            match = re.search(rf'(?m)^{updater_constant} = b?"([^"]+)"$', updater)
            self.assertIsNotNone(match, updater_constant)
            self.assertIn(f"{installer_constant} = '{match.group(1)}';", self.script)

        body = self._routine('_RemoveRoseUpdateWorkspace')
        self.assertIn(r"CompareText(Workspace, ExpandConstant('{autopf}\{#MyAppName}.update'))", body)
        self.assertIn('if not _IsPlainDirectoryPath(Workspace) then', body)
        self.assertIn('_GetFileAttributes(Marker) and (DirectoryAttribute or ReparsePointAttribute)', body)
        self.assertIn('Contents <> UpdateMarkerVersion', body)
        self.assertIn('Entry.Attributes and ReparsePointAttribute', body)
        self.assertIn('_RemoveRoseUpdateWorkspace();', self._routine('CurUninstallStepChanged'))

    def test_update_cleanup_preserves_nonempty_recovery_snapshots(self):
        body = self._routine('_RemoveRoseUpdateWorkspace')
        self.assertNotRegex(body, r'(?i)\bDelTree\b')
        self.assertIn("(Name <> 'staging') and (Name <> 'previous') and (Name <> 'failed')", body)
        self.assertRegex(
            body,
            r'(?s)if not RemoveDir\(Folders\[I\]\) then\s*begin\s*Log\(.*?\);\s*exit;\s*end;\s*'
            r'for I := 0 to Files.Count - 1 do\s*if not DeleteFile\(Files\[I\]\)',
        )

    def _routine(self, name):
        match = re.search(rf'(?ms)^(?:function|procedure) {name}\(.*?^end;', self.script)
        self.assertIsNotNone(match, name)
        return match.group(0)

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
