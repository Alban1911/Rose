#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent pseudonymous installation identifier for analytics."""

import uuid
from pathlib import Path
from typing import Optional

from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir

log = get_logger()

INSTALL_ID_FILENAME = "analytics_install_id.txt"
_install_id_cache: Optional[str] = None


def _read_install_id(path: Path) -> Optional[str]:
    try:
        value = path.read_text(encoding="utf-8").strip()
        parsed = uuid.UUID(value)
    except (OSError, ValueError):
        return None

    return str(parsed)


def get_install_id() -> str:
    """Return the stable, randomly generated ID for this Rose installation."""
    global _install_id_cache

    if _install_id_cache is not None:
        return _install_id_cache

    user_data_dir = get_user_data_dir()
    install_id_path = user_data_dir / INSTALL_ID_FILENAME
    existing_id = _read_install_id(install_id_path)
    if existing_id:
        _install_id_cache = existing_id
        return existing_id

    new_id = str(uuid.uuid4())
    try:
        user_data_dir.mkdir(parents=True, exist_ok=True)
        install_id_path.write_text(new_id, encoding="utf-8")
    except OSError as exc:
        log.warning("Unable to persist analytics installation ID: %s", exc)

    _install_id_cache = new_id
    return new_id
