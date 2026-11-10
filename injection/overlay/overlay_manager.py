#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

# Import psutil with fallback for development environments
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

from injection.game.reconnect import kill_game, reconnect_to_game
from utils.core.logging import get_logger, log_event
from utils.core.issue_reporter import report_issue
from ..tools.bridge import BridgeCommandError, BridgeUnavailable
from ..mods.fantome import fantome_display_name, write_fantome_zip
from ..mods.fingerprint import mod_fingerprint
from ..mods.ltk_ref import split_mod_names
from ..mods.mod_files import is_mod_archive
from utils.core.modpkg import is_modpkg
from utils.system.process_list import running_processes
from .ltf_report import (
    LATE_JOIN_MESSAGE,
    LTF_LOGS_HINT,
    LTK_ACL_REFUSAL,
    NOT_ATTACHED_MESSAGE,
    OVERLAY_DISABLED_MESSAGE,
    SIGNATURE_FAILURE_MESSAGE,
    cdp_unreachable,
    cdp_unreachable_reason,
    report_ltf_failure,
)
from .ltf_session import (
    LIBRARY_IMPORT_HEADROOM_BYTES,
    LAUNCHER_SHELL_PARENT,
    MIN_LIBRARY_FREE_BYTES,
    LtfHost,
    LtfSession,
    archive_for_ltk,
)
from .ltk_data import LtkLogTail, entry_name
from config import (
    GAME_EXECUTABLE_NAMES,
    PROCESS_MONITOR_SLEEP_S,
)

log = get_logger()

# The patcher status is polled while the game runs (one tick per sleep)
PATCHER_STATUS_POLL_TICKS = 4
# After start_patcher, how long the injection waits for the patcher to build
# the overlay and scan. A game the client creates before the scan is missed:
# it is restarted (within the Monitor Auto-Resume Timeout) or reported.
PATCHER_READY_TIMEOUT_S = 45.0
# The patcher only overlays a game the client created after its scan started,
# and it cannot hook a frozen game: a game it missed is killed and the client
# reconnects to the match, launching it again under the scan. At most this
# many times a session, so a relaunch the patcher misses too cannot loop
RESTART_MISSED_GAME = True
RECONNECT_MAX = 1
# The Monitor Auto-Resume Timeout setting: how long after the client created
# the game Rose may still restart it for the patcher. Past it the player is in
# the match: the game is left running without the overlay, and Troubleshooting
# suggests a longer timeout
RESTART_WINDOW_DEFAULT_S = 60.0
RESTART_WINDOW_MIN_S = 1.0
RESTART_WINDOW_MAX_S = 180.0
RESTART_SKIPPED_MESSAGE = "Rose did not restart the game for the LTK patcher"


def restart_window_s() -> float:
    """The Monitor Auto-Resume Timeout (General/monitor_auto_resume_timeout)."""
    try:
        from config import get_config_float
        value = float(get_config_float("General", "monitor_auto_resume_timeout", RESTART_WINDOW_DEFAULT_S))
    except Exception as e:  # noqa: BLE001
        log.debug(f"[INJECT] Could not read the Monitor Auto-Resume Timeout: {e}")
        return RESTART_WINDOW_DEFAULT_S
    if value != value:  # NaN
        return RESTART_WINDOW_DEFAULT_S
    return max(RESTART_WINDOW_MIN_S, min(RESTART_WINDOW_MAX_S, value))
PATCHER_READY_POLL_S = 0.25
# While the patcher builds, a thread watches for the game and suspends it as
# soon as the client creates it: the game guards its process (access denied)
# within a second of its start, too late for the patcher wait's own polling
HOLD_WATCH = True
HOLD_WATCH_POLL_S = 0.05  # what the old game monitor used
HOLD_WATCH_HELD_POLL_S = 0.1
# A patcher still idle this long after start_patcher answered did not start
PATCHER_IDLE_GRACE_S = 3.0
# Unanswered status polls in a row (CDP busy, a slow eval) before the session
# counts as broken: one failed poll is not the end of a game
STATUS_FAILURE_LIMIT = 5

# LTK Manager stops its patcher only once the overlay build in progress is done
# (62s with map mods in #437): a start in between is refused as ALREADY_RUNNING.
# How long to wait for the stopping patcher before giving up
PATCHER_ALREADY_RUNNING = "ALREADY_RUNNING"
PATCHER_STOP_WAIT_S = 120.0

# The DLL's host verification refusing the overlay (docs/ltf-vrf-host-verification.md):
# the code names the check that failed, the bracket after it what it saw
OVERLAY_REFUSED_CODE = re.compile(r"\[(vrf\d{8})\]\s*\(([^)]*)\)?", re.IGNORECASE)
# A check in that chain naming a WinVerifyTrust result: Windows could not verify
# the Authenticode signature of LTK Manager's own files (0x80096010
# TRUST_E_BAD_DIGEST: a file modified or damaged after signing; 0x800B01xx: a
# certificate Windows does not trust). Reinstalling LTK Manager fixes it (#442)
OVERLAY_SIGNATURE_CODE = re.compile(r"\[vrf\d{8}\]\s*\((800960[0-9a-f]{2}|800b0[0-9a-f]{3})\)", re.IGNORECASE)
# The DLL's integrity scan turning the overlay off in the game: a mod's WAD
# failed a check, which the rest of the line names (a custom skin made of
# another skin's files: "base-skin check: skin0 is another skin: ...")
OVERLAY_DISABLED_LINE = re.compile(r"overlay verification failed, disabling overlay:\s*([^\r\n\"]+)", re.IGNORECASE)
# LTK's host found the game but its DLL never loaded into it: the game runs
# without the overlay, and the incident LTK Manager files for it can be titled
# "Unexplained Game Exit", which does not say so (#475)
DLL_NOT_ATTACHED_LINE = re.compile(r"DLL never attached after \d+\s*s", re.IGNORECASE)
# A mod LTK Manager cannot read (its metadata empty or damaged): its library
# leaves it out, so Rose never saw it to turn off, but an enabled one still
# fails every overlay build with "Serialization(... expected value ...)" (#479)
BROKEN_ENTRY_LINE = re.compile(r"Skipping broken mod entry ([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})")
# LTK Manager checks each mod new to its library ("Automatically check mods"),
# and Rose installs the picked skin anew for each game. That check takes
# seconds; on a slow drive it took 4 to 6 minutes, reading the disk while the
# game loaded, and the game sat on a black loading screen until it was closed
# (#481). Its log line gives the time as a Rust duration ("263.05s", "361.8ms")
SLOW_MOD_CHECK_LINE = re.compile(r"Swept mod health in ([0-9.]+)(ns|µs|us|ms|s)\b")
DURATION_UNITS_S = {"ns": 1e-9, "µs": 1e-6, "us": 1e-6, "ms": 1e-3, "s": 1.0}
SLOW_MOD_CHECK_S = 30.0
SLOW_MOD_CHECK_MESSAGE = "LTK Manager's automatic mod check took"
SLOW_MOD_CHECK_HINT = (
    "Quit Rose, open LTK Manager from the Start menu > Settings > Library, turn off \"Automatically check mods\", "
    "then close LTK Manager (also from the system tray) and start Rose again."
)
# LTK Manager's diagnosis of a game that went wrong (a WAD League could not
# mount, a crash...), kept as <id>.json in its incidents folder
INCIDENT_LINE = re.compile(r"Incident recorded:\s*([^\r\n]*?)\s+id=(\S+)\s+verdict=(\w+)")
LTK_INCIDENTS_DIR = "%APPDATA%\\dev.leaguetoolkit.manager\\incidents"
# What LTK Manager's log says about the patcher's start (its lines begin with
# a UTC time): how long the overlay took to build, and when the host began to
# scan. The patcher only overlays a game created after that moment.
_LTK_LOG_TIME = r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)Z"
SCAN_STARTED_LINE = re.compile(r"^" + _LTK_LOG_TIME + r"[^\n]*session started: scanning for game", re.MULTILINE)
OVERLAY_BUILT_LINE = re.compile(r"Overlay build complete:[^\n]*? in ([\d.]+)(ms|s)\b")
# LTK Manager's own reason when its patcher gives up: an ERROR line of its
# patcher or overlay builder ("No patcher DLL is available" when the DLL it
# downloads on the first start could not be fetched, "Overlay build failed",
# "Start patcher failed" for League set to run as administrator...)
LTK_PATCHER_ERROR_LINE = re.compile(
    r"^" + _LTK_LOG_TIME + r"\s+ERROR\s+[\w:]*(?:patch|overlay)[\w:]*:\s*([^\r\n]+)",
    re.MULTILINE | re.IGNORECASE,
)
LTK_ERROR_MAX_CHARS = 300


