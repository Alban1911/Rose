"""Structured results for Rose's direct Pengu integration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PenguStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class ActivationStage(str, Enum):
    NONE = "none"
    VALIDATE_RUNTIME = "validate_runtime"
    CHECK_ELEVATION = "check_elevation"
    QUERY_DEBUGGER = "query_debugger"
    OPEN_IFEO = "open_ifeo"
    CREATE_TARGET = "create_target"
    SET_DEBUGGER = "set_debugger"
    DELETE_DEBUGGER = "delete_debugger"
    WRITE_PENGU_CONFIG = "write_pengu_config"
    WRITE_ROSE_CONFIG = "write_rose_config"
    WRITE_SESSION = "write_session"
    VERIFY_STATE = "verify_state"
    RESTART_CLIENT = "restart_client"


class ActivationErrorKind(str, Enum):
    NONE = "none"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    INVALID_INPUT = "invalid_input"
    CONFLICT = "conflict"
    PARTIAL_STATE = "partial_state"
    OTHER = "other"


@dataclass(frozen=True)
class ActivationResult:
    succeeded: bool
    stage: ActivationStage = ActivationStage.NONE
    error_kind: ActivationErrorKind = ActivationErrorKind.NONE
    native_error_code: int = 0
    message: str = ""
    registry_active: bool | None = None
    config_updated: bool | None = None

    @classmethod
    def success(
        cls,
        *,
        stage: ActivationStage = ActivationStage.NONE,
        registry_active: bool | None = None,
        config_updated: bool | None = None,
        message: str = "",
    ) -> "ActivationResult":
        return cls(
            True,
            stage,
            ActivationErrorKind.NONE,
            0,
            message,
            registry_active,
            config_updated,
        )

    @classmethod
    def failure(
        cls,
        stage: ActivationStage,
        error_kind: ActivationErrorKind,
        *,
        native_error_code: int = 0,
        message: str = "",
        registry_active: bool | None = None,
        config_updated: bool | None = None,
    ) -> "ActivationResult":
        return cls(
            False,
            stage,
            error_kind,
            native_error_code,
            message,
            registry_active,
            config_updated,
        )

    def describe(self) -> str:
        if self.succeeded:
            return "success"
        return f"{self.stage.value} ({self.error_kind.value})"

    def __bool__(self) -> bool:
        return self.succeeded