#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import psutil

from utils.core.issue_reporter import report_issue
from utils.core.junction import link_file
from utils.core.logging import get_logger
from utils.core.modpkg import MODPKG_SUFFIX, is_modpkg
from utils.core.paths import get_user_data_dir
from ..mods.fantome import fantome_display_name, write_fantome_zip
from ..mods.manifest import lives_in_ltk, manifest_ltk_ids
from ..tools.bridge import (
    BridgeCommandError,
    BridgeUnavailable,
    LtkBridge,
    find_bridge,
)
from ..tools.tools_manager import LTF_BRIDGE_DLL, LTF_LAUNCHER, ToolsManager
from .ltf_journal import KeptRecord, LibraryId, LibraryNames, LtfJournal
from .ltf_report import cdp_unreachable, report_ltf_failure
from .ltk_data import LtkLogTail, entry_name
from .ltk_switches import SavedModSwitches
from .process_manager import LTK_MANAGER_PROCESSES

log = get_logger()

BRIDGE_REQUEST_LINE_CAP_BYTES = 64 * 1024 * 1024
BASE64_PAYLOAD_CAP_BYTES = BRIDGE_REQUEST_LINE_CAP_BYTES // 4 * 3
REQUEST_ENVELOPE_BYTES = 8 * 1024 * 1024
BYTES_IMPORT_LIMIT = BASE64_PAYLOAD_CAP_BYTES - REQUEST_ENVELOPE_BYTES

LAUNCHER_TIMEOUT_S = 60
LTK_LOGS_FOLDER = "ltk"
LAUNCHER_LOG_ROTATE_BYTES = 1024 * 1024
LAUNCHER_PARENT_LOG_LINE = re.compile(r"parent pid = \d+ \(([^)]*)\)")
LAUNCHER_SHELL_PARENT = "explorer.exe"
BRIDGE_START_TIMEOUT_S = 30
# LTK Manager's built-in browser (CDP) answers seconds after its bridge does:
# a command sent in between fails with "CDP unavailable", and the countdown's
# staging gave up on its first try (#431). How long to wait for it, and how
# often to ask
CDP_READY_TIMEOUT_S = 20.0
CDP_READY_POLL_S = 0.5
EXIT_GRACE_BEFORE_NEXT_SESSION_S = 3.0


class LauncherExit(IntEnum):
    """ltk_launcher.exe's exit codes (native/ltf/LeagueToolFlop-inj.cpp)."""

    OK = 0
    DLL_MISSING = 1
    EXE_MISSING = 2
    SPAWN_FAILED = 3
    INJECT_FAILED = 4
    ALREADY_RUNNING = 5
    NO_LIVE_INSTANCE = 6


MIN_LIBRARY_FREE_BYTES = 1 * 1024 * 1024 * 1024
LIBRARY_IMPORT_HEADROOM_BYTES = 512 * 1024 * 1024

ALREADY_OPEN_REASON = "LTK Manager is already open without Rose's bridge"


class MissingComponent(StrEnum):
    """Why a session could not start for want of a component (LtfHost.last_failure_reason)."""

    LTF_BRIDGE = "Rose's LTF bridge files are missing"
    LTK_MANAGER = "LTK Manager is not installed"
# LTK Manager's page loaded, its Tauri IPC not yet: the browser answers but
# window.__TAURI_INTERNALS__ is still undefined (#441)
TAURI_NOT_READY_MARKER = "reading 'invoke'"

# LTK Manager's built-in mods that put every champion's archive (~16 GB) into
# its overlay (settings.json "builtinMods"): each build then takes minutes, so
# the game starts long before the patcher scans, and games crashed with it (#441)
HEAVY_BUILTINS_MESSAGE = "LTK Manager's built-in mods put every champion's archive into the overlay"
HEAVY_BUILTINS_HINT = (
    "Quit Rose, open LTK Manager from the Start menu > Settings > Built-in mods, set Base skins to Off "
    "(or Modded champions) and limit Character inking to chosen champions, then close LTK Manager "
    "(also from the system tray) and start Rose again."
)


def ltk_logs_dir() -> Path:
    """Rose's logs\\ltk folder (%LOCALAPPDATA%\\Rose\\logs\\ltk)."""
    from utils.core.paths import get_user_data_dir
    return get_user_data_dir() / "logs" / LTK_LOGS_FOLDER


def launcher_log_paths() -> tuple:
    """Where ltk_launcher.exe logs how it started LTK Manager, and why it fell
    back when it could not make explorer.exe its parent: Rose's logs\\ltk
    folder; C:\\Users\\Public and the temp folder for a launcher not given it
    (or its helper, when it cannot write there). Rose copies a start's lines
    into its own log, so a report has them (#478)."""
    return (
        ltk_logs_dir() / "ltk_launcher.log",
        Path(r"C:\Users\Public\ltk_launcher.log"),
        Path(tempfile.gettempdir()) / "ltk_launcher.log",
    )


