# Task: Port Rose’s Pengu clone to current official Pengu activation behavior

## Objective

Update the vendored C# Pengu Loader in `Alban1911/Rose` so that its **Windows activation, deactivation, elevation, registry access, status detection, error reporting, and logging behavior** match the current official `PenguLoader/PenguLoader` implementation as closely as possible.

Keep the existing Rose-specific UI, CLI commands, plugins, datastore handling, `config.ini` handling, session recovery, and League restart integration.

Do **not** replace the entire C# loader with the upstream Rust/Tauri application. Port only the relevant Windows activation semantics.

Use this official upstream implementation as the pinned reference:

* Commit: `f635604762019e683bbef658ec232abb667772fa`
* `loader/src-tauri/src/windows/mod.rs`
* `loader/src-tauri/src/windows/mod_ifeo.rs`

The official implementation:

* Runs normally without elevation.
* Elevates a child process only for install/uninstall.
* Opens the IFEO parent with `KEY_CREATE_SUB_KEY`.
* Creates/opens the target with `KEY_SET_VALUE`.
* Writes the `Debugger` value.
* Deletes only the `Debugger` value during deactivation.
* Returns errors with an activation stage and error kind.

---

# Current Rose behavior that must change

Relevant existing files:

```text
vendor/PenguLoader-1.1.6/loader/Program.cs
vendor/PenguLoader-1.1.6/loader/Main/IFEO.cs
vendor/PenguLoader-1.1.6/loader/Main/Module.cs
vendor/PenguLoader-1.1.6/loader/Main/Logger.cs
vendor/PenguLoader-1.1.6/loader/Properties/App.manifest
utils/integration/pengu_loader.py
test/test_pengu_loader.py
scripts/build_pengu_loader.py
```

Current problems:

1. `App.manifest` uses `requireAdministrator`, so every loader invocation is elevated.
2. `IFEO.SetDebugger()` uses:

```csharp
Registry.LocalMachine.CreateSubKey(path, true)
```

This requests broader .NET registry permissions instead of the specific access rights used by official Pengu.
3. Deactivation calls `DeleteSubKeyTree()`, deleting the entire `LeagueClientUx.exe` IFEO key rather than only the `Debugger` value.
4. Activation status compares the full debugger command string instead of extracting and comparing the DLL path.
5. The debugger string currently contains a trailing space:

```csharp
$"rundll32 \"{ModulePath}\", #6000 "
```

The official format has no trailing space.
6. Expected registry failures are currently surfaced as generic exceptions rather than structured activation-stage failures.
7. The Python wrapper currently sends duplicate aliases such as:

```text
--install --activate --silent
```

and:

```text
--uninstall --deactivate --silent
```

Official-style invocation should use one command only.

---

# Required architecture

Add these files unless equivalent abstractions already exist:

```text
vendor/PenguLoader-1.1.6/loader/Main/ActivationResult.cs
vendor/PenguLoader-1.1.6/loader/Main/Win32Registry.cs
vendor/PenguLoader-1.1.6/loader/Main/Elevation.cs
```

Refactor:

```text
Main/IFEO.cs
Main/Module.cs
Program.cs
Properties/App.manifest
Main/Logger.cs
utils/integration/pengu_loader.py
test/test_pengu_loader.py
```

Before changing a public or internal method signature, search all call sites in the repository.

Do not break the WPF loader UI or the Python integration.

---

# Phase 1: Add structured activation results

Create an explicit activation stage enum matching upstream names and ordering:

```csharp
internal enum ActivationStage : byte
{
    None = 0,
    OpenIFEO = 1,
    CreateTarget = 2,
    SetDebugger = 3,
    DeleteDebugger = 4,
    GetLeaguePath = 5,
    CreateSymlink = 6,
    DeleteSymlink = 7,
    RunElevated = 8
}
```

Create a stable C# error-kind enum:

```csharp
internal enum ActivationErrorKind : byte
{
    None = 0,
    NotFound = 1,
    PermissionDenied = 2,
    AlreadyExists = 3,
    InvalidInput = 4,
    Cancelled = 5,
    Other = 255
}
```

Create an immutable `ActivationResult` containing:

