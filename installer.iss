; Rose Installer Script for Inno Setup
; This creates a proper Windows installer that registers the app

#define MyAppName "Rose"
#define MyAppVersion "1.5.6"
#define MyAppVersionInfo "1.5.6.0"
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

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\injection\overlay"
Type: filesandordirs; Name: "{app}\injection\mods"
; %LOCALAPPDATA%\Rose is not listed here: whether it survives is a checkbox on
; the uninstaller page, see _KeepUserData() in [Code] ([UninstallDelete] checks
; run at install time, not when the user answers)

[Code]
var
  { The uninstaller's keep-data checkbox. Left nil in silent mode. }
  KeepUserDataBox: TNewCheckBox;

function _UserDataFolder(): String;
begin
  { Rose stores user data in %LOCALAPPDATA%\Rose }
  Result := ExpandConstant('{localappdata}\Rose');
end;

function _KeepUserData(): Boolean;
begin
  { No page means a silent uninstall, which removes Rose completely as it
    always did: only a user who ticks the box keeps their data. }
  Result := (KeepUserDataBox <> nil) and KeepUserDataBox.Checked;
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
  IntroText.Caption := 'Your settings, skin history and downloaded skins are kept unless you untick this.';

  KeepUserDataBox := TNewCheckBox.Create(UninstallProgressForm);
  KeepUserDataBox.Parent := Page;
  KeepUserDataBox.Left := Left0;
  KeepUserDataBox.Top := Top0 + ScaleY(48);
  KeepUserDataBox.Width := Width0;
  KeepUserDataBox.Caption := 'Keep my data in ' + _UserDataFolder();
  KeepUserDataBox.Checked := True;

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

{ Rose turns its hook off when it exits, so a crash or shutdown leaves it on,
  pointing at the core.dll copy in the desktop user's %LOCALAPPDATA%\Rose\Pengu Loader.
  The bundled loader's --uninstall only removes a hook on its own copy, and that
  folder survives an uninstall that keeps the user's data, so remove Rose's hook here. }
procedure _RemoveRosePenguIfeo();
var
  Debugger: string;
begin
  if not RegQueryStringValue(HKLM, IfeoKey, 'Debugger', Debugger) then
    exit;
  { The elevated uninstaller's localappdata can be another account's, so match
    the folder names rather than the full path. }
  if _ContainsTextLower(Debugger, '\rose\pengu loader\core.dll"') or
     _ContainsTextLower(Debugger, '"' + LowerCase(ExpandConstant('{app}\_internal\Pengu Loader\core.dll')) + '"') then
    RegDeleteValue(HKLM, IfeoKey, 'Debugger');
end;

const
  LegacyUninstallKey = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}';

procedure _CleanupLegacyUninstallEntry();
var
  InstallLocation: string;
  DisplayName: string;
  Publisher: string;
begin
  { Inno owns the AppId-based Apps entry. Remove only our duplicate from older
    installers, and only when it belongs to this installation. }
  if RegQueryStringValue(HKLM, LegacyUninstallKey, 'InstallLocation', InstallLocation) and
     RegQueryStringValue(HKLM, LegacyUninstallKey, 'DisplayName', DisplayName) and
     RegQueryStringValue(HKLM, LegacyUninstallKey, 'Publisher', Publisher) and
     (CompareText(AddBackslash(InstallLocation), AddBackslash(ExpandConstant('{app}'))) = 0) and
     (DisplayName = '{#MyAppName}') and (Publisher = '{#MyAppPublisher}') then
  begin
    RegDeleteKeyIncludingSubkeys(HKLM, LegacyUninstallKey);
  end;
end;

procedure _DeleteLocalAppDataRose();
begin
  { Ensure user data is removed before running external cleanup }
  DelTree(_UserDataFolder(), True, True, True);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    _CleanupStartupRegistry();
    _CleanupLegacyUninstallEntry();
    { Only Rose's data names the mods Rose added to LTK Manager's library:
      remove them while Rose is still here to do it. Kept data keeps them.
      Not in [UninstallRun], whose Check: is evaluated at install time. }
    if not _KeepUserData then
    begin
      Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--remove-ltk-mods', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      if (ResultCode <> 0) and not UninstallSilent then
        MsgBox(
          '{#MyAppName} could not finish cleaning up LTK Manager.'#13#10 +
          'Some of your LTK Manager mods may still be turned off: turn them back on in LTK Manager.',
          mbInformation,
          MB_OK
        );
    end;
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    if not _KeepUserData then
      _DeleteLocalAppDataRose();
    { Inno removes installed files; a shared/custom install root may also
      contain unrelated files. Remove the root only when it is empty. }
    RemoveDir(ExpandConstant('{app}'));
    _RemoveRosePenguIfeo();
    { Safety net if Pengu's own --uninstall could not run }
    _RemoveDeadPenguIfeo();
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { Clean up a dead hook left by an older Rose uninstall }
    _RemoveDeadPenguIfeo();

    _CleanupLegacyUninstallEntry();
  end;
end;
