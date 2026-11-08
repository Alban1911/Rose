#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Mapping, Optional

from utils.core.logging import get_logger
from utils.core.modpkg import MODPKG_SUFFIX

from ..mods.fingerprint import mod_fingerprint
from ..mods.manifest import ARCHIVE_SUFFIX, manifest_ltk_ids
from ..mods.mod_facts import stamp_of
from ..mods.storage import ModStorageService
from ..tools.bridge import BridgeCommandError, BridgeUnavailable
from .ltf_session import (
    ALREADY_OPEN_REASON,
    MissingComponent,
    LtfHost,
    LtfSession,
    archive_for_ltk,
)
from .ltk_data import entry_archive

log = get_logger()

__all__ = [
    "ALREADY_OPEN_REASON",
    "BridgeCommandError",
    "BridgeUnavailable",
    "MissingComponent",
    "LibrarySession",
    "LtkBusy",
    "LtkLibrary",
    "LtkUnavailable",
    "remove_rose_mods",
]

REJECTED_SEVERITIES = ("fatal", "error")
MAX_REPAIR_PASSES = 3


def _answer_value(response: dict) -> dict:
    """The value LTK Manager answered a library command with ({} when none)."""
    nested = response.get("response") if isinstance(response, dict) else None
    value = nested.get("value") if isinstance(nested, dict) else None
    return value if isinstance(value, dict) else {}


def _rejected_by_game(verdict: dict) -> List[dict]:
    """What in LTK Manager's verdict still makes the game reject the mod."""
    rules = verdict.get("rules") or []
    problems = [
        {"rule": str(rule.get("rule") or ""), "title": str(rule.get("title") or ""),
         "description": str(rule.get("description") or "")}
        for rule in rules
        if isinstance(rule, dict) and rule.get("severity") in REJECTED_SEVERITIES and int(rule.get("count") or 0) > 0
    ]
    counts = verdict.get("counts") or {}
    if not problems and int(counts.get("fatals") or 0) + int(counts.get("errors") or 0) > 0:
        problems.append({"rule": "", "title": "", "description": ""})
    return problems


def _verdict_summary(verdict: dict) -> str:
    counts = verdict.get("counts") or {}
    return ", ".join(f"{counts.get(key, 0)} {key}" for key in ("fatals", "errors", "warnings")) + \
        f", {verdict.get('fixable', 0)} fixable"


class LtkBusy(RuntimeError):
    """LTK Manager is in use: an injection's session holds it (champion
    select, a game), or another session is connecting."""


class LtkUnavailable(RuntimeError):
    """LTK Manager could not be reached; str() is why (not installed, open
    without Rose's bridge, could not start, bridge gone)."""


