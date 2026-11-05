#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Overlay Manager
Drives LTK Manager through the LeagueToolFlop (LTF) bridge.

Rose builds the LTF bridge from native/ltf/ (ltk_launcher.exe +
LeagueToolFlop.dll). The launcher starts LTK Manager hidden with the DLL
injected, and the DLL serves a TCP API (injection/tools/bridge.py) that
imports Rose's mod folders into LTK Manager's library and starts LTK
Manager's own patcher. The patcher builds the overlay and starts scanning;
Rose then resumes the game, watches for the end of it, stops the patcher,
removes the mods it installed and turns the user's own mods back on.

The patcher only overlays a game the client creates after its scan started,
and any library change restarts the scan. The client creates the game about a
second after the injection begins, so the selected skin is staged during the
countdown (stage_mods): the injection then finds the same mods installed and
the scan already running.

Security Notes:
    - subprocess calls use only internal paths (tools_dir, mods_dir) and the
      LTK Manager path from config/known install locations
    - Commands only execute ltk_launcher.exe from the verified tools directory
    - Mod names are folder names Rose itself extracted into mods_dir
"""

import json
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

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
from ..tools.bridge import (
    BridgeCommandError,
    BridgeUnavailable,
    LtkBridge,
    find_bridge,
)
from ..tools.tools_manager import LTF_BRIDGE_DLL, LTF_LAUNCHER, ToolsManager
from ..mods.fantome import fantome_display_name, write_fantome_zip
from ..mods.fingerprint import mod_fingerprint
from .process_manager import LTK_MANAGER_PROCESSES
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

# The DLL caps a request line at 64 MB and base64 adds a third, so only an
# archive up to this size can be sent inline when LTK Manager cannot read it
BYTES_IMPORT_LIMIT = 40 * 1024 * 1024

LAUNCHER_TIMEOUT_S = 60
BRIDGE_START_TIMEOUT_S = 30
# LTK Manager's built-in browser (CDP) answers seconds after its bridge does:
# a command sent in between fails with "CDP unavailable", and the countdown's
# staging gave up on its first try (#431). How long to wait for it, and how
# often to ask
CDP_READY_TIMEOUT_S = 20.0
# LTK Manager stops its patcher only once the overlay build in progress is done
# (62s with map mods in #437): a start in between is refused as ALREADY_RUNNING.
# How long to wait for the stopping patcher before giving up
PATCHER_ALREADY_RUNNING = "ALREADY_RUNNING"
PATCHER_STOP_WAIT_S = 120.0
CDP_READY_POLL_S = 0.5
# ltk_launcher.exe exit codes (native/ltf/LeagueToolFlop-inj.cpp)
LAUNCHER_EXIT_ALREADY_RUNNING = 5
LAUNCHER_EXIT_NO_LIVE_INSTANCE = 6

# LTK Manager needs free space in its own library for the imported mods: a
# gigabyte is a conservative lower bound for a normal skin, while the extracted
# mod size catches larger map/voiceover mods.
MIN_FREE_SPACE_BYTES = 1 * 1024 * 1024 * 1024
DISK_SPACE_HEADROOM_BYTES = 512 * 1024 * 1024

# Exit code of a process another program terminated (DBG_TERMINATE_PROCESS),
# most often an antivirus
KILLED_EXIT_CODE = 0x40010004

# The patcher's verdict when the game loaded its files before the DLL hooked it
LATE_JOIN_MESSAGE = "joined too late"
# The DLL's host verification refusing the overlay (docs/ltf-vrf-host-verification.md):
# the code names the check that failed, the bracket after it what it saw
OVERLAY_REFUSED_MESSAGE = "host verification failed"
OVERLAY_REFUSED_CODE = re.compile(r"\[(vrf\d{8})\]\s*\(([^)]*)\)?", re.IGNORECASE)
# A check in that chain naming a WinVerifyTrust result: Windows could not verify
# the Authenticode signature of LTK Manager's own files (0x80096010
# TRUST_E_BAD_DIGEST: a file modified or damaged after signing; 0x800B01xx: a
# certificate Windows does not trust). Reinstalling LTK Manager fixes it (#442)
OVERLAY_SIGNATURE_CODE = re.compile(r"\[vrf\d{8}\]\s*\((800960[0-9a-f]{2}|800b0[0-9a-f]{3})\)", re.IGNORECASE)
SIGNATURE_FAILURE_MESSAGE = "Windows could not verify the signature of LTK Manager's files"
# The DLL's integrity scan turning the overlay off in the game: a mod's WAD
# failed a check, which the rest of the line names (a custom skin made of
# another skin's files: "base-skin check: skin0 is another skin: ...")
OVERLAY_DISABLED_LINE = re.compile(r"overlay verification failed, disabling overlay:\s*([^\r\n\"]+)", re.IGNORECASE)
OVERLAY_DISABLED_MESSAGE = "disabled the overlay"
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
# The longest LTK Manager error kept for a report
LTK_ERROR_MAX_CHARS = 300
ALREADY_OPEN_REASON = "LTK Manager is already open without Rose's bridge"
# The bridge drives LTK Manager through the remote debugging port (CDP) of its
# WebView2 window; when that port never answers, every command fails with this
CDP_FAILURE_MARKER = "cdp unavailable"
# LTK Manager's page loaded, its Tauri IPC not yet: the browser answers but
# window.__TAURI_INTERNALS__ is still undefined (#441)
TAURI_NOT_READY_MARKER = "reading 'invoke'"
CDP_UNREACHABLE_REASON = "Rose's bridge could not reach LTK Manager's built-in browser (CDP unavailable or timed out)"
# Every LTF report's hint ends with it (Troubleshooting recognizes the reports by it)
LTF_LOGS_HINT = "Details are in C:\\Users\\Public\\ltk_bridge.log, ltk_api.log and ltk_launcher.log."


def ltk_failure_cause(reason: str) -> str:
    """Why the LTF session failed, from the reason Rose reported: what to do
    about it depends on it (Troubleshooting shows a hint for each)"""
    lowered = reason.lower()
    # Before "import" and "bridge": a failed install or command names them too
    if CDP_FAILURE_MARKER in lowered or "built-in browser" in lowered:
        return "cdp"
    # LTK Manager refuses to patch across an elevation boundary (ADR-0074):
    # League set to run as administrator, or LTK Manager itself elevated
    if "league_elevated" in lowered or "league is set to run as administrator" in lowered:
        return "league_admin"
    if "manager_elevated" in lowered or "ltk manager is running as administrator" in lowered:
        return "manager_admin"
    # LTK Manager's own patcher missing from its folder (an antivirus took
    # it): reinstalling LTK Manager is the fix, not Rose's files
    if "ltk_patcher_host.exe not found" in lowered:
        return "host_missing"
    if OVERLAY_DISABLED_MESSAGE in lowered:
        return "disabled"
    if "corruptarchive" in lowered:
        return "corrupt"
    if "recorded an incident" in lowered:
        return "incident"
    if "import" in lowered:
        return "import"
    if "already open" in lowered:
        return "running"
    if LATE_JOIN_MESSAGE in lowered:
        return "late"
    if SIGNATURE_FAILURE_MESSAGE.lower() in lowered:
        return "signature"
    if OVERLAY_REFUSED_MESSAGE in lowered or "refused the overlay" in lowered:
        return "refused"
    if lowered.startswith("could not start"):
        return "start"
    if "bridge" in lowered:
        return "bridge"
    exit_code = re.search(r"exited with code (-?\d+)", reason)
    if exit_code:
        code = int(exit_code.group(1)) & 0xFFFFFFFF
        if code == KILLED_EXIT_CODE:
            return "killed"
        # NTSTATUS errors (access violation...): LTK Manager itself crashed
        if code >= 0xC0000000:
            return "crashed"
    return "unknown"


def _cdp_unreachable(error: BaseException) -> bool:
    """Whether a bridge command failed because LTK Manager's browser did not answer."""
    return CDP_FAILURE_MARKER in str(error).lower()


