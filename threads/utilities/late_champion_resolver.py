#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Late champion resolution for Arena "random champion" matches.

In Arena a random champion can be handed to the player only when the game
starts: the LCU never publishes it during champ select, so the normal flow
(champion lock -> historic skin -> injection) never runs and Rose injects
nothing.

This module watches ``/lol-gameflow/v1/session`` right after the game starts,
matches the local player in ``teamOne``/``teamTwo`` by summoner id, and - if a
numeric historic skin exists for that champion - runs the normal injection
path late. Without a historic entry it falls back to a random downloaded skin
of that champion (Arena only, disable with
``[Debug] arena_late_fallback_local_skin = false``). A skin the client has
already applied itself (an owned one) is never overridden.

Best effort by design:
- only while the champion is still unknown (normal flow always wins),
- only on the GameStart/InProgress entry of a real game (never on a Rose
  started mid-match or on a Swiftplay game),
- once per game,
- every failure is logged and simply means "no skin"; the match is never
  touched (no LCU writes, no state reset).

Enable/disable with ``[Debug] arena_late_injection = false`` in config.ini.
"""

from __future__ import annotations

import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from config import (
    ARENA_LATE_FALLBACK_LOCAL_SKIN,
    ARENA_LATE_GAMEFLOW_PATH,
    ARENA_LATE_INJECTION_ENABLED,
    ARENA_LATE_LCU_TIMEOUT_S,
    ARENA_LATE_RESOLVE_INTERVAL_MS,
    ARENA_LATE_RESOLVE_TIMEOUT_S,
    ARENA_LATE_SUMMONER_PATH,
    get_config_option,
)
from injection.game.game_monitor import make_game_ended_callback
from utils.core.historic import get_historic_skin_for_champion, is_custom_mod_path
from utils.core.logging import get_logger
from utils.core.paths import get_skins_dir

log = get_logger()

_TRUTHY = {"1", "true", "yes", "on"}
_START_PHASES = frozenset({"GameStart", "InProgress"})
# Entering InProgress is only trusted right after the game itself started. A
# phase observed with no previous phase (Rose launched mid-match) or after a
# reconnect must not trigger an injection into a game that is already running.
_IN_PROGRESS_FROM = frozenset({"ChampSelect", "FINALIZATION", "GameStart"})
_HANDLED_KEYS_MAX = 8
_ARCHIVE_EXTENSIONS = (".zip", ".fantome")
_ARENA_MAP_ID = 30
_ARENA_QUEUE_IDS = frozenset({1700, 1740, 1750})
# A game frozen by the early monitor must not stay frozen while the resolver
# keeps retrying: past this point an injection would be too late anyway.
_SUSPENDED_WAIT_LIMIT_S = 6.0
# Phases that mean the game is over (or never started): release the monitor
# and the patcher a late injection may have prepared.
_RELEASE_PHASES = frozenset(
    {"ChampSelect", "Matchmaking", "ReadyCheck", "Lobby", "WaitingForStats", "EndOfGame"}
)


def enabled() -> bool:
    """Injection switch. ``[Debug] arena_late_injection`` wins over config.py."""
    raw = get_config_option("Debug", "arena_late_injection")
    if raw is None:
        return bool(ARENA_LATE_INJECTION_ENABLED)
    return raw.strip().lower() in _TRUTHY


def fallback_enabled() -> bool:
    """Random local skin when the champion has no historic entry (Arena only)."""
    raw = get_config_option("Debug", "arena_late_fallback_local_skin")
    if raw is None:
        return bool(ARENA_LATE_FALLBACK_LOCAL_SKIN)
    return raw.strip().lower() in _TRUTHY


def _lcu_get(lcu, path: str) -> Tuple[Any, Optional[str]]:
    """GET through Rose's LCU client, bypassing its GET cache (errors included)."""
    if lcu is None:
        return (None, "no LCU client")
    try:
        api = getattr(lcu, "_api", None)
        if api is not None:
            return (api.get(path, timeout=ARENA_LATE_LCU_TIMEOUT_S, use_cache=False), None)
        return (lcu.get(path, timeout=ARENA_LATE_LCU_TIMEOUT_S), None)
    except Exception as exc:  # noqa: BLE001 - a failed read only means "retry later"
        return (None, f"{type(exc).__name__}: {exc}")


def _same_id(left: Any, right: Any) -> bool:
    """Compare summoner ids that may come back as int or str."""
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return False


def find_my_champion(
    game_data: Optional[Dict[str, Any]], summoner_id: Any
) -> Tuple[Optional[str], Optional[int]]:
    """Return (team key, championId) for the local player.

    ``playerChampionSelections`` carries no summoner id, but ``teamOne`` and
    ``teamTwo`` do, which is the only way to tell *your* champion apart in
    Arena, where every player has one.
    """
    if not isinstance(game_data, dict) or summoner_id is None:
        return (None, None)
    for key in ("teamOne", "teamTwo"):
        members = game_data.get(key)
        if not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            champion = member.get("championId")
            if champion and _same_id(member.get("summonerId"), summoner_id):
                return (key, champion)
    return (None, None)


