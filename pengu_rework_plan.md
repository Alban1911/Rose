# Task: Integrate Pengu directly into Rose

## Objective

Make Pengu activation part of Rose's Python source, following the same architectural idea as Copia:

- Rose directly activates, detects, and deactivates Pengu.
- Rose directly updates the registry and configuration state.
- Rose directly restarts League Client UX when required.
- Rose never launches Pengu Loader.exe.
- Rose never uses Pengu CLI commands such as --install, --uninstall, --status, --set-league-path, or --restart-client.
- The release no longer contains the WPF loader or its .NET UI dependencies.

The native core.dll and JavaScript plugins remain required. core.dll is loaded into LeagueClientUx.exe and cannot be replaced by Python. This migration removes the external controller, not the native payload.

## Final runtime model

    Rose.exe (Python/PyInstaller, administrator)
        |
        +-- direct Python Pengu integration
        |     +-- direct Win32 IFEO registry calls
        |     +-- runtime/config synchronization
        |     +-- session ownership and crash recovery
        |     +-- direct LCU restart request
        |
        +-- %LOCALAPPDATA%\Rose\Pengu Loader\
              +-- core.dll
              +-- config
              +-- datastore
              +-- plugins\

Keep the existing LocalAppData path for compatibility with current installations, plugin state, datastore contents, and existing Rose IFEO values. The directory name does not mean an external loader executable remains.

## Non-negotiable boundaries

- No runtime dependency on Pengu Loader.exe.
- No subprocess for Pengu activation, status, deactivation, configuration, or League restart.
- No hidden Pengu helper CLI inside Rose.
- core.dll and plugins remain bundled with upstream license/provenance.
- Production Rose continues requesting administrator rights through Rose.spec.
- Normal tests never modify the real LeagueClientUx.exe IFEO key.
- Deactivation deletes only a Rose-owned Debugger value.
- Foreign IFEO values are never overwritten or deleted.
- Existing plugins, datastore data, and plugin enable state survive upgrades.
- Tray quit, Ctrl+C, forced quit, Windows shutdown, and stale-session recovery remain idempotent.

## Current code being replaced

The subprocess boundary is currently in:

    utils/integration/pengu_loader.py

It owns runtime synchronization and session recovery, but delegates these operations to the C# executable:

    --install --silent
    --uninstall --silent
    --status --silent
    --set-league-path
    --restart-client

Current callers:

    main/__init__.py
    main/core/cleanup.py
    main/core/signals.py
    utils/integration/__init__.py

Current build/uninstall dependencies:

    scripts/build_pengu_loader.py
    scripts/build_pyinstaller.py
    Rose.spec
    installer.iss
    vendor/PenguLoader-1.1.6/loader/

## Target source structure

Add:

    pengu/integration/
        __init__.py
        models.py
        registry.py
        runtime.py
        activation.py
        session.py
        league.py

### models.py

Define structured results instead of reducing errors to booleans:

    ActivationStage
        NONE
        VALIDATE_RUNTIME
        CHECK_ELEVATION
        QUERY_DEBUGGER
        OPEN_IFEO
        CREATE_TARGET
        SET_DEBUGGER
        DELETE_DEBUGGER
        WRITE_PENGU_CONFIG
        WRITE_ROSE_CONFIG
        WRITE_SESSION
        VERIFY_STATE
        RESTART_CLIENT

    ActivationErrorKind
        NONE
        NOT_FOUND
        PERMISSION_DENIED
        INVALID_INPUT
        CONFLICT
        PARTIAL_STATE
        OTHER

    ActivationResult
        succeeded
        stage
        error_kind
        native_error_code
        message
        registry_active
        config_updated

No exit-code transport is needed because no child process exists.

### registry.py

Implement an injectable direct Win32 backend with ctypes and advapi32.dll:

    RegOpenKeyExW
    RegCreateKeyExW
    RegQueryValueExW
    RegSetValueExW
    RegDeleteValueW
    RegCloseKey

Use only:

    KEY_QUERY_VALUE     = 0x0001
    KEY_SET_VALUE       = 0x0002
    KEY_CREATE_SUB_KEY  = 0x0004

Never request KEY_WRITE, KEY_ALL_ACCESS, DELETE, WRITE_DAC, or WRITE_OWNER.

Never invoke reg.exe, cmd.exe, PowerShell, or another subprocess.

Production uses Win32RegistryApi. Tests use FakeRegistryApi. Every handle must close in a finally block, including partial failures.

### runtime.py

Move the safe parts of the current wrapper here:

