#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper utilities for interacting with Pengu Loader's command-line interface.

The Pengu Loader CLI is used to force activate/deactivate mods and optionally
restart the League client when required. This module provides a small wrapper
around the executable bundled alongside Rose.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - psutil is part of requirements, but guard just in case
    psutil = None  # type: ignore

from utils.core.logging import get_logger
from utils.core.paths import get_app_dir, get_user_data_dir

log = get_logger("pengu_loader")

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

        # Copy bundled Pengu Loader to runtime location (overwrites bundled files, preserves extras)
        shutil.copytree(bundled_dir, runtime_dir, dirs_exist_ok=True)
        log.info("Synced Pengu Loader to runtime directory (preserving user files): %s", runtime_dir)

        # Ensure disabled plugins stay disabled after the overlay sync.
        _sanitize_plugin_entrypoints(runtime_dir)
        
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


def activate_on_start(league_path: Optional[str] = None) -> bool:
    """
    Force activate Pengu Loader when Rose launches.
    
    Args:
        league_path: Optional League path to set before activation
        
    Returns True if the activation command completed successfully.
    """
    if not _is_available():
        log.debug("Pengu Loader not available; skipping activation.")
        return False

    # Set league path if provided
    if league_path:
        if not set_league_path(league_path):
            log.warning("Failed to set league path in Pengu Loader, continuing with activation anyway.")

    _terminate_pengu_ui()
    restart_needed = _is_league_running()

    log.info("Activating Pengu Loader (restart League client: %s).", restart_needed)
    activated = _run_cli(["--force-activate", "--silent"])

    if activated and restart_needed:
        _run_cli(["--restart-client", "--silent"])

    return activated


def deactivate_on_exit() -> bool:
    """
    Force deactivate Pengu Loader when Rose shuts down.

    Returns True if the deactivation command completed successfully.
    """
    if not _is_available():
        return False

    restart_needed = _is_league_running()

    log.info("Deactivating Pengu Loader (restart League client: %s).", restart_needed)
    deactivated = _run_cli(["--force-deactivate", "--silent"])

    if deactivated and restart_needed:
        _run_cli(["--restart-client", "--silent"])

    return deactivated


