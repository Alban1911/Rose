"""Persistent ownership state for direct Pengu activation."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.core.logging import get_logger
from utils.core.paths import get_state_dir


log = get_logger("pengu")
SESSION_FILE = get_state_dir() / "pengu_session.json"
ACTIVE_FLAG = get_state_dir() / "pengu_active.flag"


def read_session() -> dict[str, Any] | None:
    try:
        if not SESSION_FILE.exists():
            return None
        value = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError) as exc:
        log.error("Could not read Pengu session state %s: %s", SESSION_FILE, exc)
        return None


def write_session(was_active: bool, rose_activated: bool) -> bool:
    record = {
        "version": 2,
        "rose_pid": os.getpid(),
        "pengu_was_active_before_rose": was_active,
        "rose_activated_pengu": rose_activated,
        "activated_at": datetime.now().astimezone().isoformat(),
    }
    temporary = SESSION_FILE.with_suffix(SESSION_FILE.suffix + ".tmp")
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        temporary.replace(SESSION_FILE)
        return True
    except OSError as exc:
        log.error("Failed to write Pengu session state %s: %s", SESSION_FILE, exc)
        return False


def clear_session() -> None:
    try:
        SESSION_FILE.unlink(missing_ok=True)
        ACTIVE_FLAG.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Failed to clear Pengu session state: %s", exc)


def has_legacy_state() -> bool:
    return ACTIVE_FLAG.exists()


def session_requires_deactivation(session: dict[str, Any] | None) -> bool:
    return bool(session and session.get("rose_activated_pengu"))


def migrate_legacy_state() -> bool:
    if not ACTIVE_FLAG.exists():
        return False
    if SESSION_FILE.exists():
        return True
    return write_session(False, True)


def recovery_present() -> bool:
    return SESSION_FILE.exists() or ACTIVE_FLAG.exists()