def _ltk_log_time(stamp: str) -> Optional[float]:
    """The epoch time of an LTK Manager log line's UTC stamp (2026-11-04T18:08:17.201030)."""
    whole, _, fraction = stamp.partition(".")
    try:
        moment = datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return moment.timestamp() + (float(f"0.{fraction}") if fraction.isdigit() else 0.0)


class OverlayManager:
    """Manages the LTF session: install mods, run LTK Manager's patcher"""

    def __init__(self, tools_dir: Path, mods_dir: Path, game_dir: Optional[Path], process_manager=None):
        self.tools_dir = tools_dir
        self.mods_dir = mods_dir
        self.game_dir = game_dir
        self.process_manager = process_manager
        self.last_injection_timing = None
        # Session connected (or launched) at the countdown or when the
        # injection starts, before the mods are prepared; mk_run_overlay
        # takes it over
        self._early_session: Optional[dict] = None
        self._early_session_lock = threading.Lock()
        self._early_session_unwanted = False
        self._countdown_staging_open = False
        self.host = LtfHost(tools_dir, mods_dir.parent, process_manager, in_use=self._holds_ltk_manager)

    @property
    def current_overlay_process(self):
        """Get current overlay process from process manager"""
        return self.process_manager.current_overlay_process if self.process_manager else None

    @current_overlay_process.setter
    def current_overlay_process(self, value):
        """Set current overlay process on process manager"""
        if self.process_manager:
            self.process_manager.current_overlay_process = value

    def _holds_ltk_manager(self) -> bool:
        """Whether the early session or the countdown's staging holds LTK
        Manager (LtfHost.busy)."""
        with self._early_session_lock:
            return self._early_session is not None or self._countdown_staging_open

    def _new_session(self, ltf: LtfSession) -> dict:
        return {
            "ltf": ltf,
            "patcher_running": False,
            "ltk_log": None,  # LtkLogTail from the patcher's start
            "broken_entries": set(),
            "broken_off": set(),  # those Rose turned off
            # Read from LTK Manager's log since the patcher's (last) start
            "overlay_build_s": None,
            "scan_started_at": None,  # epoch time the host began to scan
            "ltk_attached": False,
            "ltk_late": False,
            "ltk_refused": None,  # (check code, what it saw)
            "ltk_signature": None,  # the WinVerifyTrust result in that refusal, as 0x...
            "ltk_disabled": None,  # why the DLL's integrity scan turned the overlay off
            "ltk_incident": None,  # (title, id, verdict) LTK Manager recorded after the game
            "ltk_not_attached": None,  # LTK's host giving up on getting its DLL into the game
            "ltk_slow_mod_check_s": None,  # LTK Manager's longest automatic mod check, when slow
            "ltk_error": None,  # LTK Manager's first patcher ERROR line
            "staged_after_s": None,  # pick -> patcher start, for the staged mods
            "library_snapshot": None,
            "attach_logged": False,
            "stopper": None,
            "state": None,
            "error": None,
            "done": False,
            "game_seen": False,
            "status_failures": 0,
            "late_join_reported": False,
            "reconnects": 0,  # games killed and reconnected to (RECONNECT_MAX)
            "restarted_at": None,  # epoch time of the last such restart
            "hold_lock": threading.Lock(),
            "hold_thread": None,
            "hold_done": False,  # the patcher is ready (or gave up): hold no more
            "hold_failed": False,
            "held_game": None,
            "held_at": None,  # time.monotonic() of the hold
            "refused_reported": False,
            "disabled_reported": False,
            "incident_reported": False,
            "not_attached_reported": False,
            "slow_mod_check_reported": False,
            "early_stop_logged": False,
        }

    def _start_ltf_session(self, report: bool = True, cancelled: Optional[Callable[[], bool]] = None) -> Optional[dict]:
        """A new LTF session (LtfHost.start) for this injection to run, None
        when it could not start."""
        ltf = self.host.start(report=report, cancelled=cancelled)
        return None if ltf is None else self._new_session(ltf)

    def start_patcher_early(self) -> None:
        """Bring LTK Manager and its bridge up now, before the mods are prepared.

        Starting LTK Manager takes seconds, and preparing the mods (extraction,
        loading screen name, party skins) more on a slow PC, while the client
        launches the game: the bridge is brought up early. mk_run_overlay
        takes this session over; it reports missing components itself.
        """
        if self.game_dir is None:
            return
        with self._early_session_lock:
            self._early_session_unwanted = False
        if not self.host.launcher_lock.acquire(blocking=False):
            return  # the connect in flight brings it up
        try:
            with self._early_session_lock:
                session = self._early_session
            if session is not None:
                if self._check_bridge(session):
                    return
                # Rose stopped it after the last game: connect again for this one
                with self._early_session_lock:
                    if self._early_session is session:
                        self._early_session = None
                self._end_session(session)

            session = self._start_ltf_session(report=False, cancelled=lambda: self._early_session_unwanted)
            if session is None:
                return
            with self._early_session_lock:
                keep = not self._early_session_unwanted
                if keep:
                    self._early_session = session
            if not keep:
                log.debug("[INJECT] The early LTF session is no longer wanted - stopping it")
                self._end_session(session)
        finally:
            self.host.launcher_lock.release()

    def _acquire_session(self) -> Optional[dict]:
        """The early session if its bridge is still up, else a new one.

        Waits for an early connect in flight rather than start a second
        LTK Manager next to it.
        """
        with self.host.launcher_lock:
            with self._early_session_lock:
                session, self._early_session = self._early_session, None
            if session is not None:
                if self._check_bridge(session):
                    return session
                self._end_session(session)
            return self._start_ltf_session(report=True, cancelled=self._stopped_by_rose)

    def discard_early_patcher(self) -> None:
        """Stop an LTF session whose injection never built its overlay.

        Returns at once while LTK Manager is still starting: that connect
        drops its session when it completes.
        """
        with self._early_session_lock:
            session, self._early_session = self._early_session, None
            self._early_session_unwanted = True
            self._countdown_staging_open = False
        if session:
            log.debug("[INJECT] Stopping the LTF session started for an injection that did not happen")
            self._end_session(session)

    def _end_session(self, session: dict) -> None:
        """End the LTF session (LtfHost.end: Rose's mods removed, the user's
        turned back on, LTK Manager closed if Rose started it), a held game
        resumed first.

        Safe to call more than once: Rose's cleanup and the session loop can
        both get here.
        """
        def ending():
            self._release_held_game(session)
            if self.process_manager and session.get("stopper") is not None:
                self.process_manager.clear_session_stopper(session["stopper"])
            if self.process_manager:
                self.process_manager.current_overlay_process = None

        self.host.end(session["ltf"], ending)

    def _release_held_game(self, session: dict) -> None:
        """Hold the game no more and resume it: a held game is never left frozen."""
        session["hold_done"] = True
        self._resume_held_game(session)

    def _check_bridge(self, session: dict) -> bool:
        """Whether the bridge inside LTK Manager still answers."""
        ltf = session.get("ltf")
        if ltf is None or ltf.ended:
            return False
        return ltf.bridge.alive()

    def _stopped_by_rose(self) -> bool:
        """Whether Rose (or the user) asked to stop the current session."""
        if not self.process_manager:
            return False
        return bool(self.process_manager.stopped_by_user or self.process_manager.stopped_by_rose)

    def _session_stopped(self, session: dict) -> bool:
        """Whether the session was stopped (by Rose, the user, or its end)."""
        return bool(session["ltf"].ended) or self._stopped_by_rose()

    def _install_mods(self, session: dict, mod_names: List[str], folder_dir: Optional[Path] = None,
                      report: bool = True, stopped: Optional[Callable[[], bool]] = None,
                      archives: Optional[Dict[str, Path]] = None) -> bool:
        """Make Rose's mods in LTK Manager's library exactly the folders
        *mod_names* (in *folder_dir*, mods_dir by default), and the saved mods
        LTK Manager holds that *mod_names* name by their LTK reference
        switched on: those are never imported (SavedModSwitches).

        A mod already installed from the same content (staged during the
        countdown, see stage_mods) is kept as it is: an unchanged library keeps
        the patcher's scan running. Any other change stops the patcher first,
        as LTK Manager itself would to rebuild the overlay.

        Each import installs a new copy, so the id it creates is recorded in
        the state file right away: _end_session removes them again, and a
        crashed session is cleaned up by the next one. report=False keeps
        failures out of Troubleshooting (the staging leaves that to the
        injection); *stopped* tells when to give up. *archives* are folders
        already packed (pack_mods), imported as they are.
        """
        ltf = session["ltf"]
        bridge = ltf.bridge
        folder_dir = Path(folder_dir) if folder_dir else self.mods_dir
        if stopped is None:
            stopped = lambda: self._session_stopped(session)
        session["library_snapshot"] = None

        files, ltk_ids = split_mod_names(mod_names)
        wanted = []
        for name in files:
            folder = folder_dir / name
            if not folder.is_dir() and not is_mod_archive(folder) and not is_modpkg(folder):
                log.error(f"[INJECT] Mod not found: {folder}")
                continue
            try:
                wanted.append((name, folder, mod_fingerprint(folder)))
            except OSError as e:
                log.error(f"[INJECT] Could not read the mod folder {folder}: {e}")
        switch_on, switch_off = self.host.switches.changes(ltf, ltk_ids)
        shared_library_read: Optional[list] = None
        if switch_on:
            try:
                shared_library_read = bridge.library()
            except (BridgeUnavailable, BridgeCommandError) as e:
                return self._saved_mods_failed(e, report and not stopped())
            switch_on = self.host.switches.listed(switch_on, shared_library_read)
        if not wanted and not switch_on and not (set(ltk_ids) & ltf.confirmed_on):
            log.error("[INJECT] No mods could be installed into LTK Manager")
            if report and not stopped():
                report_issue(
                    "LTF_IMPORT_FAILED",
                    "error",
                    "Injection failed: no mods could be installed into LTK Manager.",
                    details={"mods": "/".join(mod_names)},
                    hint=f"Retry; if it keeps happening, report it with rose_*.log. {LTF_LOGS_HINT}",
                )
            return False

        kept, to_import = set(), []
        for name, folder, fingerprint in wanted:
            match = next(
                (mod_id for mod_id, tracked in ltf.imports.items()
                 if tracked.source_digest == fingerprint and mod_id not in kept),
                None,
            )
            if match is None:
                to_import.append((name, folder, fingerprint))
            else:
                kept.add(match)
        unwanted = [mod_id for mod_id in ltf.imports if mod_id not in kept]
        reuse, parked = self._reuse_parked(to_import)
        if not to_import and not unwanted and not reuse and not switch_on and not switch_off:
            return True  # the library already holds exactly these mods

        if session["patcher_running"]:
            log.warning(
                "[INJECT] The mods differ from the ones staged during the countdown - restarting the "
                "LTK patcher (it only overlays a game the client starts after that)"
            )
            self._stop_patcher(session)
        if unwanted and not self.host.remove_unwanted(ltf, unwanted):
            return False
        if reuse:
            shared_library_read = self.host.reuse_kept(ltf, reuse, parked, to_import, shared_library_read)
        try:
            self.host.switches.switch(ltf, switch_on, switch_off, shared_library_read)
        except (BridgeUnavailable, BridgeCommandError) as e:
            return self._saved_mods_failed(e, report and not stopped())

        staging = self.host.staging_root() / uuid.uuid4().hex
        try:
            for name, folder, fingerprint in to_import:
                if stopped():
                    log.info("[INJECT] Stopped while the mods were being installed")
                    return False
                display_name = fantome_display_name(folder)
                try:
                    if shared_library_read is None:
                        shared_library_read = bridge.library()
                    archive = (archives or {}).get(name)
                    if archive is None or not Path(archive).is_file():
                        staging.mkdir(parents=True, exist_ok=True)
                        archive = archive_for_ltk(folder, staging / f"{name}.fantome")
                    before_ids = {str(e.get("id")) for e in shared_library_read if e.get("id")}
                    entry = self.host.import_archive(ltf, Path(archive), folder, display_name, fingerprint,
                                                     before_ids=before_ids)
                    shared_library_read.append(entry)
                    if not entry.get("enabled"):
                        bridge.toggle(str(entry.get("id")), True)
                    log.info(f"[INJECT] Installed {display_name} into LTK Manager")
                except (OSError, BridgeUnavailable, BridgeCommandError) as e:
                    log.error(f"[INJECT] Could not install {display_name}: {e}")
                    if report and not stopped():
                        if cdp_unreachable(e):
                            report_ltf_failure(cdp_unreachable_reason())
                        elif LTK_ACL_REFUSAL in str(e).lower():
                            report_ltf_failure(f"LTK Manager refused Rose's commands ({e})")
                        elif not self._report_low_disk_space_failure(mod_names):
                            report_issue(
                                "LTF_IMPORT_FAILED",
                                "error",
                                f"Injection failed: could not install {display_name} ({e}).",
                                details={"mod": folder.name, "error": str(e)},
                                hint=f"Free some disk space, then retry. {LTF_LOGS_HINT}",
                            )
                    return False
            session["library_snapshot"] = shared_library_read
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return True

    def _reuse_parked(self, to_import: list) -> tuple:
        """(reuse, parked): the saved mods of *to_import* an earlier game left
        in LTK Manager (LtfHost._park), taken out of *to_import* to be turned
        back on instead of installed again, and every such parked mod."""
        reuse = []
        parked = self.host.journal.kept() if to_import else {}
        if parked:
            by_fingerprint = {record["fingerprint"]: mod_id for mod_id, record in parked.items()}
            for item in list(to_import):
                mod_id = by_fingerprint.pop(item[2], None)
                if mod_id is not None:
                    reuse.append((item, mod_id))
                    to_import.remove(item)
        return reuse, parked

    def _saved_mods_failed(self, error: Exception, report: bool) -> bool:
        """Fail the install: a saved mod LTK Manager holds could not be
        switched (one left off is missing from the overlay, one left on
        applies with it)."""
        log.error(f"[INJECT] Could not switch the saved mods in LTK Manager: {error}")
        if report:
            report_ltf_failure(
                cdp_unreachable_reason() if cdp_unreachable(error)
                else f"could not switch a saved mod in LTK Manager ({error})"
            )
        return False

    def pack_mods(self, folder_dir: Path, mod_names: List[str]) -> Dict[str, Path]:
        """Pack the mod folders into the archives LTK Manager imports, ahead of the install.

        The countdown's stager packs while the selection settles, so its
        install only has to import (stage_mods(archives=...)). Each archive
        lands next to its folder (<folder_dir>/<name>.fantome); a folder that
        cannot be packed is left out and packed by the install instead. So is
        a mod an earlier pick already staged (a saved map or voiceover mod,
        the same for every skin): the install keeps it as it is. A mod that
        is an archive already needs no packing, nor does a saved mod LTK
        Manager holds (named by its LTK reference).
        """
        staged = self._staged_fingerprints()
        archives: Dict[str, Path] = {}
        for name in split_mod_names(mod_names)[0]:
            folder = Path(folder_dir) / name
            archive = Path(folder_dir) / f"{name}.fantome"
            if folder.is_file():
                continue
            try:
                if staged and mod_fingerprint(folder) in staged:
                    continue
                write_fantome_zip(folder, archive)
                archives[name] = archive
            except OSError as e:
                log.debug(f"[STAGE] Could not pack {name} ahead of the install: {e}")
        return archives

    def _staged_fingerprints(self) -> set:
        """The content digests of the mods staged in the early session's LTK
        Manager, and of the saved mods kept there from an earlier game."""
        kept = {record["fingerprint"] for record in self.host.journal.kept().values()}
        with self._early_session_lock:
            session = self._early_session
        if session is None:
            return kept
        try:
            return kept | {tracked.source_digest for tracked in list(session["ltf"].imports.values())
                           if tracked.source_digest}
        except RuntimeError:  # an install changed them meanwhile
            return kept

    def _start_patcher(self, session: dict, report: bool = True) -> bool:
        """Start LTK Manager's patcher (it builds the overlay, then scans for the game)."""
        tail = LtkLogTail(LtkLogTail.log_dir())  # LTK's own log from this start on
        try:
            try:
                session["ltf"].bridge.start_patcher()
            except BridgeCommandError as e:
                # The last patcher has not exited yet: it finishes its overlay
                # build first. Wait for it, then start this one (#437)
                if PATCHER_ALREADY_RUNNING not in str(e).upper() or not self._wait_patcher_stopped(session):
                    raise
                session["ltf"].bridge.start_patcher()
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.error(f"[INJECT] Could not start the LTK patcher: {e}")
            if report and not self._session_stopped(session):
                report_ltf_failure(
                    cdp_unreachable_reason() if cdp_unreachable(e) else f"could not start the LTK patcher ({e})"
                )
            return False
        session["patcher_running"] = True
        session["patcher_started_at"] = time.monotonic()
        session["ltk_log"] = tail
        # This start builds its own overlay and scan
        session["overlay_build_s"] = None
        session["scan_started_at"] = None
        session["staged_after_s"] = None
        session["ltk_error"] = None
        # A game the client creates while this build runs is held at once
        session["hold_done"] = False
        self._start_hold_watch(session)
        return True

    def _wait_patcher_stopped(self, session: dict) -> bool:
        """Stop LTK Manager's patcher and wait until it exited, up to
        PATCHER_STOP_WAIT_S: a stop takes effect once the overlay build in
        progress is done. Whether it exited."""
        bridge = session["ltf"].bridge
        log.info("[INJECT] The last LTK patcher is still finishing its overlay build - waiting for it to stop")
        try:
            bridge.stop_patcher()
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.debug(f"[INJECT] Stop of the last LTK patcher: {e}")
        started = time.monotonic()
        while time.monotonic() - started < PATCHER_STOP_WAIT_S:
            if self._session_stopped(session):
                return False
            try:
                payload = bridge.patcher_status().get("response")
            except BridgeUnavailable:
                payload = None
            value = payload.get("value") if isinstance(payload, dict) else None
            if isinstance(value, dict) and not value.get("running"):
                log.info(f"[INJECT] The last LTK patcher stopped after {time.monotonic() - started:.1f}s")
                return True
            time.sleep(PATCHER_READY_POLL_S)
        log.warning(f"[INJECT] The last LTK patcher did not stop within {PATCHER_STOP_WAIT_S:.0f}s")
        return False

    def _stop_patcher(self, session: dict) -> None:
        try:
            session["ltf"].bridge.stop_patcher()
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.debug(f"[INJECT] Could not stop the LTK patcher: {e}")
        session["patcher_running"] = False

    # -- staging during the loadout countdown ---------------------------------
    def open_staging(self) -> None:
        """Let stage_mods prepare LTK Manager for this champ select.

        A stop Rose or the user asked for before it (the lobby's cleanup
        stops a session even when none runs) was the last session's, as
        mk_run_overlay clears it for the injection: left set, the staged
        patcher's game hold quit at once, and its restart for another pick
        gave up instead of waiting for the last build, so the client's game
        ran before the overlay was ready. A stop from here on counts."""
        if self.process_manager:
            self.process_manager.stopped_by_user = False
            self.process_manager.stopped_by_rose = False
        with self._early_session_lock:
            self._countdown_staging_open = True
            self._early_session_unwanted = False

    @contextmanager
    def _staging_closed(self) -> Iterator[None]:
        """Close the countdown's staging, and hold the library change lock once
        an in-flight staging has finished: its mods are likely the ones the
        injection wants."""
        self.close_staging()
        with self.host.library_change_lock:
            yield

    def close_staging(self) -> None:
        """No more staging: the injection (or a discard) owns the session now."""
        with self._early_session_lock:
            self._countdown_staging_open = False

    def _staging_session(self) -> Optional[dict]:
        """The early session, connected (or LTK Manager started) if it is not up."""
        with self.host.launcher_lock:
            with self._early_session_lock:
                session = self._early_session
            if session is not None and self._check_bridge(session):
                return session
            if session is not None:
                with self._early_session_lock:
                    if self._early_session is session:
                        self._early_session = None
                self._end_session(session)
            session = self._start_ltf_session(
                report=False, cancelled=lambda: self._early_session_unwanted or not self._countdown_staging_open
            )
            if session is None:
                return None
            with self._early_session_lock:
                keep = self._countdown_staging_open and not self._early_session_unwanted
                if keep:
                    self._early_session = session
            if not keep:
                self._end_session(session)
                return None
            return session

    def _may_start_staging(self, stopped: Callable[[], bool]) -> bool:
        """Whether a staging may start: nothing new starts once the injection
        closed staging. An install already running goes on while it is still
        wanted: the injection waits for the library change lock, and takes it
        over when it is its own skin."""
        return self._countdown_staging_open and not stopped() and self.game_dir is not None

    def stage_mods(self, folder_dir: Path, mod_names: List[str],
                   still_wanted: Callable[[], bool] = lambda: True,
                   archives: Optional[Dict[str, Path]] = None,
                   selected_at: Optional[float] = None) -> bool:
        """Install these mods and start LTK Manager's patcher during the countdown.

        The patcher only overlays a game the client creates after its scan
        started, and the client creates the game about a second after the
        injection begins: too soon to install the mods and start the patcher
        then. Staged here, the injection finds the same mods installed
        (mod_fingerprint) and leaves the library alone, so the scan keeps
        running. *archives* are the folders already packed (pack_mods);
        *selected_at* (time.monotonic()) is when the player picked them.
        Returns whether the mods are staged.
        """
        def stopped() -> bool:
            return not still_wanted()

        with self.host.library_change_lock:
            if not self._may_start_staging(stopped):
                return False
            session = self._staging_session()
            if session is None or stopped():
                return False
            if not self._install_mods(session, mod_names, folder_dir, report=False,
                                      stopped=lambda: session["ltf"].ended or stopped(), archives=archives):
                return False
            if session["ltf"].ended or stopped():
                return False
            self._disable_other_mods(session)
            restarted = not session["patcher_running"]
            if restarted and not self._start_patcher(session, report=False):
                return False
            if not restarted:
                log.info(f"[STAGE] {', '.join(mod_names)} already staged - the LTK patcher keeps its scan")
                return True
            after = ""
            if selected_at is not None:
                elapsed = time.monotonic() - selected_at
                session["staged_after_s"] = elapsed
                after = f" {elapsed:.1f}s after the pick"
            log.info(
                f"[STAGE] Staged {', '.join(mod_names)}{after} - LTK Manager builds the overlay, "
                "then scans for the game (it only overlays a game created after that)"
            )
            return True

    @staticmethod
    def _take_library_snapshot(session: dict) -> Optional[list]:
        """What _install_mods just read of the library, its imports added: it
        is still LTK Manager's library. Taken once."""
        library, session["library_snapshot"] = session.get("library_snapshot"), None
        return library

    def _disable_other_mods(self, session: dict) -> None:
        """Turn off the user's own enabled mods for this session.

        LTK Manager's patcher applies every enabled mod, and the overlay must
        hold Rose's alone (as mod-tools' did). Each one is recorded before it
        is turned off, so a crash still turns it back on next session. Rose's
        own (a kept copy, a saved mod not picked for this game) are turned
        off, and never turned back on as the user's.
        """
        ltf = session["ltf"]
        bridge = ltf.bridge
        library = self._take_library_snapshot(session)
        try:
            if library is None:
                library = bridge.library()
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.warning(f"[INJECT] Could not read LTK Manager's library - its other enabled mods may apply too: {e}")
            return
        rose_entries = set(self.host.journal.kept()) | ltf.saved_mod_ids
        for entry in library:
            mod_id = str(entry.get("id") or "")
            if not mod_id or mod_id in ltf.imports or mod_id in ltf.switched_on or not entry.get("enabled"):
                continue
            if mod_id in rose_entries:
                try:
                    bridge.toggle(mod_id, False)
                except (BridgeUnavailable, BridgeCommandError) as e:
                    log.warning(f"[INJECT] Could not turn off {entry_name(entry)} - it may apply too: {e}")
                continue
            self.host.track_disabled(ltf, mod_id)
            try:
                bridge.toggle(mod_id, False)
                log.info(f"[INJECT] Turned off {entry_name(entry)} in LTK Manager for this game")
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.warning(f"[INJECT] Could not turn off {entry_name(entry)} - it may apply too: {e}")
        self._disable_broken_entries(session, library)

    def _disable_broken_entries(self, session: dict, library: List[dict]) -> None:
        """Turn off the mods LTK Manager cannot read (#479).

        Its library leaves them out, so the loop above never sees them, but
        an enabled one fails every overlay build. They stay off after the
        game: LTK Manager cannot apply them anyway, and turning one back on
        would break the next build again.
        """
        ltf = session["ltf"]
        tail = ltf.start_log_tail
        if tail is not None:
            session["broken_entries"].update(BROKEN_ENTRY_LINE.findall(tail.read()))
        listed = {str(entry.get("id") or "") for entry in library}
        done = session["broken_off"]
        for mod_id in sorted(session["broken_entries"] - listed - set(ltf.imports) - done):
            done.add(mod_id)  # LTK Manager names it at every library read: once is enough
            try:
                ltf.bridge.toggle(mod_id, False)
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.warning(f"[INJECT] Could not turn off LTK Manager's unreadable mod {mod_id}: {e}")
                continue
            log.warning(
                f"[INJECT] Turned off LTK Manager's unreadable mod {mod_id} (its files are damaged): "
                "an enabled one fails every overlay build"
            )

    # -- injection ----------------------------------------------------------
    def mk_run_overlay(self, mod_names: List[str], timeout: int = 120, stop_callback: Optional[Callable] = None) -> int:
        """Install the mods and run LTK Manager's patcher until the game ends

        Args:
            mod_names: Mod folders (in mods_dir), and the LTK references of saved mods LTK Manager holds, to inject
            timeout: Unused (kept for backward compatibility) - the session runs until explicitly stopped
            stop_callback: Optional callback to check if game ended
        """
        if self.game_dir is None:
            log.error("[INJECTOR] Cannot create overlay - League game directory not found")
            log.error("[INJECTOR] Please ensure League Client is running or manually set the path in config.ini")
            return 127

        if self.process_manager:
            # A stop from the previous session must not count against this
            # one; a stop from now on does, even while LTK Manager starts
            self.process_manager.stopped_by_user = False
            self.process_manager.stopped_by_rose = False

        with self._staging_closed():
            session = self._acquire_session()
            if session is None:
                return 0 if self._stopped_by_rose() else 1
            if self._session_stopped(session):
                log.info("[INJECT] Injection stopped while LTK Manager was starting")
                self._end_session(session)
                return 0

            install_start = time.time()
            installed = self._install_mods(session, mod_names)
            self.last_injection_timing = {
                "import_duration": time.time() - install_start,
                "timestamp": time.time(),
            }
            if not installed:
                stopped = self._session_stopped(session)
                self._end_session(session)
                return 0 if stopped else 1

            # The extracted files were packed into LTK Manager's own archives
            self._wipe_mods_dir()
            if self._session_stopped(session):
                self._end_session(session)
                return 0
            self._disable_other_mods(session)

            if self.process_manager:
                # Rose's cleanup (user stop, lobby change, shutdown) ends the
                # session gracefully instead of killing the manager outright
                session["stopper"] = lambda: self._end_session(session)
                self.process_manager.set_session_stopper(session["stopper"])
            if session["patcher_running"]:
                self._read_ltk_log(session)
                log.info(f"[INJECT] The staged mods are the ones to inject - {self._patcher_progress(session)}")
            elif not self._start_patcher(session):
                self._end_session(session)
                return 1

        if not self._wait_for_patcher(session):
            failed = bool(session["error"]) and not self._stopped_by_rose()
            if failed:
                log.error(f"[INJECT] LTK patcher failed: {session['error']}")
                report_ltf_failure(session["error"])
            self._end_session(session)
            return 1 if failed else 0

        if session.get("restart_skipped"):
            # The Monitor Auto-Resume Timeout resumed the held game: the patcher still builds
            log_event(log, "Mods installed - the game resumed before the LTK patcher was ready", "")
        else:
            log_event(log, "Mods installed - the LTK patcher is ready", "")
        self._restart_early_game(session)
        return self._run_session(session, stop_callback)

    def _restart_early_game(self, session: dict) -> None:
        """A game the client created before the patcher's scan started cannot
        get the overlay: restart it now rather than let it load first."""
        self._read_ltk_log(session)
        scan = session.get("scan_started_at")
        game = self._running_game()
        if scan is None or game is None:
            return
        try:
            created = game.create_time()
        except (psutil.Error, OSError, AttributeError):
            return
        if created >= scan:
            return
        log.warning(
            f"[INJECT] The client created the game {scan - created:.1f}s before the LTK patcher was scanning"
        )
        self._restart_missed_game(session, game)

    def _restart_missed_game(self, session: dict, game) -> Optional[bool]:
        """Kill a game the patcher missed and reconnect to the match: the
        client launches it again while the patcher scans. None when not
        attempted (turned off, already done this session, no game), else
        whether the client reconnected (False also when the game was past the
        restart window: that was reported instead)."""
        if session.get("restart_skipped"):
            return False
        if not RESTART_MISSED_GAME or game is None or session.get("reconnects", 0) >= RECONNECT_MAX:
            return None
        if self._session_stopped(session):
            return None
        try:
            age = time.time() - float(game.create_time())
        except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
            age = None
        window = restart_window_s()
        if age is not None and age > window:
            # The player is in the match by now: leave the game alone
            session["restart_skipped"] = True
            session["late_join_reported"] = True  # this report replaces the late join's
            log.warning(
                f"[INJECT] Not restarting the game: the LTK patcher was ready after {age:.0f}s, "
                f"past the Monitor Auto-Resume Timeout ({window:.0f}s)"
            )
            report_issue(
                "AUTO_RESUME_TRIGGERED",
                "warning",
                f"{RESTART_SKIPPED_MESSAGE}: it was ready after {age:.0f}s, "
                f"past the Monitor Auto-Resume Timeout ({window:.0f}s).",
                details={"auto_resume_timeout_s": f"{window:.0f}", "elapsed_s": f"{age:.1f}"},
                hint="Settings → Monitor Auto-Resume Timeout → increase it, so Rose can still restart the game "
                     "once LTK Manager is ready.",
            )
            return False
        session["reconnects"] = session.get("reconnects", 0) + 1
        log.warning("[INJECT] Restarting the game for the LTK patcher: closing it, then reconnecting to the match")
        if not kill_game(game):
            return None
        session["restarted_at"] = time.time()
        if not reconnect_to_game(stopped=lambda: self._session_stopped(session)):
            log.error("[INJECT] The game was closed, but the client did not reconnect - use Reconnect in the client")
            if not self._stopped_by_rose():
                report_ltf_failure(
                    "Rose restarted the game so the LTK patcher could apply the overlay, but the client did not "
                    "reconnect to the match (use Reconnect in the client)"
                )
            return False
        # The relaunched game reports to the patcher anew
        session["ltk_attached"] = False
        session["attach_logged"] = False
        session["ltk_late"] = False
        session["late_join_reported"] = False
        log.info("[INJECT] Reconnected: the game starts again while the LTK patcher scans")
        return True

    def _wait_for_patcher(self, session: dict) -> bool:
        """Wait until the patcher has built the overlay and is scanning.

        A game the client creates meanwhile cannot get the overlay. It is held
        (suspended: no window yet, and the client stays in the match instead
        of showing its reconnect screen) while the patcher builds. Once the
        patcher scans, it is closed and the client reconnects at once, so the
        player only sees the reconnect screen for a moment (the patcher cannot
        hook a game that was frozen, hence the restart). The Monitor
        Auto-Resume Timeout caps the hold: past it the game is resumed without
        the overlay.

        False when it failed (session["error"]) or the session was stopped.
        A patcher still building at the timeout keeps the session. A held game
        is never left frozen.
        """
        start = time.monotonic()
        deadline = start + PATCHER_READY_TIMEOUT_S
        try:
            while True:
                now = time.monotonic()
                held_at = session.get("held_at")
                if held_at is None and now >= deadline:
                    break
                if held_at is not None and now - held_at >= restart_window_s():
                    self._resume_held_game(session, waited=now - held_at)
                    return True
                if self._session_stopped(session):
                    return False
                value = self._read_patcher_status(session)
                if session["error"]:
                    return False
                if value is not None:
                    phase = str(value.get("phase") or "").lower()
                    session["state"] = phase or ("running" if value.get("running") else "idle")
                    if phase in ("failed", "error"):
                        session["error"] = self._with_ltk_error(session, f"the LTK patcher is {phase}")
                        return False
                    if value.get("running") and phase not in ("building", "idle"):
                        log.info(
                            f"[INJECT] LTK patcher ready (phase={phase or 'running'}) "
                            f"after {time.monotonic() - start:.1f}s"
                        )
                        session["hold_done"] = True
                        held = session.get("held_game")
                        if held is not None:
                            if self._created_under_scan(session, held):
                                self._resume_held_game(session)  # held a moment only
                            else:
                                held_at = session.get("held_at") or time.monotonic()
                                self._restart_held_game(session, waited=time.monotonic() - held_at)
                        return True
                    if (not value.get("running") and phase in ("", "idle")
                            and time.monotonic() - start >= PATCHER_IDLE_GRACE_S):
                        session["error"] = self._with_ltk_error(session, "the LTK patcher stopped before it was ready")
                        return False
                self._hold_early_game(session)
                time.sleep(PATCHER_READY_POLL_S)
        finally:
            # Failed, stopped, or an exception: the game plays on (without the overlay)
            session["hold_done"] = True
            self._resume_held_game(session)
        log.warning(
            f"[INJECT] The LTK patcher is not ready after {PATCHER_READY_TIMEOUT_S:.0f}s "
            f"(phase={session['state'] or 'unknown'}) - resuming the game anyway"
        )
        return True

    @staticmethod
    def _game_alive(game) -> bool:
        try:
            return bool(game.is_running())
        except (psutil.Error, OSError, AttributeError):
            return False

    def _start_hold_watch(self, session: dict) -> None:
        """Watch for the game while the patcher builds (one thread a session)."""
        if not HOLD_WATCH or not RESTART_MISSED_GAME:
            return
        thread = session.get("hold_thread")
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(target=self._hold_watch, args=(session,), daemon=True, name="GameHold")
        session["hold_thread"] = thread
        thread.start()

    def _hold_watch(self, session: dict) -> None:
        """Suspend the game the moment the client creates it, until the
        patcher is ready (the wait restarts it then) or the Monitor
        Auto-Resume Timeout (resumed without the overlay)."""
        try:
            while not session["ltf"].ended and not session.get("hold_done") and not self._session_stopped(session):
                self._hold_early_game(session)
                held_at = session.get("held_at")
                if held_at is not None:
                    waited = time.monotonic() - held_at
                    if waited >= restart_window_s():
                        self._resume_held_game(session, waited=waited)
                        return
                    time.sleep(HOLD_WATCH_HELD_POLL_S)
                elif session.get("hold_failed"):
                    return
                else:
                    time.sleep(HOLD_WATCH_POLL_S)
        except Exception as e:  # never leave the game frozen over a bug
            log.warning(f"[INJECT] The game hold stopped: {e}")
            self._resume_held_game(session)
            return
        if not session.get("hold_done"):
            self._resume_held_game(session)  # stopped: the wait no longer owns it

    @staticmethod
    def _game_alive(game) -> bool:
        try:
            return bool(game.is_running())
        except (psutil.Error, OSError, AttributeError):
            return False

    def _created_under_scan(self, session: dict, game) -> bool:
        """Whether the game was created after the patcher's scan started."""
        self._read_ltk_log(session)
        scan = session.get("scan_started_at")
        if scan is None:
            return False
        try:
            return float(game.create_time()) >= scan
        except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
            return False

    def _hold_early_game(self, session: dict) -> None:
        """Suspend a game the client created while the patcher still builds
        the overlay (it would be missed), until the patcher scans. A held game
        that died (the client relaunched the match) is replaced by the new one."""
        if not RESTART_MISSED_GAME or session.get("hold_failed") or session.get("hold_done"):
            return
        if self._session_stopped(session):
            return
        lock = session.setdefault("hold_lock", threading.Lock())
        with lock:
            if session.get("hold_done"):
                return
            held = session.get("held_game")
            if held is not None and self._game_alive(held):
                return
            if held is None and session.get("reconnects", 0) >= RECONNECT_MAX:
                return
            game = self._running_game()
            if game is None:
                return
            try:
                game.suspend()
            except (psutil.Error, OSError) as e:
                session["hold_failed"] = True
                log.warning(
                    f"[INJECT] Could not hold the game while the LTK patcher builds the overlay "
                    f"({type(e).__name__}: {e})"
                )
                return
            if held is None:
                session["held_at"] = time.monotonic()
            session["held_game"] = game
        if held is None:
            log.warning(
                "[INJECT] The client created the game while the LTK patcher was still building the overlay - "
                "holding it until the patcher scans, then restarting it"
            )
        else:
            log.warning("[INJECT] The client relaunched the game while the LTK patcher was still building - holding it")

    def _take_held_game(self, session: dict):
        lock = session.setdefault("hold_lock", threading.Lock())
        with lock:
            game = session.get("held_game")
            session["held_game"] = None
            session["held_at"] = None
        return game

    def _resume_held_game(self, session: dict, waited: Optional[float] = None) -> None:
        """Let a held game play on without the overlay: the Monitor
        Auto-Resume Timeout ran out (waited), or the session failed or stopped."""
        game = self._take_held_game(session)
        if game is None:
            return
        if waited is not None:
            window = restart_window_s()
            session["hold_done"] = True
            # Nothing to restart once the patcher is ready: the player is in the match
            session["restart_skipped"] = True
            session["late_join_reported"] = True  # this report replaces the late join's
            log.warning(
                f"[INJECT] The LTK patcher is still building after {waited:.0f}s, past the Monitor Auto-Resume "
                f"Timeout ({window:.0f}s) - resuming the game without the overlay"
            )
            report_issue(
                "AUTO_RESUME_TRIGGERED",
                "warning",
                f"{RESTART_SKIPPED_MESSAGE}: it was still building the overlay after {waited:.0f}s, past the "
                f"Monitor Auto-Resume Timeout ({window:.0f}s), so Rose resumed the game without it.",
                details={"auto_resume_timeout_s": f"{window:.0f}", "elapsed_s": f"{waited:.1f}"},
                hint="Settings → Monitor Auto-Resume Timeout → increase it, so Rose can hold the game until "
                     "LTK Manager is ready.",
            )
        try:
            game.resume()
            log.info("[INJECT] Resumed the held game")
        except (psutil.Error, OSError) as e:
            log.debug(f"[INJECT] Could not resume the held game: {e}")

    def _restart_held_game(self, session: dict, waited: float) -> bool:
        """The patcher scans: close the held game and reconnect to the match,
        so the client launches it again under the scan."""
        game = self._take_held_game(session)
        if game is None:
            return False
        session["reconnects"] = session.get("reconnects", 0) + 1
        log.info(
            f"[INJECT] The LTK patcher scans after holding the game {waited:.1f}s - "
            "closing it, then reconnecting to the match"
        )
        if not kill_game(game):
            try:
                game.resume()
            except (psutil.Error, OSError, AttributeError):
                pass
            return False
        session["restarted_at"] = time.time()
        if not reconnect_to_game(stopped=lambda: self._session_stopped(session)):
            log.error("[INJECT] The game was closed, but the client did not reconnect - use Reconnect in the client")
            if not self._stopped_by_rose():
                report_ltf_failure(
                    "Rose restarted the game so the LTK patcher could apply the overlay, but the client did not "
                    "reconnect to the match (use Reconnect in the client)"
                )
            return False
        # The relaunched game reports to the patcher anew
        session["ltk_attached"] = False
        session["attach_logged"] = False
        session["ltk_late"] = False
        session["late_join_reported"] = False
        log.info("[INJECT] Reconnected: the game starts again while the LTK patcher scans")
        return True

    def _run_session(self, session: dict, stop_callback: Optional[Callable] = None) -> int:
        """Serve the overlay until the game exits."""
        try:
            ticks = 0
            while True:
                if session["ltf"].ended:
                    break
                if stop_callback and stop_callback():
                    game = self._running_game()
                    if game is not None:
                        log.info("[INJECT] The game is still running - keeping the LTK patcher until it exits")
                        self._wait_for_game_exit(game, session)
                        if session["ltf"].ended or session["error"]:
                            break  # the session itself stopped: handled below
                        if not stop_callback():
                            continue  # the game came back (reconnect)
                    log.info("[INJECT] Game ended, stopping LTK patcher")
                    self._check_patcher_verdict(session)  # LTK Manager's verdict on the game
                    break
                if session["ltf"].ended:
                    continue  # Rose stopped the session while the callback ran
                if not self._check_bridge(session):
                    session["error"] = "the LTF bridge went away during the game"
                    log.error("[INJECT] The LTF bridge went away - LTK Manager closed")
                    break
                ticks += 1
                if ticks % PATCHER_STATUS_POLL_TICKS == 0:
                    self._poll_patcher_status(session)
                    if session["error"] or session["done"]:
                        break
                time.sleep(PROCESS_MONITOR_SLEEP_S)

            if session["error"] and not self._stopped_by_rose():
                log.error(f"[INJECT] LTK patcher failed: {session['error']}")
        except Exception as e:
            log.error(f"[INJECT] LTF session error: {e}")
            if not session["error"]:
                session["error"] = str(e)
        finally:
            stopped = self._stopped_by_rose()
            self._end_session(session)

        if stopped:
            log.info("[INJECT] LTK patcher stopped by Rose")
            return 0
        if session["error"]:
            report_ltf_failure(session["error"])
            return 1
        log.debug("[INJECT] LTF session completed successfully")
        return 0

    def _read_patcher_status(self, session: dict) -> Optional[dict]:
        """The patcher status value ({running, phase, session, ...}), or None.

        The status answers {ok, response: {ok, value}}. A missing answer (CDP
        busy with another command, a slow eval) is retried on the next poll;
        only STATUS_FAILURE_LIMIT of them in a row fail the session.
        """
        bridge = session["ltf"].bridge
        try:
            response = bridge.patcher_status()
        except BridgeUnavailable as e:
            if not bridge.alive():
                session["error"] = "the LTF bridge went away during the game"
                return None
            failure = str(e)
        else:
            payload = response.get("response")
            if response.get("ok") is False or not isinstance(payload, dict) or payload.get("ok") is False:
                source = payload if isinstance(payload, dict) and payload.get("ok") is False else response
                failure = str(source.get("error") or source.get("message") or "no answer")
            elif isinstance(payload.get("value"), dict):
                session["status_failures"] = 0
                return payload["value"]
            else:
                failure = "the status had no value"
        session["status_failures"] += 1
        log.debug(f"[INJECT] LTK patcher status unavailable ({failure})")
        if session["status_failures"] >= STATUS_FAILURE_LIMIT:
            session["error"] = f"the LTK patcher stopped answering ({failure})"
        return None

    @staticmethod
    def _note_ltk_text(session: dict, text: str) -> None:
        """Record what LTK Manager's log (or its patcher status) says: the
        overlay's build time, the scan's start, the DLL's verdict, and why
        the patcher gave up."""
        if not text:
            return
        if session.get("ltk_error") is None:
            failed = LTK_PATCHER_ERROR_LINE.search(text)
            if failed:
                message = failed.group(2).strip()
                if len(message) > LTK_ERROR_MAX_CHARS:
                    message = message[:LTK_ERROR_MAX_CHARS - 3].rstrip() + "..."
                session["ltk_error"] = message
        lowered = text.lower()
        if "dll attached" in lowered:
            session["ltk_attached"] = True
        if LATE_JOIN_MESSAGE in lowered:
            session["ltk_late"] = True
        refused = OVERLAY_REFUSED_CODE.search(text)
        if refused and session.get("ltk_refused") is None:
            session["ltk_refused"] = (refused.group(1).upper(), (refused.group(2) or "").strip())
        signature = OVERLAY_SIGNATURE_CODE.search(text)
        if signature and session.get("ltk_signature") is None:
            session["ltk_signature"] = "0x" + signature.group(1).upper()
        disabled = OVERLAY_DISABLED_LINE.search(text)
        if disabled and session.get("ltk_disabled") is None:
            session["ltk_disabled"] = disabled.group(1).strip()[:LTK_ERROR_MAX_CHARS]
        not_attached = DLL_NOT_ATTACHED_LINE.search(text)
        if not_attached and session.get("ltk_not_attached") is None:
            session["ltk_not_attached"] = not_attached.group(0)
        for sweep in SLOW_MOD_CHECK_LINE.finditer(text):
            seconds = float(sweep.group(1)) * DURATION_UNITS_S[sweep.group(2)]
            if seconds >= SLOW_MOD_CHECK_S and seconds > (session.get("ltk_slow_mod_check_s") or 0.0):
                session["ltk_slow_mod_check_s"] = seconds
        incident = INCIDENT_LINE.search(text)
        if incident and session.get("ltk_incident") is None:
            session["ltk_incident"] = (incident.group(1).strip(), incident.group(2), incident.group(3))
        if session.get("overlay_build_s") is None:
            built = OVERLAY_BUILT_LINE.search(text)
            if built:
                amount = float(built.group(1))
                session["overlay_build_s"] = amount / 1000.0 if built.group(2) == "ms" else amount
        if session.get("scan_started_at") is None:
            scanning = SCAN_STARTED_LINE.search(text)
            if scanning:
                session["scan_started_at"] = _ltk_log_time(scanning.group(1))

    def _read_ltk_log(self, session: dict) -> None:
        """Read what LTK Manager logged since the last read (see _note_ltk_text)."""
        tail = session.get("ltk_log")
        if tail is not None:
            self._note_ltk_text(session, tail.read())

    def _with_ltk_error(self, session: dict, reason: str) -> str:
        """*reason* with LTK Manager's own error, when its log has one."""
        self._read_ltk_log(session)
        if session.get("ltk_error"):
            return f"{reason} (LTK Manager: {session['ltk_error']})"
        return reason

    @staticmethod
    def _patcher_progress(session: dict) -> str:
        """Where the started patcher is, from LTK Manager's log: still building
        the overlay, or scanning (since when)."""
        started = time.monotonic() - session.get("patcher_started_at", time.monotonic())
        if session.get("ltk_error"):
            return f"the LTK patcher was started {started:.1f}s ago and failed (LTK Manager: {session['ltk_error']})"
        tail = session.get("ltk_log")
        if tail is None or tail.directory is None:
            return f"the LTK patcher was started {started:.1f}s ago"
        build = session.get("overlay_build_s")
        built = f" (overlay built in {build:.1f}s)" if build is not None else ""
        scan = session.get("scan_started_at")
        if scan is not None:
            return f"the LTK patcher has been scanning for {max(0.0, time.time() - scan):.1f}s{built}"
        if build is not None:
            return f"the LTK patcher was started {started:.1f}s ago and is not scanning yet{built}"
        return f"the LTK patcher was started {started:.1f}s ago and is still building the overlay"

    def _late_join_detail(self, session: dict) -> str:
        """Why the patcher came too late, from what Rose saw: when its scan
        started against when the client created the game, and what took the
        time before it ("" when nothing is known)."""
        parts = []
        scan = session.get("scan_started_at")
        game = self._running_game() if scan is not None else None
        created = None
        if game is not None:
            try:
                created = game.create_time()
            except (psutil.Error, OSError, AttributeError):
                created = None
        if scan is not None and created is not None:
            gap = scan - created
            if gap >= 0:
                parts.append(f"its scan started {gap:.1f}s after the client created the game")
            else:
                parts.append(f"its scan started {-gap:.1f}s before the client created the game")
        build = session.get("overlay_build_s")
        if build is not None:
            parts.append(f"LTK Manager took {build:.1f}s to build the overlay")
        staged = session.get("staged_after_s")
        if staged is not None:
            parts.append(f"Rose started it {staged:.1f}s after the skin was picked")
        return "; ".join(parts)

    @staticmethod
    def _status_may_be_killed_games(session: dict) -> bool:
        """Whether the patcher's status may still carry the verdict of a game
        killed for a restart: only LTK Manager's log (new lines) speaks for
        the new game then."""
        return session.get("restarted_at") is not None

    def _check_patcher_verdict(self, session: dict, value: Optional[dict] = None) -> None:
        """Log the patcher reaching the game, and report it joining too late
        (the DLL then stays inert: the game runs without the overlay)."""
        if value is not None and not self._status_may_be_killed_games(session):
            try:
                self._note_ltk_text(session, json.dumps(value))
            except (TypeError, ValueError):
                pass
        self._read_ltk_log(session)
        if session["ltk_attached"] and not session["attach_logged"]:
            session["attach_logged"] = True
            log.info("[INJECT] The LTK patcher attached to the game")
        if session["ltk_late"] and not session["late_join_reported"]:
            log.warning("[INJECT] The LTK patcher joined the game too late")
            restarted = self._restart_missed_game(session, self._running_game())
        else:
            restarted = True  # nothing to report
        if restarted is False:
            session["late_join_reported"] = True  # the failed reconnect was reported
        elif restarted is None and session["ltk_late"] and not session["late_join_reported"]:
            session["late_join_reported"] = True
            detail = self._late_join_detail(session)
            log.error(
                "[INJECT] The LTK patcher joined the game too late - the overlay is not applied this game"
                + (f" ({detail})" if detail else "")
            )
            if not self._stopped_by_rose():
                report_ltf_failure(
                    "the game started before the LTK patcher was scanning (joined too late"
                    + (f": {detail})" if detail else ")")
                )
        refused = session["ltk_refused"]
        if refused and not session["refused_reported"]:
            session["refused_reported"] = True
            check, seen = refused
            described = f"{check} ({seen})" if seen else check
            log.error(f"[INJECT] The LTK patcher refused the overlay: host verification failed {described}")
            signature = session.get("ltk_signature")
            if signature:
                log.error(f"[INJECT] {SIGNATURE_FAILURE_MESSAGE} ({signature}): reinstall LTK Manager")
            # The check wants LTK Manager started under explorer.exe: when the
            # launcher could not do that, its lines in this log say why (#478)
            parent = self.host.logged_manager_parent
            unparented = parent is not None and parent != LAUNCHER_SHELL_PARENT
            if unparented:
                log.error(
                    f"[INJECT] LTK Manager was not started under explorer.exe ({parent}), which the patcher's "
                    "check refuses - the ltk_launcher lines above say why"
                )
            if not self._stopped_by_rose():
                details = [f"host verification failed: {described}"]
                if signature:
                    details.append(f"{SIGNATURE_FAILURE_MESSAGE}, {signature}")
                if unparented:
                    details.append(f"LTK Manager's parent was not explorer.exe ({parent})")
                report_ltf_failure(f"LTK Manager's patcher refused the overlay ({'; '.join(details)})")
        not_attached = session.get("ltk_not_attached")
        if not_attached and not session.get("ltk_attached") and not session.get("not_attached_reported"):
            session["not_attached_reported"] = True
            log.error(f"[INJECT] {NOT_ATTACHED_MESSAGE} ({not_attached}) - it runs without the overlay")
            if not self._stopped_by_rose():
                report_ltf_failure(f"{NOT_ATTACHED_MESSAGE} ({not_attached})")
        disabled = session.get("ltk_disabled")
        if disabled and not session.get("disabled_reported"):
            session["disabled_reported"] = True
            log.error(f"[INJECT] LTK Manager's integrity check disabled the overlay this game: {disabled}")
            report_ltf_failure(f"LTK Manager {OVERLAY_DISABLED_MESSAGE} ({disabled})")
        incident = session.get("ltk_incident")
        if incident and not session.get("incident_reported"):
            session["incident_reported"] = True
            title, incident_id, verdict = incident
            where = f"{LTK_INCIDENTS_DIR}\\{incident_id}.json"
            log.error(f"[INJECT] LTK Manager recorded an incident: {title} ({verdict}), see {where}")
            incident_repeats_a_report = disabled or session.get("not_attached_reported")
            if not incident_repeats_a_report:
                report_ltf_failure(f"LTK Manager recorded an incident after the game: {title} ({verdict}; {where})")
        slow = session.get("ltk_slow_mod_check_s")
        if slow is not None and not session.get("slow_mod_check_reported"):
            session["slow_mod_check_reported"] = True
            message = f"{SLOW_MOD_CHECK_MESSAGE} {slow:.0f}s on this PC, slowing down the game's loading"
            log.warning(f"[INJECT] {message}")
            report_issue(
                "LTK_SLOW_MOD_CHECK",
                "warning",
                f"{message}.",
                details={"seconds": f"{slow:.0f}"},
                hint=SLOW_MOD_CHECK_HINT,
                dedupe_window_s=600.0,
            )

    def _poll_patcher_status(self, session: dict) -> None:
        """Record what the LTK patcher reports while the game runs.

        A patcher that only stops early is logged, not failed: whether it
        completed cannot be told apart from it giving up, and the bridge
        aliveness already catches the crash case. A stopped patcher ends the
        session only once the game it served has exited: before the game
        appears, the session waits for it (or for Rose to end it).
        """
        value = self._read_patcher_status(session)
        if value is None:
            return
        phase = str(value.get("phase") or "").lower()
        session["state"] = phase or ("running" if value.get("running") else "idle")
        self._check_patcher_verdict(session, value)
        if phase in ("failed", "error"):
            session["error"] = f"the LTK patcher is {phase}"
            return
        game = self._running_game()
        if game is not None:
            session["game_seen"] = True
        if value.get("running"):
            return
        if game is None:
            if session["game_seen"]:
                session["done"] = True  # the game is over; the loop ends on it
        elif not session["early_stop_logged"]:
            session["early_stop_logged"] = True
            log.warning(
                f"[INJECT] The LTK patcher stopped on its own (phase={phase or 'unknown'}) "
                "while the game was running"
            )

    @staticmethod
    def _running_game():
        """The game's process, if a game is running (either executable name)."""
        if not PSUTIL_AVAILABLE:
            return None
        names = {name.lower() for name in GAME_EXECUTABLE_NAMES}
        try:
            # Called every 50 ms while the game is held, and during the game
            for pid, name in running_processes():
                if name.lower() in names:
                    try:
                        return psutil.Process(pid)
                    except psutil.NoSuchProcess:
                        continue  # exited since the snapshot
        except (psutil.Error, OSError) as e:
            log.debug(f"[INJECT] Could not look for the game process: {e}")
        return None

    def _wait_for_game_exit(self, game, session: dict) -> None:
        """Wait on the game process itself; stop early if the bridge dies."""
        while not session["ltf"].ended and not session["error"]:
            try:
                game.wait(timeout=1.0)
                return
            except psutil.TimeoutExpired:
                self._check_patcher_verdict(session)
                if not self._check_bridge(session):
                    session["error"] = "the LTF bridge went away during the game"
                    return
            except psutil.Error:
                return

    def mk_overlay_only(self, mod_names: List[str], timeout: int = 60) -> int:
        """Install the mods into LTK Manager without starting its patcher - for testing"""
        if self.game_dir is None:
            log.error("[INJECTOR] Cannot create overlay - League game directory not found")
            log.error("[INJECTOR] Please ensure League Client is running or manually set the path in config.ini")
            return 127

        if self.process_manager:
            self.process_manager.stopped_by_user = False
            self.process_manager.stopped_by_rose = False

        session = self._acquire_session()
        if session is None:
            return 1

        install_start = time.time()
        installed = self._install_mods(session, mod_names)
        self.last_injection_timing = {
            "import_duration": time.time() - install_start,
            "timestamp": time.time(),
        }
        if not installed:
            self._end_session(session)
            return 1

        # Leave the mods installed without starting the patcher; the next
        # session removes them through the state file
        if self.process_manager:
            session["stopper"] = lambda: self._end_session(session)
            self.process_manager.set_session_stopper(session["stopper"])
        log.info("[INJECT] Mods installed in LTK Manager (patcher not started)")
        return 0

    # -- reporting ----------------------------------------------------------
    @staticmethod
    def _directory_size(directory: Path) -> int:
        '''Return the best-effort size of files below *directory*.'''
        total = 0
        try:
            for path in directory.rglob('*'):
                try:
                    if path.is_file():
                        total += path.stat().st_size
                except OSError:
                    continue
        except OSError:
            return 0
        return total

    @staticmethod
    def _format_bytes(size: int) -> str:
        '''Format a byte count for log and diagnostics messages.'''
        value = float(max(0, size))
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if value < 1024 or unit == 'TB':
                return f'{value:.1f} {unit}'
            value /= 1024
        return f'{value:.1f} TB'

    def _report_low_disk_space_failure(self, mod_names: Optional[List[str]] = None) -> bool:
        '''Report a failed import when its output drive is out of space.'''
        free_bytes = None
        required_bytes = max(MIN_LIBRARY_FREE_BYTES, LIBRARY_IMPORT_HEADROOM_BYTES)
        try:
            usage = shutil.disk_usage(self.mods_dir.parent)
            free_bytes = usage.free
            extracted_bytes = self._directory_size(self.mods_dir)
            required_bytes = max(
                MIN_LIBRARY_FREE_BYTES,
                extracted_bytes + LIBRARY_IMPORT_HEADROOM_BYTES,
            )
        except (OSError, ValueError) as exc:
            log.debug(f'[INJECT] Could not inspect free disk space after injection failure: {exc}')

        if free_bytes is None or free_bytes >= required_bytes:
            return False

        free_text = self._format_bytes(free_bytes)
        required_text = self._format_bytes(required_bytes)
        log.error(
            '[INJECT] Injection failed because disk space is too low '
            f'({free_text} free; approximately {required_text} recommended on {self.mods_dir.parent})'
        )
        report_issue(
            'LOW_DISK_SPACE',
            'error',
            f'Injection failed: not enough disk space to install the mod ({free_text} free).',
            details={
                'free_bytes': free_bytes,
                'required_bytes': required_bytes,
                'overlay_path': str(self.mods_dir.parent),
                'mods': '/'.join(mod_names or ()),
            },
            hint='Free up disk space on the drive containing Rose injection files, then retry the skin.',
        )
        return True

    def _wipe_mods_dir(self):
        """Delete extracted mod files once they are in LTK Manager's library"""
        try:
            for p in self.mods_dir.iterdir():
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
            log.debug("[INJECT] Wiped mods directory after the import")
        except Exception as e:
            log.debug(f"[INJECT] Could not wipe mods directory: {e}")
