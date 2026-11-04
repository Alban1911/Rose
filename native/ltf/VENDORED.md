# Vendored LeagueToolFlop (LTF) sources

Rose builds the LTF bridge from these sources instead of bundling LTK's
patcher binaries. `ltk_launcher.exe` starts LTK Manager (hidden), injects
`LeagueToolFlop.dll` into it, and the DLL serves the TCP bridge API that
`injection/tools/bridge.py` talks to (import/toggle mods, start/stop LTK
Manager's patcher).

Built by `scripts/build_ltf.py` into `injection/tools/`.

## Files

| File | Origin |
| --- | --- |
| `LeagueToolFlop-inj.cpp` | LTF launcher (builds to `ltk_launcher.exe`) |
| `LeagueToolFlop_dll.cpp` | LTF bridge DLL (builds to `LeagueToolFlop.dll`) |

The launcher hardcodes the bridge DLL's file name: it must find
`LeagueToolFlop.dll` next to `ltk_launcher.exe`.

To update: copy the two files from the LTF project again. The LTF project
also ships `fantome_processor.hpp` (with zstd and miniz), which rewrote each
skin on import: Rose does not use it, so leave it out and keep `CmdImport`
installing the archive as Rose sent it.

## Rose's changes to the LTF sources

An update must carry these over (Rose's Python side depends on them):

- **Launcher**: `wmain` (UTF-16 paths), `--quiet` (no message boxes), a free
  CDP port per launch instead of 9222, and `--remote-allow-origins` limited to
  the endpoint's own origin. It never kills a running LTK Manager: it exits
  with code 5 instead. It injects only into the process it spawned, or the one
  that process restarted itself as (LTK Manager relaunches unelevated), exits
  with code 6 when neither is alive, and prints `LTK_MANAGER_PID=<pid>`.
  It starts LTK Manager with `explorer.exe` as the recorded parent
  (`PROC_THREAD_ATTRIBUTE_PARENT_PROCESS`): the patcher DLL verifies the chain
  that started it and refuses the overlay otherwise
  (docs/ltf-vrf-host-verification.md). `CreateProcessWithTokenW` refuses that
  attribute, so an elevated launcher starts an unelevated copy of itself
  (`--as-user-child`) that spawns, injects and resumes the manager, and relays
  its pid through `--pid-file`.
- **DLL**: UTF-8 paths are opened with the wide file APIs. Only LTK Manager's
  own CDP page is used (no fallback to another program's page). Every command
  but `hello`/`ping` needs the token the DLL publishes in
  `HKCU\Software\LTKBridge\ApiToken` and `%LOCALAPPDATA%\LTKBridge\token.txt`.
  `raw_invoke` is removed. Installs get a 3-minute CDP budget, and staged
  file names are sanitized and always get an archive extension. `import`
  hands LTK Manager the archive unchanged: the processor is removed, and an
  archive sent as bytes is only written to a staging file for it.