```csharp
bool Succeeded
ActivationStage Stage
ActivationErrorKind ErrorKind
int NativeErrorCode
string NativeErrorMessage
```

Required helpers:

```csharp
ActivationResult Success()
ActivationResult Failure(
    ActivationStage stage,
    ActivationErrorKind errorKind,
    int nativeErrorCode,
    string nativeErrorMessage)

int EncodeExitCode()
static ActivationResult DecodeExitCode(int exitCode)
string ToOfficialStyleString()
```

Exit-code format:

```csharp
success: 0
failure: ((int)Stage << 8) | (int)ErrorKind
```

Expected formatted error:

```text
SetDebugger (permission_denied)
```

The native Win32 error code does not need to survive the child-process exit code, but it must be written to the child’s log before exit.

Create one function that maps Win32 errors:

```csharp
5    -> PermissionDenied
2    -> NotFound
3    -> NotFound
87   -> InvalidInput
183  -> AlreadyExists
1223 -> Cancelled
other -> Other
```

Do not depend on exception message text for classification.

---

# Phase 2: Replace .NET registry writes with exact Win32 access rights

## New native registry layer

In `Main/Win32Registry.cs`, wrap these APIs from `advapi32.dll`:

```text
RegOpenKeyExW
RegCreateKeyExW
RegQueryValueExW
RegSetValueExW
RegDeleteValueW
RegCloseKey
```

Use `SetLastError = true` and Unicode entry points.

Required constants:

```csharp
private static readonly UIntPtr HKEY_LOCAL_MACHINE =
    new UIntPtr(0x80000002u);

private const int ERROR_SUCCESS = 0;
private const int ERROR_FILE_NOT_FOUND = 2;
private const int ERROR_PATH_NOT_FOUND = 3;

private const uint KEY_QUERY_VALUE = 0x0001;
private const uint KEY_SET_VALUE = 0x0002;
private const uint KEY_CREATE_SUB_KEY = 0x0004;

private const uint REG_OPTION_NON_VOLATILE = 0x00000000;
private const uint REG_SZ = 1;

private const uint REG_CREATED_NEW_KEY = 1;
private const uint REG_OPENED_EXISTING_KEY = 2;
```

Do not request:

```text
KEY_ALL_ACCESS
KEY_WRITE
WRITE_DAC
WRITE_OWNER
DELETE
KEY_CREATE_LINK
```

Do not use the old writable `RegistryKey.CreateSubKey()` path for activation.

Do not use `Registry.LocalMachine.DeleteSubKeyTree()`.

Close every native handle in `finally`, including partial-failure paths.

## Activation algorithm

Use:

```text
HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\
Image File Execution Options
```

Target:

```text
LeagueClientUx.exe
```

Implement this exact sequence:

### Stage `OpenIFEO`

```csharp
RegOpenKeyExW(
    HKEY_LOCAL_MACHINE,
    IFEO_PATH,
    0,
    KEY_CREATE_SUB_KEY,
    out ifeoHandle)
```

On failure, return:

```text
Stage = OpenIFEO
NativeErrorCode = RegOpenKeyExW result
```

### Stage `CreateTarget`

```csharp
RegCreateKeyExW(
    ifeoHandle,
    "LeagueClientUx.exe",
    0,
    null,
    REG_OPTION_NON_VOLATILE,
    KEY_SET_VALUE,
    IntPtr.Zero,
    out targetHandle,
    out disposition)
```

On failure:

```text
Stage = CreateTarget
```

Log whether the key was created or already existed.

### Stage `SetDebugger`

Write a UTF-16 `REG_SZ` including its null terminator:

```text
rundll32 "<absolute core.dll path>", #6000
```

Exact C# format:

```csharp
$"rundll32 \"{modulePath}\", #6000"
```

There must be no trailing space.

Use:

```csharp
var bytes = Encoding.Unicode.GetBytes(value + "\0");
```

Then:

```csharp
RegSetValueExW(
    targetHandle,
    "Debugger",
    0,
    REG_SZ,
    bytes,
    (uint)bytes.Length)
```

On failure:

```text
Stage = SetDebugger
```

Do not continue into config writes when the registry operation failed.

---

# Phase 3: Match official deactivation behavior

Deactivation must never delete the entire target key.

Open:

