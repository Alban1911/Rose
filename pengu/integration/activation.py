"""Direct in-process Pengu activation coordinator."""

from __future__ import annotations

import ctypes
import re
import sys
import threading
from pathlib import Path
from typing import Any

from utils.core.logging import get_logger

from . import runtime
from .league import is_league_running, restart_client
from .models import (
    ActivationErrorKind,
    ActivationResult,
    ActivationStage,
    PenguStatus,
)
from .registry import (
    DEBUGGER_VALUE,
    ERROR_FILE_NOT_FOUND,
    ERROR_PATH_NOT_FOUND,
    IFEO_PATH,
    KEY_CREATE_SUB_KEY,
    KEY_QUERY_VALUE,
    KEY_SET_VALUE,
    RegistryApi,
    RegistryError,
    TARGET_NAME,
    Win32RegistryApi,
)
from .session import (
    ACTIVE_FLAG,
    clear_session,
    has_legacy_state,
    migrate_legacy_state,
    read_session,
    recovery_present,
    session_requires_deactivation,
    write_session,
)


log = get_logger("pengu")
_operation_lock = threading.RLock()
_TARGET_PATH = IFEO_PATH + "\\" + TARGET_NAME


def _kind_for_code(code: int) -> ActivationErrorKind:
    return {
        2: ActivationErrorKind.NOT_FOUND,
        3: ActivationErrorKind.NOT_FOUND,
        5: ActivationErrorKind.PERMISSION_DENIED,
        87: ActivationErrorKind.INVALID_INPUT,
        183: ActivationErrorKind.OTHER,
    }.get(code, ActivationErrorKind.OTHER)


def _failure_from_exception(
    stage: ActivationStage,
    exc: BaseException,
    *,
    registry_active: bool | None = None,
    config_updated: bool | None = None,
) -> ActivationResult:
    code = int(getattr(exc, "code", getattr(exc, "winerror", 0)) or 0)
    kind = _kind_for_code(code)
    message = str(exc)
    log.error(
        "[Pengu] stage=%s error_kind=%s win32=%s registry_active=%s config_updated=%s message=%s",
        stage.value,
        kind.value,
        code,
        registry_active,
        config_updated,
        message,
    )
    return ActivationResult.failure(
        stage,
        kind,
        native_error_code=code,
        message=message,
        registry_active=registry_active,
        config_updated=config_updated,
    )


def is_elevated() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _registry_or_none(registry: RegistryApi | None) -> RegistryApi | None:
    if registry is not None:
        return registry
    try:
        return Win32RegistryApi()
    except OSError as exc:
        log.error("[Pengu] Direct registry backend unavailable: %s", exc)
        return None


def _normalize_path(value: str | None) -> str:
    return (value or "").replace("/", "\\").lower()


def build_debugger_command(core_path: Path) -> str:
    return f'rundll32 "{core_path}", #6000'