def find_my_skin_choice(
    game_data: Optional[Dict[str, Any]], summoner_id: Any
) -> Optional[int]:
    """Skin the client already applied for the local player (0 = base skin).

    The game flow only carries it for some payloads, hence Optional: without a
    value the caller keeps its own logic. A positive value means an *owned* skin
    is already in use, which the client will load on its own - there is nothing
    to inject (and no reason to override the player's choice).
    """
    if not isinstance(game_data, dict) or summoner_id is None:
        return None
    for key in ("teamOne", "teamTwo"):
        members = game_data.get(key)
        if not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            if not _same_id(member.get("summonerId"), summoner_id):
                continue
            for field in ("selectedSkinIndex", "selectedSkinId", "skinId"):
                value = member.get(field)
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
            return None
    return None


def build_injection_name(
    champion_id: int, historic_value: Any
) -> Tuple[Optional[str], Optional[str]]:
    """Turn a historic entry into an injection name.

    Returns ``(name, None)`` or ``(None, reason)``. Only numeric skin/chroma
    ids are supported: a historic custom mod needs its own selection flow,
    which is not worth replicating late in the loading screen.

    The ``skin_`` prefix is deliberate even for chromas: the zip resolver falls
    back to the chroma directory when the id is not a base skin.
    """
    if historic_value is None:
        return (None, "no historic skin for this champion")
    if is_custom_mod_path(historic_value):
        return (None, "historic entry is a custom mod (not supported late)")
    if isinstance(historic_value, bool) or not isinstance(historic_value, (int, str)):
        return (None, f"invalid historic entry {historic_value!r}")
    try:
        skin_id = int(historic_value)
        champion = int(champion_id)
    except (TypeError, ValueError):
        return (None, f"invalid historic entry {historic_value!r}")
    if skin_id <= 0:
        return (None, f"invalid historic skin id {skin_id}")
    if skin_id // 1000 != champion:
        return (None, f"skin {skin_id} does not belong to champion {champion}")
    return (f"skin_{skin_id}", None)