def _cdp_unreachable_reason() -> str:
    """CDP_UNREACHABLE_REASON, with its usual cause when this account has it:
    both PCs where the browser never answered ran every program as
    administrator (#425 built-in Administrator, #426 UAC turned off)."""
    try:
        from utils.system.windows_account import shell_account
        account = shell_account()
    except Exception:  # a diagnostic must never fail the report
        account = None
    if account is not None and account.elevated:
        return f"{CDP_UNREACHABLE_REASON}; Windows runs every program as administrator on this account"
    return CDP_UNREACHABLE_REASON


# LTK Manager's built-in mods that put every champion's archive (~16 GB) into
# its overlay (settings.json "builtinMods"): each build then takes minutes, so
# the game starts long before the patcher scans, and games crashed with it (#441)
HEAVY_BUILTINS_MESSAGE = "LTK Manager's built-in mods put every champion's archive into the overlay"
HEAVY_BUILTINS_HINT = (
    "Quit Rose, open LTK Manager from the Start menu > Settings > Built-in mods, set Base skins to Off "
    "(or Modded champions) and limit Character inking to chosen champions, then close LTK Manager "
    "(also from the system tray) and start Rose again."
)


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


class LtkLogTail:
    """What LTK Manager writes to its own log from the moment this was made.

    The patcher's verdict on the game ("dll attached", "joined too late, not
    overlaying") only shows there: the status the bridge reads does not carry it.
    """

    LOG_PATTERN = "ltk-manager*.log"

    def __init__(self, directory: Optional[Path]):
        self.directory = directory
        self.path = self._newest()
        self.offset = self._size(self.path)

    @staticmethod
    def log_dir() -> Optional[Path]:
        """LTK Manager's log folder: in the roaming app data of the desktop
        user it runs as (an elevated Rose may run as another account)."""
        import os

        candidates = []
        try:
            from utils.core.paths import get_user_data_dir

            candidates.append(get_user_data_dir().parent.parent / "Roaming" / "dev.leaguetoolkit.manager" / "logs")
        except Exception:
            pass
        roaming = os.environ.get("APPDATA")
        if roaming:
            candidates.append(Path(roaming) / "dev.leaguetoolkit.manager" / "logs")
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return None

    @staticmethod
    def _size(path: Optional[Path]) -> int:
        try:
            return path.stat().st_size if path else 0
        except OSError:
            return 0

    def _newest(self) -> Optional[Path]:
        if self.directory is None:
            return None
        try:
            logs = list(self.directory.glob(self.LOG_PATTERN))
            return max(logs, key=lambda log_path: log_path.stat().st_mtime) if logs else None
        except OSError:
            return None

    def read(self) -> str:
        """The text written since the last read."""
        newest = self._newest()
        if newest is None:
            return ""
        if newest != self.path:
            self.path, self.offset = newest, 0  # a new day's file
        if self._size(self.path) < self.offset:
            self.offset = 0  # rewritten
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.offset)
                data = handle.read()
        except OSError:
            return ""
        self.offset += len(data)
        return data.decode("utf-8", "replace")


def _ltk_log_time(stamp: str) -> Optional[float]:
    """The epoch time of an LTK Manager log line's UTC stamp (2026-11-04T18:08:17.201030)."""
    whole, _, fraction = stamp.partition(".")
    try:
        moment = datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return moment.timestamp() + (float(f"0.{fraction}") if fraction.isdigit() else 0.0)