def _rotate_launcher_log(path: Path) -> None:
    """Keep ltk_launcher.log under LAUNCHER_LOG_ROTATE_BYTES (the previous one as .old)."""
    try:
        if path.stat().st_size > LAUNCHER_LOG_ROTATE_BYTES:
            path.replace(path.with_name(path.stem + ".old.log"))
    except OSError:
        pass


def _log_sizes(paths) -> Dict[Path, int]:
    """Each log's size now, so _new_log_lines reads only what follows."""
    sizes = {}
    for path in paths:
        try:
            sizes[path] = path.stat().st_size
        except OSError:
            sizes[path] = 0
    return sizes


def _new_log_lines(sizes: Dict[Path, int]) -> List[str]:
    """The non-empty lines appended to each log since *sizes* were taken (a
    log that shrank, deleted and written again, is read from its start)."""
    lines: List[str] = []
    for path, start in sizes.items():
        try:
            with open(path, "rb") as handle:
                end = handle.seek(0, 2)
                handle.seek(start if start <= end else 0)
                data = handle.read()
        except OSError:
            continue
        lines.extend(line.strip() for line in data.decode("utf-8", "replace").splitlines() if line.strip())
    return lines


def heavy_builtin_mods(settings: dict) -> List[str]:
    """The built-in mods of LTK Manager's settings that hold every champion's archive."""
    builtins = settings.get("builtinMods") if isinstance(settings, dict) else None
    if not isinstance(builtins, dict):
        return []
    found = []
    if builtins.get("baseSkins") == "allChampions":
        found.append("Base skins: Every champion")
    inking = builtins.get("characterInking")
    if isinstance(inking, dict) and inking.get("enabled") and inking.get("scope", "all") == "all":
        found.append("Character inking: every champion")
    return found


def archive_for_ltk(mod: Path, dest: Path) -> Path:
    """Put at *dest* the .fantome LTK Manager installs for the mod at *mod*,
    and return where it is: an archive goes as it is (a hard link, however
    large), a .modpkg under that suffix (LTK Manager reads the format by
    it), a folder is packed."""
    if mod.is_file():
        if is_modpkg(mod):
            dest = dest.with_suffix(MODPKG_SUFFIX)
        link_file(mod, dest)
        log.debug(f"[INJECT] {mod.name} goes to LTK Manager as it is")
    else:
        write_fantome_zip(mod, dest)
    return dest


def _unreadable_archive(error: Exception) -> bool:
    """Whether an import failed because LTK Manager could not read the file."""
    text = str(error).lower()
    return any(marker in text for marker in ("not found:", "cannot read file:", "failed to read file:"))


def _resendable_as_bytes(error: Exception, archive: Path) -> bool:
    """Whether an import of *archive* can be sent again as its bytes: LTK
    Manager refused it before installing anything (it could not read the
    file), and the bytes fit a bridge request."""
    return _unreadable_archive(error) and archive.stat().st_size <= BYTES_IMPORT_LIMIT


def _same_content_kept(kept: Dict[LibraryId, KeptRecord], mod_id: str, fingerprint: str) -> bool:
    """Whether another kept entry than *mod_id* holds the same content already."""
    return any(record["fingerprint"] == fingerprint for other, record in kept.items() if other != mod_id)


def _same_file(candidate: Path, linked: os.stat_result) -> bool:
    try:
        stat = candidate.stat()
    except OSError:
        return False
    return stat.st_size == linked.st_size and os.path.samestat(stat, linked)


def _cdp_not_up_yet(error: Exception) -> bool:
    """Whether a command failed because LTK Manager's browser is not up yet:
    no browser, or its page without Tauri's IPC."""
    return cdp_unreachable(error) or TAURI_NOT_READY_MARKER in str(error).lower()


_OLD_BRIDGE_OR_UNREADY_PAGE = (BridgeCommandError, BridgeUnavailable)


@dataclass
class TrackedImport:
    """An entry Rose imported into LTK Manager's library: the session's end
    removes it unless it was kept."""

    source_folder: str
    source_digest: Optional[str] = None
    saved_mod_source: Optional[str] = None


@dataclass(eq=False)
class LtfSession:
    """One connection to LTK Manager through Rose's bridge, and what Rose
    changed in LTK Manager's library during it."""

    bridge: Any
    rose_started_manager: bool
    imports: Dict[LibraryId, TrackedImport] = field(default_factory=dict)
    user_mods_turned_off: List[LibraryId] = field(default_factory=list)
    switched_on: LibraryNames = field(default_factory=dict)
    switch_on_unconfirmed: Set[LibraryId] = field(default_factory=set)
    saved_mod_ids: Set[LibraryId] = field(default_factory=set)
    start_log_tail: Optional[LtkLogTail] = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    ended: bool = False

    @property
    def confirmed_on(self) -> Set[LibraryId]:
        """The entries this session switched on and LTK Manager confirmed."""
        return set(self.switched_on) - self.switch_on_unconfirmed


