# Injection reports success but the skin never applies — `VRF0000000x host verification failed`

## Summary

On the LTF-bridge pipeline, Rose reports `INJECTION COMPLETED` but the skin does
not appear in-game. The cause is **downstream of Rose**: LTK Manager's patcher DLL
builds the overlay, attaches to the game, and then **refuses to apply it** with a
host-verification error written to **LTK Manager's own log**.

Rose's launcher tripped that check by starting `ltk-manager.exe` itself: the DLL
walks the process chain that started `ltk_patcher_host.exe` and only accepts the
chain a hand-started manager has (`ltk_patcher_host.exe` ← `ltk-manager.exe` ←
`explorer.exe`). Rose's chain has `ltk_launcher.exe` where `explorer.exe` should
be. `native/ltf/LeagueToolFlop-inj.cpp` now seeds the manager's parent as the
desktop shell, which makes the chain match while keeping Rose's environment, the
suspended start and the WebView2 debugging port. See **The fix** below.

## Evidence (LTK Manager's own log)

`%APPDATA%\dev.leaguetoolkit.manager\logs\ltk-manager.<date>.log`

```
[ltk-host] injected: dll attached
[ltk-dll ... INFO] ltk_patcher_dll::hooks::fsov::imp: patched CreateFileA
[ltk-dll ... ERROR] ltk_patcher_dll::verify: host verification failed, refusing overlay: [VRF00000007] (27688)
```

The overlay build itself succeeds (`Overlay build complete: 3 built, 0 reused`),
the host is spawned, the DLL is injected into the game (pid=28800) and installs
its hooks — then `verify` refuses the overlay about 1.2 s later. Rose's log for
the same run is clean end to end (`[INJECT] The LTK patcher attached to the game`,
`INJECTION COMPLETED >>> SKIN_105002 <<<`): the bridge's status never carries the
refusal, only LTK's log does.

Retained local history:

| When | Patcher | Manager | Outcome |
| --- | --- | --- | --- |
| 2026-11-02 00:52 / 00:53 | `ltk_patcher-26` | 1.32.1 | `joined too late, not overlaying` (timing, separate) |
| 2026-11-02 01:12 | `ltk_patcher-26` | 1.32.1 | `[VRF00000007] (5184)` |
| 2026-11-04 12:32 | `ltk_patcher-26` | 1.32.2 | `[VRF00000007] (27688)` |
| 2026-11-04 17:21 | `ltk_patcher-30` | 1.32.2 | patcher replaced (`delivery.json`: `ltk_patcher-30`, `managers >= 1.30.0`, same `eol`) |

The failing run started the manager unelevated as the desktop user, and LTK
Manager records the parent it sees:

```
Process elevation facts=ElevationFacts { ..., parent: Some("ltk_launcher.exe") }
```

A run where the manager relaunched itself through the shell logged
`parent: Some("explorer.exe")` instead — the only structural difference between
Rose's chain and a hand-started manager's.

## What the check looks like in the DLL

`ltk_patcher_dll.dll` contains a small fixed set of strings the verification is
built from:

- process images: `ltk_patcher_host.exe`, `ltk-manager.exe`, `explorer.exe`,
  `\windows\explorer.exe`, and the NT prefix `\\?\GLOBALROOT`;
- signature validation: `WinVerifyTrust`, `WTHelperGetProvSignerFromChain`,
  `WTHelperProvDataFromStateData`, the signer name **`Natoken LLC`** and the
  `2.5.4.3` / `2.5.4.10` OIDs;
- the refusal text `host verification failed, refusing overlay: ` and a code
  table `[VRF00000001] (` … `[VRF00000009] (`;
- a pipe handshake (`\\.\pipe\ltk-patcher-pipe`, `read handshake`,
  `get pipe server process id`, `pipe server pid mismatch`), separate from the
  chain check;
- process inspection through `NtQuerySystemInformation` + `ReadProcessMemory`
  (image name and parent of another process), plus a per-process check that
  compares the image name and validates its Authenticode signature.

