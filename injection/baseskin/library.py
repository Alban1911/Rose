#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keep the stored custom skins matching the base skin of the game installed.

A skin is fixed as it is added (MessageHandler._check_imported_mods). That
leaves out the skins stored before Rose fixed them, those added during a game
(the fix waits: it rewrites the mod while the game runs) or before the game's
folder was known, and those fixed against a patch that changed the base skin
since. So while the client is idle (home screen, lobby: on_phase), Rose checks
every stored skin it has not checked against the game's current champion WADs,
and fixes those that need it. A check is cheap: a WAD is read file by file.

What was checked is kept in <mods>/.rose_baseskin.json, per mod: the size and
time of the mod checked, those of the champion WADs it was checked against, and
whether every step could run (a mod a step failed on is tried again at the
next start of Rose).

Rewriting a stored mod changes its file: party mode shares the hash of the
file as it was picked (its sourceHash; for a skin an older Rose added, the
hashes ModStorageService.remember_source_hashes keeps before the first
rewrite), so a friend's copy of the same mod still matches; after it, the
manifest's archive index is updated (ModStorageService.refresh_mod_hashes),
which a renamed skin is found by.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Set

from utils.core.atomic_file import atomic_write
from utils.core.junction import is_junction
from utils.core.logging import get_logger

from .package import FixResult, fix_mod

log = get_logger()

STATE_FILE = ".rose_baseskin.json"
# Raise it when the steps write something else: every stored skin is checked again
STEPS_VERSION = 1
# Where the pass may run: the client shows its home screen or a lobby. Not from
# matchmaking on (Swiftplay injects then), nor while a game ends. The phase
# thread keeps the home screen as None in the shared state
IDLE_PHASES = frozenset({None, "None", "Lobby"})
_STORED_SUFFIXES = (".fantome", ".zip")

# One fix of one mod at a time: an import and the pass never rewrite a mod together
_FIX_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_pass_thread: Optional[threading.Thread] = None
# Mods a step failed on, tried again once per start of Rose
_retried: Set[str] = set()


# --------------------------------------------------------------------------------------
# one stored mod
# --------------------------------------------------------------------------------------

def _mod_stamp(mod: Path) -> List[int]:
    """[size, mtime_ns] of an archive; of its WAD files for a folder."""
    if mod.is_dir():
        size = latest = 0
        for item in (mod / "WAD").rglob("*") if (mod / "WAD").is_dir() else ():
            if item.is_file():
                stat = item.stat()
                size += stat.st_size
                latest = max(latest, stat.st_mtime_ns)
        return [size, latest]
    stat = mod.stat()
    return [stat.st_size, stat.st_mtime_ns]


def _champions_dir(game_dir: Path) -> Path:
    return Path(game_dir) / "DATA" / "FINAL" / "Champions"


def _up_to_date(known: Optional[dict], stamp: List[int], champions_dir: Path, key: str) -> bool:
    if not isinstance(known, dict) or known.get("version") != STEPS_VERSION or known.get("mod") != stamp:
        return False
    if not known.get("complete") and key not in _retried:
        return False
    for name, game_stamp in (known.get("game") or {}).items():
        try:
            stat = (champions_dir / name).stat()
        except OSError:
            return False
        if [stat.st_size, stat.st_mtime_ns] != game_stamp:
            return False
    return True


@contextmanager
def stored_skin_rewrite() -> Iterator[None]:
    """Hold while anything else than the base-skin fix rewrites a stored
    custom skin or reads it whole (LTK Manager's repair written back, its
    hashes recorded again): one at a time with the fix, as a replace fails
    on Windows while another holds the file open."""
    with _FIX_LOCK:
        yield


def fix_stored_mod(storage, mod: Path, game_dir: Path) -> FixResult:
    """Fix a stored custom skin in place (fix_mod), keeping its manifest's
    hashes right, and remember it was checked. Raises what fix_mod raises."""
    mod = Path(mod)
    with _FIX_LOCK:
        # Before Rose rewrites the mod: what a friend's copy of it hashes to
        listed = storage.remember_source_hashes(mod)
        result = fix_mod(mod, game_dir)
        if result.changed:
            storage.refresh_mod_hashes(mod, listed)
        _remember(storage.mods_root, mod, result)
    return result


def _remember(mods_root: Path, mod: Path, result: FixResult) -> None:
    try:
        key = mod.relative_to(mods_root).as_posix()
        stamp = _mod_stamp(mod)
    except (OSError, ValueError):
        return
    with _STATE_LOCK:
        state = _load(mods_root)
        state[key] = {"version": STEPS_VERSION, "mod": stamp, "game": result.game_wads, "complete": result.complete}
        _save(mods_root, state)