def local_skin_ids(champion_id: int, skins_dir: Optional[Path] = None) -> list:
    """Skin ids with a local archive for the champion (base skin excluded)."""
    try:
        base = Path(skins_dir) if skins_dir is not None else get_skins_dir()
        champ_dir = base / str(int(champion_id))
    except (TypeError, ValueError):
        return []
    if not champ_dir.is_dir():
        return []
    base_skin_id = int(champion_id) * 1000
    skin_ids = []
    try:
        entries = list(champ_dir.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        skin_id = int(entry.name)
        if skin_id <= 0 or skin_id == base_skin_id:
            continue
        if any((entry / f"{entry.name}{ext}").exists() for ext in _ARCHIVE_EXTENSIONS):
            skin_ids.append(skin_id)
    return sorted(skin_ids)


def pick_local_skin(champion_id: int, skins_dir: Optional[Path] = None) -> Optional[int]:
    """Random downloaded skin id for the champion, or None when nothing is local."""
    candidates = local_skin_ids(champion_id, skins_dir)
    return random.choice(candidates) if candidates else None


def is_arena(state) -> bool:
    """Whether the current game is Arena (where random champions happen)."""
    if getattr(state, "current_map_id", None) == _ARENA_MAP_ID:
        return True
    return getattr(state, "current_queue_id", None) in _ARENA_QUEUE_IDS


def expects_late_injection(state) -> bool:
    """Whether this game may need the late path (Arena, champion still unknown).

    Used before the game starts to keep the monitor and the patcher ready: the
    champion only appears at game start, so the injection cannot be prepared
    the normal way.
    """
    if not enabled():
        return False
    if getattr(state, "is_swiftplay_mode", False):
        return False
    if getattr(state, "locked_champ_id", None):
        return False
    return is_arena(state)


def _game_key(game_data: Dict[str, Any]) -> Optional[tuple]:
    """Stable per-match key, used to inject at most once per game."""
    game_id = game_data.get("gameId")
    if game_id:
        return ("game", game_id)
    champions = []
    for key in ("teamOne", "teamTwo"):
        members = game_data.get(key)
        if not isinstance(members, list):
            continue
        for member in members:
            if isinstance(member, dict):
                champions.append(member.get("championId") or 0)
    if not champions:
        return None
    return ("players", tuple(sorted(champions)))


class _LateInjectionSession:
    """Polls the gameflow until the local champion is known, then injects once."""

    def __init__(self, state, lcu, injection_manager, reason: str) -> None:
        self._state = state
        self._lcu = lcu
        self._injection_manager = injection_manager
        self._reason = reason
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._t0 = time.monotonic()
        self._summoner_id: Optional[Any] = None
        self._summoner_attempts = 0
        self._handled = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="arena-late-injection", daemon=True
        )
        self._thread.start()

    def stop(self, reason: str) -> None:
        if not self._stop_event.is_set():
            self._stop_event.set()
            log.debug("[arena-late] stop requested (%s)", reason)

    def is_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    # -- main loop ---------------------------------------------------------
    def _run(self) -> None:
        interval_s = max(ARENA_LATE_RESOLVE_INTERVAL_MS, 50) / 1000.0
        timeout_s = max(ARENA_LATE_RESOLVE_TIMEOUT_S, interval_s)
        deadline = self._t0 + timeout_s
        log.info(
            "[arena-late] start | reason=%s | interval=%dms | timeout=%ss | phase=%s | queue=%s",
            self._reason,
            ARENA_LATE_RESOLVE_INTERVAL_MS,
            ARENA_LATE_RESOLVE_TIMEOUT_S,
            getattr(self._state, "phase", None),
            getattr(self._state, "current_queue_id", None),
        )
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            try:
                outcome = self._attempt()
            except Exception as exc:  # noqa: BLE001 - the match must never be affected
                log.warning(
                    "[arena-late] attempt failed: %s: %s", type(exc).__name__, exc
                )
                outcome = "retry"
            if outcome == "done":
                return
            if outcome == "abort":
                return
            if self._game_is_waiting() and self.elapsed_ms() >= _SUSPENDED_WAIT_LIMIT_S * 1000:
                log.warning(
                    "[arena-late] giving up after %dms - the game is frozen and waiting",
                    self.elapsed_ms(),
                )
                break
            self._stop_event.wait(interval_s)
        if not self._handled:
            log.info(
                "[arena-late] giving up after %dms (champion not resolved)",
                self.elapsed_ms(),
            )
            self._release_game()

    def _game_is_waiting(self) -> bool:
        """Whether the early monitor froze the game while the champion resolves."""
        manager = self._injection_manager
        try:
            return bool(manager is not None and manager.is_game_suspended())
        except Exception:  # noqa: BLE001 - a broken manager must not block the retry loop
            return False

    def _release_game(self) -> None:
        """Resume the game and stop the patcher when no injection will happen."""
        manager = self._injection_manager
        if manager is None:
            return
        try:
            manager.abort_late_injection()
        except Exception as exc:  # noqa: BLE001 - releasing is best effort
            log.debug("[arena-late] could not release the early injection: %s", exc)

    def _attempt(self) -> str:
        phase = getattr(self._state, "phase", None)
        if phase not in _START_PHASES:
            log.info("[arena-late] abort: phase is now %s", phase)
            self._release_game()
            return "abort"
        if getattr(self._state, "is_swiftplay_mode", False):
            log.info("[arena-late] abort: Swiftplay game")
            self._release_game()
            return "abort"
        locked = getattr(self._state, "locked_champ_id", None)
        if locked:
            log.info("[arena-late] abort: champion already known (%s)", locked)
            self._release_game()
            return "abort"

        session, error = _lcu_get(self._lcu, ARENA_LATE_GAMEFLOW_PATH)
        if error or not isinstance(session, dict):
            return "retry"
        game_data = session.get("gameData")
        if not isinstance(game_data, dict):
            return "retry"

        summoner_id = self._my_summoner()
        if summoner_id is None:
            return "retry"

        team, champion_id = find_my_champion(game_data, summoner_id)
        if not champion_id:
            return "retry"

        key = _game_key(game_data)
        with _STATE_LOCK:
            if key is not None and key in _handled_keys:
                self._release_game()
                return "abort"
            if key is not None:
                _handled_keys.append(key)
                del _handled_keys[:-_HANDLED_KEYS_MAX]

        log.info(
            "[arena-late] resolved champion %s (summoner=%s team=%s) after %dms | queue=%s",
            champion_id,
            summoner_id,
            team,
            self.elapsed_ms(),
            getattr(self._state, "current_queue_id", None),
        )
        self._handled = True
        self._inject(champion_id, find_my_skin_choice(game_data, summoner_id))
        return "done"

    def _my_summoner(self) -> Optional[Any]:
        """Local summoner id, read once per session."""
        if self._summoner_id is not None or self._summoner_attempts >= 3:
            return self._summoner_id
        self._summoner_attempts += 1
        payload, _error = _lcu_get(self._lcu, ARENA_LATE_SUMMONER_PATH)
        if isinstance(payload, dict) and payload.get("summonerId"):
            self._summoner_id = payload["summonerId"]
        return self._summoner_id

    def _inject(self, champion_id: int, selected_skin: Optional[int] = None) -> None:
        """Inject the historic skin for the champion, if there is one."""
        try:
            historic = get_historic_skin_for_champion(champion_id)
        except Exception as exc:  # noqa: BLE001 - a broken historic file is not fatal
            log.warning("[arena-late] could not read historic skins: %s", exc)
            self._release_game()
            return

        name, reason = build_injection_name(champion_id, historic)
        source = "historic"
        if not name:
            if selected_skin is not None and selected_skin > 0:
                log.info(
                    "[arena-late] champion %s already runs its selected (owned) skin "
                    "%s - nothing to inject",
                    champion_id,
                    selected_skin,
                )
                self._release_game()
                return
            if not fallback_enabled() or not is_arena(self._state):
                log.info(
                    "[arena-late] champion %s resolved, nothing to inject: %s",
                    champion_id,
                    reason,
                )
                self._release_game()
                return
            skin_id = pick_local_skin(champion_id)
            if not skin_id:
                log.info(
                    "[arena-late] champion %s resolved, nothing to inject: %s "
                    "(no local skin either)",
                    champion_id,
                    reason,
                )
                self._release_game()
                return
            name = f"skin_{skin_id}"
            source = "random local"
            log.info(
                "[arena-late] champion %s: %s - falling back to local skin %s",
                champion_id,
                reason,
                skin_id,
            )

        if self._injection_manager is None:
            log.warning("[arena-late] no injection manager available")
            self._release_game()
            return

        log.info(
            "[arena-late] injecting %s (%s) for champion %s (%dms after start)",
            name,
            source,
            champion_id,
            self.elapsed_ms(),
        )
        try:
            success = self._injection_manager.inject_skin_immediately(
                name,
                stop_callback=make_game_ended_callback(self._state),
                champion_name=None,
                champion_id=champion_id,
            )
        except Exception as exc:  # noqa: BLE001 - never let injection break the game
            log.warning(
                "[arena-late] injection raised %s: %s", type(exc).__name__, exc
            )
            self._release_game()
            return

        log.info(
            "[arena-late] injection %s for %s",
            "completed" if success else "failed",
            name,
        )