The payload after the code is what the check saw: a pid alone (`(27688)`), or a
pid and name (`(19480,ltk-manager.exe)` in
[Rose#404](https://github.com/Alban1911/Rose/issues/404)). The payload shapes do
not pin down each code's meaning, and reading the accepted chain out of the
machine code is not a short job. What is certain:

- the check exists to block third-party apps driving LTK's patcher
  ([ltk-manager#923](https://github.com/LeagueToolkit/ltk-manager/issues/923);
  contributor: *"This check is meant to block third-party apps from using the DLL."*);
- a patcher built before the check (1.29.1) applies Rose's overlays
  ([Rose#401](https://github.com/Alban1911/Rose/issues/401) comment, Oct 31:
  `overlay verified 2 wad(s)`, skin visibly worked), so the refusal lives in the
  DLL, not in Rose's drive method;
- the check arrived with `ltk_patcher-25` / Manager 1.30.0 and is still there on
  `ltk_patcher-30`.

Of everything the check can read, the parent chain is the one signal Rose can
correct without touching LTK's binaries, and the one that visibly differs from a
hand-started manager. That is what the launcher now changes. If the refusal comes
back with a shell-parented manager, the payload names the check that fired.

## The fix

`native/ltf/LeagueToolFlop-inj.cpp` starts `ltk-manager.exe` with
`PROC_THREAD_ATTRIBUTE_PARENT_PROCESS` set to the desktop shell's process. Windows
records `explorer.exe` as the manager's parent, so the chain the DLL reads becomes

```
game ← ltk_patcher_host.exe ← ltk-manager.exe ← explorer.exe
```

exactly what a manager started from the Start menu looks like. Rose keeps
everything it needs:

- the launcher's environment (`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`,
  `LTF_CDP_PORT`), so the bridge still finds WebView2's debugging endpoint;
- `CREATE_SUSPENDED`, so `LeagueToolFlop.dll` is injected before WebView2 starts;
- `--shell-relaunched`, so LTK Manager does not relaunch itself.

If the parent cannot be seeded (no shell handle, or the system rejects the
attribute), the launcher logs why and starts the manager as before: the previous
behaviour, not a broken session. It also logs what Windows recorded:

```
[launch] spawned pid = N (suspended), parent pid = M (explorer.exe)
```

Rose no longer reports a refusal as a success. `LtkLogTail` already reads LTK
Manager's log while the game runs (that is how `dll attached` and `joined too
late` are noticed), so `_check_patcher_verdict` now also matches
`host verification failed` / `[VRF########]` and reports `LTF_FAILED` with a
`refused` cause, the code, and what the check saw.

On an elevated Rose the manager still has to run with the desktop user's token,
and `CreateProcessWithTokenW` refuses the extended startup info (err 87). The
launcher therefore starts an unelevated copy of itself (`--as-user-child`) that
opens the shell, spawns the manager with that parent, injects the bridge and
resumes it, then hands the pid back through `--pid-file`. `CreateProcessAsUser`
is tried first; when the caller lacks `SeAssignPrimaryTokenPrivilege` the copy
takes over.

## Verified

A game run after the fix:

```
[launch] started unelevated as the desktop user, shell parent by the helper
[launch] helper reported pid=7896
[launch] spawned pid = 7896 (suspended), parent pid = 9848 (explorer.exe)
```

```
[ltk-dll pid=26332 ...] ltk_patcher_dll::verify: overlay verified 2 wad(s)
[ltk-dll pid=26332 ...] hooks::fsov::imp: redirected wad: DATA/FINAL/Champions/Nilah.wad.client
```

No `host verification failed`, and the skin showed in game.

A skin changed *after* the game process exists still ends in
`joined too late, not overlaying`: LTK's host locates the game by its window
(`League of Legends (TM) Client`, `FindWindowExA` + `SetWindowsHookEx`), so it
cannot hook a game that Rose froze, and by the time the game is resumed and found
it has already opened its WADs. That is a hard limit of this patcher, not
something Rose can wait out: the patcher must be scanning before the game process
is created (Rose's staging does exactly that), so a skin change made after the
client started the game applies to the next game at best.

## Why the pinned-patcher workaround is not durable

Pinning a pre-1.30 patcher pair works only for game builds that predate it: the
DLL refuses a game build newer than its own end of life (`end of life reached,
please update`, `module timestamp is in the future`). The 1.29.1 pair that worked
on Oct 31 was reported broken by the 2026-11-03 patch, and the delivered manifest
now names `ltk_patcher-30` (`managers >= 1.30.0`, `eol` 1794988800 ≈ 2026-11-18)
for any Manager 1.30.0+.

Shipping a modified LTK DLL remains the cat-and-mouse option it was: the check
changes between patcher releases.

## Related

- LeagueToolkit/ltk-manager #923 — `host verification failed, refusing overlay: [VRF00000008]` (third-party app; a contributor confirms the intent)
- Rose #404 — selected skin/chroma fails to appear in the match; its log shows `[VRF00000008] (19480,ltk-manager.exe)`
- Rose #401 — not working on latest patch; 1.28.1/1.29.1 patcher pairs reported working, then broken by the 2026-11-03 patch
- dat1208/Dat-Rose PR #1 — pins a signed patcher pair and turns the host check into a warning only
