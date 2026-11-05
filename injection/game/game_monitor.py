#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Game Monitor
The game process around an injection: when its game is over, and releasing a
game left frozen.

While LTK Manager's patcher builds the overlay, a game the client creates is
held (suspended) until the patcher scans, then restarted (kill + reconnect,
see injection/overlay/overlay_manager.py and injection/game/reconnect.py):
the patcher never overlays a game created before its scan, nor hooks a
frozen one.
"""

from typing import Callable

# Import psutil with fallback for development environments
try:
    import psutil
    PSUTIL_AVAILABLE = True
    STATUS_STOPPED = psutil.STATUS_STOPPED
    NoSuchProcess = psutil.NoSuchProcess
    AccessDenied = psutil.AccessDenied
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None
    STATUS_STOPPED = 'stopped'
    NoSuchProcess = Exception
    AccessDenied = PermissionError

from config import GAME_EXECUTABLE_NAMES
from utils.core.logging import get_logger

log = get_logger()
_GAME_PROCESS_NAMES = frozenset(name.lower() for name in GAME_EXECUTABLE_NAMES)


def make_game_ended_callback(state) -> Callable[[], bool]:
    """Stop callback for an injection: True once the game it was made for is over.

    The LTK patcher keeps running through reconnects, so every injection must
    pass one: without it the patcher runs until a later cleanup kills it.

    Args:
        state: Shared application state (its phase is polled)
    """
    has_been_in_progress = False

    def game_ended_callback() -> bool:
        nonlocal has_been_in_progress
        phase = state.phase
        if phase == "InProgress":
            has_been_in_progress = True
            return False
        if phase in ("Reconnect", "GameStart"):
            return False
        return has_been_in_progress

    return game_ended_callback


def resume_orphaned_game() -> int:
    """Resume a game left suspended: by a Rose that died while it held the
    game for the patcher (at startup), or held when Rose exits (cleanup).

    Without it the game stays frozen until the user kills it.
    Returns how many game processes were resumed.
    """
    if not PSUTIL_AVAILABLE:
        return 0
    resumed = 0
    try:
        processes = list(psutil.process_iter(['name', 'pid']))
    except Exception as e:
        log.warning(f"[monitor] Could not look for a suspended game: {e}")
        return 0
    for proc in processes:
        if (proc.info.get('name') or '').lower() not in _GAME_PROCESS_NAMES:
            continue
        try:
            if proc.status() != STATUS_STOPPED:
                continue
            proc.resume()
            resumed += 1
            log.warning(f"[monitor] Resumed a game left suspended (PID={proc.info['pid']})")
        except (NoSuchProcess, AccessDenied) as e:
            log.warning(f"[monitor] Could not resume the suspended game (PID={proc.info['pid']}): {e}")
    return resumed
