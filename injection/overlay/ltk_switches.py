#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple

from utils.core.logging import get_logger

from ..mods.manifest import forget_ltk_removals, ltk_removals
from ..tools.bridge import BridgeCommandError, BridgeUnavailable
from .ltk_data import entry_name

if TYPE_CHECKING:
    from .ltf_session import LtfHost, LtfSession

log = get_logger()


@dataclass
class Leftovers:
    """What earlier sessions left of the saved mods in LTK Manager."""

    deleted_in_rose: List[str] = field(default_factory=list)
    already_gone: List[str] = field(default_factory=list)
    found_switched_on: List[str] = field(default_factory=list)
    unended_switches: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Whether LTK Manager's library has to change."""
        return bool(self.deleted_in_rose or self.found_switched_on)


class SavedModSwitches:
    """Switches the saved mods LTK Manager holds on and off for an
    LtfHost's sessions: a session's switched_on holds the entries it switched
    on, its saved_mod_ids every entry a saved mod's manifest named when it
    started."""

    def __init__(self, host: LtfHost) -> None:
        self._host = host

    def _record(self, session: LtfSession, ltk_id: str, name: str) -> bool:
        """Journal the entry as switched on, before it is: False when the
        journal could not be written (a crash would then leave it on for good)."""
        if not self._host.journal.update(lambda state: state["switched"].__setitem__(ltk_id, name)):
            return False
        session.switched_on[ltk_id] = name
        return True

    def _forget(self, ltk_ids: Iterable[str]) -> None:
        ltk_ids = set(ltk_ids)
        if not ltk_ids:
            return

        def drop(state):
            state["switched"] = {k: v for k, v in state["switched"].items() if k not in ltk_ids}

        self._host.journal.update(drop)

    def leftovers(self, library: Dict[str, dict], switched: Dict[str, str], saved_mod_ids: set) -> Leftovers:
        """What to undo at a session's start, from LTK Manager's *library*
        (id -> entry), the entries earlier sessions recorded as *switched* on,
        and every saved mod's entry (*saved_mod_ids*)."""
        removals = ltk_removals(self._host.saved_mods_dir())
        remove = [ltk_id for ltk_id in removals if ltk_id in library]
        return Leftovers(
            deleted_in_rose=remove,
            already_gone=[ltk_id for ltk_id in removals if ltk_id not in library],
            found_switched_on=sorted(
                ltk_id for ltk_id in (set(switched) | set(saved_mod_ids)) - set(remove)
                if library.get(ltk_id, {}).get("enabled")
            ),
            unended_switches=list(switched),
        )

    def undo(self, bridge, leftovers: Leftovers) -> None:
        """Undo *leftovers*, LTK Manager's patcher stopped (it holds library
        edits while it runs). What could not be undone stays recorded for the
        next start."""
        removed = list(leftovers.already_gone)
        for ltk_id in leftovers.deleted_in_rose:
            try:
                bridge.uninstall(ltk_id)
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not remove the saved mod deleted in Rose ({ltk_id}): {e}")
                continue
            removed.append(ltk_id)
            log.info(f"[INJECT] Removed {ltk_id} from LTK Manager: its saved mod was deleted in Rose")
        if removed:
            forget_ltk_removals(self._host.saved_mods_dir(), removed)
        still_on = set()
        for ltk_id in leftovers.found_switched_on:
            try:
                bridge.toggle(ltk_id, False)
            except (BridgeUnavailable, BridgeCommandError) as e:
                still_on.add(ltk_id)
                log.debug(f"[INJECT] Could not switch off the saved mod {ltk_id}: {e}")
                continue
            log.info(f"[INJECT] Switched off the saved mod {ltk_id} in LTK Manager: it is on only for a game")
        self._forget(set(leftovers.unended_switches) - still_on)

    @staticmethod
    def changes(session: LtfSession, ltk_ids: List[str]) -> Tuple[List[str], List[str]]:
        """(the entries to switch on, those to switch off) for the session's
        saved mods to be exactly *ltk_ids*."""
        on = [ltk_id for ltk_id in ltk_ids if ltk_id not in session.switched_on]
        off = [ltk_id for ltk_id in session.switched_on if ltk_id not in ltk_ids]
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

    def switch(self, session: LtfSession, on: List[str], off: List[str], library: Optional[List[dict]]) -> None:
        """Switch the entries *on* on for the session and *off* off, keeping
        *library* (the read the install shares) as LTK Manager now has it.
        Raises BridgeUnavailable or BridgeCommandError: a mod left off is
        missing from the overlay, one left on applies with it.

        Each switch-on holds the session's lock, which LtfHost.end takes to
        end it: a session that ended (a discard while this read the library)
        switches nothing on, and one ending after sees the entry to switch off.
        One that fails to switch on is not counted as on, so the next install
        of the session switches it on again; its journal record stays, so a
        next session's start switches it off had LTK Manager applied it anyway.
        """
        entries = {str(entry.get("id")): entry for entry in library or () if entry.get("id")}
        for ltk_id in off:
            self._switch_off(session, ltk_id)
            if ltk_id in entries:
                entries[ltk_id]["enabled"] = False
        for ltk_id in on:
            name = entry_name(entries[ltk_id]) if ltk_id in entries else ltk_id
            with session.lock:
                if session.ended:
                    log.debug(f"[INJECT] The session ended: {name} stays off")
                    return
                if not self._record(session, ltk_id, name):
                    log.warning(f"[INJECT] Could not record {name} in Rose's LTF session state - left off: "
                                "a crash would leave it on in LTK Manager")
                    continue
                try:
                    session.bridge.toggle(ltk_id, True)
                except (BridgeUnavailable, BridgeCommandError):
                    session.switched_on.pop(ltk_id, None)
                    raise
            if ltk_id in entries:
                entries[ltk_id]["enabled"] = True
            log.info(f"[INJECT] Switched on {name} in LTK Manager (a saved mod)")

    def switch_off_all(self, session: LtfSession) -> None:
        """Switch off every entry the session switched on: they are the user's
        saved mods, never removed. One that cannot be switched off stays
        recorded: the next session's start does it."""
        for ltk_id in list(session.switched_on):
            try:
                self._switch_off(session, ltk_id)
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not switch off {session.switched_on.get(ltk_id)} in LTK Manager: {e}")

    def _switch_off(self, session: LtfSession, ltk_id: str) -> None:
        name = session.switched_on.get(ltk_id, ltk_id)
        session.bridge.toggle(ltk_id, False)
        session.switched_on.pop(ltk_id, None)
        self._forget([ltk_id])
        log.debug(f"[INJECT] Switched off {name} in LTK Manager")
