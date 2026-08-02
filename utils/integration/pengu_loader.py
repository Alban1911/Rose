"""Compatibility facade for Rose's direct Pengu integration.

The implementation now lives in pengu.integration. This module remains as a
short-lived import facade for existing Rose call sites and third-party code.
"""

from __future__ import annotations

from pathlib import Path

from pengu.integration.activation import (
    PENGU_CORE,
    PENGU_DIR,
    activate as _activate,
    activate_on_start,
    cleanup_if_dirty,
    deactivate,
    deactivate_on_exit,
    get_status,
    is_available,
    recover_stale_session,
    restore_after_rose,
    set_league_path,
)
from pengu.integration.league import is_league_running, restart_client
from pengu.integration.models import ActivationErrorKind, ActivationResult, ActivationStage, PenguStatus
from pengu.integration.runtime import remove_legacy_logs


def activate(league_path: str | None = None, *, registry=None) -> ActivationResult:
    if not league_path:
        league_path = _read_configured_league_path()
    if not league_path:
        return ActivationResult.failure(
            ActivationStage.WRITE_PENGU_CONFIG,
            ActivationErrorKind.INVALID_INPUT,
            message="League path is required for activation.",
        )
    return _activate(league_path, registry=registry)


def _read_configured_league_path() -> str | None:
    path = PENGU_DIR / "config"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and line.split("=", 1)[0].strip().lower() == "leaguepath":
            value = line.split("=", 1)[1].strip()
            return value or None
    return None


def _remove_legacy_pengu_logs(pengu_dir: Path) -> None:
    remove_legacy_logs(pengu_dir)


__all__ = [
    "ActivationErrorKind",
    "ActivationResult",
    "ActivationStage",
    "PenguStatus",
    "PENGU_DIR",
    "PENGU_CORE",
    "activate",
    "activate_on_start",
    "cleanup_if_dirty",
    "deactivate",
    "deactivate_on_exit",
    "get_status",
    "is_available",
    "is_league_running",
    "recover_stale_session",
    "restart_client",
    "restore_after_rose",
    "set_league_path",
]
