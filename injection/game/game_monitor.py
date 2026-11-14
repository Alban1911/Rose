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

import time
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
# How long a match outlives a client that is gone: restarting the client and
# reconnecting to the game takes well under it. Past it the client was closed
# for good or reopened on its home screen, and the session ends (a game still
# running is served until it exits, see OverlayManager._run_session)
CLIENT_OUTAGE_GRACE_S = 180.0
# How long champion select may read no phase before it counts as left. The
# client can stall for seconds while the game launches, and a client restarted
# in champion select comes back to it, so this is far longer than the brief
# gaps between phases; a client closed for good shows its home screen (no phase)
CHAMP_SELECT_OUTAGE_GRACE_S = 60.0
# The countdown keeps "FINALIZATION" while the client still reads ChampSelect
_CHAMP_SELECT_PHASES = ("ChampSelect", "FINALIZATION")


def make_game_ended_callback(state, clock: Callable[[], float] = time.monotonic) -> Callable[[], bool]:
    """Stop callback for an injection: True once the game it was made for is over.

    The LTK patcher keeps running through reconnects, so every injection must
    pass one: without it the patcher runs until a later cleanup kills it.

    Args:
        state: Shared application state (its phase is polled)
        clock: monotonic seconds, for the client outage's deadline
    """
    has_been_in_progress = False
    # Made in champion select: a dodge before the session polls still counts
    in_champ_select = getattr(state, "phase", None) in _CHAMP_SELECT_PHASES
    outage_since = None

    def game_ended_callback() -> bool:
        nonlocal has_been_in_progress, in_champ_select, outage_since
        if getattr(state, "stop", False):
            return True
        phase = state.phase
        if phase == "InProgress":
            has_been_in_progress = True
            outage_since = None
            return False
        if not has_been_in_progress:
            if phase in _CHAMP_SELECT_PHASES:
                in_champ_select = True
                outage_since = None
                return False
            if phase in ("GameStart", "Reconnect"):
                in_champ_select = False  # the game launches
            if not in_champ_select:
                return False
            # Champion select ended without a game (a dodge, the client closed):
            # no later cleanup ends the session, and it holds the next injection.
            # The poller writes the home screen as None, the WebSocket as "None"
            if phase in (None, "None"):
                if outage_since is None:
                    outage_since = clock()
                return clock() - outage_since >= CHAMP_SELECT_OUTAGE_GRACE_S
            return True
        if phase is None:
            # No phase: the client is gone (or on its home screen). It can close
            # and come back to Reconnect the match, which needs the patcher still
            # running (#413), so the match outlives it for a while, not forever
            if outage_since is None:
                outage_since = clock()
            return clock() - outage_since >= CLIENT_OUTAGE_GRACE_S
        outage_since = None
        return phase not in ("Reconnect", "GameStart")

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