class LtfHost:
    """Rose's sessions with LTK Manager: start one (connected, or LTK Manager
    started, and an earlier session's leftovers undone), track what it
    imports until the import is removed, kept for the next game (_park) or
    handed to a saved mod (keep), and end it.

    *in_use* says whether the injection holds LTK Manager before a game's
    session is registered (its countdown's session, staging): busy() counts
    it as the game's session.
    """

    def __init__(self, tools_dir: Path, injection_dir: Path, process_manager=None,
                 in_use: Callable[[], bool] = lambda: False) -> None:
        self.tools_dir = tools_dir
        self.injection_dir = injection_dir
        self.process_manager = process_manager
        self._in_use = in_use
        self.saved_mods_root: Optional[Path] = None
        self.library_change_lock = threading.Lock()
        self.launcher_lock = threading.Lock()
        self.last_failure_reason: Optional[str] = None
        self.logged_manager_parent: Optional[str] = None
        self.journal = LtfJournal(injection_dir / "ltf_installed.json")
        self.switches = SavedModSwitches(self)

    def busy(self) -> bool:
        """Whether an injection holds LTK Manager (champion select, a game)."""
        return self._in_use() or (self.process_manager is not None and self.process_manager.session_active())

    def saved_mods_dir(self) -> Path:
        """Where the user's saved mods live: only those are kept in LTK Manager between games (_park).
        Rose's data folder is looked up only when no root was set, since finding the desktop user
        can create that user's folder."""
        return Path(self.saved_mods_root) if self.saved_mods_root is not None else get_user_data_dir() / "mods"

    def staging_root(self) -> Path:
        """Where archives wait for LTK Manager to import them.

        Not tempfile: Python 3.13 makes its folders private to the elevated
        Rose, and LTK Manager restarts itself unelevated, so it could not read
        them. Rose's data folder belongs to the desktop user, who runs it.
        """
        return self.injection_dir / "ltf_staging"

    def start(self, report: bool = True, cancelled: Optional[Callable[[], bool]] = None) -> Optional[LtfSession]:
        """Connect to the bridge inside LTK Manager, starting it through the
        LTF launcher when nothing is running yet.

        Returns the session, or None when a required component is missing
        (report=False keeps that out of Troubleshooting: the injection that
        would use this session reports it itself). *cancelled* ends the wait
        for a starting LTK Manager early.
        """
        self.last_failure_reason = None
        tools_manager = ToolsManager(self.tools_dir)

        launcher = tools_manager.detect_ltf_launcher()
        if launcher is None:
            self.last_failure_reason = MissingComponent.LTF_BRIDGE
            log.error(f"[INJECT] Missing LTF bridge in {self.tools_dir}: {LTF_LAUNCHER} + {LTF_BRIDGE_DLL}")
            if report:
                report_issue(
                    "LTF_MISSING",
                    "error",
                    "Injection failed: Rose's LTF bridge files are missing.",
                    details={"missing": f"{LTF_LAUNCHER} + {LTF_BRIDGE_DLL}"},
                    hint="Reinstall Rose, or restore ltk_launcher.exe and LeagueToolFlop.dll "
                         "from your antivirus quarantine, then restart Rose.",
                )
            return None

        manager = tools_manager.detect_ltk_manager()
        if manager is None:
            self.last_failure_reason = MissingComponent.LTK_MANAGER
            log.error("[INJECT] LTK Manager is not installed")
            if report:
                report_issue(
                    "LTK_MANAGER_MISSING",
                    "error",
                    "Injection failed: LTK Manager is not installed.",
                    hint="Install LTK Manager, or set ltkManagerPath in config.ini to its "
                         "ltk-manager.exe, then retry.",
                )
            return None

        # LTK Manager set to run as administrator: Windows refuses to start it
        # as the desktop user (error 740), which Rose's bridge cannot work with
        try:
            from utils.system.windows_account import check_ltk_settings
            check_ltk_settings()
        except Exception as e:
            log.debug(f"[INJECT] Could not check LTK Manager's compatibility settings: {e}")

        bridge, launched = self._connect_bridge(launcher, manager, report, cancelled)
        if bridge is None:
            return None

        session = LtfSession(
            bridge,
            launched,
            saved_mod_ids=manifest_ltk_ids(self.saved_mods_dir()),
            start_log_tail=LtkLogTail(LtkLogTail.log_dir()),
        )
        self._ready_library(session)
        shutil.rmtree(self.staging_root(), ignore_errors=True)
        return session

    def _ready_library(self, session: LtfSession) -> None:
        """Ready LTK Manager's library before the session's first install (an
        install is what sets the automatic mod check off): the check turned
        off, the built-in mods checked, an earlier session's leftovers undone."""
        self._turn_off_health_check(session.bridge)
        self._check_ltk_builtins()
        self._cleanup_stale_installs(session)

    def end(self, session: LtfSession, ending: Optional[Callable[[], None]] = None) -> None:
        """Stop the patcher, remove Rose's mods (the user's saved mods stay,
        turned off, for the next game: _park; those LTK Manager holds are
        switched off), turn the user's back on, and close LTK Manager if Rose
        started it (a running one is the user's). *ending* runs first, once
        the session is marked ended: what its user undoes before (a game held
        frozen).

        Safe to call more than once: Rose's cleanup and the session loop can
        both get here.
        """
        with session.lock:
            if session.ended:
                return
            session.ended = True
        if ending is not None:
            ending()

        bridge = session.bridge
        if not bridge.alive():
            log.info("[INJECT] The LTF bridge is gone - Rose's mods are removed at the next session")
            if session.rose_started_manager:
                self._terminate_manager(bridge.pid)
            return
        try:
            bridge.stop_patcher()
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.debug(f"[INJECT] Could not stop the LTK patcher: {e}")

        removed = []
        for mod_id, tracked in session.imports.items():
            if self._park(session, mod_id):
                log.debug(f"[INJECT] Turned off {tracked.source_folder} in LTK Manager, kept for the next game")
                continue
            try:
                bridge.uninstall(mod_id)
                removed.append(mod_id)
                log.debug(f"[INJECT] Removed {tracked.source_folder} from LTK Manager")
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not remove {tracked.source_folder} from LTK Manager: {e}")
        self.switches.switch_off_all(session)
        restored = []
        for mod_id in session.user_mods_turned_off:
            try:
                bridge.toggle(mod_id, True)
                restored.append(mod_id)
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not turn {mod_id} back on in LTK Manager: {e}")
        self.journal.untrack(removed, restored)

        if session.rose_started_manager:
            bridge.kill()
            self._terminate_manager(bridge.pid, grace_s=EXIT_GRACE_BEFORE_NEXT_SESSION_S)

    def import_archive(self, session: LtfSession, archive: Path, folder: Path, display_name: str,
                       fingerprint: Optional[str] = None, before_ids: Optional[set] = None) -> dict:
        """Import *archive* into LTK Manager's library and return its entry,
        tracked as Rose's (removed at the session's end) from here.

        *before_ids* are the library's ids before this import (read here when
        not given): an id among them is never taken for the import's.
        """
        bridge = session.bridge
        if before_ids is None:
            before_ids = {str(entry.get("id")) for entry in bridge.library() if entry.get("id")}
        try:
            try:
                response = bridge.import_fantome(str(archive), name=display_name)
            except BridgeCommandError as e:
                if not _resendable_as_bytes(e, archive):
                    raise
                log.info(f"[INJECT] LTK Manager cannot read {archive.name} ({e}) - sending its bytes instead")
                response = bridge.import_fantome_bytes(archive.read_bytes(), name=archive.name)
        except (BridgeUnavailable, BridgeCommandError):
            self._track_late_install(session, before_ids, folder, display_name)
            raise
        entry = self._installed_entry(bridge, response, before_ids, folder, display_name)
        if entry is None:
            raise BridgeCommandError(f"{display_name} is not in the library after the import")
        tracked = self._track(session, str(entry.get("id")), folder.name, fingerprint)
        if fingerprint:
            tracked.saved_mod_source = self._keep_source(folder)
        return entry

    def keep(self, session: LtfSession, ltk_id: str) -> None:
        """Hand the entry to a saved mod for good: neither the session's end
        nor the next start removes it. Turned off; raises when it could not
        be (it is kept all the same)."""
        ltk_id = str(ltk_id)
        session.imports.pop(ltk_id, None)

        def release(state):
            state["installed"].pop(ltk_id, None)
            state["kept"].pop(ltk_id, None)

        self.journal.update(release)
        session.bridge.toggle(ltk_id, False)

    def uninstall(self, session: LtfSession, ltk_id: str) -> None:
        ltk_id = str(ltk_id)
        session.bridge.uninstall(ltk_id)
        if session.imports.pop(ltk_id, None) is not None:
            self.journal.untrack(removed=[ltk_id])

    def track_disabled(self, session: LtfSession, mod_id: str) -> None:
        """Record a user's mod turned off for the session, before it is."""
        session.user_mods_turned_off.append(mod_id)

        def add(state):
            if mod_id not in state["disabled"]:
                state["disabled"].append(mod_id)

        self.journal.update(add)

    def _track(self, session: LtfSession, mod_id: str, folder: str,
               fingerprint: Optional[str] = None) -> TrackedImport:
        tracked = session.imports[mod_id] = TrackedImport(folder, fingerprint)
        self.journal.update(lambda state: state["installed"].__setitem__(mod_id, folder))
        return tracked

    def remove_unwanted(self, session: LtfSession, mod_ids: List[str]) -> bool:
        """Remove Rose's mods that are no longer selected (staged for another skin)."""
        bridge = session.bridge
        removed, ok = [], True
        for mod_id in mod_ids:
            tracked = session.imports[mod_id]
            if self._park(session, mod_id):
                session.imports.pop(mod_id, None)
                log.debug(f"[INJECT] Turned off {tracked.source_folder} in LTK Manager (no longer selected, kept for later)")
                continue
            try:
                bridge.uninstall(mod_id)
            except (BridgeUnavailable, BridgeCommandError) as e:
                ok = self._turn_off_instead(bridge, mod_id, tracked, e) and ok
                tracked.source_digest = None
                continue
            removed.append(mod_id)
            session.imports.pop(mod_id, None)
            log.debug(f"[INJECT] Removed {tracked.source_folder} from LTK Manager (no longer selected)")
        self.journal.untrack(removed)
        return ok

    @staticmethod
    def _turn_off_instead(bridge, mod_id: str, tracked: TrackedImport, error: Exception) -> bool:
        """Turn off an import that could not be removed: left enabled it would
        apply too. False when it could not be turned off either."""
        try:
            bridge.toggle(mod_id, False)
            log.warning(f"[INJECT] Could not remove {tracked.source_folder} from LTK Manager ({error}) - "
                        "turned it off instead")
            return True
        except (BridgeUnavailable, BridgeCommandError) as toggle_error:
            log.error(f"[INJECT] Could not remove {tracked.source_folder} from LTK Manager: {toggle_error}")
            return False

    def reuse_kept(self, session: LtfSession, reuse: list, parked: Dict[str, dict], to_import: list,
                   library: Optional[list] = None) -> Optional[list]:
        """Turn the kept mods in *reuse* ((name, folder, fingerprint), id)
        back on for this session. One no longer in LTK Manager's library, or
        that cannot be turned on, goes back to *to_import*. Returns the
        library read (None when it could not be read: all are installed anew);
        *library* is one the install made already."""
        bridge = session.bridge
        if library is None:
            try:
                library = bridge.library()
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not read LTK Manager's library to reuse the kept mods: {e}")
                to_import.extend(item for item, _ in reuse)
                return None
        listed = {str(entry.get("id")) for entry in library if entry.get("id")}
        removed_by_user = []
        for (name, folder, fingerprint), mod_id in reuse:
            if mod_id not in listed:
                removed_by_user.append(mod_id)
                to_import.append((name, folder, fingerprint))
                continue
            try:
                bridge.toggle(mod_id, True)
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not turn the kept {name} back on ({e}) - installing it anew")
                to_import.append((name, folder, fingerprint))
                continue
            self._track_reused(session, mod_id, folder, fingerprint, parked[mod_id]["source"])
            log.info(f"[INJECT] Turned {fantome_display_name(folder) or name} back on in LTK Manager "
                     "(kept from an earlier game)")
        if removed_by_user:
            self.journal.forget_kept(removed_by_user)
        return library

    @staticmethod
    def _track_reused(session: LtfSession, mod_id: str, folder: Path, fingerprint: str, source: str) -> None:
        """Track a kept mod turned back on for the session. Its journal record
        stays the kept one: a crash leaves it in LTK Manager, and the next
        session turns it off."""
        session.imports[mod_id] = TrackedImport(folder.name, fingerprint, source)

    def _keep_source(self, mod: Path) -> Optional[str]:
        """Where *mod* in the injection's mods folder really is, when it is
        one of the user's saved mods LTK Manager may keep (a junction to a
        saved folder, or a hard link to a saved archive, of a mod that lives
        in LTK Manager's library: manifest.lives_in_ltk); None for a custom
        skin, Rose's skins, a generated mod, a party skin."""
        try:
            root = self.saved_mods_dir().resolve()
            source = Path(mod).resolve()
            if not source.is_relative_to(root):
                # A hard link does not resolve: find the saved archive that is the same file
                linked = source.stat()
                if not source.is_file() or linked.st_nlink < 2:
                    return None
                source = next((candidate for candidate in root.rglob("*") if _same_file(candidate, linked)), None)
            if source is not None and lives_in_ltk(source.relative_to(root).parts[0]):
                return str(source)
        except (OSError, ValueError):
            return None
        return None

    def _park(self, session: LtfSession, mod_id: str) -> bool:
        """Leave a saved mod Rose installed in LTK Manager, turned off, so the
        next game turns it back on instead of installing it again: a voiceover
        pack is a 3.5 GB copy each time (#486). False when it is not one to
        keep (skins, generated mods, an older copy of a kept one): remove it."""
        tracked = session.imports.get(mod_id)
        if tracked is None or not tracked.source_digest or not tracked.saved_mod_source:
            return False
        fingerprint, source = tracked.source_digest, tracked.saved_mod_source
        kept = self.journal.kept()
        if _same_content_kept(kept, mod_id, fingerprint):
            return False
        try:
            session.bridge.toggle(mod_id, False)
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.debug(f"[INJECT] Could not turn off {tracked.source_folder} to keep it: {e}")
            return False
        record = {"folder": tracked.source_folder, "fingerprint": fingerprint, "source": source}
        replaced = self._drop_earlier_versions(session, kept, mod_id, source, tracked.source_folder)

        def keep(state):
            state["installed"].pop(mod_id, None)
            for other in replaced:
                state["kept"].pop(other, None)
            state["kept"][mod_id] = record

        self.journal.update(keep)
        return True

    @staticmethod
    def _drop_earlier_versions(session: LtfSession, kept: Dict[LibraryId, KeptRecord], mod_id: str,
                               source: str, folder: str) -> List[str]:
        """Remove the kept copies of an earlier version of the saved mod
        *source*: it is not wanted any more. Returns those removed; one that
        could not be removed stays recorded, and the next park of this mod
        tries again."""
        replaced = []
        for other, kept_record in kept.items():
            if other == mod_id or kept_record["source"] != source:
                continue
            try:
                session.bridge.uninstall(other)
                replaced.append(other)
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not remove the earlier copy of {folder} ({other}): {e}")
        return replaced

    @staticmethod
    def _entry_matches(entry: dict, folder: Path, display_name: str) -> bool:
        names = {
            str(entry.get("displayName") or "").lower(),
            str(entry.get("name") or "").lower(),
        }
        return bool(names & {display_name.lower(), folder.name.lower()})

    @classmethod
    def _created_entries(cls, library: list, before_ids: set, folder: Path, display_name: str) -> list:
        """The entries an import created: new ids only, never one the user
        already had (it would be removed with Rose's). Name matches first;
        a lone new entry otherwise."""
        new_entries = [e for e in library if e.get("id") and str(e.get("id")) not in before_ids]
        named = [e for e in new_entries if cls._entry_matches(e, folder, display_name)]
        if named:
            return named
        return new_entries if len(new_entries) == 1 else []

    def _installed_entry(self, bridge: LtkBridge, response: dict, before_ids: set,
                         folder: Path, display_name: str) -> Optional[dict]:
        """The library entry a just-finished import created.

        LTK Manager answers an install with the entry it created: when that
        answer names a new id and says whether it is enabled, the library is
        not read again (each read is a round trip through LTK Manager).
        """
        nested = response.get("response")
        value = nested.get("value") if isinstance(nested, dict) else None
        if (isinstance(value, dict) and value.get("id") and "enabled" in value
                and str(value.get("id")) not in before_ids):
            return dict(value)
        library = bridge.library()
        new_entries = [e for e in library if e.get("id") and str(e.get("id")) not in before_ids]
        if isinstance(value, dict) and value.get("id"):
            for entry in new_entries:
                if str(entry.get("id")) == str(value.get("id")):
                    return entry
        created = self._created_entries(library, before_ids, folder, display_name)
        return created[-1] if created else None

    def _track_late_install(self, session: LtfSession, before_ids: set, folder: Path, display_name: str) -> None:
        """Record whatever an import that reported a failure still installed
        (its answer lost or too late): it is Rose's to remove."""
        try:
            library = session.bridge.library()
        except (BridgeUnavailable, BridgeCommandError):
            return
        for entry in self._created_entries(library, before_ids, folder, display_name):
            log.warning(f"[INJECT] {display_name} was installed although the import failed - Rose removes it after the session")
            self._track(session, str(entry.get("id")), folder.name)

    def _cleanup_stale_installs(self, session: LtfSession) -> None:
        """Undo what an earlier session left in LTK Manager (Rose crashed or
        was closed before its cleanup ran): remove its mods, turn the user's
        back on, switch off the saved mods it switched on. What cannot be
        undone now stays recorded for the next try. Kept saved mods stay,
        turned off, unless their saved mod is gone. An entry a saved mod's
        manifest names (session.saved_mod_ids) is the user's mod: never removed
        as a leftover, only switched off (SavedModSwitches)."""
        bridge, saved_mod_ids = session.bridge, session.saved_mod_ids
        state = self.journal.read()
        installed, disabled, kept = state["installed"], state["disabled"], state["kept"]
        if not installed and not disabled and not kept and not state["switched"] and not saved_mod_ids:
            return
        try:
            library = {str(entry.get("id")): entry for entry in bridge.library() if entry.get("id")}
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.debug(f"[INJECT] Could not read LTK Manager's library to clean up an earlier session: {e}")
            return

        forgotten = [mod_id for mod_id in kept if mod_id not in library or mod_id in saved_mod_ids]
        orphaned = [mod_id for mod_id in kept
                    if mod_id not in forgotten and not Path(kept[mod_id]["source"]).exists()]
        enabled = [mod_id for mod_id in kept
                   if mod_id not in forgotten and mod_id not in orphaned and library[mod_id].get("enabled")]
        leftovers = self.switches.leftovers(library, state["switched"], saved_mod_ids)
        if installed or disabled or orphaned or enabled or leftovers:
            try:
                bridge.stop_patcher()
            except (BridgeUnavailable, BridgeCommandError):
                pass
        for mod_id in orphaned:
            try:
                bridge.uninstall(mod_id)
                forgotten.append(mod_id)
                log.debug(f"[INJECT] Removed the kept {kept[mod_id]['folder']}: its saved mod was deleted")
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not remove the kept {kept[mod_id]['folder']} ({mod_id}): {e}")
        for mod_id in enabled:
            try:
                bridge.toggle(mod_id, False)
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not turn off the kept {kept[mod_id]['folder']} ({mod_id}): {e}")
        if forgotten:
            self.journal.forget_kept(forgotten)
        self.switches.undo(bridge, leftovers)

        removed, restored = [], []
        for mod_id, folder in installed.items():
            gone_or_now_a_saved_mod = mod_id not in library or mod_id in saved_mod_ids
            if gone_or_now_a_saved_mod:
                removed.append(mod_id)
                continue
            try:
                bridge.uninstall(mod_id)
                removed.append(mod_id)
                log.debug(f"[INJECT] Removed {folder} left behind by an earlier session")
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not remove the leftover {folder} ({mod_id}): {e}")
        for mod_id in disabled:
            entry = library.get(mod_id)
            if entry is None or entry.get("enabled"):
                restored.append(mod_id)
                continue
            try:
                bridge.toggle(mod_id, True)
                restored.append(mod_id)
                log.debug(f"[INJECT] Turned {entry_name(entry)} back on (an earlier session turned it off)")
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not turn {mod_id} back on: {e}")
        self.journal.untrack(removed, restored)

    @staticmethod
    def _process_created(pid: Optional[int]) -> Optional[float]:
        if not pid:
            return None
        try:
            return psutil.Process(pid).create_time()
        except (psutil.Error, OSError):
            return None

    def _register_manager(self, pid: Optional[int]) -> None:
        """Remember the LTK Manager Rose started: it is the only one Rose closes."""
        if not pid:
            return
        created = self._process_created(pid)
        if self.process_manager:
            self.process_manager.ltk_manager_process = (pid, created)
        self.journal.update(lambda state: state.__setitem__("manager", {"pid": pid, "created": created}))

    def _is_rose_manager(self, pid: Optional[int]) -> bool:
        """Whether the LTK Manager with *pid* is one Rose started (this run or before)."""
        manager = self.journal.read()["manager"]
        if not pid or not manager or manager.get("pid") != pid:
            return False
        created, recorded = self._process_created(pid), manager.get("created")
        return created is None or recorded is None or abs(created - float(recorded)) <= 1.0

    def _terminate_manager(self, pid: Optional[int], grace_s: float = 0.0) -> None:
        """Terminate the LTK Manager *pid* Rose started, if it still runs
        after *grace_s* (the time a requested exit gets to finish)."""
        if not pid:
            return
        try:
            proc = psutil.Process(pid)
            if (proc.name() or "").lower() not in LTK_MANAGER_PROCESSES:
                return
            if grace_s > 0:
                try:
                    proc.wait(timeout=grace_s)
                    return
                except psutil.TimeoutExpired:
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                proc.kill()
            log.info(f"[INJECT] Closed the LTK Manager Rose started (PID {pid})")
        except (psutil.Error, OSError) as e:
            log.debug(f"[INJECT] Could not close LTK Manager (PID {pid}): {e}")

    def _close_stale_rose_manager(self) -> None:
        """Close an LTK Manager Rose started whose bridge no longer answers."""
        manager = self.journal.read()["manager"]
        if not manager:
            return
        pid = manager.get("pid")
        if self._is_rose_manager(pid) and self._process_created(pid) is not None:
            log.info(f"[INJECT] The LTK Manager Rose started (PID {pid}) lost its bridge - closing it")
            self._terminate_manager(pid)
        self.journal.update(lambda state: state.__setitem__("manager", None))

    def _users_manager_open(self) -> bool:
        """Whether an LTK Manager Rose did not start is open (one Rose started
        whose bridge is gone is closed first). The bridge only loads into an
        LTK Manager the launcher starts, and the user's stays open."""
        self._close_stale_rose_manager()
        return self._ltk_manager_running()

    @staticmethod
    def _ltk_manager_running() -> bool:
        """Whether any LTK Manager is running."""
        try:
            for proc in psutil.process_iter(['name']):
                if (proc.info.get('name') or '').lower() in LTK_MANAGER_PROCESSES:
                    return True
        except (psutil.Error, OSError) as e:
            log.debug(f"[INJECT] Could not look for LTK Manager: {e}")
        return False

    @staticmethod
    def _turn_off_health_check(bridge) -> None:
        """Turn off LTK Manager's "Automatically check mods": it checks each
        mod new to its library, and Rose installs the picked skin anew for each
        game, so it checked every game; on a hard drive that took minutes while
        the game sat on its loading screen (#481). The check means nothing for
        Rose's skins, and the user can still run it by hand in LTK Manager."""
        try:
            response = bridge.health_check_off()
        except _OLD_BRIDGE_OR_UNREADY_PAGE as e:
            log.debug(f"[INJECT] Could not turn off LTK Manager's automatic mod check: {e}")
            return
        if response.get("changed"):
            log.info(
                "[INJECT] Turned off LTK Manager's automatic mod check (Settings > Library > Automatically "
                "check mods): it checked Rose's skin anew every game"
            )

    @staticmethod
    def _check_ltk_builtins() -> None:
        """Warn (log and Troubleshooting) when LTK Manager's settings turn on a
        built-in mod that puts every champion's archive into the overlay."""
        logs = LtkLogTail.log_dir()
        if logs is None:
            return
        try:
            settings = json.loads((logs.parent / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.debug(f"[INJECT] Could not read LTK Manager's settings: {e}")
            return
        heavy = heavy_builtin_mods(settings)
        if not heavy:
            return
        names = ", ".join(heavy)
        log.warning(f"[INJECT] {HEAVY_BUILTINS_MESSAGE} ({names}): each overlay build takes minutes")
        report_issue(
            "LTK_HEAVY_BUILTINS",
            "warning",
            f"{HEAVY_BUILTINS_MESSAGE} ({names}).",
            details={"builtins": names},
            hint=HEAVY_BUILTINS_HINT,
            dedupe_window_s=600.0,
        )

    @staticmethod
    def _wait_for_cdp(bridge, cancelled: Optional[Callable[[], bool]] = None) -> None:
        """Wait until LTK Manager's built-in browser answers the bridge, up to
        CDP_READY_TIMEOUT_S: it comes up seconds after the bridge itself. One
        that never answers is left to the commands that need it to report."""
        started = time.monotonic()
        while True:
            try:
                bridge.library()
            except BridgeCommandError as e:
                left_to_library_commands = not _cdp_not_up_yet(e)
                if left_to_library_commands:
                    return
            except BridgeUnavailable:
                return
            else:
                waited = time.monotonic() - started
                if waited >= CDP_READY_POLL_S:
                    log.info(f"[INJECT] LTK Manager's built-in browser answered after {waited:.1f}s")
                return
            if time.monotonic() - started >= CDP_READY_TIMEOUT_S or (cancelled is not None and cancelled()):
                log.warning(
                    f"[INJECT] LTK Manager's built-in browser did not answer within {CDP_READY_TIMEOUT_S:.0f}s"
                )
                return
            time.sleep(CDP_READY_POLL_S)

    def _log_launcher_run(self, sizes: Dict[Path, int]) -> None:
        """Copy what ltk_launcher.exe (and its helper) logged for this start
        into Rose's log, and keep the parent it gave LTK Manager."""
        parent = None
        for line in _new_log_lines(sizes):
            if line.startswith("=========="):
                continue
            if line.startswith(("[warn]", "[err]")):
                log.warning(f"[INJECT] ltk_launcher: {line}")
            elif line.startswith("[launch]"):
                log.info(f"[INJECT] ltk_launcher: {line}")
            else:
                log.debug(f"[INJECT] ltk_launcher: {line}")
            found = LAUNCHER_PARENT_LOG_LINE.search(line)
            if found:
                parent = found.group(1).strip()
        self.logged_manager_parent = parent

    def _session_failed(self, reason: str, report: bool) -> None:
        """Keep why the session could not start (last_failure_reason), and
        report it as before."""
        self.last_failure_reason = reason
        report_ltf_failure(reason, report)

    def _connect_bridge(self, launcher: Path, manager: Path, report: bool,
                        cancelled: Optional[Callable[[], bool]] = None):
        """The bridge and whether Rose started LTK Manager for it."""
        found = find_bridge()
        if found is not None:
            port, hello = found
            pid = hello.get("pid")
            launched = self._is_rose_manager(pid)
            if launched:
                self._register_manager(pid)
            log.info(
                f"[INJECT] Reusing the running LTK Manager (bridge on port {port}"
                f"{', started by Rose' if launched else ''})"
            )
            return LtkBridge(port, pid=pid), launched

        if self._users_manager_open():
            log.warning("[INJECT] LTK Manager is already open without Rose's bridge - leaving it alone")
            self._session_failed(ALREADY_OPEN_REASON, report)
            return None, False

        log.info(f"[INJECT] Starting LTK Manager through {launcher.name}")
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        log_dir = ltk_logs_dir()
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.debug(f"[INJECT] Could not create {log_dir}: {e}")
        _rotate_launcher_log(log_dir / "ltk_launcher.log")
        launcher_logs = _log_sizes(launcher_log_paths())
        try:
            result = subprocess.run(
                [str(launcher), "--exe", str(manager), "--quiet", "--log-dir", str(log_dir)],
                cwd=str(launcher.parent),
                creationflags=creationflags,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=LAUNCHER_TIMEOUT_S,
            )
        except Exception as e:
            self._log_launcher_run(launcher_logs)
            self._session_failed(f"could not start the LTF launcher ({e})", report)
            return None, False
        self._log_launcher_run(launcher_logs)
        if result.returncode == LauncherExit.ALREADY_RUNNING:
            log.warning("[INJECT] LTK Manager opened before the launcher could start it - leaving it alone")
            self._session_failed(ALREADY_OPEN_REASON, report)
            return None, False
        if result.returncode != LauncherExit.OK:
            self._session_failed(
                f"could not start the LTF launcher (exit code {result.returncode})", report
            )
            return None, False

        match = re.search(r"LTK_MANAGER_PID=(\d+)", result.stdout or "")
        hidden_manager_pid = int(match.group(1)) if match else None
        try:
            bridge = LtkBridge.wait_for_bridge(
                timeout=BRIDGE_START_TIMEOUT_S, expected_pid=hidden_manager_pid, cancelled=cancelled
            )
        except BridgeUnavailable as e:
            reason = f"the LTF bridge is unreachable ({e})"
            if cancelled is not None and cancelled():
                self.last_failure_reason = reason
                log.debug("[INJECT] Stopped waiting for the LTF bridge: the session is no longer wanted")
            else:
                self._session_failed(reason, report)
            self._terminate_manager(hidden_manager_pid)
            return None, False
        self._register_manager(bridge.pid or hidden_manager_pid)
        self._wait_for_cdp(bridge, cancelled)
        return bridge, True