_SESSION: Optional[_LateInjectionSession] = None
_SESSION_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_handled_keys: list = []
_served_game = False


def is_active() -> bool:
    session = _SESSION
    return session is not None and session.is_alive()


def maybe_start(
    *,
    state,
    lcu,
    injection_manager=None,
    phase: Optional[str],
    previous_phase: Optional[str] = None,
) -> bool:
    """Start resolving once per game. Returns False when not applicable."""
    global _SESSION, _served_game
    if phase not in _START_PHASES:
        return False
    if _served_game:
        return False
    if not enabled():
        return False
    if phase == "InProgress" and previous_phase not in _IN_PROGRESS_FROM:
        log.debug(
            "[arena-late] skip InProgress (entered from %s, not a game start)",
            previous_phase,
        )
        return False
    if getattr(state, "is_swiftplay_mode", False):
        return False
    if getattr(state, "locked_champ_id", None):
        return False

    with _SESSION_LOCK:
        if _SESSION is not None and _SESSION.is_alive():
            return False
        session = _LateInjectionSession(
            state, lcu, injection_manager, reason=f"{phase} (from {previous_phase})"
        )
        _SESSION = session
    try:
        session.start()
    except Exception as exc:  # noqa: BLE001 - a failed thread must not break the phase flow
        log.warning("[arena-late] could not start resolver thread: %s", exc)
        return False
    with _SESSION_LOCK:
        _served_game = True
    return True


def stop(reason: str = "manual") -> None:
    """Stop polling (also called when the game flow leaves the game)."""
    session = _SESSION
    if session is not None:
        session.stop(reason)


def on_phase_change(
    phase: Optional[str],
    previous_phase: Optional[str],
    *,
    state,
    lcu,
    injection_manager=None,
) -> None:
    """Single hook called for every gameflow phase change (see PhaseHandler)."""
    global _served_game
    if phase in _START_PHASES:
        maybe_start(
            state=state,
            lcu=lcu,
            injection_manager=injection_manager,
            phase=phase,
            previous_phase=previous_phase,
        )
    else:
        # Leaving the game (or champ select/lobby) ends the current match.
        _served_game = False
        stop(reason=str(phase))
        if phase in _RELEASE_PHASES and injection_manager is not None:
            # A late injection may have frozen the game and kept the patcher
            # scanning; release both once the game is over (or never started).
            try:
                injection_manager.abort_late_injection()
            except Exception as exc:  # noqa: BLE001 - releasing is best effort
                log.debug("[arena-late] could not release the early injection: %s", exc)