class LtkLibrary:
    """LTK Manager's library through Rose's bridge, for the saved mods.

    *game_dir* is the injection's League game folder: check_mod does not run
    without one."""

    def __init__(self, host: LtfHost, game_dir: Optional[Path] = None) -> None:
        self.host = host
        self.game_dir = game_dir

    @contextmanager
    def session(self, *, wait: bool = False) -> Iterator["LibrarySession"]:
        """A session with LTK Manager, started if it is not running and closed
        again after if Rose started it. Entries imported in it are removed at
        its end unless kept (LibrarySession.keep).

        Raises LtkBusy at once while an injection holds LTK Manager: nothing
        here ever waits on a game. *wait* waits for another session's connect
        instead (the uninstall cleanup, with Rose not running).

        The library change lock is held throughout, taken before the launcher lock as
        the injection takes them: an injection installs under it before its
        session is registered (session_active), and a session starting then
        would remove the mods it just installed as an earlier session's.
        """
        host = self.host
        if not host.library_change_lock.acquire(blocking=wait):
            raise LtkBusy("LTK Manager is in use for a game")
        try:
            if not host.launcher_lock.acquire(blocking=wait):
                raise LtkBusy("LTK Manager is busy with another session")
            try:
                if host.busy():
                    raise LtkBusy("LTK Manager is in use for a game")
                session = host.start(report=False)
                if session is None:
                    raise LtkUnavailable(host.last_failure_reason or "LTK Manager could not be started")
                try:
                    yield LibrarySession(host, session)
                finally:
                    host.end(session)
            finally:
                host.launcher_lock.release()
        finally:
            host.library_change_lock.release()

    def check_mod(self, mod: Path, display_name: str,
                  on_kept: Optional[Callable[..., bool]] = None) -> Optional[dict]:
        """Have LTK Manager check a mod the user adds and repair what it can:
        import it, check it, and with *on_kept* keep it there, turned off,
        unless the game would still reject it.

        LTK Manager's Problems rules find what makes the game drop or reject a
        mod (an audio bank of an old version, a bin type a patch changed,
        another skin's model...): run as the mod is added, the user learns
        then, not in a game, that LTK Manager would turn it off, and a
        repairable mod is repaired once. A rejected mod is removed again.

        A mod that moves into LTK Manager's library (a category's) is repaired
        in LTK Manager's copy. *on_kept(ltk_id, stamp=...)* records the entry
        in the mod's manifest before the entry is kept, and returns whether it
        did: once kept, nothing removes the entry, and one no manifest named
        would stay in LTK Manager for good. *stamp* is LTK Manager's archive
        as it was when Rose read the mod's facts from its own copy; None when
        LTK Manager repaired its copy since, so the next sync reads them again
        from it.

        Without *on_kept*, the mod stays Rose's (a custom skin): LTK Manager's
        repair is written back into *mod*, and its entry is removed as the
        session ends, as a game's mods are.

        None when it did not run: no game folder yet, no file at *mod*, an
        injection's session holds LTK Manager (champion select, a game), LTK
        Manager is missing or failed; the mod then stays in Rose as it was
        added. Otherwise {"health": LTK's word before any repair, "repaired":
        fixes applied (written back into *mod* when it stays Rose's),
        "problems": [{"rule", "title", "description"}] that make the game
        reject the mod, and "ltkId" once the entry is kept}.
        """
        if self.game_dir is None or not Path(mod).exists():
            return None
        try:
            with self.session() as session:
                ltk_id = str(session.import_archive(Path(mod), display_name).get("id"))
                result = session.check_and_repair(ltk_id, display_name)
                if on_kept is None:
                    if result["repaired"] and not session.take_repaired_archive(ltk_id, Path(mod)):
                        result["repaired"] = 0
                    return result
                return self._keep_checked(session, ltk_id, display_name, on_kept, result)
        except LtkBusy:
            log.debug(f"[MODCHECK] LTK Manager is in use for a game - not checking {display_name}")
        except LtkUnavailable as e:
            log.info(f"[MODCHECK] Not checking {display_name}, it stays in Rose for now: {e}")
        except (BridgeUnavailable, BridgeCommandError, OSError, ValueError) as e:
            log.warning(f"[MODCHECK] LTK Manager could not check {display_name}: {e}")
        return None

    @staticmethod
    def _keep_checked(session: "LibrarySession", ltk_id: str, display_name: str,
                      on_kept: Callable[..., bool], result: dict) -> dict:
        if result["problems"]:
            return result
        entry = session.confirm(ltk_id)
        if entry is None:
            log.warning(f"[MODCHECK] {display_name} is not in LTK Manager's library after its check: it stays in Rose")
            return result
        archive = entry_archive(entry)
        stamp = stamp_of(archive) if archive is not None and not result["repaired"] else None
        if not on_kept(ltk_id, stamp=stamp):
            log.warning(f"[MODCHECK] {display_name} could not be recorded as LTK Manager's: it stays in Rose")
            return result
        try:
            session.keep(ltk_id)
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.debug(f"[MODCHECK] Could not turn {display_name} off, the next session start does: {e}")
        result["ltkId"] = ltk_id
        log.info(f"[MODCHECK] {display_name} is in LTK Manager's library now")
        return result