- Resolve assets in development and PyInstaller builds.
- Synchronize assets to %LOCALAPPDATA%\Rose\Pengu Loader.
- Preserve datastore.
- Preserve custom plugin directories.
- Preserve index.js and index.js_ enable state.
- Validate core.dll before activation.
- Update the Pengu config while preserving unknown keys.
- Store the detected path as LeaguePath.
- Return the absolute runtime core.dll path.
- Atomically update files where practical.

On upgrade, remove only these known obsolete files:

    Pengu Loader.exe
    Pengu Loader.exe.config
    ModernWpf.dll
    ModernWpf.Controls.dll
    Ookii.Dialogs.Wpf.dll
    System.ValueTuple.dll

Never remove core.dll, config, datastore, plugins, user-added files, or unknown DLLs.

### session.py

Port the existing session behavior without changing ownership semantics:

- Preserve pengu_session.json.
- Preserve migration from pengu_active.flag.
- Record whether Pengu was active before Rose.
- Record whether Rose activated it.
- Recover a stale Rose-owned session.
- Adopt active stale state while League still has core.dll loaded.
- Deactivate only state owned by Rose.
- Keep recovery state when cleanup fails.
- Write the session atomically.
- Use a versioned schema.

### league.py

Replace --restart-client with a direct request:

    POST /riotclient/kill-and-restart-ux

Reuse Rose's current LCU connection and credentials. Add post() to LCUAPI if needed.

Rules:

- Restart only when LeagueClientUx.exe is running and a state change requires it.
- Finish activation/deactivation before requesting restart.
- Report restart failure and tell the user to restart League manually.
- Do not use taskkill.exe or another CLI.
- Process detection may continue using psutil.

### activation.py

Coordinate registry, config, session, verification, and restart under one re-entrant process lock.

Public API:

    is_available() -> bool
    get_status() -> PenguStatus
    activate_on_start(league_path, lcu) -> ActivationResult
    restore_after_rose(lcu=None) -> ActivationResult
    cleanup_if_dirty(lcu=None) -> ActivationResult
    deactivate_on_exit(lcu=None) -> ActivationResult

Callers must retain the ActivationResult so the log and UI show the real failing stage.

## IFEO behavior

Registry target:

    HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\
    Image File Execution Options\LeagueClientUx.exe

Value name:

    Debugger

Exact value:

    rundll32 "<absolute runtime core.dll path>", #6000

There must be no trailing space.

### Status

Open the target with KEY_QUERY_VALUE only.

Return:

- INACTIVE when the key or Debugger value is absent.
- ACTIVE when the command uses rundll32 and its first quoted path matches Rose's normalized runtime core.dll.
- CONFLICT when a non-empty Debugger value exists but does not belong to Rose.
- UNKNOWN after an unexpected registry or parsing failure.

Normalize case and slash direction only. Do not accept substring ownership checks.

### Activation transaction

1. Synchronize and validate runtime assets.
2. Confirm a high-integrity administrator token.
3. Write LeaguePath to the Pengu runtime config.
4. Query the existing Debugger value.
5. If it already matches Rose, treat activation as idempotent.
6. If a foreign value exists, return CONFLICT and leave it untouched.
7. Open the IFEO parent with KEY_CREATE_SUB_KEY.
8. Create/open LeagueClientUx.exe with KEY_SET_VALUE.
9. Write the exact UTF-16 REG_SZ, including its null terminator.
10. Update %LOCALAPPDATA%\Rose\config.ini:
    - General.disabled=0
    - General.loaderpath=<runtime directory>
11. Re-read the registry and verify ACTIVE.
12. Persist the Rose session record.
13. Restart League Client UX if it was already running.

If config, verification, or session persistence fails after Rose creates Debugger, remove the value and restore the previous config state. If rollback fails, return PARTIAL_STATE, preserve recovery state, and log the exact remaining state.

### Deactivation transaction

1. Query Debugger with KEY_QUERY_VALUE.
2. Treat an absent key/value as successful idempotent cleanup.
3. Return CONFLICT without modification if the value is foreign.
4. Open the target with KEY_SET_VALUE.
5. Delete only Debugger with RegDeleteValueW.
6. Never delete the LeagueClientUx.exe key.
7. Preserve unrelated values such as VerifierDlls, GlobalFlag, and sentinels.
8. Update Rose config:
    - General.disabled=1
    - General.loaderpath=
9. Verify Rose is INACTIVE.
10. Clear the session only after successful cleanup.
11. Restart League Client UX if it was running.

If a later step fails, attempt to restore the debugger value. Keep recovery state whenever final state is uncertain.

## Elevation policy

Rose.spec already sets:

    uac_admin=True

The installer also launches Rose using runas. Keep this behavior. Production flow is therefore:

    Rose.exe -> Python integration -> advapi32.dll