def _unreadable_archive(error: Exception) -> bool:
    """Whether an import failed because LTK Manager could not read the file."""
    text = str(error).lower()
    return any(marker in text for marker in ("not found:", "cannot read file:", "failed to read file:"))


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
        # Guards _early_session and _early_discard only: never held while
        # LTK Manager starts, so a discard never waits on a launch
        self._session_lock = threading.Lock()
        # One launch/connect at a time: two launchers would fight over LTK Manager
        self._connect_lock = threading.Lock()
        # Set by discard_early_patcher: an early connect in flight drops its session
        self._early_discard = False
        self._state_file_lock = threading.Lock()
        # Held while LTK Manager's library is changed (staging during the
        # countdown, the injection's own install): one change at a time
        self._stage_lock = threading.Lock()
        # Staging is open from the countdown's start until the injection or a
        # discard: a late stage must not touch the injection's session
        self._staging_open = False

    @property
    def current_overlay_process(self):
        """Get current overlay process from process manager"""
        return self.process_manager.current_overlay_process if self.process_manager else None

    @current_overlay_process.setter
    def current_overlay_process(self, value):
        """Set current overlay process on process manager"""
        if self.process_manager:
            self.process_manager.current_overlay_process = value

    # -- persisted state ----------------------------------------------------
    @property
    def _installed_state_path(self) -> Path:
        """What a session changed in LTK Manager (the mods it installed, the
        user's mods it turned off, the manager it started), so a crashed
        session is undone by the next one"""
        return self.mods_dir.parent / "ltf_installed.json"

    def _read_state(self) -> dict:
        try:
            document = json.loads(self._installed_state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            document = {}
        if not isinstance(document, dict):
            document = {}
        if not any(key in document for key in ("installed", "disabled", "manager")):
            # The first layout held the installed ids alone
            document = {"installed": {k: v for k, v in document.items() if isinstance(v, str)}}
        installed = document.get("installed")
        disabled = document.get("disabled")
        manager = document.get("manager")
        return {
            "installed": dict(installed) if isinstance(installed, dict) else {},
            "disabled": [str(mod_id) for mod_id in disabled] if isinstance(disabled, list) else [],
            "manager": manager if isinstance(manager, dict) else None,
        }

    def _update_state(self, change: Callable[[dict], None]) -> None:
        """Apply *change* to the state file (read, change, write)."""
        with self._state_file_lock:
            state = self._read_state()
            change(state)
            try:
                self._installed_state_path.write_text(
                    json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except OSError as e:
                log.debug(f"[INJECT] Could not write the LTF session state: {e}")

    def _track_installed(self, session: dict, mod_id: str, folder: str, fingerprint: Optional[str] = None) -> None:
        session["installed"][mod_id] = folder
        if fingerprint:
            session["fingerprints"][mod_id] = fingerprint
        self._update_state(lambda state: state["installed"].__setitem__(mod_id, folder))

    def _track_disabled(self, session: dict, mod_id: str) -> None:
        session["disabled"].append(mod_id)

        def add(state):
            if mod_id not in state["disabled"]:
                state["disabled"].append(mod_id)

        self._update_state(add)

    def _untrack(self, removed=(), restored=()) -> None:
        """Forget the mods Rose removed and the user's mods it turned back on."""
        removed, restored = set(removed), set(restored)
        if not removed and not restored:
            return

        def drop(state):
            state["installed"] = {k: v for k, v in state["installed"].items() if k not in removed}
            state["disabled"] = [mod_id for mod_id in state["disabled"] if mod_id not in restored]

        self._update_state(drop)

    def _cleanup_stale_installs(self, bridge: LtkBridge) -> None:
        """Undo what an earlier session left in LTK Manager (Rose crashed or
        was closed before its cleanup ran): remove its mods, turn the user's
        back on. What cannot be undone now stays recorded for the next try."""
        state = self._read_state()
        installed, disabled = state["installed"], state["disabled"]
        if not installed and not disabled:
            return
        try:
            library = {str(entry.get("id")): entry for entry in bridge.library() if entry.get("id")}
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.debug(f"[INJECT] Could not read LTK Manager's library to clean up an earlier session: {e}")
            return
        try:
            bridge.stop_patcher()  # library edits wait for a running patcher
        except (BridgeUnavailable, BridgeCommandError):
            pass

        removed, restored = [], []
        for mod_id, folder in installed.items():
            if mod_id not in library:
                removed.append(mod_id)  # already gone
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
                log.debug(f"[INJECT] Turned {self._entry_name(entry)} back on (an earlier session turned it off)")
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not turn {mod_id} back on: {e}")
        self._untrack(removed, restored)

    # -- the LTK Manager Rose started -----------------------------------------
    @staticmethod
    def _process_created(pid: Optional[int]) -> Optional[float]:
        if not pid or not PSUTIL_AVAILABLE:
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
        self._update_state(lambda state: state.__setitem__("manager", {"pid": pid, "created": created}))

    def _is_rose_manager(self, pid: Optional[int]) -> bool:
        """Whether the LTK Manager with *pid* is one Rose started (this run or before)."""
        manager = self._read_state()["manager"]
        if not pid or not manager or manager.get("pid") != pid:
            return False
        created, recorded = self._process_created(pid), manager.get("created")
        return created is None or recorded is None or abs(created - float(recorded)) <= 1.0

    def _terminate_manager(self, pid: Optional[int], grace_s: float = 0.0) -> None:
        """Terminate the LTK Manager *pid* Rose started, if it still runs
        after *grace_s* (the time a requested exit gets to finish)."""
        if not pid or not PSUTIL_AVAILABLE:
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
        manager = self._read_state()["manager"]
        if not manager:
            return
        pid = manager.get("pid")
        if self._is_rose_manager(pid) and self._process_created(pid) is not None:
            log.info(f"[INJECT] The LTK Manager Rose started (PID {pid}) lost its bridge - closing it")
            self._terminate_manager(pid)
        self._update_state(lambda state: state.__setitem__("manager", None))

    @staticmethod
    def _ltk_manager_running() -> bool:
        """Whether any LTK Manager is running."""
        if not PSUTIL_AVAILABLE:
            return False
        try:
            for proc in psutil.process_iter(['name']):
                if (proc.info.get('name') or '').lower() in LTK_MANAGER_PROCESSES:
                    return True
        except (psutil.Error, OSError) as e:
            log.debug(f"[INJECT] Could not look for LTK Manager: {e}")
        return False

    # -- session lifecycle --------------------------------------------------
    def _new_session(self, bridge: LtkBridge, launched: bool) -> dict:
        return {
            "bridge": bridge,
            "launched": launched,
            "installed": {},  # library id -> mod folder name
            "fingerprints": {},  # library id -> content digest of the folder it came from
            "disabled": [],  # the user's mods turned off for the session
            "patcher_running": False,
            "ltk_log": None,  # LtkLogTail from the patcher's start
            # Read from LTK Manager's log since the patcher's (last) start
            "overlay_build_s": None,
            "scan_started_at": None,  # epoch time the host began to scan
            "ltk_attached": False,
            "ltk_late": False,
            "ltk_refused": None,  # (check code, what it saw)
            "ltk_signature": None,  # the WinVerifyTrust result in that refusal, as 0x...
            "ltk_disabled": None,  # why the DLL's integrity scan turned the overlay off
            "ltk_incident": None,  # (title, id, verdict) LTK Manager recorded after the game
            "ltk_error": None,  # LTK Manager's first patcher ERROR line
            "staged_after_s": None,  # pick -> patcher start, for the staged mods
            # The library as _install_mods last read it, for _disable_other_mods
            "library_snapshot": None,
            "attach_logged": False,
            "stopper": None,
            "state": None,
            "error": None,
            "done": False,
            "ended": False,
            "game_seen": False,
            "status_failures": 0,
            "late_join_reported": False,
            "reconnects": 0,  # games killed and reconnected to (RECONNECT_MAX)
            "restarted_at": None,  # epoch time of the last such restart
            # A game held (suspended) while the patcher builds (_hold_watch)
            "hold_lock": threading.Lock(),
            "hold_thread": None,
            "hold_done": False,  # the patcher is ready (or gave up): hold no more
            "hold_failed": False,
            "held_game": None,
            "held_at": None,  # time.monotonic() of the hold
            "refused_reported": False,
            "disabled_reported": False,
            "incident_reported": False,
            "early_stop_logged": False,
            "lock": threading.Lock(),
        }

    def _start_ltf_session(self, report: bool = True, cancelled: Optional[Callable[[], bool]] = None) -> Optional[dict]:
        """Connect to the bridge inside LTK Manager, starting it through the
        LTF launcher when nothing is running yet.

        Returns the session, or None when a required component is missing
        (report=False keeps that out of Troubleshooting: the injection that
        would use this session reports it itself). *cancelled* ends the wait
        for a starting LTK Manager early.
        """
        tools_manager = ToolsManager(self.tools_dir)

        launcher = tools_manager.detect_ltf_launcher()
        if launcher is None:
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

        bridge, launched = self._connect_bridge(launcher, manager, report, cancelled)
        if bridge is None:
            return None

        session = self._new_session(bridge, launched)
        self._check_ltk_builtins()
        self._cleanup_stale_installs(bridge)
        shutil.rmtree(self._staging_root(), ignore_errors=True)
        return session

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
                # Not up yet: no browser, or its page without Tauri's IPC
                if not _cdp_unreachable(e) and TAURI_NOT_READY_MARKER not in str(e).lower():
                    return  # another failure: the commands that need the library report it
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

        # The bridge only loads into an LTK Manager the launcher starts, and
        # an LTK Manager Rose did not start is the user's: it stays open
        self._close_stale_rose_manager()
        if self._ltk_manager_running():
            log.warning("[INJECT] LTK Manager is already open without Rose's bridge - leaving it alone")
            self._report_ltf_failure(ALREADY_OPEN_REASON, report)
            return None, False

        log.info(f"[INJECT] Starting LTK Manager through {launcher.name}")
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            result = subprocess.run(
                [str(launcher), "--exe", str(manager), "--quiet"],
                cwd=str(launcher.parent),
                creationflags=creationflags,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=LAUNCHER_TIMEOUT_S,
            )
        except Exception as e:
            self._report_ltf_failure(f"could not start the LTF launcher ({e})", report)
            return None, False
        if result.returncode == LAUNCHER_EXIT_ALREADY_RUNNING:
            log.warning("[INJECT] LTK Manager opened before the launcher could start it - leaving it alone")
            self._report_ltf_failure(ALREADY_OPEN_REASON, report)
            return None, False
        if result.returncode != 0:
            self._report_ltf_failure(
                f"could not start the LTF launcher (exit code {result.returncode})", report
            )
            return None, False

        match = re.search(r"LTK_MANAGER_PID=(\d+)", result.stdout or "")
        pid = int(match.group(1)) if match else None
        try:
            bridge = LtkBridge.wait_for_bridge(
                timeout=BRIDGE_START_TIMEOUT_S, expected_pid=pid, cancelled=cancelled
            )
        except BridgeUnavailable as e:
            if cancelled is not None and cancelled():
                log.debug("[INJECT] Stopped waiting for the LTF bridge: the session is no longer wanted")
            else:
                self._report_ltf_failure(f"the LTF bridge is unreachable ({e})", report)
            # Started hidden by Rose: it would linger out of sight
            self._terminate_manager(pid)
            return None, False
        self._register_manager(bridge.pid or pid)
        # Its bridge is up; its browser, which every command goes through, follows
        self._wait_for_cdp(bridge, cancelled)
        return bridge, True

    def start_patcher_early(self) -> None:
        """Bring LTK Manager and its bridge up now, before the mods are prepared.

        Starting LTK Manager takes seconds, and preparing the mods (extraction,
        loading screen name, party skins) more on a slow PC, while the client
        launches the game: the bridge is brought up early. mk_run_overlay
        takes this session over; it reports missing components itself.
        """
        if self.game_dir is None:
            return
        with self._session_lock:
            self._early_discard = False  # a session is wanted (again)
        if not self._connect_lock.acquire(blocking=False):
            return  # the connect in flight brings it up
        try:
            with self._session_lock:
                session = self._early_session
            if session is not None:
                if self._check_bridge(session):
                    return
                # Rose stopped it after the last game: connect again for this one
                with self._session_lock:
                    if self._early_session is session:
                        self._early_session = None
                self._end_session(session)

            session = self._start_ltf_session(report=False, cancelled=lambda: self._early_discard)
            if session is None:
                return
            with self._session_lock:
                keep = not self._early_discard
                if keep:
                    self._early_session = session
            if not keep:
                log.debug("[INJECT] The early LTF session is no longer wanted - stopping it")
                self._end_session(session)
        finally:
            self._connect_lock.release()

    def _acquire_session(self) -> Optional[dict]:
        """The early session if its bridge is still up, else a new one.

        Waits for an early connect in flight rather than start a second
        LTK Manager next to it.
        """
        with self._connect_lock:
            with self._session_lock:
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
        with self._session_lock:
            session, self._early_session = self._early_session, None
            self._early_discard = True
            self._staging_open = False
        if session:
            log.debug("[INJECT] Stopping the LTF session started for an injection that did not happen")
            self._end_session(session)

    def _end_session(self, session: dict) -> None:
        """Stop the patcher, remove Rose's mods, turn the user's back on, and
        close LTK Manager if Rose started it (a running one is the user's).

        Safe to call more than once: Rose's cleanup and the session loop can
        both get here.
        """
        with session["lock"]:
            if session["ended"]:
                return
            session["ended"] = True
        # Never leave a held game frozen
        session["hold_done"] = True
        self._resume_held_game(session)

        if self.process_manager and session.get("stopper") is not None:
            self.process_manager.clear_session_stopper(session["stopper"])

        bridge = session["bridge"]
        if not bridge.alive():
            # Nothing answers to undo anything: the state file keeps it for
            # the next session
            log.info("[INJECT] The LTF bridge is gone - Rose's mods are removed at the next session")
            if session["launched"]:
                self._terminate_manager(bridge.pid)
        else:
            try:
                bridge.stop_patcher()
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.debug(f"[INJECT] Could not stop the LTK patcher: {e}")

            removed = []
            for mod_id, folder in session["installed"].items():
                try:
                    bridge.uninstall(mod_id)
                    removed.append(mod_id)
                    log.debug(f"[INJECT] Removed {folder} from LTK Manager")
                except (BridgeUnavailable, BridgeCommandError) as e:
                    log.debug(f"[INJECT] Could not remove {folder} from LTK Manager: {e}")
            restored = []
            for mod_id in session["disabled"]:
                try:
                    bridge.toggle(mod_id, True)
                    restored.append(mod_id)
                except (BridgeUnavailable, BridgeCommandError) as e:
                    log.debug(f"[INJECT] Could not turn {mod_id} back on in LTK Manager: {e}")
            self._untrack(removed, restored)

            if session["launched"]:
                bridge.kill()
                # Gone before the next session looks for a running LTK Manager
                self._terminate_manager(bridge.pid, grace_s=3.0)

        if self.process_manager:
            self.process_manager.current_overlay_process = None

    def _check_bridge(self, session: dict) -> bool:
        """Whether the bridge inside LTK Manager still answers."""
        bridge = session.get("bridge")
        if bridge is None or session.get("ended"):
            return False
        return bridge.alive()

    def _stopped_by_rose(self) -> bool:
        """Whether Rose (or the user) asked to stop the current session."""
        if not self.process_manager:
            return False
        return bool(self.process_manager.stopped_by_user or self.process_manager.stopped_by_rose)

    def _session_stopped(self, session: dict) -> bool:
        """Whether the session was stopped (by Rose, the user, or its end)."""
        return bool(session["ended"]) or self._stopped_by_rose()

    # -- mod installation ---------------------------------------------------
    @staticmethod
    def _entry_name(entry: dict) -> str:
        return str(entry.get("displayName") or entry.get("name") or entry.get("id"))

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

    def _track_late_install(self, session: dict, before_ids: set, folder: Path, display_name: str) -> None:
        """Record whatever an import that reported a failure still installed
        (its answer lost or too late): it is Rose's to remove."""
        try:
            library = session["bridge"].library()
        except (BridgeUnavailable, BridgeCommandError):
            return
        for entry in self._created_entries(library, before_ids, folder, display_name):
            log.warning(f"[INJECT] {display_name} was installed although the import failed - Rose removes it after the session")
            self._track_installed(session, str(entry.get("id")), folder.name)

    def _staging_root(self) -> Path:
        """Where archives wait for LTK Manager to import them.

        Not tempfile: Python 3.13 makes its folders private to the elevated
        Rose, and LTK Manager restarts itself unelevated, so it could not read
        them. Rose's data folder belongs to the desktop user, who runs it.
        """
        return self.mods_dir.parent / "ltf_staging"

    def _import_archive(self, session: dict, archive: Path, folder: Path, display_name: str,
                        fingerprint: Optional[str] = None, before_ids: Optional[set] = None) -> dict:
        """Import *archive* into LTK Manager's library and return its entry.

        *before_ids* are the library's ids before this import (read here when
        not given): an id among them is never taken for the import's.
        """
        bridge = session["bridge"]
        if before_ids is None:
            before_ids = {str(entry.get("id")) for entry in bridge.library() if entry.get("id")}
        try:
            try:
                response = bridge.import_fantome(str(archive), name=display_name)
            except BridgeCommandError as e:
                if not _unreadable_archive(e) or archive.stat().st_size > BYTES_IMPORT_LIMIT:
                    raise
                # Refused before anything was installed: sending it again is safe
                log.info(f"[INJECT] LTK Manager cannot read {archive.name} ({e}) - sending its bytes instead")
                response = bridge.import_fantome_bytes(archive.read_bytes(), name=archive.name)
        except (BridgeUnavailable, BridgeCommandError):
            self._track_late_install(session, before_ids, folder, display_name)
            raise
        entry = self._installed_entry(bridge, response, before_ids, folder, display_name)
        if entry is None:
            raise BridgeCommandError(f"{display_name} is not in the library after the import")
        self._track_installed(session, str(entry.get("id")), folder.name, fingerprint)
        return entry

    def _remove_unwanted(self, session: dict, mod_ids: List[str]) -> bool:
        """Remove Rose's mods that are no longer selected (staged for another skin)."""
        bridge = session["bridge"]
        removed, ok = [], True
        for mod_id in mod_ids:
            folder = session["installed"].get(mod_id)
            try:
                bridge.uninstall(mod_id)
            except (BridgeUnavailable, BridgeCommandError) as e:
                # Left enabled it would apply too: at least turn it off
                try:
                    bridge.toggle(mod_id, False)
                    log.warning(f"[INJECT] Could not remove {folder} from LTK Manager ({e}) - turned it off instead")
                except (BridgeUnavailable, BridgeCommandError) as toggle_error:
                    log.error(f"[INJECT] Could not remove {folder} from LTK Manager: {toggle_error}")
                    ok = False
                session["fingerprints"].pop(mod_id, None)
                continue
            removed.append(mod_id)
            session["installed"].pop(mod_id, None)
            session["fingerprints"].pop(mod_id, None)
            log.debug(f"[INJECT] Removed {folder} from LTK Manager (no longer selected)")
        self._untrack(removed)
        return ok

    def _install_mods(self, session: dict, mod_names: List[str], folder_dir: Optional[Path] = None,
                      report: bool = True, stopped: Optional[Callable[[], bool]] = None,
                      archives: Optional[Dict[str, Path]] = None) -> bool:
        """Make Rose's mods in LTK Manager's library exactly the folders
        *mod_names* (in *folder_dir*, mods_dir by default).

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
        bridge = session["bridge"]
        folder_dir = Path(folder_dir) if folder_dir else self.mods_dir
        if stopped is None:
            stopped = lambda: self._session_stopped(session)
        session["library_snapshot"] = None

        wanted = []
        for name in mod_names:
            folder = folder_dir / name
            if not folder.is_dir():
                log.error(f"[INJECT] Mod folder not found: {folder}")
                continue
            try:
                wanted.append((name, folder, mod_fingerprint(folder)))
            except OSError as e:
                log.error(f"[INJECT] Could not read the mod folder {folder}: {e}")
        if not wanted:
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
                (mod_id for mod_id, known in session["fingerprints"].items()
                 if known == fingerprint and mod_id not in kept),
                None,
            )
            if match is None:
                to_import.append((name, folder, fingerprint))
            else:
                kept.add(match)
        unwanted = [mod_id for mod_id in session["installed"] if mod_id not in kept]
        if not to_import and not unwanted:
            return True  # the library already holds exactly these mods

        if session["patcher_running"]:
            log.warning(
                "[INJECT] The mods differ from the ones staged during the countdown - restarting the "
                "LTK patcher (it only overlays a game the client starts after that)"
            )
            self._stop_patcher(session)
        if unwanted and not self._remove_unwanted(session, unwanted):
            return False

        staging = self._staging_root() / uuid.uuid4().hex
        # One read of the library for all the imports (and _disable_other_mods
        # after them): each read is a round trip through LTK Manager
        library: Optional[list] = None
        try:
            for name, folder, fingerprint in to_import:
                if stopped():
                    log.info("[INJECT] Stopped while the mods were being installed")
                    return False
                display_name = fantome_display_name(folder)
                try:
                    if library is None:
                        library = bridge.library()
                    archive = (archives or {}).get(name)
                    if archive is None or not Path(archive).is_file():
                        staging.mkdir(parents=True, exist_ok=True)
                        archive = staging / f"{name}.fantome"
                        write_fantome_zip(folder, archive)
                    before_ids = {str(e.get("id")) for e in library if e.get("id")}
                    entry = self._import_archive(session, Path(archive), folder, display_name, fingerprint,
                                                 before_ids=before_ids)
                    library.append(entry)
                    if not entry.get("enabled"):
                        bridge.toggle(str(entry.get("id")), True)
                    log.info(f"[INJECT] Installed {display_name} into LTK Manager")
                except (OSError, BridgeUnavailable, BridgeCommandError) as e:
                    log.error(f"[INJECT] Could not install {display_name}: {e}")
                    if report and not stopped():
                        if _cdp_unreachable(e):
                            self._report_ltf_failure(_cdp_unreachable_reason())
                        elif not self._report_low_disk_space_failure(mod_names):
                            report_issue(
                                "LTF_IMPORT_FAILED",
                                "error",
                                f"Injection failed: could not install {display_name} ({e}).",
                                details={"mod": folder.name, "error": str(e)},
                                hint=f"Free some disk space, then retry. {LTF_LOGS_HINT}",
                            )
                    return False
            session["library_snapshot"] = library
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return True

    def pack_mods(self, folder_dir: Path, mod_names: List[str]) -> Dict[str, Path]:
        """Pack the mod folders into the archives LTK Manager imports, ahead of the install.

        The countdown's stager packs while the selection settles, so its
        install only has to import (stage_mods(archives=...)). Each archive
        lands next to its folder (<folder_dir>/<name>.fantome); a folder that
        cannot be packed is left out and packed by the install instead. So is
        a mod an earlier pick already staged (a saved map or voiceover mod,
        the same for every skin): the install keeps it as it is.
        """
        staged = self._staged_fingerprints()
        archives: Dict[str, Path] = {}
        for name in mod_names:
            folder = Path(folder_dir) / name
            archive = Path(folder_dir) / f"{name}.fantome"
            try:
                if staged and mod_fingerprint(folder) in staged:
                    continue
                write_fantome_zip(folder, archive)
                archives[name] = archive
            except OSError as e:
                log.debug(f"[STAGE] Could not pack {name} ahead of the install: {e}")
        return archives

    def _staged_fingerprints(self) -> set:
        """The content digests of the mods staged in the early session's LTK Manager."""
        with self._session_lock:
            session = self._early_session
        if session is None:
            return set()
        try:
            return set(list(session["fingerprints"].values()))
        except RuntimeError:  # an install changed them meanwhile
            return set()

    def _start_patcher(self, session: dict, report: bool = True) -> bool:
        """Start LTK Manager's patcher (it builds the overlay, then scans for the game)."""
        tail = LtkLogTail(LtkLogTail.log_dir())  # LTK's own log from this start on
        try:
            try:
                session["bridge"].start_patcher()
            except BridgeCommandError as e:
                # The last patcher has not exited yet: it finishes its overlay
                # build first. Wait for it, then start this one (#437)
                if PATCHER_ALREADY_RUNNING not in str(e).upper() or not self._wait_patcher_stopped(session):
                    raise
                session["bridge"].start_patcher()
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.error(f"[INJECT] Could not start the LTK patcher: {e}")
            if report and not self._session_stopped(session):
                self._report_ltf_failure(
                    _cdp_unreachable_reason() if _cdp_unreachable(e) else f"could not start the LTK patcher ({e})"
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
        bridge = session["bridge"]
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
            session["bridge"].stop_patcher()
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.debug(f"[INJECT] Could not stop the LTK patcher: {e}")
        session["patcher_running"] = False

    # -- staging during the loadout countdown ---------------------------------
    def open_staging(self) -> None:
        """Let stage_mods prepare LTK Manager for this champ select."""
        with self._session_lock:
            self._staging_open = True
            self._early_discard = False

    def close_staging(self) -> None:
        """No more staging: the injection (or a discard) owns the session now."""
        with self._session_lock:
            self._staging_open = False

    def _staging_session(self) -> Optional[dict]:
        """The early session, connected (or LTK Manager started) if it is not up."""
        with self._connect_lock:
            with self._session_lock:
                session = self._early_session
            if session is not None and self._check_bridge(session):
                return session
            if session is not None:
                with self._session_lock:
                    if self._early_session is session:
                        self._early_session = None
                self._end_session(session)
            session = self._start_ltf_session(
                report=False, cancelled=lambda: self._early_discard or not self._staging_open
            )
            if session is None:
                return None
            with self._session_lock:
                keep = self._staging_open and not self._early_discard
                if keep:
                    self._early_session = session
            if not keep:
                self._end_session(session)
                return None
            return session

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

        with self._stage_lock:
            # Once the injection closed staging nothing new starts; an install
            # already running goes on while it is still wanted (the injection
            # waits for this lock and takes it over when it is its own skin)
            if not self._staging_open or stopped() or self.game_dir is None:
                return False
            session = self._staging_session()
            if session is None or stopped():
                return False
            if not self._install_mods(session, mod_names, folder_dir, report=False,
                                      stopped=lambda: session["ended"] or stopped(), archives=archives):
                return False
            if session["ended"] or stopped():
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

    def _disable_other_mods(self, session: dict) -> None:
        """Turn off the user's own enabled mods for this session.

        LTK Manager's patcher applies every enabled mod, and the overlay must
        hold Rose's alone (as mod-tools' did). Each one is recorded before it
        is turned off, so a crash still turns it back on next session.
        """
        bridge = session["bridge"]
        # What _install_mods just read (with its imports added) is still the library
        library, session["library_snapshot"] = session.get("library_snapshot"), None
        try:
            if library is None:
                library = bridge.library()
        except (BridgeUnavailable, BridgeCommandError) as e:
            log.warning(f"[INJECT] Could not read LTK Manager's library - its other enabled mods may apply too: {e}")
            return
        for entry in library:
            mod_id = str(entry.get("id") or "")
            if not mod_id or mod_id in session["installed"] or not entry.get("enabled"):
                continue
            self._track_disabled(session, mod_id)
            try:
                bridge.toggle(mod_id, False)
                log.info(f"[INJECT] Turned off {self._entry_name(entry)} in LTK Manager for this game")
            except (BridgeUnavailable, BridgeCommandError) as e:
                log.warning(f"[INJECT] Could not turn off {self._entry_name(entry)} - it may apply too: {e}")

    # -- injection ----------------------------------------------------------
    def mk_run_overlay(self, mod_names: List[str], timeout: int = 120, stop_callback: Optional[Callable] = None) -> int:
        """Install the mods and run LTK Manager's patcher until the game ends

        Args:
            mod_names: List of mod folders (in mods_dir) to inject
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

        # The countdown's staging ends here (an in-flight one finishes first:
        # its mods are likely the ones this injection wants)
        self.close_staging()
        with self._stage_lock:
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
                self._report_ltf_failure(session["error"])
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
                self._report_ltf_failure(
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
            while not session["ended"] and not session.get("hold_done") and not self._session_stopped(session):
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
                self._report_ltf_failure(
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
                if session["ended"]:
                    break
                if stop_callback and stop_callback():
                    # The client can close during a match (CN/WeGame), which looks
                    # like the end of the game: serve the overlay until the game exits
                    game = self._running_game()
                    if game is not None:
                        log.info("[INJECT] The game is still running - keeping the LTK patcher until it exits")
                        self._wait_for_game_exit(game, session)
                        if session["ended"] or session["error"]:
                            break  # the session itself stopped: handled below
                        if not stop_callback():
                            continue  # the game came back (reconnect)
                    log.info("[INJECT] Game ended, stopping LTK patcher")
                    self._check_patcher_verdict(session)  # LTK Manager's verdict on the game
                    break
                if session["ended"]:
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
            self._report_ltf_failure(session["error"])
            return 1
        log.debug("[INJECT] LTF session completed successfully")
        return 0

    def _read_patcher_status(self, session: dict) -> Optional[dict]:
        """The patcher status value ({running, phase, session, ...}), or None.

        The status answers {ok, response: {ok, value}}. A missing answer (CDP
        busy with another command, a slow eval) is retried on the next poll;
        only STATUS_FAILURE_LIMIT of them in a row fail the session.
        """
        bridge = session["bridge"]
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

    def _check_patcher_verdict(self, session: dict, value: Optional[dict] = None) -> None:
        """Log the patcher reaching the game, and report it joining too late
        (the DLL then stays inert: the game runs without the overlay)."""
        # After a restart the status may still carry the killed game's
        # verdict: only LTK Manager's log (new lines) speaks for the new game
        if value is not None and session.get("restarted_at") is None:
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
                self._report_ltf_failure(
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
            if not self._stopped_by_rose():
                self._report_ltf_failure(
                    f"LTK Manager's patcher refused the overlay (host verification failed: {described}"
                    + (f"; {SIGNATURE_FAILURE_MESSAGE}, {signature})" if signature else ")")
                )
        # LTK Manager's own verdicts on the game: the overlay turned off by its
        # integrity scan, an incident after the game. Rose's injection
        # "completes" either way: without these, nothing told the user (#432)
        disabled = session.get("ltk_disabled")
        if disabled and not session.get("disabled_reported"):
            session["disabled_reported"] = True
            log.error(f"[INJECT] LTK Manager's integrity check disabled the overlay this game: {disabled}")
            self._report_ltf_failure(f"LTK Manager {OVERLAY_DISABLED_MESSAGE} ({disabled})")
        incident = session.get("ltk_incident")
        if incident and not session.get("incident_reported"):
            session["incident_reported"] = True
            title, incident_id, verdict = incident
            where = f"{LTK_INCIDENTS_DIR}\\{incident_id}.json"
            log.error(f"[INJECT] LTK Manager recorded an incident: {title} ({verdict}), see {where}")
            if not disabled:  # its incident only repeats the disabled overlay
                self._report_ltf_failure(f"LTK Manager recorded an incident after the game: {title} ({verdict}; {where})")

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
            for proc in psutil.process_iter(['name']):
                if (proc.info.get('name') or '').lower() in names:
                    return proc
        except (psutil.Error, OSError) as e:
            log.debug(f"[INJECT] Could not look for the game process: {e}")
        return None

    def _wait_for_game_exit(self, game, session: dict) -> None:
        """Wait on the game process itself; stop early if the bridge dies."""
        while not session["ended"] and not session["error"]:
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
        required_bytes = max(MIN_FREE_SPACE_BYTES, DISK_SPACE_HEADROOM_BYTES)
        try:
            usage = shutil.disk_usage(self.mods_dir.parent)
            free_bytes = usage.free
            extracted_bytes = self._directory_size(self.mods_dir)
            required_bytes = max(
                MIN_FREE_SPACE_BYTES,
                extracted_bytes + DISK_SPACE_HEADROOM_BYTES,
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

    @staticmethod
    def _ltk_failure_hint(reason: str) -> str:
        """What the user can do about a session failure, by the cause it reported."""
        logs = LTF_LOGS_HINT
        report = "report it with rose_*.log and those logs"
        cause = ltk_failure_cause(reason)
        if cause == "cdp":
            return ("Rose drives LTK Manager through the debugging port of its built-in browser, which did not "
                    "answer. Restart your PC, then retry. If it keeps happening, use a regular Windows account (not "
                    f"the built-in Administrator) and check that your antivirus does not block LTK Manager. {logs}")
        if cause == "league_admin":
            return ("League is set to run as administrator, and LTK Manager does not patch it then. Right-click "
                    "League of Legends.exe and LeagueClient.exe (in the League of Legends folder) > Properties > "
                    'Compatibility, untick "Run this program as an administrator" (also under "Change settings '
                    f'for all users"), then restart League. {logs}')
        if cause == "manager_admin":
            return ("LTK Manager runs as administrator, and it does not patch League then. Turn User Account "
                    "Control back on, or use a regular Windows account (not the built-in Administrator), then "
                    f"restart the PC. {logs}")
        if cause == "host_missing":
            return ("LTK Manager's own patcher (ltk_patcher_host.exe) is missing from its folder, most often "
                    "removed by an antivirus. Reinstall LTK Manager, then add its folder (C:\\Program Files\\LTK "
                    f"Manager) to your antivirus exclusions. {logs}")
        if cause == "disabled":
            return ("LTK Manager's integrity check turned the overlay off because of a mod: the reason names its "
                    "WAD. LTK Manager refuses a custom skin made of another skin's files: use another custom skin "
                    f"or the official one. {logs}")
        if cause == "corrupt":
            return ("League could not read a file of the overlay, most often a mod made for an older patch. Turn "
                    "your mods off, then back on one at a time to find it; LTK Manager's incident file names the "
                    f"WAD and the mods that wrote it. {logs}")
        if cause == "incident":
            return (f"LTK Manager's incident file says what went wrong in the game and which mods it suspects. {logs}")
        if cause == "start":
            return ("Rose could not start the LTK patcher. Check that ltk_launcher.exe and LeagueToolFlop.dll "
                    f"are still in Rose's tools folder: an antivirus may have removed them. {logs}")
        if cause == "running":
            return ("Close LTK Manager (also from the system tray), then retry: Rose starts it with its "
                    f"bridge and closes it again after the game. {logs}")
        if cause == "late":
            return ("The game started before the patcher was scanning: the skin changed in the last seconds "
                    "of the countdown and LTK Manager needed longer to build its overlay (a skin that also "
                    "changes a map file takes seconds), or LTK Manager was slow to start. Pick the skin a few "
                    f"seconds earlier, or retry the next game. {logs}")
        if cause == "signature":
            return ("LTK Manager's patcher checks the digital signature of LTK Manager's own files, and Windows "
                    "could not verify it: a file was modified or damaged. Reinstall LTK Manager from its official "
                    f"release (github.com/LeagueToolkit/ltk-manager/releases), then retry. {logs}")
        if cause == "refused":
            return ("LTK Manager's patcher refused to apply the overlay. Update Rose (its launcher starts LTK "
                    f"Manager the way the patcher expects); if it still happens, {report}. {logs}")
        if cause == "bridge":
            return (f"LTK Manager closed while the game was running. Retry the next game; "
                    f"if it happens every game, {report}. {logs}")
        if cause == "import":
            return f"Rose could not install the mod into LTK Manager. Free some disk space, then retry. {logs}"
        if cause == "killed":
            return ("Another program closed LTK Manager, most often an antivirus. "
                    f"Add Rose's folder to its exclusions, then retry. {logs}")
        if cause == "crashed":
            return (f"LTK Manager crashed. Retry the next game; if it crashes every game, {report}. {logs}")
        return f"Retry the next game. If it fails every game, {report}. {logs}"

    @classmethod
    def _report_ltf_failure(cls, reason: str, report: bool = True):
        """Show an LTF session failure in Troubleshooting."""
        if not report:
            log.debug(f"[INJECT] LTF session failure (not reported): {reason}")
            return
        report_issue(
            "LTF_FAILED",
            "error",
            f"Injection failed: {reason}",
            details={"reason": reason, "cause": ltk_failure_cause(reason)},
            hint=cls._ltk_failure_hint(reason),
        )

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
