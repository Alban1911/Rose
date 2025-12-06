#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper utilities for interacting with Pengu Loader's command-line interface.

The Pengu Loader CLI is used to force activate/deactivate mods and optionally
restart the League client when required. This module provides a small wrapper
around the executable bundled alongside Rose.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - psutil is part of requirements, but guard just in case
    psutil = None  # type: ignore

from utils.core.logging import get_logger
from utils.core.paths import get_app_dir

log = get_logger("pengu_loader")


def _resolve_pengu_dir() -> Path:
    """Locate the Pengu Loader directory in dev and frozen builds."""
    # 1. PyInstaller onefile/onedir: resources live under _MEIPASS
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "Pengu Loader"
        if candidate.exists():
            return candidate

    # 2. Standard frozen build: alongside executable
    app_dir = get_app_dir()
    candidate = app_dir / "Pengu Loader"
    if candidate.exists():
        return candidate

    # 3. Development environment: relative to project root
    repo_dir = Path(__file__).resolve().parent.parent
    candidate = repo_dir / "Pengu Loader"
    if candidate.exists():
        return candidate

    # Fallback to app_dir (even if missing) so logging remains consistent
    return app_dir / "Pengu Loader"


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