def _load(mods_root: Path) -> Dict[str, dict]:
    try:
        state = json.loads((mods_root / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save(mods_root: Path, state: Dict[str, dict]) -> None:
    try:
        with atomic_write(mods_root / STATE_FILE, "w", durable=False) as handle:
            json.dump(state, handle, ensure_ascii=False, indent=1, sort_keys=True)
    except OSError as e:
        log.debug(f"[BASESKIN] Could not save {STATE_FILE}: {e}")


# --------------------------------------------------------------------------------------
# the stored skins
# --------------------------------------------------------------------------------------

def stored_skins(storage) -> Iterator[Path]:
    """The custom skins in the mods storage (skins/<id>/): archives and folders."""
    try:
        parents = sorted(child for child in storage.skins_dir.iterdir() if child.is_dir() and child.name.isdigit())
    except OSError:
        return
    for parent in parents:
        try:
            entries = sorted(parent.iterdir(), key=lambda entry: entry.name.lower())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir() and not is_junction(entry):
                yield entry
            elif entry.is_file() and entry.suffix.lower() in _STORED_SUFFIXES:
                yield entry


def fix_stored_skins(storage, game_dir: Path, stop: Callable[[], bool]) -> int:
    """Check every stored custom skin not yet checked against the game's
    current champion WADs, and fix those that need it; return how many were
    fixed. *stop()* is asked between two mods."""
    champions_dir = _champions_dir(game_dir)
    if not champions_dir.is_dir():
        return 0
    with _STATE_LOCK:
        state = _load(storage.mods_root)
    fixed = 0
    present: Set[str] = set()
    finished = True
    for mod in stored_skins(storage):
        if stop():
            finished = False
            break
        try:
            key = mod.relative_to(storage.mods_root).as_posix()
            stamp = _mod_stamp(mod)
        except (OSError, ValueError):
            continue
        present.add(key)
        if _up_to_date(state.get(key), stamp, champions_dir, key):
            continue
        _retried.add(key)
        try:
            result = fix_stored_mod(storage, mod, game_dir)
        except Exception as e:  # noqa: BLE001 - one mod must not stop the others
            log.warning(f"[BASESKIN] Could not check {mod.name} against the base skin: {e}")
            failed = FixResult()
            failed.complete = False  # tried again at the next start, not at every lobby
            _remember(storage.mods_root, mod, failed)
            continue
        if result.changed:
            fixed += 1
            log.info(f"[BASESKIN] Fixed the stored skin {mod.name} against the game's base skin: "
                     f"{describe(result)}")
    if finished:
        with _STATE_LOCK:
            state = _load(storage.mods_root)
            gone = [key for key in state if key not in present]
            if gone:
                for key in gone:
                    del state[key]
                _save(storage.mods_root, state)
    return fixed


def describe(result: FixResult) -> str:
    found = result.findings
    return (f"{len(found.names)} skin name(s), {len(found.meshes)} model file(s), "
            f"{found.audio_merges} sound tag merge(s), {found.unit_renames} bank unit rename(s)")


# --------------------------------------------------------------------------------------
# when
# --------------------------------------------------------------------------------------

def on_phase(phase: Optional[str], injection_manager, state) -> None:
    """Start the pass in the background when the client becomes idle. It
    stops between two mods once the client leaves the idle phases or an
    injection starts."""
    global _pass_thread
    if phase not in IDLE_PHASES:
        return
    injector = getattr(injection_manager, "injector", None)
    game_dir = getattr(injector, "game_dir", None) or getattr(injection_manager, "game_dir", None)
    if game_dir is None:
        return  # once the injection system knows the game's folder

    def stop() -> bool:
        return (getattr(state, "phase", None) not in IDLE_PHASES
                or bool(getattr(injection_manager, "_injection_in_progress", False)))

    def run() -> None:
        from injection.mods.storage import ModStorageService
        try:
            fixed = fix_stored_skins(ModStorageService(), Path(game_dir), stop)
            if fixed:
                log.info(f"[BASESKIN] Fixed {fixed} stored skin(s) so LTK Manager does not take them for skinhacks")
        except Exception as e:  # noqa: BLE001 - a background pass must not take Rose down
            log.warning(f"[BASESKIN] Could not check the stored skins: {e}")

    with _STATE_LOCK:
        if _pass_thread is not None and _pass_thread.is_alive():
            return
        _pass_thread = threading.Thread(target=run, name="BaseSkinPass", daemon=True)
        _pass_thread.start()
