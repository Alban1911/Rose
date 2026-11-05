# Launcher token integration test

`launcher_token_test.cpp` includes the production launcher and starts a real,
suspended Windows `cmd.exe` with Explorer as its recorded parent. It checks that
the child keeps the caller's integrity level and the Explorer parent, then
terminates only that test child. It does not start League or a patcher session.

From the repository root on Windows with the MSVC x64 build tools installed:

```bat
python scripts/test_ltf_launcher.py
```

Run once normally and once as administrator. Both should return
zero and `"ok":true`; the respective integrity levels should be 8192 and 12288.
On a headless CI runner, the test process takes Explorer's place as the recorded
parent. Registry tests use a unique temporary HKCU key, not WebView2's real
policy key. They cover missing, string and binary previous values, restoration
after scope exit, unrelated values added during startup, and concurrent edits.

The administrator integration check should also launch the real LTK Manager
through `ltk_launcher.exe` and verify that its loopback bridge can read the
library and patcher status, its integrity stays high after WebView2 mounts, and
the executable-specific HKLM WebView2 arguments match their original value.
Restoration should also be checked when process creation fails, with absent,
string, and binary prior registry values. These checks do not require a game.