```text
HKLM\...\Image File Execution Options\LeagueClientUx.exe
```

with exactly:

```text
KEY_SET_VALUE
```

Call:

```csharp
RegDeleteValueW(targetHandle, "Debugger")
```

Return a `DeleteDebugger` failure for any unexpected error.

Because `Module.SetActive(false)` already checks whether the loader is inactive before mutating state, a missing value should normally not reach this operation. Still handle race conditions safely:

* `ERROR_FILE_NOT_FOUND` for the target key or value may be treated as successful deactivation.
* Log it as an idempotent no-op.
* Do not delete the target key.

Preserve unrelated values such as:

```text
VerifierDlls
GlobalFlag
UseFilter
RoseSentinel
```

Official Pengu deletes only the value.

---

# Phase 4: Match official activation detection

Replace full debugger-string equality with official-style parsing.

## Query algorithm

Open the target key with:

```text
KEY_QUERY_VALUE
```

Read `Debugger` with `RegQueryValueExW`.

Return inactive when:

* The target key does not exist.
* `Debugger` does not exist.
* The value is not a supported string type.
* The command does not begin with `rundll32`, case-insensitively.
* No quoted path is present.
* The quoted path does not match the current `core.dll`.

## Parsing behavior

Mirror upstream behavior:

```csharp
private static string ExtractQuotedPath(string value)
{
    var start = value.IndexOf('"');
    if (start < 0)
        return null;

    var end = value.IndexOf('"', start + 1);
    if (end < 0)
        return null;

    return value.Substring(start + 1, end - start - 1);
}
```

Normalization must mirror upstream rather than adding new canonicalization rules:

```csharp
private static string NormalizePath(string path)
{
    return path?.ToLowerInvariant().Replace('/', '\\');
}
```

Do not require exact equality for the complete command string.

Official Pengu only checks the `rundll32` prefix, extracts the quoted path, normalizes slashes/case, and compares the DLL path.

---

# Phase 5: Port official self-elevation flow

## Manifest

Change:

```xml
<requestedExecutionLevel
    level="requireAdministrator"
    uiAccess="false" />
```

to:

```xml
<requestedExecutionLevel
    level="asInvoker"
    uiAccess="false" />
```

The normal UI, status command, plugin commands, datastore commands, and configuration commands must not request UAC.

## Elevation detection

Add `Elevation.IsAdministrator()` using:

```csharp
WindowsIdentity.GetCurrent()
WindowsPrincipal
WindowsBuiltInRole.Administrator
```

Log both:

```text
IsAdministrator
IsElevated
```

On standard UAC-enabled Windows these should normally agree, but use a token-elevation query if needed to distinguish an administrator account from an elevated process.

## Install/uninstall coordinator

Restructure `Program.HandleInstall()` carefully.

The current operation mutex must not be held by the unelevated parent while it waits for an elevated child, or the child will fail to acquire the same mutex.

Required flow:

```text
HandleInstall(active, silent)
    |
    +-- process elevated?
        |
        +-- no:
        |    RunElevated(active, silent)
        |    Do not acquire operation mutex in parent
        |
        +-- yes:
             acquire operation mutex
             HandleInstallCore(active, silent)
```

## Elevated child launch

Use:

```csharp
var startInfo = new ProcessStartInfo
{
    FileName = currentExecutablePath,
    Arguments = active
        ? "--install --silent"
        : "--uninstall --silent",
    Verb = "runas",
    UseShellExecute = true,
    WorkingDirectory = AppDomain.CurrentDomain.BaseDirectory,
    WindowStyle = ProcessWindowStyle.Hidden
};
```

Requirements:

* Use the exact current loader executable.
* Child always receives `--silent`.
* Parent is responsible for displaying or printing the final result.
* Wait for the child to exit.
* Decode its exit code.
* Do not show a second success/error message from the child.
* Do not launch recursively when the elevated child starts.
* If already elevated, execute directly without another process.
* UAC cancellation, Win32 error `1223`, becomes:

```text
RunElevated (cancelled)
```

* Other `Process.Start()` failures become:

```text
RunElevated (<mapped kind>)
```

Official Pengu launches itself with `runas`, waits, decodes the child exit code, and reports the resulting stage.

## Child exit behavior

The elevated child must return:

```csharp
return result.EncodeExitCode();
```

The parent must decode it and return the same encoded failure to external callers.

For non-silent UI activation:

* Parent shows one message.
* Child shows none.

For Rose’s `--silent` CLI call:

* Parent writes the official-style result to the attached console.
* Parent returns zero or the encoded failure.
* No message box appears.

---

# Phase 6: Refactor `Module.SetActive`

Change the activation path so registry failures retain their stage.

Preferred API:

```csharp
public static ActivationResult SetActive(bool active)
```

Behavior:

1. If `IsActivated == active`:

   * Update Rose’s core config.
   * Return success.
2. If using symlink mode:

   * Preserve existing symlink behavior.
   * Return a structured result.
3. If using IFEO:

   * Call the new IFEO activation/deactivation API.
   * Stop immediately on failure.
4. Only after the native activation operation succeeds:

   * Write Rose’s `config.ini`.
5. Re-read `IsActivated`.
6. If final state does not equal requested state:

   * Return an `Other` failure with the relevant stage.
7. Otherwise return success.

Do not write:

```ini
disabled=0
loaderpath=<path>
```

when the registry write failed.

Do not remove the Rose-specific config behavior currently implemented after registry activation.

Search and update all `Module.SetActive()` call sites.

---

# Phase 7: Normalize Python CLI invocation

In:

```text
utils/integration/pengu_loader.py
```

Change activation:

```python
_run_cli_result(['--install', '--activate', '--silent'])
```

to:

```python
_run_cli_result(['--install', '--silent'])
```

Change deactivation:

```python
_run_cli_result(['--uninstall', '--deactivate', '--silent'])
```

to:

```python
_run_cli_result(['--uninstall', '--silent'])
```

Keep:

```text
--status --silent
```

unchanged.

Do not bypass the loader by writing the registry from Python.

Do not make Rose itself request elevation.

Preserve session ownership, stale-session recovery, runtime synchronization, and restart behavior.

The runtime loader is copied into `%LOCALAPPDATA%\Rose\Pengu Loader`, so ensure the newly built executable is copied into the bundled `Pengu Loader` directory and then refreshed into the runtime directory on next Rose launch.

---

# Logging specification

Extend `pengu.log`; do not create another activation log.

The existing logger already records invocation information, command line, PID, base directory, operating system, and process bitness.

Add the following fields at startup:

```text
ProcessUser
IsAdministrator
IsElevated
IntegrityLevel
ParentPID
RegistryView
ExecutablePath
```

Do not log access tokens, credentials, or complete environment variables.

## Activation request

Example:

```text
[INFO] [Activation] Request active=true silent=true elevated=false pid=1234
```

## Elevation launch

```text
[INFO] [Elevation] Launching elevated child
[INFO] [Elevation] Executable=C:\...\Pengu Loader.exe
[INFO] [Elevation] Arguments=--install --silent
```

Do not log `Verb=runas` as a secret or obscure it; it is useful diagnostic information.

## Child result

```text
[INFO] [Elevation] Child exited exitCode=770
[ERROR] [Elevation] Decoded failure stage=SetDebugger kind=permission_denied
```

## Registry stages

Before each operation:

```text
[DEBUG] [IFEO] stage=OpenIFEO path="SOFTWARE\...\Image File Execution Options" access=KEY_CREATE_SUB_KEY(0x0004)
[DEBUG] [IFEO] stage=CreateTarget target="LeagueClientUx.exe" access=KEY_SET_VALUE(0x0002)
[DEBUG] [IFEO] stage=SetDebugger valueName="Debugger" valueType=REG_SZ dllPath="C:\...\core.dll" entry="#6000"
```

After success:

```text
[INFO] [IFEO] stage=OpenIFEO succeeded
[INFO] [IFEO] stage=CreateTarget succeeded disposition=opened_existing
[INFO] [IFEO] stage=SetDebugger succeeded
```

After native failure:

```text
[ERROR] [IFEO] stage=SetDebugger failed win32=5 kind=permission_denied message="Access is denied."
```

For status detection:

