#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A stored custom skin, matched to the base skin once, as it is added.

A skin is fixed as it is added (MessageHandler._check_imported_mods), and only
then: Rose does not go back over the skins it stores. What was checked is kept
in <mods>/.rose_baseskin.json, per mod: the size and time of the mod checked,
those of the champion WADs it was checked against, the steps' version, and
whether every step could run. A skin picked for a game that this Rose's steps
did not fix (one an older Rose fixed, one added during a game, whose fix
waits, or one a step failed on) is the player's to add again: Troubleshooting
tells them (needs_reinstall, report_outdated).

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
from typing import Dict, Iterator, List

from utils.core.atomic_file import atomic_write
from utils.core.logging import get_logger

from .package import FixResult, fix_mod

log = get_logger()

STATE_FILE = ".rose_baseskin.json"
# Raise it when the steps write something else: a skin fixed by older steps is
# then one to add again (needs_reinstall)
STEPS_VERSION = 4  # 2: unpacked WAD folders are fixed too; 3: meshes rebuilt, bank paths moved, event names unlisted; 4: tags after the number unlisted too (ZoeSkin18W), game skin0's own names kept, unnamed base events paired

# One fix of one mod at a time: never two rewrites of one mod together
_FIX_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()


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


def describe(result: FixResult) -> str:
    found = result.findings
    return (f"{len(found.names)} skin name(s), {len(found.meshes)} model file(s), "
            f"{found.audio_merges} sound tag merge(s), {found.unit_renames} bank unit rename(s), "
            f"{found.bank_moves} bank path move(s), {found.event_names_unlisted} skin event name(s) unlisted")


# --------------------------------------------------------------------------------------
# a stored skin this Rose did not fix
# --------------------------------------------------------------------------------------

def needs_reinstall(mods_root: Path, mod: Path) -> bool:
    """Whether the stored custom skin *mod* is not as this Rose's steps fix
    a skin: never checked (added during a game, or before Rose knew the
    game's folder), fixed by an older Rose (an older STEPS_VERSION), or this
    Rose's fix of it could not complete. As it is, it may fail in game, and
    Rose does not fix it again: the player adds it again."""
    try:
        key = Path(mod).relative_to(mods_root).as_posix()
    except ValueError:
        return False
    with _STATE_LOCK:
        known = _load(Path(mods_root)).get(key)
    if not isinstance(known, dict):
        return True
    return known.get("version") != STEPS_VERSION or not known.get("complete")


def report_outdated(name: str) -> None:
    """Tell the player, in Troubleshooting, to add the custom skin *name* again."""
    from utils.core.issue_reporter import report_issue

    log.warning(f"[BASESKIN] The custom skin {name} is not prepared for this Rose: it must be added again")
    report_issue(
        "CUSTOM_SKIN_OUTDATED",
        "error",
        f"Custom skin {name} was added with an older Rose",
        details={"skin": name},
        hint="Please update your custom skin by reinstalling it into Rose.",
    )
