; Rose Installer Script for Inno Setup
; This creates a proper Windows installer that registers the app

#define MyAppName "Rose"
#define MyAppVersion "1.4.9"
#define MyAppVersionInfo "1.4.9.0"
#define MyAppPublisher "Rose Team"
#define MyAppURL "https://github.com/Alban1911/Rose"
#define MyAppExeName "Rose.exe"
#define MyAppDescription "Effortless skin changer for League of Legends"
; Must match config.SINGLE_INSTANCE_MUTEX_NAME (used by the app to enforce single-instance)
#define MyAppMutex "Local\RoseSingleInstance"

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
; Do not use the same AppId value in installers for other applications.
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installer
OutputBaseFilename=Rose_Setup_{#MyAppVersion}
SetupIconFile=assets\icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersionInfo}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppDescription}
VersionInfoProductName={#MyAppName}
; Prevent install/uninstall while Rose is running (mutex is created by the running app)
AppMutex={#MyAppMutex}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode
; Restore the patcher files a previous uninstall saved. Hidden when there is no
; backup, so it never shows an option that would do nothing; see
; _ShouldOfferLtkRestore() in [Code].
Name: "restoreltk"; Description: "Restore the LTK patcher files saved by a previous uninstall"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; Check: _ShouldOfferLtkRestore

[Files]
; Main application files
; hashes.game.txt is user-managed and must be preserved across installations.
Source: "dist\Rose\*"; DestDir: "{app}"; Excludes: "injection\tools\hashes.game.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\icon.ico"
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon; IconFilename: "{app}\icon.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}} (as Administrator)"; Flags: nowait postinstall skipifsilent shellexec; Verb: runas

[UninstallRun]
; Uninstall Pengu Loader (removes its IFEO activation and disables the native hook)
Filename: "{app}\_internal\Pengu Loader\Pengu Loader.exe"; Parameters: "--uninstall --silent"; Flags: runhidden waituntilterminated skipifdoesntexist
; Always remove the Rose auto-start scheduled task (created via schtasks /TN "Rose")
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN Rose /F"; Flags: runhidden

; NOTE: there is deliberately no [UninstallDelete] entry for {app} here.
; "Source: dist\Rose\*" with recursesubdirs records the whole tree, and Inno
; fails the uninstall with "location not accessible" when a recorded directory
; still holds a file it never recorded -- the user's own ltk_patcher binaries
; and the excluded hashes.game.txt. DelTree() in CurUninstallStepChanged
; removes {app} leftovers, user files included, instead.
;
; %LOCALAPPDATA%\Rose is also not listed here: whether it survives is a
; checkbox on the uninstaller page, see _DeleteUserData() in [Code].
; Note: State files are now stored in user data directory, not in app directory

[Code]
var
  { The uninstaller's keep-data page. Left nil in silent mode. }
  KeepUserDataBox: TNewCheckBox;
  BackupLtkToolsBox: TNewCheckBox;
  { One line per file, built while copying so the user is told what really
    happened instead of assuming the promised backup exists. }
  LtkBackupReport: String;

const
  LtkBackupFolderName = 'LtkPatcher';
  LtkHostFileName = 'ltk_patcher_host.exe';
  LtkDllFileName = 'ltk_patcher_dll.dll';

function _UserDataFolder(): String;
begin
  { Rose stores user data in %LOCALAPPDATA%\Rose }
  Result := ExpandConstant('{localappdata}\Rose');
end;

function _LtkBackupFolder(): String;
begin
  Result := _UserDataFolder() + '\' + LtkBackupFolderName;
end;

{ PyInstaller onedir ships the tools under _internal (see
  launcher/update/update_installer.py); the bare path is the layout older
  installs still carry, and hash_updater.py looks in both. }
function _LtkToolPath(const FileName: String): String;
begin
  if FileExists(ExpandConstant('{app}\_internal\injection\tools\') + FileName) then
    Result := ExpandConstant('{app}\_internal\injection\tools\') + FileName
  else
    Result := ExpandConstant('{app}\injection\tools\') + FileName;
end;

{ Where a restored file has to be written. Unlike _LtkToolPath, which looks
  for a file that is already there, this has to decide by folder: during a
  restore the file does not exist yet, so the check above would pick the bare
  path and drop it outside _internal, where the patcher host would not see it. }
function _LtkToolsDir(): String;
begin
  if DirExists(ExpandConstant('{app}\_internal\injection\tools')) then
    Result := ExpandConstant('{app}\_internal\injection\tools')
  else
    Result := ExpandConstant('{app}\injection\tools');
end;

{ Rose does not ship the patcher binaries, so an install may have neither or
  only one of them. There is nothing to offer a checkbox for in that case. }
function _HasLtkFiles(): Boolean;
begin
  Result := FileExists(_LtkToolPath(LtkHostFileName)) or
            FileExists(_LtkToolPath(LtkDllFileName));
end;

{ A previous uninstall left copies behind. They are only worth offering when
  the install does not already ship the files, so restoring stays a choice
  rather than something that silently overwrites. }
function _ShouldOfferLtkRestore(): Boolean;
begin
  Result := (FileExists(_LtkBackupFolder() + '\' + LtkHostFileName) or
             FileExists(_LtkBackupFolder() + '\' + LtkDllFileName)) and
            not _HasLtkFiles();
end;

{ Put a saved patcher file back where the patcher host expects to find it. }
procedure _RestoreLtkFile(const FileName: String);
var
  Source, ToolsDir: String;
begin
  Source := _LtkBackupFolder() + '\' + FileName;
  if not FileExists(Source) then
    Exit;

  ToolsDir := _LtkToolsDir();
  if not DirExists(ToolsDir) then
    CreateDir(ToolsDir);
  FileCopy(Source, ToolsDir + '\' + FileName, False);
end;

procedure _RestoreLtkFiles();
begin
  _RestoreLtkFile(LtkHostFileName);
  _RestoreLtkFile(LtkDllFileName);
end;

{ The patcher binaries come from the user's own LTK Manager install and cannot
  be downloaded again, so copy them out before Inno removes them. Rose does not
  ship them, so a missing file is normal and is reported, not treated as an
  error. }
procedure _AddLtkReportLine(const Line: String);
begin
  if LtkBackupReport <> '' then
    LtkBackupReport := LtkBackupReport + #13#10;
  LtkBackupReport := LtkBackupReport + Line;
end;

procedure _BackupLtkFile(const FileName: String);
var
  Source: String;
begin
  Source := _LtkToolPath(FileName);

  if not FileExists(Source) then
  begin
    _AddLtkReportLine(FileName + ': not in the install folder, nothing to copy');
    Exit;
  end;

  { CreateDir only makes the last level, so make sure the parent is there }
  if not DirExists(_UserDataFolder()) then
    CreateDir(_UserDataFolder());
  CreateDir(_LtkBackupFolder());

  if FileCopy(Source, _LtkBackupFolder() + '\' + FileName, False) then
    _AddLtkReportLine(FileName + ': saved')
  else
    _AddLtkReportLine(FileName + ': COULD NOT BE COPIED');
end;

{ A tick that promises a backup and silently makes none is the worst outcome
  here, so every file gets a line saying what happened to it. }
procedure _ReportLtkBackup();
var
  Message: String;
  Failed: Boolean;
begin
  if LtkBackupReport = '' then
    Exit;

  Failed := Pos('COULD NOT BE COPIED', LtkBackupReport) > 0;
  Message := 'LTK patcher backup:' + #13#10 + LtkBackupReport + #13#10#13#10 +
             'Saved to: ' + _LtkBackupFolder();

  if Failed then
  begin
    Message := Message + #13#10#13#10 +
               'Anything marked COULD NOT BE COPIED is deleted with the install. ' +
               'Close a running patcher or antivirus scan and uninstall again.';
  end
  else if Pos(': saved', LtkBackupReport) = 0 then
  begin
    Message := Message + #13#10#13#10 +
               'Neither file was in the install folder, so nothing was saved.';
  end;

  if Failed then
    MsgBox(Message, mbError, MB_OK)
  else
    MsgBox(Message, mbInformation, MB_OK);
end;

function _KeepUserData(): Boolean;
begin
  { No page means a silent uninstall: keep everything. }
  Result := (KeepUserDataBox = nil) or KeepUserDataBox.Checked;
end;

function _BackupLtkTools(): Boolean;
begin
  { No checkbox means nothing to back up: no files, or a silent uninstall. }
  Result := (BackupLtkToolsBox <> nil) and BackupLtkToolsBox.Checked;
end;

{ Deletes the user data folder. A backup the user asked for survives even when
  the rest is deleted; one they turned off goes with everything else. }
procedure _DeleteUserData();
var
  FindRec: TFindRec;
  Root, Item: String;
  IsBackup: Boolean;
begin
  Root := _UserDataFolder();
  if not DirExists(Root) then
    Exit;

  if FindFirst(Root + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          IsBackup := CompareText(FindRec.Name, LtkBackupFolderName) = 0;
          if not (IsBackup and _BackupLtkTools) then
          begin
            Item := Root + '\' + FindRec.Name;
            if DirExists(Item) then
              DelTree(Item, True, True, True)
            else
              DeleteFile(Item);
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

{ Inno Setup cannot add wizard pages to the uninstaller, so the only way to
  offer a checkbox is to borrow the progress form's notebook for one step. }
procedure InitializeUninstallProgressForm();
var
  Page: TNewNotebookPage;
  IntroText: TNewStaticText;
  UninstallButton: TNewButton;
  SavedPageName, SavedPageDescription: String;
  SavedCancelEnabled: Boolean;
  SavedCancelModalResult: Integer;
  SavedCancelLeft: Integer;
  Top0, Left0, Width0: Integer;
begin
  if UninstallSilent then
    Exit;

  Top0 := UninstallProgressForm.StatusLabel.Top;
  Left0 := UninstallProgressForm.StatusLabel.Left;
  Width0 := UninstallProgressForm.StatusLabel.Width;

  SavedPageName := UninstallProgressForm.PageNameLabel.Caption;
  SavedPageDescription := UninstallProgressForm.PageDescriptionLabel.Caption;
  SavedCancelEnabled := UninstallProgressForm.CancelButton.Enabled;
  SavedCancelModalResult := UninstallProgressForm.CancelButton.ModalResult;

  Page := TNewNotebookPage.Create(UninstallProgressForm);
  Page.Notebook := UninstallProgressForm.InnerNotebook;
  Page.Parent := UninstallProgressForm.InnerNotebook;
  Page.Align := alClient;
  UninstallProgressForm.InnerNotebook.ActivePage := Page;

  IntroText := TNewStaticText.Create(UninstallProgressForm);
  IntroText.Parent := Page;
  IntroText.Left := Left0;
  IntroText.Top := Top0;
  IntroText.Width := Width0;
  IntroText.Height := ScaleY(36);
  IntroText.AutoSize := False;
  IntroText.ShowAccelChar := False;
  IntroText.Caption := 'Choose what to keep. Everything unchecked is deleted.';

  KeepUserDataBox := TNewCheckBox.Create(UninstallProgressForm);
  KeepUserDataBox.Parent := Page;
  KeepUserDataBox.Left := Left0;
  KeepUserDataBox.Top := Top0 + ScaleY(48);
  KeepUserDataBox.Width := Width0;
  KeepUserDataBox.Caption := 'Keep my data in ' + _UserDataFolder();
  KeepUserDataBox.Checked := True;

  { Only offer this when there is something in the install folder to copy. }
  if _HasLtkFiles() then
  begin
    BackupLtkToolsBox := TNewCheckBox.Create(UninstallProgressForm);
    BackupLtkToolsBox.Parent := Page;
    BackupLtkToolsBox.Left := Left0;
    BackupLtkToolsBox.Top := Top0 + ScaleY(80);
    BackupLtkToolsBox.Width := Width0;
    BackupLtkToolsBox.Caption := 'Save a copy of the LTK patcher files in ' + _LtkBackupFolder();
    BackupLtkToolsBox.Checked := True;
  end;

  { The uninstaller form only has a Cancel button, on the right. Take its spot
    for the button that continues and shift Cancel to the left of it. }
  UninstallButton := TNewButton.Create(UninstallProgressForm);
  UninstallButton.Parent := UninstallProgressForm;
  UninstallButton.Width := UninstallProgressForm.CancelButton.Width;
  UninstallButton.Height := UninstallProgressForm.CancelButton.Height;
  UninstallButton.Left := UninstallProgressForm.CancelButton.Left;
  UninstallButton.Top := UninstallProgressForm.CancelButton.Top;
  UninstallButton.Caption := 'Uninstall';
  UninstallButton.ModalResult := mrOK;
  UninstallButton.TabOrder := UninstallProgressForm.CancelButton.TabOrder;

  SavedCancelLeft := UninstallProgressForm.CancelButton.Left;
  UninstallProgressForm.CancelButton.Left :=
    SavedCancelLeft - UninstallButton.Width - ScaleX(10);
  UninstallProgressForm.CancelButton.TabOrder := UninstallButton.TabOrder + 1;

  UninstallProgressForm.PageNameLabel.Caption := 'Uninstall {#MyAppName}';
  UninstallProgressForm.PageDescriptionLabel.Caption :=
    'Tick the data you want to keep, then continue.';
  UninstallProgressForm.CancelButton.Enabled := True;
  UninstallProgressForm.CancelButton.ModalResult := mrCancel;

  if UninstallProgressForm.ShowModal = mrCancel then
    Abort;

  { Put the standard page back for the rest of the run. }
  UninstallButton.Visible := False;
  UninstallProgressForm.PageNameLabel.Caption := SavedPageName;
  UninstallProgressForm.PageDescriptionLabel.Caption := SavedPageDescription;
  UninstallProgressForm.CancelButton.Enabled := SavedCancelEnabled;
  UninstallProgressForm.CancelButton.ModalResult := SavedCancelModalResult;
  UninstallProgressForm.CancelButton.Left := SavedCancelLeft;
end;

function _IsLeagueRunning(): Boolean;
var
  WbemLocator, WMIService, Processes: Variant;
begin
  Result := False;
  try
    WbemLocator := CreateOleObject('WbemScripting.SWbemLocator');
    WMIService := WbemLocator.ConnectServer('localhost', 'root\CIMV2');
    Processes := WMIService.ExecQuery(
      'SELECT Name FROM Win32_Process WHERE ' +
      'Name="LeagueClient.exe" OR ' +
      'Name="LeagueClientUx.exe" OR ' +
      'Name="LeagueClientUxRender.exe" OR ' +
      'Name="League of Legends.exe"'
    );
    Result := (Processes.Count > 0);
  except
    { If WMI fails, don't block the uninstall }
    Result := False;
  end;
end;

function InitializeUninstall(): Boolean;
var
  RoseRunning: Boolean;
  LeagueRunning: Boolean;
begin
  RoseRunning := CheckForMutexes('{#MyAppMutex}');
  LeagueRunning := _IsLeagueRunning();

  if RoseRunning and LeagueRunning then
  begin
    MsgBox(
      '{#MyAppName} and League of Legends are both currently running.'#13#10 +
      'Please close both applications and try uninstalling again.',
      mbCriticalError,
      MB_OK
    );
    Result := False;
    exit;
  end;

  if RoseRunning then
  begin
    MsgBox(
      '{#MyAppName} is currently running.'#13#10 +
      'Please close it completely (including the tray) and try uninstalling again.',
      mbCriticalError,
      MB_OK
    );
    Result := False;
    exit;
  end;

  if LeagueRunning then
  begin
    MsgBox(
      'League of Legends is currently running.'#13#10 +
      'Please close League of Legends and try uninstalling again.',
      mbCriticalError,
      MB_OK
    );
    Result := False;
    exit;
  end;

  Result := True;
end;

function _ContainsTextLower(const Haystack: string; const NeedleLower: string): Boolean;
begin
  Result := Pos(NeedleLower, LowerCase(Haystack)) > 0;
end;

procedure _DeleteStartupValuesIfMatch(const RootKey: Integer; const SubKey: string);
var
  Names: TArrayOfString;
  I: Integer;
  Val: string;
  ValLower: string;
begin
  if not RegGetValueNames(RootKey, SubKey, Names) then
    exit;

  for I := 0 to GetArrayLength(Names) - 1 do
  begin
    if RegQueryStringValue(RootKey, SubKey, Names[I], Val) then
    begin
      ValLower := LowerCase(Val);

      { Remove legacy/broken startup entries that invoke rundll32 on Pengu Loader core.dll.
        This is what produces the RunDLL "module not found" dialog after uninstall. }
      if (_ContainsTextLower(ValLower, 'rundll32') and _ContainsTextLower(ValLower, 'pengu loader\core.dll')) or
         _ContainsTextLower(ValLower, '\rose\_internal\pengu loader\core.dll') then
      begin
        RegDeleteValue(RootKey, SubKey, Names[I]);
      end;
    end;
  end;
end;

const
  RunKey      = 'Software\Microsoft\Windows\CurrentVersion\Run';
  RunOnceKey  = 'Software\Microsoft\Windows\CurrentVersion\RunOnce';
  RunKey6432  = 'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run';
  RunOnce6432 = 'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce';

procedure _CleanupStartupRegistry();
begin
  { 64-bit and user/machine startup keys }
  _DeleteStartupValuesIfMatch(HKCU, RunKey);
  _DeleteStartupValuesIfMatch(HKLM, RunKey);
  _DeleteStartupValuesIfMatch(HKCU, RunOnceKey);
  _DeleteStartupValuesIfMatch(HKLM, RunOnceKey);

  { 32-bit view keys (defensive) }
  _DeleteStartupValuesIfMatch(HKCU, RunKey6432);
  _DeleteStartupValuesIfMatch(HKLM, RunKey6432);
  _DeleteStartupValuesIfMatch(HKCU, RunOnce6432);
  _DeleteStartupValuesIfMatch(HKLM, RunOnce6432);
end;

const
  IfeoKey = 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\LeagueClientUx.exe';

{ Pengu hooks the client with an IFEO debugger: rundll32 "<dir>\core.dll", #6000.
  If that core.dll is gone (Rose uninstalled or moved), Windows shows a RunDLL
  "module not found" error on every League start, so remove the dead entry.
  A working Pengu install elsewhere keeps its key. }
procedure _RemoveDeadPenguIfeo();
var
  Debugger: string;
  StartPos: Integer;
  Rest: string;
  EndPos: Integer;
  DllPath: string;
begin
  if not RegQueryStringValue(HKLM, IfeoKey, 'Debugger', Debugger) then
    exit;
  if not _ContainsTextLower(Debugger, 'core.dll') then
    exit;

  DllPath := '';
  StartPos := Pos('"', Debugger);
  if StartPos > 0 then
  begin
    Rest := Copy(Debugger, StartPos + 1, Length(Debugger));
    EndPos := Pos('"', Rest);
    if EndPos > 0 then
      DllPath := Copy(Rest, 1, EndPos - 1);
  end;

  if (DllPath = '') or not FileExists(DllPath) then
    RegDeleteKeyIncludingSubkeys(HKLM, IfeoKey);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    _CleanupStartupRegistry();

    { Inno has not removed the installed files yet, so this is the last point
      at which the user's own patcher binaries can be copied out. }
    if _BackupLtkTools then
    begin
      LtkBackupReport := '';
      _BackupLtkFile(LtkHostFileName);
      _BackupLtkFile(LtkDllFileName);
      _ReportLtkBackup();
    end;
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    if not _KeepUserData then
      _DeleteUserData();

    { Remove the entire install directory (Program Files\Rose) in case
      runtime-generated files (logs, caches, etc.) were left behind. }
    DelTree(ExpandConstant('{app}'), True, True, True);
    { Safety net if Pengu's own --uninstall could not run }
    _RemoveDeadPenguIfeo();
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { Put back the patcher files a previous uninstall saved, before anything
      reads them. [Files] has already unpacked the install by now. }
    if WizardIsTaskSelected('restoreltk') then
      _RestoreLtkFiles();

    { Clean up a dead hook left by an older Rose uninstall }
    _RemoveDeadPenguIfeo();

    // Create registry entries for Windows Apps list
    RegWriteStringValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}', 'DisplayName', '{#MyAppName}');
    RegWriteStringValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}', 'DisplayVersion', '{#MyAppVersion}');
    RegWriteStringValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}', 'Publisher', '{#MyAppPublisher}');
    RegWriteStringValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}', 'URLInfoAbout', '{#MyAppURL}');
    RegWriteStringValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}', 'InstallLocation', ExpandConstant('{app}'));
    RegWriteStringValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}', 'UninstallString', ExpandConstant('{uninstallexe}'));
    RegWriteDWordValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}', 'NoModify', 1);
    RegWriteDWordValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}', 'NoRepair', 1);
    RegWriteStringValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}', 'DisplayIcon', ExpandConstant('{app}\{#MyAppExeName}'));
  end;
end;
