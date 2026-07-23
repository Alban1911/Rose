#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper utilities for interacting with Pengu Loader's command-line interface.

The Pengu Loader CLI manages Pengu's IFEO activation and optionally
restart the League client when required. This module provides a small wrapper
around the executable bundled alongside Rose.
"""

from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Optional, Sequence

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - psutil is part of requirements, but guard just in case
    psutil = None  # type: ignore

from utils.core.logging import get_logger
from utils.core.paths import get_app_dir, get_state_dir, get_user_data_dir

log = get_logger("pengu_loader")

_ACTIVE_FLAG = get_state_dir() / "pengu_active.flag"
_PLUGIN_ENTRYPOINT = "index.js"
_PLUGIN_ENTRYPOINT_DISABLED = "index.js_"
_PLUGIN_ENTRYPOINT_BUNDLED_BACKUP = "index.js.bundled"


def _sanitize_plugin_entrypoints(pengu_dir: Path) -> None:
    """
    Ensure plugin enable/disable state survives Pengu Loader sync.

    Background:
    - Disabling a plugin renames `index.js` -> `index.js_`
    - In frozen builds, Rose overlays the bundled `Pengu Loader` onto the runtime directory.
      `copytree(..., dirs_exist_ok=True)` does not delete extra files, so a disabled plugin
      can end up with BOTH `index.js_` and a freshly-copied `index.js`, effectively re-enabling
      (or duplicating) the plugin on next launch.

    Rule:
    - If `index.js_` exists in a plugin directory, treat it as authoritative (disabled) and
      remove/park any `index.js` that was reintroduced by the sync.
    """
    try:
        plugins_dir = pengu_dir / "plugins"
        if not plugins_dir.exists():
            return

        for plugin_dir in plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            enabled = plugin_dir / _PLUGIN_ENTRYPOINT
            disabled = plugin_dir / _PLUGIN_ENTRYPOINT_DISABLED

            if not disabled.exists():
                continue

            if enabled.exists():
                backup = plugin_dir / _PLUGIN_ENTRYPOINT_BUNDLED_BACKUP
                try:
                    if backup.exists():
                        backup.unlink()
                    enabled.replace(backup)
                    log.info(
                        "Preserved disabled plugin state by parking %s to %s",
                        enabled,
                        backup,
                    )
                except Exception as exc:
                    # If we can't park it (locked/permission), at least try to delete it
                    try:
                        enabled.unlink()
                        log.info(
                            "Removed reintroduced entrypoint for disabled plugin: %s",
                            enabled,
                        )
                    except Exception:
                        log.debug(
                            "Failed to remove/park %s for disabled plugin (%s): %s",
                            plugin_dir.name,
                            enabled,
                            exc,
                        )
    except Exception as exc:
        # Non-fatal: never block Rose launch for a best-effort cleanup.
        log.debug("Failed to sanitize plugin entrypoints: %s", exc)


def _snapshot_plugin_enable_state(pengu_dir: Path) -> tuple[set[str], set[str]]:
    """
    Snapshot the user's enabled/disabled state for plugins before overlay sync.

    Returns:
        (enabled, disabled) as sets of plugin directory names.

    Notes:
    - "enabled" means `index.js` exists and `index.js_` does NOT.
    - "disabled" means `index.js_` exists (regardless of `index.js`).
    """
    enabled: set[str] = set()
    disabled: set[str] = set()

    try:
        plugins_dir = pengu_dir / "plugins"
        if not plugins_dir.exists():
            return enabled, disabled

        for plugin_dir in plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            enabled_entry = plugin_dir / _PLUGIN_ENTRYPOINT
            disabled_entry = plugin_dir / _PLUGIN_ENTRYPOINT_DISABLED

            if disabled_entry.exists():
                disabled.add(plugin_dir.name)
            elif enabled_entry.exists():
                enabled.add(plugin_dir.name)
    except Exception as exc:
        log.debug("Failed to snapshot plugin enable state: %s", exc)

    return enabled, disabled


def _restore_plugin_enable_state(pengu_dir: Path, enabled: set[str], disabled: set[str]) -> None:
    """
    After overlay sync, restore the user's prior plugin enable/disable choices.

    Problem:
    - The bundled repo may ship a plugin as disabled (`index.js_` only), but a user may
      have enabled it locally (`index.js` exists).
    - Overlay sync can introduce `index.js_` into the runtime dir without deleting the
      user's `index.js`, leaving both. The old sanitize logic would treat that as disabled.
    """
    try:
        plugins_dir = pengu_dir / "plugins"
        if not plugins_dir.exists():
            return

        # If the user had a plugin enabled, prefer enabled state: remove any
        # reintroduced `index.js_` from the bundle.
        for plugin_name in enabled:
            plugin_dir = plugins_dir / plugin_name
            if not plugin_dir.is_dir():
                continue

            enabled_entry = plugin_dir / _PLUGIN_ENTRYPOINT
            disabled_entry = plugin_dir / _PLUGIN_ENTRYPOINT_DISABLED
            if enabled_entry.exists() and disabled_entry.exists():
                try:
                    disabled_entry.unlink()
                    log.info(
                        "Preserved enabled plugin state by removing bundled disabled entrypoint: %s",
                        disabled_entry,
                    )
                except Exception as exc:
                    log.debug(
                        "Failed to remove bundled disabled entrypoint for enabled plugin %s: %s",
                        plugin_name,
                        exc,
                    )

        # If the user had a plugin disabled, keep disabled state authoritative.
        # (This also handles the "both files exist" case by parking `index.js`.)
        _sanitize_plugin_entrypoints(pengu_dir)
    except Exception as exc:
        log.debug("Failed to restore plugin enable state: %s", exc)


def _get_bundled_pengu_dir() -> Optional[Path]:
    """Locate the bundled Pengu Loader directory (read-only location)."""
    # 1. PyInstaller onefile: resources live under _MEIPASS
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "Pengu Loader"
        if candidate.exists():
            return candidate

    # 2. PyInstaller onedir: resources in _internal folder
    if getattr(sys, 'frozen', False):
        app_dir = get_app_dir()
        candidate = app_dir / "_internal" / "Pengu Loader"
        if candidate.exists():
            return candidate
        # Fallback: directly alongside executable
        candidate = app_dir / "Pengu Loader"
        if candidate.exists():
            return candidate

    # 3. Development environment: relative to project root
    repo_dir = Path(__file__).resolve().parent.parent
    candidate = repo_dir / "Pengu Loader"
    if candidate.exists():
        return candidate

    return None


def _resolve_pengu_dir() -> Path:
    """
    Locate the Pengu Loader directory for execution.
    
    For frozen builds, copies Pengu Loader to AppData to ensure write permissions
    (Program Files is read-only, causing datastore failures).
    For development, uses the source directory directly.
    """
    # Development mode: use source directory directly (it's writable)
    if not getattr(sys, 'frozen', False):
        bundled = _get_bundled_pengu_dir()
        if bundled:
            return bundled
        # Fallback
        return get_app_dir() / "Pengu Loader"

    # Frozen mode: copy to AppData for write permissions
    bundled_dir = _get_bundled_pengu_dir()
    if not bundled_dir:
        log.warning("Bundled Pengu Loader directory not found in frozen build")
        return get_app_dir() / "Pengu Loader"

    # Runtime location in user data directory
    runtime_dir = get_user_data_dir() / "Pengu Loader"
    
    try:
        # Keep the runtime directory and overlay updates on top of it.
        #
        # IMPORTANT: users can add custom plugins under:
        #   %LOCALAPPDATA%\Rose\Pengu Loader\plugins
        # Deleting the runtime directory on each launch wipes those user-installed plugins.
        runtime_dir.mkdir(parents=True, exist_ok=True)

        # Snapshot plugin enabled/disabled state BEFORE overlaying bundled files.
        enabled_plugins, disabled_plugins = _snapshot_plugin_enable_state(runtime_dir)

        # Copy bundled Pengu Loader to runtime location (overwrites bundled files, preserves extras).
        #
        # IMPORTANT: preserve the runtime `datastore` file.
        # Pengu Loader stores plugin/user settings there via `DataStore.*`. Overwriting it on
        # app update would wipe user preferences (e.g., enabled plugins, selected borders/icons).
        shutil.copytree(
            bundled_dir,
            runtime_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("datastore"),
        )

        # If this is a fresh runtime directory (no datastore yet), seed it once from bundled.
        bundled_datastore = bundled_dir / "datastore"
        runtime_datastore = runtime_dir / "datastore"
        if (not runtime_datastore.exists()) and bundled_datastore.exists():
            try:
                shutil.copy2(bundled_datastore, runtime_datastore)
            except Exception as exc:
                log.debug("Failed to seed Pengu Loader datastore: %s", exc)
        log.info("Synced Pengu Loader to runtime directory (preserving user files): %s", runtime_dir)

        # Restore plugin enable/disable state after the overlay sync.
        _restore_plugin_enable_state(runtime_dir, enabled_plugins, disabled_plugins)
        
    except Exception as exc:
        log.error("Failed to copy Pengu Loader to runtime directory: %s", exc)
        # Fallback to bundled directory (will likely fail due to permissions, but better than crashing)
        return bundled_dir

    return runtime_dir


PENGU_DIR = _resolve_pengu_dir()
PENGU_EXE = PENGU_DIR / "Pengu Loader.exe"

_LEAGUE_PROCESSES: set[str] = {
    "LeagueClient.exe",
    "LeagueClientUx.exe",
    "LeagueClientUxRender.exe",
    "League of Legends.exe",
}
_PENGU_UI_PROCESS = "Pengu Loader.exe"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_managed_pengu_process: Optional[subprocess.Popen] = None


def _is_windows() -> bool:
    return sys.platform == "win32"


def _is_available() -> bool:
    return _is_windows() and PENGU_EXE.exists()


def _run_cli(args: Sequence[str], ok_codes: Iterable[int] = (0,)) -> bool:
    """
    Execute Pengu Loader CLI with the provided arguments.

    Returns True when the command completed with an expected return code.
    """
    if not _is_available():
        log.debug("Pengu Loader executable not found; skipping command %s", args)
        return False

    command = [str(PENGU_EXE), *args]

    try:
        result = subprocess.run(
            command,
            cwd=str(PENGU_DIR),
            text=True,
            capture_output=True,
            check=False,
            creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        log.warning("Pengu Loader executable is missing at %s", PENGU_EXE)
        return False
    except OSError as exc:
        log.warning("Failed to launch Pengu Loader CLI %s: %s", command, exc)
        return False

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if stdout:
        log.debug("Pengu Loader CLI stdout: %s", stdout)
    if stderr:
        log.debug("Pengu Loader CLI stderr: %s", stderr)

    if result.returncode not in ok_codes:
        log.warning(
            "Pengu Loader CLI command %s exited with code %s (expected %s)",
            " ".join(args),
            result.returncode,
            tuple(ok_codes),
        )
        return False

    return True


def _stop_managed_pengu(deactivate: bool = True) -> bool:
    """Ask the Rose-owned loader to cleanly deactivate and exit."""
    global _managed_pengu_process

    process = _managed_pengu_process
    if process is None:
        return False

    requested_stop = False
    forced_termination = False
    if process.poll() is None:
        # The child owns the activation state. Signal it so its finally block
        # removes the IFEO entry before the process exits.
        if deactivate:
            requested_stop = _run_cli(["--rose-stop", str(os.getpid()), "--silent"])

        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            log.warning("Rose-owned Pengu Loader did not exit after a graceful stop request.")
            forced_termination = True
            try:
                process.terminate()
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            except OSError as exc:
                log.debug("Failed to terminate Rose-owned Pengu Loader: %s", exc)
        except OSError as exc:
            log.debug("Failed to wait for Rose-owned Pengu Loader: %s", exc)

    _managed_pengu_process = None

    # This is a registry-only fallback now that Rose uses Pengu's IFEO mode.
    # It does not copy or delete a DLL in the League directory.
    if deactivate and (not requested_stop or forced_termination):
        return _run_cli(["--force-deactivate", "--silent"])

    return requested_stop


def _start_managed_pengu(league_path: Optional[str] = None) -> bool:
    """Start a loader that owns activation for the lifetime of this Rose process."""
    global _managed_pengu_process

    command = [str(PENGU_EXE), "--rose-managed", str(os.getpid())]
    if league_path:
        command.extend(["--set-league-path", league_path.strip()])
    command.append("--silent")

    try:
        _managed_pengu_process = subprocess.Popen(
            command,
            cwd=str(PENGU_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (FileNotFoundError, OSError) as exc:
        log.warning("Failed to start Rose-owned Pengu Loader: %s", exc)
        _managed_pengu_process = None
        return False

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if _managed_pengu_process.poll() is not None:
            log.warning(
                "Rose-owned Pengu Loader exited during startup with code %s.",
                _managed_pengu_process.returncode,
            )
            _managed_pengu_process = None
            return False
        time.sleep(0.1)

    log.info("Started Rose-owned Pengu Loader (PID %s).", _managed_pengu_process.pid)
    return True


def _remove_legacy_proxy(league_path: Optional[str]) -> bool:
    """Remove the old Rose proxy only when it exactly matches our core.dll."""
    if not league_path or not _is_windows():
        return False

    core_path = PENGU_DIR / "core.dll"
    proxy_path = Path(league_path) / "d3d9.dll"

    try:
        if not core_path.exists() or not proxy_path.exists():
            return False
        if not filecmp.cmp(core_path, proxy_path, shallow=False):
            log.warning("Leaving non-Rose League d3d9.dll untouched: %s", proxy_path)
            return False

        for _ in range(10):
            try:
                proxy_path.unlink()
                log.info("Removed legacy Rose proxy: %s", proxy_path)
                return True
            except PermissionError:
                time.sleep(0.25)
            except OSError as exc:
                log.debug("Could not remove legacy Rose proxy %s: %s", proxy_path, exc)
                return False
    except OSError as exc:
        log.debug("Could not inspect legacy Rose proxy %s: %s", proxy_path, exc)

    log.info("Legacy Rose proxy is still in use; will retry after the client closes: %s", proxy_path)
    return False


def _terminate_pengu_ui() -> None:
    if not _is_windows():
        return

    try:
        result = subprocess.run(
            ["taskkill", "/IM", _PENGU_UI_PROCESS, "/F"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=_CREATE_NO_WINDOW,
        )
        if result.returncode not in (0, 128, 255):
            log.debug(
                "taskkill for Pengu UI returned %s (stdout=%r, stderr=%r)",
                result.returncode,
                (result.stdout or "").strip(),
                (result.stderr or "").strip(),
            )
    except FileNotFoundError:
        log.debug("taskkill command not found; skipping Pengu UI termination.")
    except OSError as exc:
        log.debug("Failed to terminate Pengu Loader UI process: %s", exc)


def _is_league_running() -> bool:
    if not _is_windows():
        return False
    if psutil is None:
        log.debug("psutil not available; assuming League client is not running.")
        return False

    try:
        for proc in psutil.process_iter(["name"]):
            name = proc.info.get("name")
            if name and name in _LEAGUE_PROCESSES:
                log.debug("Detected running League process: %s", name)
                return True
    except (psutil.Error, OSError) as exc:  # type: ignore[attr-defined]
        log.debug("Failed to inspect running processes: %s", exc)
    return False


def set_league_path(league_path: str) -> bool:
    """
    Set the League path in Pengu Loader configuration.
    
    Args:
        league_path: Path to League of Legends.exe directory
        
    Returns True if the command completed successfully.
    """
    if not _is_available():
        log.debug("Pengu Loader not available; skipping set-league-path.")
        return False
    
    if not league_path or not league_path.strip():
        log.warning("Empty league path provided; skipping set-league-path.")
        return False
    
    log.info("Setting League path in Pengu Loader: %s", league_path)
    return _run_cli(["--set-league-path", league_path.strip(), "--silent"])


def _write_active_flag() -> None:
    """Write the dirty-state flag indicating Pengu is currently activated."""
    try:
        _ACTIVE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        _ACTIVE_FLAG.write_text("active")
        log.debug("Pengu active flag written: %s", _ACTIVE_FLAG)
    except OSError as exc:
        log.debug("Failed to write Pengu active flag: %s", exc)


def _clear_active_flag() -> None:
    """Remove the dirty-state flag after successful deactivation."""
    try:
        _ACTIVE_FLAG.unlink(missing_ok=True)
        log.debug("Pengu active flag cleared.")
    except OSError as exc:
        log.debug("Failed to clear Pengu active flag: %s", exc)


def cleanup_if_dirty() -> bool:
    """
    Check for a leftover active flag from a previous unclean shutdown and
    deactivate Pengu Loader if found.

    Returns True if cleanup was performed.
    """
    if not _ACTIVE_FLAG.exists():
        return False

    log.info("Detected leftover Pengu active flag — cleaning up from previous session.")
    deactivated = deactivate_on_exit()
    # Flag is already cleared inside deactivate_on_exit(); clear explicitly
    # in case deactivation itself failed but we still want to avoid an
    # infinite retry loop on every launch.
    _clear_active_flag()
    return deactivated


def activate_on_start(league_path: Optional[str] = None) -> bool:
    """
    Start Rose-owned Pengu Loader when Rose launches.

    The child loader performs activation, watches Rose's PID, and deactivates
    itself when Rose exits or crashes.
    """
    if not _is_available():
        log.debug("Pengu Loader not available; skipping activation.")
        return False

    # Stop a previous managed instance before killing the legacy UI process
    # with the broad taskkill fallback.
    _stop_managed_pengu()
    _terminate_pengu_ui()
    _remove_legacy_proxy(league_path)
    restart_needed = _is_league_running()

    log.info("Starting Rose-owned Pengu Loader (restart League client: %s).", restart_needed)

    # Write flag *before* activation so it persists even if Rose is killed
    # during child startup.
    _write_active_flag()

    started = _start_managed_pengu(league_path)
    if started and restart_needed:
        _run_cli(["--restart-client", "--silent"])
        _remove_legacy_proxy(league_path)

    if not started:
        _clear_active_flag()

    return started


def deactivate_on_exit() -> bool:
    """
    Deactivate Pengu Loader when Rose shuts down.

    Normal shutdown asks the managed child to stop so it can remove its IFEO
    entry in its own finally block. If Rose is recovering from an unclean
    shutdown, the registry-only CLI fallback removes the entry directly.
    """
    if not _is_available():
        return False

    restart_needed = _is_league_running()

    log.info("Deactivating Pengu Loader (restart League client: %s).", restart_needed)
    deactivated = _stop_managed_pengu()
    if not deactivated:
        # IFEO cleanup is safe while League is running: it only removes the
        # debugger registration and never replaces a League DLL.
        deactivated = _run_cli(["--force-deactivate", "--silent"])

    if deactivated:
        _clear_active_flag()
        if restart_needed:
            _run_cli(["--restart-client", "--silent"])

    return deactivated

