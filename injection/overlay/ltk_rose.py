#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, List, Optional

from utils.core.logging import get_logger

from ..tools.bridge import BridgeCommandError, BridgeUnavailable
from .ltk_data import entry_name

if TYPE_CHECKING:
    from .ltf_session import LtfHost, LtfSession

log = get_logger()

ROSE_NAME = "Rose"


def _named_rose(items: List[dict]) -> Optional[dict]:
    return next((item for item in items if item.get("name") == ROSE_NAME and item.get("id")), None)


class RoseProfile:
    """Rose's own profile in LTK Manager, which every session switches it to
    before it changes anything: LTK Manager enables a mod it installs in the
    active profile alone, and its patcher applies that profile's mods. The
    user's profile, and the mods they enabled in it, stay as they left them.

    The journal records the user's profile first (users_profile): a Rose that
    crashes leaves LTK Manager in Rose's profile, and the next session, or
    the next start (ltk_library.restore_users_profile), switches back."""

    def __init__(self, host: LtfHost) -> None:
        self._host = host

    def left_open(self) -> bool:
        """Whether a session left LTK Manager in Rose's profile."""
        return self._host.journal.read()["users_profile"] is not None

    def enter(self, bridge) -> None:
        """Switch LTK Manager to Rose's profile, created when missing. Raises
        BridgeUnavailable or BridgeCommandError when it may not be active:
        the session must then change nothing, as the active profile may be
        the user's."""
        self._restore_users_mods(bridge)
        profiles = bridge.profiles()
        active = bridge.active_profile()
        rose = _named_rose(profiles) or bridge.create_profile(ROSE_NAME)
        if active["id"] == rose["id"]:
            recorded = self._host.journal.read()["users_profile"]
            if recorded is not None and all(profile.get("id") != recorded for profile in profiles):
                log.warning("[INJECT] The LTK Manager profile Rose switched away from was deleted: "
                            "Rose's stays active")
                self._host.journal.update(lambda state: state.__setitem__("users_profile", None))
            return
        if not self._host.journal.update(lambda state: state.__setitem__("users_profile", active["id"])):
            raise BridgeCommandError("the user's LTK Manager profile could not be recorded")
        bridge.switch_profile(rose["id"])
        log.info(f"[INJECT] Switched LTK Manager to Rose's profile (the user's is {active.get('name')})")

    def leave(self, bridge) -> None:
        """Switch LTK Manager back to the user's profile, and forget it. One
        that cannot be switched to stays recorded for the next session."""
        users = self._host.journal.read()["users_profile"]
        if users is None:
            return
        try:
            bridge.switch_profile(users)
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.warning(f"[INJECT] Could not switch LTK Manager back to the user's profile: {e}")
            return
        self._host.journal.update(lambda state: state.__setitem__("users_profile", None))
        log.debug("[INJECT] Switched LTK Manager back to the user's profile")

    def remove(self, bridge) -> None:
        """Switch back to the user's profile and delete Rose's (the
        uninstaller's cleanup). Raises when Rose's stays."""
        self.leave(bridge)
        rose = _named_rose(bridge.profiles())
        if rose is None:
            return
        if bridge.active_profile()["id"] == rose["id"]:
            raise BridgeCommandError("Rose's LTK Manager profile is still the active one")
        bridge.delete_profile(rose["id"])

    def _restore_users_mods(self, bridge) -> None:
        """Turn back on the user's mods an older Rose turned off in their
        profile for a game and never turned back on (journal "disabled"),
        while that profile is the active one: not after a crash left Rose's
        active (users_profile). What cannot be turned on stays recorded."""
        state = self._host.journal.read()
        disabled = state["disabled"]
        if not disabled or state["users_profile"] is not None:
            return
        try:
            bridge.stop_patcher()
        except (BridgeUnavailable, BridgeCommandError):
            pass
        library = {str(entry.get("id")): entry for entry in bridge.library() if entry.get("id")}
        restored = []
        for mod_id in disabled:
            entry = library.get(mod_id)
            if entry is None or entry.get("enabled"):
                restored.append(mod_id)
                continue
            try:
                bridge.toggle(mod_id, True)
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not turn {mod_id} back on: {e}")
                continue
            restored.append(mod_id)
            log.info(f"[INJECT] Turned {entry_name(entry)} back on (an older Rose turned it off for a game)")
        self._host.journal.untrack(restored=restored)


class RoseFolder:
    """The folder named "Rose" in LTK Manager's library, which holds the mods
    Rose added there: someone who uses LTK Manager without Rose sees which
    are Rose's. The user's own mods never go there."""

    def file(self, session: LtfSession, ltk_id: str) -> None:
        """Move an entry Rose just added into its folder. Logged when it
        cannot be: the next session start files it."""
        try:
            session.bridge.move_to_folder(str(ltk_id), self._folder_id(session))
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.debug(f"[INJECT] Could not move {ltk_id} into LTK Manager's Rose folder: {e}")

    def file_all(self, session: LtfSession, ltk_ids: Iterable[str]) -> None:
        """Move each of the entries Rose added (*ltk_ids*) that LTK Manager's
        library lists outside its folder into it."""
        ltk_ids = set(ltk_ids)
        if not ltk_ids:
            return
        try:
            library = session.bridge.library()
            folder_id = self._folder_id(session) if any(str(e.get("id")) in ltk_ids for e in library) else None
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.debug(f"[INJECT] Could not read LTK Manager's folders to file Rose's mods: {e}")
            return
        unfiled = [entry for entry in library if str(entry.get("id")) in ltk_ids and entry.get("folderId") != folder_id]
        for entry in unfiled:
            self.file(session, str(entry["id"]))
        if unfiled:
            log.info(f"[INJECT] Moved {len(unfiled)} mod(s) Rose added into LTK Manager's Rose folder")

    @staticmethod
    def remove(bridge) -> None:
        """Delete Rose's folder (the uninstaller's cleanup): LTK Manager moves
        what is left in it to its root. Raises."""
        rose = _named_rose(bridge.folders())
        if rose is not None:
            bridge.delete_folder(rose["id"])

    @staticmethod
    def _folder_id(session: LtfSession) -> str:
        """Rose's folder, created when missing, looked up once a session."""
        if session.rose_folder_id is None:
            bridge = session.bridge
            session.rose_folder_id = str((_named_rose(bridge.folders()) or bridge.create_folder(ROSE_NAME))["id"])
        return session.rose_folder_id