```text
[DEBUG] [IFEO] Query target key exists=true
[DEBUG] [IFEO] Debugger value exists=true
[DEBUG] [IFEO] Debugger command usesRundll32=true
[DEBUG] [IFEO] Extracted module path="C:\...\core.dll"
[DEBUG] [IFEO] Expected module path="C:\...\core.dll"
[DEBUG] [IFEO] Activated=true
```

For deactivation:

```text
[DEBUG] [IFEO] stage=DeleteDebugger access=KEY_SET_VALUE(0x0002)
[INFO] [IFEO] Debugger value deleted; target key preserved
```

For an idempotent missing value:

```text
[INFO] [IFEO] Debugger value was already absent; treating deactivation as successful
```

## Logging rules

* Expected native failures: one structured error with stage, numeric code, kind, and message.
* Unexpected managed exceptions: include full exception and stack trace.
* Do not emit the same exception three times at different layers.
* Parent should log the decoded child failure.
* Child should log the original Win32 failure.
* Always log the final result:

```text
[INFO] [Activation] Completed active=true success=true
```

or:

```text
[ERROR] [Activation] Completed active=true success=false stage=SetDebugger kind=permission_denied
```

---

# Unit-test design

Do not make normal unit tests modify the real IFEO registry.

Introduce an injectable interface around native registry operations, for example:

```csharp
internal interface IRegistryApi
{
    int OpenLocalMachine(
        string path,
        uint desiredAccess,
        out IRegistryHandle handle);

    int CreateSubKey(
        IRegistryHandle parent,
        string name,
        uint desiredAccess,
        out IRegistryHandle handle,
        out uint disposition);

    int QueryString(
        IRegistryHandle key,
        string valueName,
        out string value);

    int SetString(
        IRegistryHandle key,
        string valueName,
        string value);

    int DeleteValue(
        IRegistryHandle key,
        string valueName);
}
```

Production implementation:

```text
Win32RegistryApi
```

Tests:

```text
FakeRegistryApi
```

Use an injectable process/elevation abstraction for elevation tests:

```csharp
internal interface IElevatedProcessRunner
{
    ElevatedProcessResult Run(
        string executable,
        string arguments,
        string workingDirectory);
}
```

Do not invoke a real UAC prompt in unit tests.

---

# Required C# unit tests

Add a Windows loader test project if the repository does not already have one:

```text
vendor/PenguLoader-1.1.6/tests/PenguLoader.Tests.csproj
```

Prefer the testing framework already available in the development environment. Keep the production project dependency-free.

Required tests:

## Debugger command

```text
DebuggerCommand_has_exact_official_format
DebuggerCommand_has_no_trailing_space
DebuggerCommand_quotes_core_path
```

Expected:

```text
rundll32 "C:\Rose\Pengu Loader\core.dll", #6000
```

## Path parsing

```text
ExtractQuotedPath_extracts_first_quoted_path
ExtractQuotedPath_returns_null_without_quotes
ExtractQuotedPath_returns_null_with_unclosed_quote
NormalizePath_is_case_insensitive
NormalizePath_converts_forward_slashes
```

## Activation detection

```text
IsActivated_true_for_matching_core_path
IsActivated_true_with_different_path_case
IsActivated_true_with_forward_slashes
IsActivated_false_for_non_rundll32_command
IsActivated_false_for_missing_debugger_value
IsActivated_false_for_unquoted_path
IsActivated_false_for_different_core_path
```

## Registry rights

Using `FakeRegistryApi`, assert exact access masks:

```text
Activate_opens_IFEO_with_KEY_CREATE_SUB_KEY_only
Activate_creates_target_with_KEY_SET_VALUE_only
Status_opens_target_with_KEY_QUERY_VALUE_only
Deactivate_opens_target_with_KEY_SET_VALUE_only
```

Fail tests if broader rights are requested.

## Activation stages

For each injected failure:

```text
OpenIFEO_failure_returns_OpenIFEO_stage
CreateTarget_failure_returns_CreateTarget_stage
SetDebugger_failure_returns_SetDebugger_stage
DeleteDebugger_failure_returns_DeleteDebugger_stage
```

## Deactivation safety

```text
Deactivate_deletes_only_Debugger_value
Deactivate_does_not_delete_target_key
Deactivate_preserves_unrelated_values
Deactivate_missing_value_is_idempotent
```

## Exit-code transport