def extract_quoted_path(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.lstrip()
    if not re.match(r"^rundll32(?:\.exe)?(?:\s|$)", stripped, re.IGNORECASE):
        return None
    start = value.find('"')
    if start < 0:
        return None
    end = value.find('"', start + 1)
    if end < 0:
        return None
    return value[start + 1:end]


def _query_debugger(
    registry: RegistryApi,
) -> tuple[str | None, ActivationResult | None]:
    try:
        with registry.open_key(_TARGET_PATH, KEY_QUERY_VALUE) as target:
            return registry.query_string(target, DEBUGGER_VALUE), None
    except RegistryError as exc:
        if exc.code in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
            return None, None
        return None, _failure_from_exception(ActivationStage.QUERY_DEBUGGER, exc)


def get_status(
    registry: RegistryApi | None = None,
    core_path: Path | None = None,
) -> PenguStatus:
    if registry is None and sys.platform != "win32":
        return PenguStatus.UNKNOWN

    try:
        directory = runtime.get_runtime_dir()
        expected = core_path or runtime.get_core_path(directory)
    except OSError as exc:
        log.error("[Pengu] Could not resolve runtime for status: %s", exc)
        return PenguStatus.UNKNOWN

    backend = _registry_or_none(registry)
    if backend is None:
        return PenguStatus.UNKNOWN

    value, failure = _query_debugger(backend)
    if failure is not None:
        return PenguStatus.UNKNOWN
    if value is None:
        return PenguStatus.INACTIVE

    extracted = extract_quoted_path(value)
    if extracted is None:
        return PenguStatus.CONFLICT
    if _normalize_path(extracted) == _normalize_path(str(expected)):
        return PenguStatus.ACTIVE
    return PenguStatus.CONFLICT


def _set_debugger(
    registry: RegistryApi,
    core_path: Path,
) -> ActivationResult:
    command = build_debugger_command(core_path)
    try:
        with registry.open_key( IFEO_PATH, KEY_CREATE_SUB_KEY) as ifeo:
            log.debug("[Pengu][IFEO] stage=open_ifeo access=0x%04x", KEY_CREATE_SUB_KEY)
            with registry.create_subkey(ifeo, TARGET_NAME, KEY_SET_VALUE)[0] as target:
                log.debug("[Pengu][IFEO] stage=create_target access=0x%04x", KEY_SET_VALUE)
                registry.set_string(target, DEBUGGER_VALUE, command)
                log.info("[Pengu][IFEO] stage=set_debugger success=true")
        return ActivationResult.success(stage=ActivationStage.SET_DEBUGGER, registry_active=True)
    except RegistryError as exc:
        operation = getattr(exc, "operation", "")
        stage = (
            ActivationStage.OPEN_IFEO
            if operation == "RegOpenKeyExW"
            else ActivationStage.CREATE_TARGET
            if operation == "RegCreateKeyExW"
            else ActivationStage.SET_DEBUGGER
        )
        return _failure_from_exception(stage, exc, registry_active=False)


def _delete_debugger(registry: RegistryApi) -> ActivationResult:
    try:
        with registry.open_key(_TARGET_PATH, KEY_SET_VALUE) as target:
            registry.delete_value(target, DEBUGGER_VALUE)
        log.info("[Pengu][IFEO] stage=delete_debugger success=true")
        return ActivationResult.success(
            stage=ActivationStage.DELETE_DEBUGGER,
            registry_active=False,
        )
    except RegistryError as exc:
        if exc.code in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
            log.info("[Pengu][IFEO] Debugger was already absent")
            return ActivationResult.success(
                stage=ActivationStage.DELETE_DEBUGGER,
                registry_active=False,
            )
        return _failure_from_exception(
            ActivationStage.DELETE_DEBUGGER,
            exc,
            registry_active=True,
        )


def _prepare() -> tuple[Path | None, ActivationResult | None]:
    try:
        directory = runtime.prepare_runtime()
        return directory, None
    except OSError as exc:
        return None, _failure_from_exception(
            ActivationStage.VALIDATE_RUNTIME,
            exc,
        )


def is_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return runtime.get_core_path().is_file()
    except OSError:
        return False


def set_league_path(league_path: str) -> ActivationResult:
    directory, failure = _prepare()
    if failure is not None:
        return failure
    try:
        runtime.write_pengu_config(league_path, directory)
        return ActivationResult.success(stage=ActivationStage.WRITE_PENGU_CONFIG)
    except (OSError, ValueError) as exc:
        return _failure_from_exception(ActivationStage.WRITE_PENGU_CONFIG, exc)


def activate(
    league_path: str,
    *,
    registry: RegistryApi | None = None,
) -> ActivationResult:
    with _operation_lock:
        directory, failure = _prepare()
        if failure is not None:
            return failure
        if registry is None and not is_elevated():
            return ActivationResult.failure(
                ActivationStage.CHECK_ELEVATION,
                ActivationErrorKind.PERMISSION_DENIED,
                message="Rose must run as administrator to activate Pengu.",
            )

        backend = _registry_or_none(registry)
        if backend is None:
            return ActivationResult.failure(
                ActivationStage.OPEN_IFEO,
                ActivationErrorKind.PERMISSION_DENIED,
                message="Direct IFEO registry access is unavailable.",
            )

        try:
            runtime.write_pengu_config(league_path, directory)
        except (OSError, ValueError) as exc:
            return _failure_from_exception(ActivationStage.WRITE_PENGU_CONFIG, exc)

        core_path = runtime.get_core_path(directory)
        current = get_status(backend, core_path)
        if current is PenguStatus.CONFLICT:
            return ActivationResult.failure(
                ActivationStage.QUERY_DEBUGGER,
                ActivationErrorKind.CONFLICT,
                message="Another IFEO debugger is already registered for LeagueClientUx.exe.",
            )
        if current is PenguStatus.UNKNOWN:
            return ActivationResult.failure(
                ActivationStage.QUERY_DEBUGGER,
                ActivationErrorKind.OTHER,
                message="Could not determine the existing IFEO debugger.",
            )

        rose_config_before = runtime.snapshot_rose_config()
        registry_changed = current is PenguStatus.INACTIVE
        if registry_changed:
            result = _set_debugger(backend, core_path)
            if not result:
                return result

        try:
            runtime.write_rose_config(True, directory)
        except (OSError, ValueError) as exc:
            rollback = _delete_debugger(backend) if registry_changed else ActivationResult.success()
            try:
                runtime.restore_rose_config(rose_config_before)
            except OSError as restore_exc:
                log.error("[Pengu] Could not restore Rose config: %s", restore_exc)
            if not rollback:
                return ActivationResult.failure(
                    ActivationStage.WRITE_ROSE_CONFIG,
                    ActivationErrorKind.PARTIAL_STATE,
                    message=f"{exc}; registry rollback failed",
                    registry_active=True,
                    config_updated=False,
                )
            return _failure_from_exception(
                ActivationStage.WRITE_ROSE_CONFIG,
                exc,
                registry_active=False,
                config_updated=False,
            )

        try:
            verified = get_status(backend, core_path)
            if verified is not PenguStatus.ACTIVE:
                raise OSError("IFEO verification did not report Rose as active")
        except (OSError, ValueError) as exc:
            rollback = _delete_debugger(backend) if registry_changed else ActivationResult.success()
            try:
                runtime.restore_rose_config(rose_config_before)
            except OSError as restore_exc:
                log.error("[Pengu] Could not restore Rose config: %s", restore_exc)
            if not rollback:
                return ActivationResult.failure(
                    ActivationStage.VERIFY_STATE,
                    ActivationErrorKind.PARTIAL_STATE,
                    message=f"{exc}; registry rollback failed",
                    registry_active=True,
                    config_updated=False,
                )
            return _failure_from_exception(
                ActivationStage.VERIFY_STATE,
                exc,
                registry_active=False,
                config_updated=False,
            )

        return ActivationResult.success(
            stage=ActivationStage.VERIFY_STATE,
            registry_active=True,
            config_updated=True,
        )


def deactivate(*, registry: RegistryApi | None = None) -> ActivationResult:
    with _operation_lock:
        directory, failure = _prepare()
        if failure is not None:
            return failure
        if registry is None and not is_elevated():
            return ActivationResult.failure(
                ActivationStage.CHECK_ELEVATION,
                ActivationErrorKind.PERMISSION_DENIED,
                message="Rose must run as administrator to deactivate Pengu.",
            )

        backend = _registry_or_none(registry)
        if backend is None:
            return ActivationResult.failure(
                ActivationStage.DELETE_DEBUGGER,
                ActivationErrorKind.PERMISSION_DENIED,
                message="Direct IFEO registry access is unavailable.",
            )

        core_path = runtime.get_core_path(directory)
        current = get_status(backend, core_path)
        if current is PenguStatus.CONFLICT:
            return ActivationResult.failure(
                ActivationStage.QUERY_DEBUGGER,
                ActivationErrorKind.CONFLICT,
                message="The IFEO debugger is not owned by Rose.",
            )
        if current is PenguStatus.UNKNOWN:
            return ActivationResult.failure(
                ActivationStage.QUERY_DEBUGGER,
                ActivationErrorKind.OTHER,
                message="Could not determine the existing IFEO debugger.",
            )

        rose_config_before = runtime.snapshot_rose_config()
        if current is PenguStatus.ACTIVE:
            result = _delete_debugger(backend)
            if not result:
                return result

        def rollback_failure(stage: ActivationStage, exc: BaseException) -> ActivationResult:
            registry_restored = True
            if current is PenguStatus.ACTIVE:
                rollback = _set_debugger(backend, core_path)
                registry_restored = bool(rollback)

            config_restored = True
            try:
                runtime.restore_rose_config(rose_config_before)
            except OSError as restore_exc:
                config_restored = False
                log.error(
                    "[Pengu] Could not restore Rose config after deactivation failure: %s",
                    restore_exc,
                )

            if not registry_restored or not config_restored:
                return ActivationResult.failure(
                    stage,
                    ActivationErrorKind.PARTIAL_STATE,
                    message=f"{exc}; deactivation rollback incomplete",
                    registry_active=current is PenguStatus.ACTIVE and registry_restored,
                    config_updated=config_restored,
                )

            return _failure_from_exception(
                stage,
                exc,
                registry_active=current is PenguStatus.ACTIVE,
                config_updated=False,
            )

        try:
            runtime.write_rose_config(False, directory)
        except (OSError, ValueError) as exc:
            return rollback_failure(ActivationStage.WRITE_ROSE_CONFIG, exc)

        verified = get_status(backend, core_path)
        if verified is not PenguStatus.INACTIVE:
            return rollback_failure(
                ActivationStage.VERIFY_STATE,
                OSError("IFEO verification did not report Rose as inactive"),
            )

        return ActivationResult.success(
            stage=ActivationStage.VERIFY_STATE,
            registry_active=False,
            config_updated=True,
        )


def cleanup_if_dirty(
    lcu: Any = None,
    *,
    adopt_active: bool = True,
    registry: RegistryApi | None = None,
) -> ActivationResult:
    with _operation_lock:
        if has_legacy_state() and not read_session():
            migrate_legacy_state()

        if not recovery_present():
            return ActivationResult.success()

        session = read_session()
        if not session:
            return ActivationResult.failure(
                ActivationStage.WRITE_SESSION,
                ActivationErrorKind.OTHER,
                message="Pengu recovery state is unreadable.",
            )

        if session_requires_deactivation(session):
            status = get_status(registry)
            if status is PenguStatus.UNKNOWN:
                return ActivationResult.failure(
                    ActivationStage.QUERY_DEBUGGER,
                    ActivationErrorKind.OTHER,
                    message="Cannot recover Pengu while status is unknown.",
                )
            if status is PenguStatus.CONFLICT:
                return ActivationResult.failure(
                    ActivationStage.QUERY_DEBUGGER,
                    ActivationErrorKind.CONFLICT,
                    message="Cannot recover because IFEO is owned by another debugger.",
                )
            if status is PenguStatus.ACTIVE:
                if adopt_active and is_league_running():
                    log.info("[Pengu] Adopted active stale session while League is running")
                    return ActivationResult.success(registry_active=True)
                result = deactivate(registry=registry)
                if not result:
                    return result

        clear_session()
        return ActivationResult.success(registry_active=False)


def activate_on_start(
    league_path: str,
    lcu: Any = None,
    *,
    registry: RegistryApi | None = None,
) -> ActivationResult:
    with _operation_lock:
        stale_session = read_session()
        stale_owned = session_requires_deactivation(stale_session)

        recovery = cleanup_if_dirty(lcu, adopt_active=True, registry=registry)
        if not recovery:
            return recovery

        initial = get_status(registry)
        if initial is PenguStatus.UNKNOWN:
            return ActivationResult.failure(
                ActivationStage.QUERY_DEBUGGER,
                ActivationErrorKind.OTHER,
                message="Cannot start Pengu because status is unknown.",
            )
        if initial is PenguStatus.CONFLICT:
            return ActivationResult.failure(
                ActivationStage.QUERY_DEBUGGER,
                ActivationErrorKind.CONFLICT,
                message="Another IFEO debugger is active for LeagueClientUx.exe.",
            )

        result = activate(league_path, registry=registry)
        if not result:
            return result

        rose_activated = initial is PenguStatus.INACTIVE or stale_owned
        was_active = not rose_activated

        if not write_session(was_active, rose_activated):
            rollback = deactivate(registry=registry) if rose_activated else ActivationResult.success()
            if not rollback:
                return ActivationResult.failure(
                    ActivationStage.WRITE_SESSION,
                    ActivationErrorKind.PARTIAL_STATE,
                    message="Session write and activation rollback both failed.",
                    registry_active=True,
                    config_updated=True,
                )
            return ActivationResult.failure(
                ActivationStage.WRITE_SESSION,
                ActivationErrorKind.OTHER,
                message="Could not persist Pengu session state.",
                registry_active=False,
                config_updated=False,
            )

        if rose_activated and is_league_running():
            if not restart_client(lcu):
                return ActivationResult.failure(
                    ActivationStage.RESTART_CLIENT,
                    ActivationErrorKind.OTHER,
                    message="Pengu is active, but League Client UX could not be restarted.",
                    registry_active=True,
                    config_updated=True,
                )

        return ActivationResult.success(
            stage=ActivationStage.VERIFY_STATE,
            registry_active=True,
            config_updated=True,
        )


def restore_after_rose(lcu: Any = None, *, registry: RegistryApi | None = None) -> ActivationResult:
    with _operation_lock:
        if has_legacy_state() and not read_session():
            migrate_legacy_state()

        session = read_session()
        if not session:
            return ActivationResult.success()

        if session_requires_deactivation(session):
            running = is_league_running()
            result = deactivate(registry=registry)
            if not result:
                log.error("[Pengu] Deactivation failed; keeping recovery state")
                return result
            if running and not restart_client(lcu):
                return ActivationResult.failure(
                    ActivationStage.RESTART_CLIENT,
                    ActivationErrorKind.OTHER,
                    message="Pengu was deactivated, but League Client UX could not restart.",
                    registry_active=False,
                    config_updated=True,
                )
            clear_session()
            return ActivationResult.success(registry_active=False, config_updated=True)

        clear_session()
        return ActivationResult.success()


def deactivate_on_exit(lcu: Any = None, *, registry: RegistryApi | None = None) -> ActivationResult:
    return restore_after_rose(lcu, registry=registry)


def recover_stale_session(
    lcu: Any = None,
    *,
    adopt_active: bool = False,
    registry: RegistryApi | None = None,
) -> ActivationResult:
    return cleanup_if_dirty(lcu, adopt_active=adopt_active, registry=registry)


PENGU_DIR = runtime.PENGU_DIR
PENGU_CORE = runtime.PENGU_CORE