class LibrarySession:
    """What a saved mod needs from LTK Manager's library, in one session.

    Bridge failures raise BridgeUnavailable (the bridge is gone: stop) or
    BridgeCommandError (this command failed).
    """

    def __init__(self, host: LtfHost, session: LtfSession) -> None:
        self._host = host
        self._session = session

    @property
    def bridge(self):
        return self._session.bridge

    def library(self) -> Dict[str, dict]:
        """LTK Manager's library by entry id."""
        return {str(entry.get("id")): entry for entry in self.bridge.library() if entry.get("id")}

    def import_archive(self, archive: Path, display_name: str) -> dict:
        """Import a saved mod (its archive, or a folder, packed) and return its
        entry. The entry is Rose's until kept: a session that ends, or a Rose
        that crashes, first removes it, as an injection's mods."""
        archive = Path(archive)
        staging = self._host.staging_root() / f"import-{uuid.uuid4().hex}"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            if archive.is_file():
                suffix = MODPKG_SUFFIX if archive.suffix.lower() == MODPKG_SUFFIX else ".fantome"
                staged = archive_for_ltk(archive, staging / f"{archive.stem}{suffix}")
            else:
                staged = archive_for_ltk(archive, staging / f"{archive.name}.fantome")
            return self._host.import_archive(self._session, staged, archive, display_name)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def confirm(self, ltk_id: str) -> Optional[dict]:
        """The entry *ltk_id* as LTK Manager's library lists it now, if it does."""
        return self.library().get(str(ltk_id))

    def keep(self, ltk_id: str) -> None:
        """Leave the entry in LTK Manager after the session, turned off: it is
        a saved mod now, whether this session imported it or a game kept it
        (kept_copy). Write its ltkId into the manifest before: from here
        nothing removes the entry, and the session-start cleanup leaves alone
        the entries a manifest lists. Raises when it could not be turned off
        (it is still kept; the next session start turns it off)."""
        self._host.keep(self._session, ltk_id)

    def kept_copy(self, stored: Path, library: Mapping[str, dict]) -> Optional[str]:
        """The entry a game left in LTK Manager of the saved mod Rose stores
        at *stored* (LtfHost._park: kept, turned off, for the next
        game), when *library* (by id) still lists it and it came from that
        very content: it is that mod's already, with no import. Raises
        OSError when *stored* cannot be read."""
        source = os.path.normcase(str(Path(stored).resolve()))
        records = {
            mod_id: record for mod_id, record in self._host.journal.kept().items()
            if mod_id in library and os.path.normcase(record["source"]) == source
        }
        if not records:
            return None
        fingerprint = mod_fingerprint(Path(stored))
        return next((mod_id for mod_id, record in records.items() if record["fingerprint"] == fingerprint), None)

    def switch(self, ltk_id: str, enabled: bool) -> None:
        self.bridge.toggle(str(ltk_id), enabled)

    def uninstall(self, ltk_id: str) -> None:
        self._host.uninstall(self._session, ltk_id)

    def check_and_repair(self, ltk_id: str, display_name: str) -> dict:
        """LTK Manager's verdict on an entry, after it repaired what it can.

        LTK Manager repairs its own copy (take_repaired_archive brings it into
        Rose's). Returns {"health": LTK's word before any repair,
        "repaired": fixes applied, "problems": [{"rule", "title",
        "description"}] that still make the game reject the mod}.
        """
        ltk_id = str(ltk_id)
        bridge = self.bridge
        verdict = _answer_value(bridge.check_mod_health(ltk_id))
        result = {"health": str(verdict.get("health") or ""), "repaired": 0, "problems": []}
        log.info(f"[MODCHECK] LTK Manager's verdict on {display_name}: {result['health'] or 'unknown'}"
                 f" ({_verdict_summary(verdict)})")
        for _ in range(MAX_REPAIR_PASSES):
            if verdict.get("health") != "repairable" or int(verdict.get("fixable") or 0) <= 0:
                break
            report = _answer_value(bridge.repair_mod(ltk_id))
            applied = int(report.get("applied") or 0)
            if report.get("failed"):
                log.warning(f"[MODCHECK] LTK Manager could not repair all of {display_name}: {report.get('failed')}")
            if not applied:
                break
            result["repaired"] += applied
            verdict = _answer_value(bridge.check_mod_health(ltk_id))
        if result["repaired"]:
            log.info(f"[MODCHECK] LTK Manager repaired {result['repaired']} problem(s) in {display_name} "
                     f"({_verdict_summary(verdict)} left)")
        result["problems"] = _rejected_by_game(verdict)
        for problem in result["problems"]:
            log.warning(f"[MODCHECK] {display_name} will not work in game: {problem['title']} - "
                        f"{problem['description']}")
        return result


    def take_repaired_archive(self, ltk_id: str, stored: Path) -> bool:
        """Replace Rose's archive of a mod it keeps (*stored*) with LTK
        Manager's repaired copy of entry *ltk_id*, copied beside it under an
        import's temporary name first: no listing takes it for a mod, and the
        next start removes a copy that stopped
        (ModStorageService._recover_conversions). False, logged, when LTK
        Manager's copy cannot be found or is not a .fantome, which Rose stores."""
        entry = self.confirm(ltk_id)
        repaired = entry_archive(entry) if entry is not None else None
        if repaired is None or not repaired.is_file():
            log.warning(f"[MODCHECK] LTK Manager repaired {stored.name}, but its archive could not be found")
            return False
        if repaired.suffix.lower() != ARCHIVE_SUFFIX:
            log.warning(f"[MODCHECK] LTK Manager repaired {stored.name} into a {repaired.suffix}: kept Rose's archive")
            return False
        temporary = stored.with_name(f"{ModStorageService.IMPORT_TEMP_PREFIX}{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(repaired, temporary)
            temporary.replace(stored)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        log.info(f"[MODCHECK] Wrote LTK Manager's repair into Rose's {stored.name}")
        return True


def remove_rose_mods(host: LtfHost) -> int:
    """Remove from LTK Manager's library every entry Rose added there, for
    Rose's uninstaller when the user does not keep Rose's data (main's
    --remove-ltk-mods): only that data names them, so nothing would remove
    them after. These are the saved mods' entries (the missing ones, and
    those of deleted mods still to remove), the copies games kept and the
    installs a Rose that crashed left. The session's start-up cleanup removes
    those installs and turns the user's own mods a game turned off back on,
    but leaves every entry a manifest names: those are removed here.

    Returns 0 when done (LTK Manager is not even started when Rose added
    nothing and turned nothing off), 1 when LTK Manager could not be reached,
    an entry could not be removed or a user's mod stays off.
    """
    state = host.journal.read()
    ids = manifest_ltk_ids(host.saved_mods_dir()) | set(state["kept"]) | set(state["installed"])
    if not ids and not state["disabled"]:
        log.info("[MODS] Rose added nothing to LTK Manager's library")
        return 0
    removed, failed = [], []
    try:
        with LtkLibrary(host).session(wait=True) as session:
            library = session.library()
            for ltk_id in sorted(ids & set(library)):
                try:
                    session.uninstall(ltk_id)
                except BridgeCommandError as e:
                    log.warning(f"[MODS] Could not remove {ltk_id} from LTK Manager's library: {e}")
                    failed.append(ltk_id)
                    continue
                removed.append(ltk_id)
            if removed:
                host.journal.forget_kept(removed)
            failed += _turn_users_mods_back_on(host, session, library)
    except (LtkBusy, LtkUnavailable, BridgeUnavailable, BridgeCommandError) as e:
        log.warning(f"[MODS] Could not remove Rose's mods from LTK Manager's library: {e}")
        return 1
    log.info(f"[MODS] Removed {len(removed)} mod(s) Rose added from LTK Manager's library")
    return 1 if failed else 0


def _turn_users_mods_back_on(host: LtfHost, session: LibrarySession, library: Mapping[str, dict]) -> List[str]:
    """Turn back on the user's own mods a game turned off that the session's
    start could not (its cleanup leaves them recorded and goes on), and
    return those still off: the uninstaller deletes that record next."""
    still_off = []
    for ltk_id in host.journal.read()["disabled"]:
        if ltk_id not in library or library[ltk_id].get("enabled"):
            continue
        try:
            session.switch(ltk_id, True)
        except BridgeCommandError as e:
            log.warning(f"[MODS] Could not turn the user's mod {ltk_id} back on in LTK Manager: {e}")
            still_off.append(ltk_id)
            continue
        host.journal.untrack(restored=[ltk_id])
    return still_off
