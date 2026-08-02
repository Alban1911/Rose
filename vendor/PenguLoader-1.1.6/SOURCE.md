# Pengu runtime provenance

The native core.dll and JavaScript plugin runtime originate from Pengu Loader and
remain distributed under the upstream MIT license.

Rose no longer ships or launches the upstream WPF loader/controller. The loader
controller was ported into pengu/integration/ and now performs IFEO activation,
status detection, deactivation, configuration, session recovery, and League UX
restart directly from Rose.

Upstream reference:

- Repository: https://github.com/PenguLoader/PenguLoader
- Baseline: Pengu Loader v1.1.6
- License: MIT

Rose-specific behavior:

- Rose manages activation directly through Win32 registry APIs.
- Rose preserves the writable runtime path at %LOCALAPPDATA%\Rose\Pengu Loader.
- Rose owns the lifecycle and does not use Pengu CLI commands.
- core.dll remains the native injected payload and is not rewritten in Python.