```text
ActivationResult_success_encodes_zero
ActivationResult_failure_round_trips_stage_and_kind
Each_stage_round_trips_through_exit_code
Unknown_error_kind_round_trips
```

## Elevation

```text
Unelevated_install_launches_elevated_child
Unelevated_uninstall_launches_elevated_child
Elevated_install_does_not_launch_child
Elevated_uninstall_does_not_launch_child
Elevated_child_receives_silent_argument
Parent_decodes_child_exit_code
Uac_cancel_maps_to_RunElevated_cancelled
Process_start_failure_maps_to_RunElevated
```

## Mutex regression

```text
Unelevated_parent_does_not_hold_operation_mutex_while_waiting
Elevated_child_acquires_operation_mutex
```

This is critical. A parent-held mutex would block its own elevated child.

## Config ordering

```text
Failed_registry_activation_does_not_enable_core_config
Successful_registry_activation_updates_core_config
Failed_deactivation_does_not_claim_inactive_config
```

---

# Required Python tests

Update `test/test_pengu_loader.py`.

Change existing argument assertions:

```python
self.assertEqual(
    run.call_args_list[0].args[0][1:],
    ['--install', '--silent'],
)
```

and:

```python
self.assertEqual(
    run.call_args_list[0].args[0][1:],
    ['--uninstall', '--silent'],
)
```

Add source-contract regression tests:

```text
test_manifest_uses_as_invoker
test_manifest_does_not_require_administrator
test_ifeo_does_not_use_delete_sub_key_tree
test_ifeo_does_not_use_managed_writable_create_subkey
test_ifeo_uses_key_create_sub_key
test_ifeo_uses_key_set_value
test_ifeo_uses_key_query_value
test_debugger_command_has_no_trailing_space
test_python_wrapper_uses_single_official_command
```

Add integration-wrapper behavior tests:

```text
test_activation_propagates_encoded_child_failure
test_deactivation_propagates_encoded_child_failure
test_uac_cancellation_does_not_create_session
test_failed_activation_does_not_write_active_session
test_successful_activation_still_verifies_status
```

Preserve the existing session recovery and logging tests.

---

# Windows integration test

Add an opt-in administrator-only test:

```text
scripts/test_pengu_ifeo_integration.ps1
```

It must use a unique fake executable target, never `LeagueClientUx.exe`:

```powershell
$Target = "RosePenguIntegration-$([guid]::NewGuid().ToString('N')).exe"
```

Test procedure:

1. Create/open the fake target through the same C# IFEO implementation.
2. Set a sentinel value:

```text
RoseSentinel = preserve-me
```

3. Activate.
4. Verify:

```text
Debugger exists
Debugger has exact expected format
RoseSentinel still exists
```

5. Deactivate.
6. Verify:

```text
Debugger no longer exists
RoseSentinel still exists
target key still exists
```

7. Remove the test target key in `finally`.

The script must:

* Refuse to operate unless the target begins with `RosePenguIntegration-`.
* Use `try/finally`.
* Print cleanup failures.
* Never modify the real League target.
* Return nonzero on failure.

Do not run this integration test automatically on non-Windows systems or without explicit opt-in.

---

# Manual regression procedure

After implementation:

## Build

```powershell
python scripts/build_pengu_loader.py
```

Confirm that these files were refreshed:

```text
Pengu Loader/Pengu Loader.exe
Pengu Loader/core.dll
```

The build script already copies generated `.exe`, `.config`, and `.dll` files into the runtime source directory.

## Automated tests

```powershell
python -m unittest test.test_pengu_loader -v
```

If a C# test project was added:

```powershell
dotnet test vendor/PenguLoader-1.1.6/tests/PenguLoader.Tests.csproj -c Release
```

Run:

```powershell
git diff --check
```

## UAC behavior

1. Start `Pengu Loader.exe` normally.
2. Confirm the GUI opens without UAC.
3. Run `--status --silent`.
4. Confirm no UAC.
5. Activate.
6. Confirm exactly one UAC prompt.
7. Accept.
8. Confirm the parent reports success.
9. Deactivate.
10. Confirm exactly one UAC prompt.

## Registry behavior

After activation:

```powershell
reg query `
  "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\LeagueClientUx.exe" `
  /v Debugger
```

