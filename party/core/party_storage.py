#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Party Storage
Keeps each account's party key across sessions, so the token (and room)
friends already have keeps working after Rose restarts.
"""

import json
import secrets
from pathlib import Path

from utils.core.atomic_file import write_text_atomic
from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir

log = get_logger()

PARTY_KEYS_FILE = "party_keys.json"
PARTY_IDENTITY_KEYS_FILE = "party_identity_keys.json"
KEY_SIZE = 32


def _keys_path() -> Path:
    return get_user_data_dir() / PARTY_KEYS_FILE


def load_party_key(summoner_id: int) -> bytes:
    """Return this account's party key, creating and saving one if needed."""
    path = _keys_path()
    keys = {}
    try:
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                keys = loaded
    except (OSError, ValueError) as e:
        log.debug(f"[PARTY] Could not read party keys: {e}")

    stored = keys.get(str(summoner_id))
    if isinstance(stored, str):
        try:
            key = bytes.fromhex(stored)
            if len(key) == KEY_SIZE:
                return key
        except ValueError:
            pass

    key = secrets.token_bytes(KEY_SIZE)
    keys[str(summoner_id)] = key.hex()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(keys, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError as e:
        # Still usable for this session; the token just changes next time
        log.warning(f"[PARTY] Could not save party key: {e}")
    return key


def load_party_identity_key(summoner_id: int) -> bytes:
    """Load or create the private key used to claim this account in rooms.

    The relay holds an ID for a credential only while it is connected, so a
    lost key costs what a reinstall does: friends who saw the old one this
    session ignore the new one until they turn Party Mode off and on.
    """
    path = get_user_data_dir() / PARTY_IDENTITY_KEYS_FILE
    keys = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            keys = loaded
    except FileNotFoundError:
        pass
    except OSError as error:
        # Locked for now (antivirus...): fail rather than replace a key a retry would find
        log.warning("[PARTY] Could not read party identity keys: %s", error)
        raise RuntimeError("Couldn't read your Party Mode identity key") from error
    except ValueError as error:
        log.warning("[PARTY] Party identity keys are corrupt, making a new key: %s", error)

    stored = keys.get(str(summoner_id))
    if isinstance(stored, str):
        try:
            key = bytes.fromhex(stored)
            if len(key) == KEY_SIZE:
                return key
        except ValueError:
            pass

    key = secrets.token_bytes(KEY_SIZE)
    keys[str(summoner_id)] = key.hex()
    try:
        write_text_atomic(path, json.dumps(keys, indent=2))
    except OSError as error:
        # Next session joins with a new key, like after a reinstall
        log.warning("[PARTY] Could not save party identity key: %s", error)
    return key
