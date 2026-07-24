#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper utilities for interacting with Pengu Loader's command-line interface.

The Pengu Loader CLI manages Pengu's IFEO activation and optionally
restart the League client when required. This module provides a small wrapper
around the executable bundled alongside Rose.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional, Sequence

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - psutil is part of requirements, but guard just in case
    psutil = None  # type: ignore

from utils.core.logging import get_logger
from utils.core.paths import get_app_dir, get_state_dir, get_user_data_dir

log = get_logger("pengu_loader")

_SESSION_FILE = get_state_dir() / 'pengu_session.json'

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
    'LeagueClient.exe', 'LeagueClientUx.exe',
    'LeagueClientUxRender.exe', 'League of Legends.exe',
}
_CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_operation_lock = threading.RLock()


class PenguStatus(Enum):
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: Optional[int]
    stdout: str = ''
    stderr: str = ''

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


def _is_windows() -> bool:
    return sys.platform == 'win32'


def _is_available() -> bool:
    return _is_windows() and PENGU_EXE.exists()


def is_available() -> bool:
    return _is_available()


def _signed_exit_code(code: int) -> int:
    return code - 2**32 if code >= 2**31 else code


def _run_cli_result(args: Sequence[str], ok_codes: Iterable[int] = (0,)) -> Optional[CommandResult]:
    expected = tuple(ok_codes)
    command_args = tuple(str(arg) for arg in args)
    if not _is_available():
        log.warning('Pengu Loader executable is unavailable: %s', PENGU_EXE)
        return None

    command = [str(PENGU_EXE), *command_args]
    try:
        result = subprocess.run(
            command, cwd=str(PENGU_DIR), text=True, capture_output=True,
            check=False, creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        log.error('Pengu Loader executable is missing at %s', PENGU_EXE)
        return None
    except OSError as exc:
        log.error('Failed to launch Pengu Loader CLI %s: %s', command, exc)
        return None

    stdout = (result.stdout or '').strip()
    stderr = (result.stderr or '').strip()
    returncode = result.returncode
    command_result = CommandResult(command_args, returncode, stdout, stderr)
    if returncode not in expected:
        signed = _signed_exit_code(returncode) if returncode is not None else None
        unsigned = (returncode & 0xFFFFFFFF) if returncode is not None else None
        log.error(
            'Pengu command failed: command=%s exit_code=%s signed_exit_code=%s hex=%s stdout=%r stderr=%r',
            ' '.join(command), returncode, signed,
            hex(unsigned) if unsigned is not None else None, stdout, stderr,
        )
    else:
        if stdout:
            log.debug('Pengu Loader CLI stdout: %s', stdout)
        if stderr:
            log.debug('Pengu Loader CLI stderr: %s', stderr)
    return command_result


def _run_cli(args: Sequence[str], ok_codes: Iterable[int] = (0,)) -> bool:
    expected = tuple(ok_codes)
    result = _run_cli_result(args, expected)
    return result is not None and result.returncode in expected


def _is_league_running() -> bool:
    if not _is_windows() or psutil is None:
        return False
    try:
        for proc in psutil.process_iter(['name']):
            if proc.info.get('name') in _LEAGUE_PROCESSES:
                return True
    except (psutil.Error, OSError) as exc:  # type: ignore[attr-defined]
        log.debug('Failed to inspect running League processes: %s', exc)
    return False


def set_league_path(league_path: str) -> bool:
    if not _is_available():
        log.warning('Pengu Loader is unavailable; cannot set League path.')
        return False
    if not league_path or not league_path.strip():
        log.warning('Empty League path provided; skipping --set-league-path.')
        return False
    path = league_path.strip()
    log.info('Setting League path: executable=%s league_path=%s', PENGU_EXE, path)
    with _operation_lock:
        return _run_cli(['--set-league-path', path, '--silent'])


def get_status() -> PenguStatus:
    with _operation_lock:
        result = _run_cli_result(['--status', '--silent'], ok_codes=(0, 1))
    if result is None:
        return PenguStatus.UNKNOWN
    output = f'{result.stdout}\n{result.stderr}'.upper()
    if re.search(r'\bINACTIVE\b', output):
        return PenguStatus.INACTIVE
    if re.search(r'\bACTIVE\b', output):
        return PenguStatus.ACTIVE
    if result.returncode == 0:
        return PenguStatus.ACTIVE
    if result.returncode == 1:
        return PenguStatus.INACTIVE
    return PenguStatus.UNKNOWN


def activate() -> bool:
    with _operation_lock:
        result = _run_cli_result(['--install', '--activate', '--silent'])
        if result is None or not result.succeeded:
            log.error('Pengu activation failed.')
            return False
        status = get_status()
        if status is not PenguStatus.ACTIVE:
            log.error('Pengu activation command succeeded, but status is %s.', status.value)
            return False
        return True


def deactivate() -> bool:
    with _operation_lock:
        result = _run_cli_result(['--uninstall', '--deactivate', '--silent'])
        if result is None or not result.succeeded:
            log.error('Pengu deactivation failed.')
            return False
        status = get_status()
        if status is not PenguStatus.INACTIVE:
            log.error('Pengu deactivation command succeeded, but status is %s.', status.value)
            return False
        return True


def restart_client() -> bool:
    with _operation_lock:
        return _run_cli(['--restart-client', '--silent'])


def _write_active_flag() -> None:
    try:
        _ACTIVE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        _ACTIVE_FLAG.write_text('active', encoding='utf-8')
    except OSError as exc:
        log.error('Failed to write legacy Pengu active flag %s: %s', _ACTIVE_FLAG, exc)


def _clear_active_flag() -> None:
    try:
        _ACTIVE_FLAG.unlink(missing_ok=True)
    except OSError as exc:
        log.warning('Failed to clear legacy Pengu active flag %s: %s', _ACTIVE_FLAG, exc)


def _read_session() -> Optional[dict[str, object]]:
    try:
        if not _SESSION_FILE.exists():
            return None
        data = json.loads(_SESSION_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError) as exc:
        log.error('Could not read Pengu session state %s: %s', _SESSION_FILE, exc)
        return None


def _write_session(was_active: bool, rose_activated: bool) -> bool:
    record = {
        'version': 1,
        'rose_pid': os.getpid(),
        'pengu_was_active_before_rose': was_active,
        'rose_activated_pengu': rose_activated,
        'activated_at': datetime.now().astimezone().isoformat(),
    }
    temporary = _SESSION_FILE.with_suffix(f'{_SESSION_FILE.suffix}.tmp')
    try:
        _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        temporary.replace(_SESSION_FILE)
        return True
    except OSError as exc:
        log.error('Failed to write Pengu session state %s: %s', _SESSION_FILE, exc)
        return False


def _clear_session() -> None:
    try:
        _SESSION_FILE.unlink(missing_ok=True)
    except OSError as exc:
        log.warning('Failed to clear Pengu session state %s: %s', _SESSION_FILE, exc)


def _session_requires_deactivation(session: dict[str, object]) -> bool:
    return bool(session.get('rose_activated_pengu')) and not bool(
        session.get('pengu_was_active_before_rose')
    )


def recover_stale_session() -> bool:
    with _operation_lock:
        session = _read_session()
        legacy = _ACTIVE_FLAG.exists()
        if session is None and not legacy:
            return False
        if session is not None:
            if _session_requires_deactivation(session):
                status = get_status()
                if status is PenguStatus.UNKNOWN:
                    log.error('Cannot recover stale Pengu session because status is unknown.')
                    return False
                if status is PenguStatus.ACTIVE and not deactivate():
                    log.error('Failed to recover stale Pengu session; keeping state.')
                    return False
            _clear_session()
            if legacy:
                _clear_active_flag()
            return True
        log.info('Detected legacy Pengu active flag; running migration deactivation.')
        if not deactivate():
            log.error('Legacy Pengu session recovery failed; keeping the active flag.')
            return False
        _clear_active_flag()
        return True


def cleanup_if_dirty() -> bool:
    return recover_stale_session()


def activate_on_start(league_path: Optional[str] = None) -> bool:
    with _operation_lock:
        if not _is_available():
            log.error('Pengu Loader executable is unavailable: %s', PENGU_EXE)
            return False
        if _SESSION_FILE.exists() or _ACTIVE_FLAG.exists():
            if not recover_stale_session():
                return False

        initial = get_status()
        if initial is PenguStatus.UNKNOWN:
            log.error('Cannot start Rose Pengu integration because initial status is unknown.')
            return False
        if league_path and not set_league_path(league_path):
            log.warning(
                'Could not configure League path: executable=%s league_path=%r',
                PENGU_EXE, league_path,
            )

        restart_needed = initial is PenguStatus.INACTIVE and _is_league_running()
        rose_activated = False
        if initial is PenguStatus.INACTIVE:
            log.info('Activating Pengu through official CLI (restart League: %s).', restart_needed)
            if not activate():
                return False
            rose_activated = True
        else:
            log.info('Pengu was already active before Rose; preserving it.')

        if not _write_session(initial is PenguStatus.ACTIVE, rose_activated):
            if rose_activated:
                log.error('Could not persist session state; reverting activation.')
                deactivate()
            return False
        if restart_needed and not restart_client():
            log.warning(
                'Pengu was activated, but League could not be restarted automatically. '
                'Please close and reopen the League client.'
            )
        return True


def restore_after_rose() -> bool:
    with _operation_lock:
        session = _read_session()
        legacy = _ACTIVE_FLAG.exists()
        if session is None and not legacy:
            return True
        should_deactivate = (
            _session_requires_deactivation(session) if session is not None else True
        )
        if should_deactivate:
            restart_needed = _is_league_running()
            if not _is_available():
                log.error('Cannot restore Pengu state; executable is unavailable: %s', PENGU_EXE)
                return False
            log.info('Deactivating Pengu through official CLI.')
            if not deactivate():
                log.error('Pengu deactivation failed; keeping recovery state.')
                return False
            if restart_needed and not restart_client():
                log.warning(
                    'Pengu was deactivated, but League could not be restarted automatically. '
                    'Please close and reopen the League client to unload the plugins.'
                )
        _clear_session()
        if legacy:
            _clear_active_flag()
        return True


def deactivate_on_exit() -> bool:
    return restore_after_rose()
