# Pengu Loader source

This directory is based on the official Pengu Loader repository:

- Repository: https://github.com/PenguLoader/PenguLoader
- Upstream tag: v1.1.6
- Upstream commit: 4d641f52bc5d70aac4c09dfa1fa7a043a9069aff

Rose-specific changes are intentionally limited to:

- Rose branding and links in the UI.
- The CLI commands used by Rose: `--status`, `--set-league-path`, and `--restart-client`, plus `--silent`.
- Mirroring activation state to `%LOCALAPPDATA%\\Rose\\config.ini`.
- IFEO written through the registry API, as upstream's current loader does: v1.1.6 ran `cmd /C reg add`, which broke on `&` and `^` in the path. Activation compares the debugger's `core.dll` path rather than the exact value.

Rose's Python integration invokes the executable; it does not write the registry itself.
