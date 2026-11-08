#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The user's saved mods LTK Manager holds, switched on for one game.

A mod the user added lives in LTK Manager's library for good
(injection.mods.manifest). An injection lists it among its mods by its LTK
reference (injection.mods.ltk_ref), and its session switches the entry on,
then off again after the game: it is never imported for a game, nor removed.

Each entry is recorded ("switched" in ltf_installed.json) before it is
switched on and forgotten once it is off again, so the next session's start
switches off what a Rose that crashed mid-game left on. That start also
switches off the saved mods found on (LTK Manager used by hand between
games) and removes the entries of saved mods deleted in Rose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from utils.core.logging import get_logger

from ..mods.manifest import forget_ltk_removals, ltk_removals
from ..tools.bridge import BridgeCommandError, BridgeUnavailable

log = get_logger()


@dataclass
class Leftovers:
    """What earlier sessions left of the saved mods in LTK Manager."""

    remove: List[str] = field(default_factory=list)  # entries of saved mods deleted in Rose
    gone: List[str] = field(default_factory=list)  # queued for removal, no longer in LTK Manager
    switch_off: List[str] = field(default_factory=list)  # saved mods found switched on
    records: List[str] = field(default_factory=list)  # switched on by a session that did not end

    def __bool__(self) -> bool:
        """Whether LTK Manager's library has to change."""
        return bool(self.remove or self.switch_off)


class SavedModSwitches:
    """Switches the saved mods LTK Manager holds on and off for an
    OverlayManager's sessions: a session's "switched" holds the entries it
    switched on (id -> name), its "rose_ids" every entry a saved mod's
    manifest named when it started."""

    def __init__(self, overlay) -> None:
        self._overlay = overlay

    def _record(self, session: dict, ltk_id: str, name: str) -> None:
        session["switched"][ltk_id] = name
        self._overlay._update_state(lambda state: state["switched"].__setitem__(ltk_id, name))

    def _forget(self, ltk_ids: Iterable[str]) -> None:
        ltk_ids = set(ltk_ids)
        if not ltk_ids:
            return

        def drop(state):
            state["switched"] = {k: v for k, v in state["switched"].items() if k not in ltk_ids}

        self._overlay._update_state(drop)

    def leftovers(self, library: Dict[str, dict], switched: Dict[str, str], rose_ids: set) -> Leftovers:
        """What to undo at a session's start, from LTK Manager's *library*
        (id -> entry), the entries earlier sessions recorded as *switched* on,
        and every saved mod's entry (*rose_ids*)."""
        queued = ltk_removals(self._overlay._saved_mods_dir())
        return Leftovers(
            remove=[ltk_id for ltk_id in queued if ltk_id in library],
            gone=[ltk_id for ltk_id in queued if ltk_id not in library],
            switch_off=sorted(
                ltk_id for ltk_id in (set(switched) | set(rose_ids)) - set(queued)
                if library.get(ltk_id, {}).get("enabled")
            ),
            records=list(switched),
        )

    def undo(self, bridge, leftovers: Leftovers) -> None:
        """Undo *leftovers*, LTK Manager's patcher stopped (it holds library
        edits while it runs). What could not be undone stays recorded for the
        next start."""
        removed = list(leftovers.gone)
        for ltk_id in leftovers.remove:
            try:
                bridge.uninstall(ltk_id)
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not remove the saved mod deleted in Rose ({ltk_id}): {e}")
                continue
            removed.append(ltk_id)
            log.info(f"[INJECT] Removed {ltk_id} from LTK Manager: its saved mod was deleted in Rose")
        if removed:
            forget_ltk_removals(self._overlay._saved_mods_dir(), removed)
        still_on = set()
        for ltk_id in leftovers.switch_off:
            try:
                bridge.toggle(ltk_id, False)
            except (BridgeUnavailable, BridgeCommandError) as e:
                still_on.add(ltk_id)
                log.debug(f"[INJECT] Could not switch off the saved mod {ltk_id}: {e}")
                continue
            log.info(f"[INJECT] Switched off the saved mod {ltk_id} in LTK Manager: it is on only for a game")
        self._forget(set(leftovers.records) - still_on)

    @staticmethod
    def changes(session: dict, ltk_ids: List[str]) -> Tuple[List[str], List[str]]:
        """(the entries to switch on, those to switch off) for the session's
        saved mods to be exactly *ltk_ids*."""
        on = [ltk_id for ltk_id in ltk_ids if ltk_id not in session["switched"]]
        off = [ltk_id for ltk_id in session["switched"] if ltk_id not in ltk_ids]
        return on, off

    @staticmethod
    def listed(ltk_ids: List[str], library: List[dict]) -> List[str]:
        """Those of *ltk_ids* LTK Manager's *library* lists. Another was
        deleted in LTK Manager since Rose last read its index: it is left out
        and the next sync marks its saved mod missing."""
        entries = {str(entry.get("id")) for entry in library if entry.get("id")}
        for ltk_id in ltk_ids:
            if ltk_id not in entries:
                log.warning(f"[INJECT] A saved mod is no longer in LTK Manager's library ({ltk_id}) - "
                            "injecting the others")
        return [ltk_id for ltk_id in ltk_ids if ltk_id in entries]

    def switch(self, session: dict, on: List[str], off: List[str], library: Optional[List[dict]]) -> None:
        """Switch the entries *on* on for the session and *off* off, keeping
        *library* (the read the install shares) as LTK Manager now has it.
        Raises BridgeUnavailable or BridgeCommandError: a mod left off is
        missing from the overlay, one left on applies with it."""
        entries = {str(entry.get("id")): entry for entry in library or () if entry.get("id")}
        for ltk_id in off:
            self._switch_off(session, ltk_id)
            if ltk_id in entries:
                entries[ltk_id]["enabled"] = False
        for ltk_id in on:
            name = self._overlay._entry_name(entries[ltk_id]) if ltk_id in entries else ltk_id
            self._record(session, ltk_id, name)
            session["bridge"].toggle(ltk_id, True)
            if ltk_id in entries:
                entries[ltk_id]["enabled"] = True
            log.info(f"[INJECT] Switched on {name} in LTK Manager (a saved mod)")

    def switch_off_all(self, session: dict) -> None:
        """Switch off every entry the session switched on: they are the user's
        saved mods, never removed. One that cannot be switched off stays
        recorded: the next session's start does it."""
        for ltk_id in list(session["switched"]):
            try:
                self._switch_off(session, ltk_id)
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not switch off {session['switched'].get(ltk_id)} in LTK Manager: {e}")

    def _switch_off(self, session: dict, ltk_id: str) -> None:
        name = session["switched"].get(ltk_id, ltk_id)
        session["bridge"].toggle(ltk_id, False)
        session["switched"].pop(ltk_id, None)
        self._forget([ltk_id])
        log.debug(f"[INJECT] Switched off {name} in LTK Manager")
