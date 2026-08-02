"""Direct Pengu integration package."""

from .activation import (
    PENGU_CORE,
    PENGU_DIR,
    activate,
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
from .league import is_league_running, restart_client
from .models import ActivationErrorKind, ActivationResult, ActivationStage, PenguStatus

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