Expected data:

```text
rundll32 "<absolute runtime path>\core.dll", #6000
```

Before deactivation, create a sentinel:

```powershell
reg add `
  "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\LeagueClientUx.exe" `
  /v RoseSentinel `
  /t REG_SZ `
  /d preserve-me `
  /f
```

After deactivation:

```powershell
reg query `
  "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\LeagueClientUx.exe"
```

Expected:

```text
Debugger is absent
RoseSentinel remains
LeagueClientUx.exe key remains
```

Remove the sentinel manually after testing.

## UAC cancellation

1. Start activation from an unelevated process.
2. Cancel the UAC prompt.
3. Confirm:

   * No activation.
   * No session file indicating Rose owns activation.
   * Parent returns a nonzero exit code.
   * Log contains:

```text
stage=RunElevated
kind=cancelled
win32=1223
```

## Already elevated

Run the loader from an administrator terminal.

Confirm activation executes directly without launching another elevated child.

## Reported-user regression

On the machine that currently gets `UnauthorizedAccessException`:

1. Install the rebuilt loader.
2. Delete or archive the old `pengu.log`.
3. Start Rose normally.
4. Activate Pengu.
5. Collect the new `pengu.log`.
6. Verify the log shows the exact registry access rights and stage.
7. Confirm whether the narrow native rights fix the failure.

---

## Deliberate deviations from upstream Pengu

The Rose clone intentionally keeps these differences from the pinned official implementation:

* Rose elevates every install/uninstall operation when the caller is not elevated, including symlink mode; it does not expose upstream developer-mode symlink activation.
* The elevated child receives only `--install --silent` or `--uninstall --silent`; Rose does not pass upstream `--symlink`.
* IFEO deactivation opens the existing target directly and treats a missing target/value as an idempotent success. It deletes only `Debugger` and preserves the target key and unrelated values.
* Status uses the narrower `KEY_QUERY_VALUE` access mask rather than upstream `KEY_READ`.

Activation now reports a separate `WriteCoreConfig` stage. Registry changes are completed before Rose's `config.ini` update; if that update fails, the result and log mark `partialState`, including whether the registry state changed and that the core configuration was not updated.
# Acceptance criteria

The task is complete only when all of these are true:

* The loader GUI no longer requests administrator rights at startup.
* Status and plugin-management commands do not request administrator rights.
* Install/uninstall request elevation only when needed.
* There is exactly one UAC prompt per unelevated install/uninstall.
* The unelevated parent does not hold the operation mutex while waiting.
* The registry parent is opened with `KEY_CREATE_SUB_KEY` only.
* The target is created/opened with `KEY_SET_VALUE` only.
* Status uses `KEY_QUERY_VALUE` only.
* The debugger value exactly matches official formatting.
* Activation detection compares the extracted DLL path, not the complete command.
* Deactivation deletes only `Debugger`.
* Unrelated IFEO values and the target key survive deactivation.
* Registry failures include a structured stage and error kind.
* The child logs the native Win32 error.
* The parent logs the decoded child result.
* Failed registry activation does not update Rose’s core configuration.
* Python calls use only `--install --silent` and `--uninstall --silent`.
* Existing Rose session recovery tests continue to pass.
* The vendored executable is rebuilt and copied into the bundled runtime directory.
* `git diff --check` passes.
* Automated tests pass.
* The previous user’s failing machine is retested with a fresh log.

---

# Out of scope

Do not:

* Replace the C# WPF loader with upstream Tauri.
* Modify `core.dll` injection behavior.
* Modify plugin APIs.
* Remove Rose session recovery.
* Remove Rose’s `config.ini` integration.
* Make Python write IFEO values directly.
* Add a permanent Windows service or scheduled task.
* Delete arbitrary IFEO keys.
* Request `KEY_ALL_ACCESS`.
* hide registry failures behind a generic `false` result.

---

# Final Codex report

At completion, provide:

1. Summary of the behavior ported.
2. Exact files changed.
3. Explanation of elevation and mutex flow.
4. Registry rights used at every stage.
5. Tests added and commands run.
6. Build result.
7. Any untested Windows-only behavior.
8. A short excerpt of expected successful and failed activation logs.
9. Remaining differences from the pinned official implementation.
