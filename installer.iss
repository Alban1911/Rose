; Rose Installer Script for Inno Setup
; This creates a proper Windows installer that registers the app

#define MyAppName "Rose"
#define MyAppVersion "1.1.11"
#define MyAppVersionInfo "1.1.11.0"
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
OutputBaseFilename=Rose_Setup
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
Source: "dist\Rose\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\icon.ico"
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon; IconFilename: "{app}\icon.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}} (as Administrator)"; Flags: nowait postinstall skipifsilent shellexec; Verb: runas

[UninstallRun]
; Uninstall Pengu Loader (removes d3d9.dll hook from the League directory)
Filename: "{localappdata}\Rose\Pengu Loader\Pengu Loader.exe"; Parameters: "--uninstall --silent"; Flags: runhidden waituntilterminated skipifdoesntexist
; Always remove the Rose auto-start scheduled task (created via schtasks /TN "Rose")
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN Rose /F"; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\injection\overlay"
Type: filesandordirs; Name: "{app}\injection\mods"
; Remove user data stored in AppData
; Rose stores user data in %LOCALAPPDATA%\Rose
Type: filesandordirs; Name: "{localappdata}\Rose"
; Note: State files are now stored in user data directory, not in app directory

[Code]
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

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
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

procedure _DeleteLocalAppDataRose();
begin
  { Ensure user data is removed before running external cleanup }
  DelTree(ExpandConstant('{localappdata}\Rose'), True, True, True);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    _CleanupStartupRegistry();
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    _DeleteLocalAppDataRose();
    { Remove the entire install directory (Program Files\Rose) in case
      runtime-generated files (logs, caches, etc.) were left behind. }
    DelTree(ExpandConstant('{app}'), True, True, True);
  end;
end;