There is no elevated Pengu child, helper process, or CLI.

For source runs:

- Detect token elevation before registry mutation.
- Return CHECK_ELEVATION / PERMISSION_DENIED with a clear message.
- Do not self-relaunch.
- Unit tests remain non-admin because they inject FakeRegistryApi.

Log once:

    is_admin
    is_elevated
    integrity_level
    process_path
    core_dll_path
    registry_view

## Rose lifecycle changes

Update main/__init__.py:

- Replace "Pengu Loader" wording with "Pengu integration".
- Pass the existing LCU instance into activation/restart.
- Activate Pengu before waiting for the LCU WebSocket so a running League client can be refreshed during startup.
- After the WebSocket is ready, initialize the injection system.
- Keep the existing LCU instance for direct activation/restart calls.
- Keep Pengu active through account reconnections.
- Surface activation failure instead of continuing as if plugins loaded.

Update main/core/cleanup.py and main/core/signals.py:

- Call the direct coordinator.
- Make concurrent cleanup idempotent.
- Keep cleanup before os._exit().
- Preserve the Windows shutdown watcher.
- Give registry calls and LCU requests bounded timeouts.

## Packaging migration

### Rose.spec

Bundle only required Pengu assets:

    core.dll
    plugins/**
    LICENSE
    SOURCE.md
    VERSION

Create config and datastore in writable LocalAppData instead of packaging developer state.

Do not bundle:

    Pengu Loader.exe
    Pengu Loader.exe.config
    ModernWpf.dll
    ModernWpf.Controls.dll
    Ookii.Dialogs.Wpf.dll
    System.ValueTuple.dll
    pengu.log

Add a build assertion that fails if Pengu Loader.exe is collected.

### Build scripts

Remove the C# build step from scripts/build_pyinstaller.py.

Retire scripts/build_pengu_loader.py. Replace it with an asset validation step if useful:

- core.dll exists.
- Required plugins exist.
- License/provenance files exist.
- Forbidden loader/UI binaries are absent.

The Rose build must no longer require MSBuild, NuGet restore, or WPF packages.

### Vendored source

After direct integration passes:

- Remove vendor/PenguLoader-1.1.6/loader/.
- Remove C# tests/scripts that only exercise the executable.
- Remove tracked WPF DLLs from Pengu Loader/.
- Keep the MIT license and source/version provenance for core.dll.
- Update SOURCE.md to describe Rose's direct controller.

## Uninstaller migration

Remove the external command from installer.iss.

Implement guarded direct cleanup in Inno Setup:

1. Read Debugger.
2. Parse and normalize its quoted DLL path.
3. Compare it exactly with Rose's LocalAppData core.dll path.
4. Delete only Debugger when Rose owns it.
5. Leave foreign values untouched.
6. Never delete the target key.
7. Log success, no-op, or ownership conflict.
8. Keep current legacy startup-entry cleanup.

The uninstaller is elevated and needs no Rose or Pengu helper.

## Logging

Use the Rose log. Do not create a controller-side pengu.log.

Successful flow example:

    [Pengu] runtime sync completed core=...
    [Pengu] activation requested status=inactive elevated=true
    [Pengu][IFEO] stage=open_ifeo access=0x0004 success=true
    [Pengu][IFEO] stage=create_target access=0x0002 success=true
    [Pengu][IFEO] stage=set_debugger success=true
    [Pengu] activation completed registry_active=true config_updated=true
    [Pengu] restart requested success=true

Failures include:

    stage
    error_kind
    Win32 code/message
    registry_active
    config_updated
    rollback result

Never log LCU passwords, authorization headers, tokens, environment dumps, or datastore contents.

## Tests

### Unit tests

Replace subprocess-focused test_pengu_loader.py coverage with:

    test/test_pengu_registry.py
    test/test_pengu_runtime.py
    test/test_pengu_activation.py
    test/test_pengu_session.py
    test/test_pengu_packaging.py

Registry tests:

- Exact rights for activate, status, and deactivate.
- Exact Debugger formatting and no trailing space.
- UTF-16 length includes the null terminator.
- Deactivation deletes only Debugger.
- Missing key/value is idempotent.
- Unrelated values/key survive.
- Foreign values return CONFLICT.
- Foreign values are never overwritten/deleted.
- Native errors retain stage and error kind.
- All handles close on every path.

Coordinator tests:

- Inactive startup activates, configures, records ownership, then restarts.
- Already active startup is idempotent.
- Registry failure prevents config/session writes.
- Config or session failure rolls activation back.
- Rollback failure reports partial state.
- Verification failure is not success.
- Restart happens only after a successful transaction.
- Restart failure preserves activation state and reports manual action.
- Concurrent cleanup performs one mutation.
- Cleanup preserves Pengu that was active before Rose.
- Stale-session adoption and crash recovery remain compatible.
- Tray, Ctrl+C, forced quit, and finally cleanup share one idempotent path.

Runtime tests:

- Fresh runtime creation.
- Datastore and custom plugin preservation.
- Enabled/disabled plugin state preservation.
- Bundled plugin updates.
- Known legacy file removal.
- Unknown file preservation.
- Config updates preserve unknown keys.
- Correct development/frozen path resolution.

Packaging tests:

- Rose.spec does not require Pengu Loader.exe.
- Build script does not build C#.
- Distribution includes core.dll/plugins/license.
- Distribution excludes loader/WPF files.
- Integration contains no subprocess.run, Popen, reg.exe, or Pengu command aliases.

### Administrator integration test

Keep an opt-in Windows test calling the Python registry backend directly.

Use only:

    RosePenguIntegration-<GUID>.exe

The test must:

1. Reject any target without that prefix.
2. Create a sentinel.
3. Activate through the production backend.
4. Verify the exact Debugger value.
5. Deactivate.
6. Verify Debugger is absent.
7. Verify sentinel and target key remain.
8. Clean the guarded fake key in finally.
9. Never reference LeagueClientUx.exe.

### Manual validation

1. Start Rose with League closed.
2. Confirm no Pengu Loader.exe process appears.
3. Start League and verify plugins load.
4. Quit through tray and verify deactivation/restart.
5. Repeat with Ctrl+C and forced quit.
6. Simulate a crash and verify stale-session recovery.
7. Start while League is running and verify one controlled UX restart.
8. Swap accounts and verify no unnecessary IFEO rewrite.
9. Verify a sentinel survives activation/deactivation.
10. Verify a foreign Debugger causes a non-destructive conflict.
11. Upgrade from 1.2.14 and verify plugins/datastore.
12. Uninstall and verify only Rose-owned Debugger is removed.
13. Inspect the final distribution for forbidden loader files.

## Implementation sequence

### Phase 1: Direct registry backend

- Add models, Win32 backend, parser, ownership detection, and tests.
- Keep production callers unchanged temporarily.

### Phase 2: Runtime and configuration

- Move asset sync and plugin preservation into the new package.
- Add direct Pengu config and Rose config writes.
- Add legacy runtime cleanup and rollback tests.

### Phase 3: Coordinator and lifecycle

- Port session recovery.
- Add direct LCU restart.
- Update startup, reconnection, tray, signal, shutdown, and forced-exit callers.
- Keep old files only for development comparison, never as runtime fallback.

### Phase 4: Switch and validate

- Make direct integration the only path.
- Run unit tests and guarded admin integration.
- Run the real League lifecycle matrix.
- Confirm no Pengu subprocess appears.

### Phase 5: Remove external loader

- Remove C# build/executable assumptions, WPF dependencies, and obsolete tests.
- Update PyInstaller and uninstaller.
- Preserve native assets and attribution.
- Validate upgrade cleanup.

### Phase 6: Release validation

- Build final distribution.
- Test clean install, upgrade, and uninstall.
- Retest a machine that previously had activation problems.
- Save before/after registry and Rose-log traces.

## Acceptance criteria

Complete only when:

- Rose activates Pengu with direct in-process Windows calls.
- No Pengu CLI strings remain in production integration.
- No Pengu Loader.exe process appears.
- The distribution excludes the loader and WPF dependencies.
- The build no longer requires MSBuild.
- core.dll/plugins load from Rose's runtime.
- Tests verify exact narrow registry rights.
- Debugger formatting is exact.
- Foreign values are preserved.
- Deactivation deletes only Rose-owned Debugger.
- Failures roll back or report explicit partial state.
- Plugin state/datastore survive upgrade.
- All shutdown/recovery paths are idempotent.
- League restart uses direct LCU.
- Uninstall cleans Rose activation without a helper.
- Unit tests, guarded integration, build validation, and git diff --check pass.
- Real League loads Rose plugins after clean install and upgrade.

## Out of scope

- Rewriting core.dll or Pengu's CEF/V8 injection in Python.
- Changing the JavaScript plugin API.
- Adding a separate loader window or UI executable.
- Adding a service, scheduled helper, elevated broker, or fallback loader.
- Overwriting/deleting another application's IFEO value.
- Deleting arbitrary IFEO keys.
- Managing plugin settings beyond preserving current files and enable state.

A future visual plugin manager should be a Rose UI feature operating on the managed plugins directory, independent of activation.