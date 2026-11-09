#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Issue Reporter

Writes a small, human-friendly diagnostics file that summarizes important
errors and "non-error failure reasons" (e.g., timeouts, settings mismatches).

File: %LOCALAPPDATA%\\Rose\\rose_diagnostics.txt
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, NamedTuple, Optional

from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir

log = get_logger()

_LOCK = threading.Lock()
_LAST: Dict[str, float] = {}  # naive dedupe: key -> last timestamp

# Keep rose_diagnostics.txt focused on actionable tuning problems and critical
# resource failures that commonly confuse users. Everything else should go to
# the normal logs.
_ALLOWED_CODES = {
    'AUTO_RESUME_TRIGGERED',  # Suggest increasing Monitor Auto-Resume Timeout
    'BASE_SKIN_FORCE_SLOW',   # Suggest increasing Injection Threshold
    'BASE_SKIN_VERIFY_FAILED',  # Base skin verification mismatch (often causes skin not to show)
    'LEAGUE_ELEVATED',        # The League client runs as administrator: LTK Manager's patcher can't reach it
    'LOW_DISK_SPACE',         # Injection could not install a mod with the available disk space
    'LTF_MISSING',            # Rose's LTF bridge files (ltk_launcher.exe + LeagueToolFlop.dll) are missing
    'LTK_MANAGER_MISSING',    # LTK Manager, which Rose drives through the bridge, is not installed
    'LTF_FAILED',             # The LTF session (bridge or LTK patcher) reported an error
    'LTK_HEAVY_BUILTINS',     # LTK Manager's built-in mods put every champion's archive into the overlay
    'LTK_SLOW_MOD_CHECK',     # LTK Manager's automatic mod check took minutes while the game loaded
    'LTK_ELEVATED',           # LTK Manager's own programs are set to run as administrator (error 740)
    'LTF_IMPORT_FAILED',      # A mod could not be imported into LTK Manager's library
    'PENGU_ACTIVATION_FAILED',  # Pengu Loader could not be activated: Rose is missing from the client
    'PENGU_INJECTION_FAILED',   # Pengu Loader was activated, but its DLL is not in the League client
    'WINDOWS_ADMIN_SHELL',    # Windows runs every program as administrator: LTK Manager refuses to patch
}

# Reports about how the PC is set up, which Rose checks again as it starts
# (Pengu Loader's activation, the Windows account) or as League connects: an
# earlier session's copy would only repeat or contradict this session's
_SETUP_CODES = {
    'LEAGUE_ELEVATED',
    'PENGU_ACTIVATION_FAILED',
    'PENGU_INJECTION_FAILED',
    'WINDOWS_ADMIN_SHELL',
}

# Setup reports Rose only checks again as LTK Manager starts (a champion
# select, a mod added): an earlier session's copy is kept, and counts as this
# session's, until that check removes it (resolve_issue) or reports it again.
# Dropped at Rose's start, the problem went unseen until a game's injection failed
_UNTIL_RECHECKED = {
    'LTF_MISSING',
    'LTK_ELEVATED',
    'LTK_MANAGER_MISSING',
}

# An earlier session's other reports stay this long
EARLIER_REPORTS_KEPT_S = 7 * 24 * 3600

# When this Rose started (start_session), shown in Troubleshooting
SESSION_START = time.time()

# Which run of Rose wrote a report: its stamp carries it, so this session's
# reports are told from earlier ones whatever the clock did between them
# (a daylight saving change, a clock set right after a boot)
SESSION_ID = secrets.token_hex(4)

# "2026-11-08 14:02:31 [LTF_FAILED] #3f9a0c21": time, code and session. Reports
# from before the session was stamped hold no "#..."; older ones hold
# "Nov 08 14:02" (no year, no code)
_STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?: \[([A-Za-z0-9_]+)\])?(?: #([0-9a-f]+))?$")
_OLD_STAMP = re.compile(r"^([A-Za-z]{3}) (\d{1,2}) (\d{1,2}):(\d{2})$")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


class Stamp(NamedTuple):
    """A report's stamp (parse_stamp)."""

    when: Optional[float]
    code: str
    session: str


def parse_stamp(stamp: str, now: Optional[float] = None) -> Stamp:
    """The time, code and session of a report's stamp, the part before " | ".
    The time is None when the stamp can't be read; the code is empty for older
    reports, the session for reports from before stamps held it. An older
    report has no year: it gets the latest one that is not in the future."""
    stamp = (stamp or "").strip()
    try:
        m = _STAMP.match(stamp)
        if m:
            return Stamp(datetime.strptime(m.group(1), _STAMP_FORMAT).timestamp(), m.group(2) or "",
                         m.group(3) or "")
        m = _OLD_STAMP.match(stamp)
        if m:
            current = datetime.fromtimestamp(time.time() if now is None else now)
            month = _MONTHS.index(m.group(1).lower()) + 1
            day, hour, minute = int(m.group(2)), int(m.group(3)), int(m.group(4))
            for year in (current.year, current.year - 1):
                try:
                    when = datetime(year, month, day, hour, minute)
                except ValueError:  # Feb 29 of a year without it
                    continue
                if when <= current:
                    return Stamp(when.timestamp(), "", "")
    except Exception:
        pass
    return Stamp(None, "", "")


def in_this_session(stamp: Stamp) -> bool:
    """Whether a report (parse_stamp) is this session's: written by this run of
    Rose, or a setup problem LTK Manager's next start is still to check again
    (_UNTIL_RECHECKED), which is the PC's until then."""
    return stamp.session == SESSION_ID or stamp.code in _UNTIL_RECHECKED


def start_session() -> None:
    """Start a new session (its id stamps the reports from here on), and drop
    the earlier sessions' setup reports Rose checks again as it starts, and
    their reports older than EARLIER_REPORTS_KEPT_S. Never raises."""
    global SESSION_START, SESSION_ID
    SESSION_START = time.time()
    SESSION_ID = secrets.token_hex(4)
    cutoff = SESSION_START - EARLIER_REPORTS_KEPT_S

    def stale(line: str, fix: str) -> bool:
        stamp = parse_stamp(line.split(" | ", 1)[0], SESSION_START)
        if stamp.code in _UNTIL_RECHECKED:
            return False
        return stamp.code in _SETUP_CODES or (stamp.when is not None and stamp.when < cutoff)

    remove_issues(stale)


def resolve_issue(code: str, message: Optional[str] = None) -> None:
    """Remove the reports of *code*, of any session: the problem it reports is
    gone. *message*, part of the report's line, also finds one an older Rose
    wrote, whose stamp holds no code. Never raises."""
    def resolved(line: str, fix: str) -> bool:
        stamp = parse_stamp(line.split(" | ", 1)[0])
        return stamp.code == code or (not stamp.code and message is not None and message in line)

    remove_issues(resolved)


def _issues_path():
    base_dir = get_user_data_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "rose_diagnostics.txt"


def report_issue(
    code: str,
    severity: str,
    message: str,
    *,
    details: Optional[Dict[str, Any]] = None,
    hint: Optional[str] = None,
    dedupe_window_s: float = 3.0,
) -> None:
    """
    Append one diagnostic line to the issue summary file.

    Never raises (safe to call from exception handlers / hot paths).
    """
    try:
        # Intentionally keep this file minimal and user-actionable.
        # If you need deeper troubleshooting, use the main log files.
        if code not in _ALLOWED_CODES:
            return

        now = time.time()
        details = details or {}

        # Dedupe spammy repeats (same code+message) for a short window
        key = f"{code}|{message}"
        last = _LAST.get(key, 0.0)
        if (now - last) < float(dedupe_window_s):
            return
        _LAST[key] = now

        # One report of a setup problem kept across sessions: this one replaces it
        if code in _UNTIL_RECHECKED:
            resolve_issue(code)

        # Novice-friendly formatting:
        #   2026-12-15 00:39:12 [LTF_FAILED] #3f9a0c21 | Something happened...
        #   Fix: Do this...
        stamp = f"{time.strftime(_STAMP_FORMAT, time.localtime(now))} [{code}] #{SESSION_ID}"
        lines = [f"{stamp} | {message}".rstrip()]
        if hint:
            lines.append(f"Fix: {hint}".rstrip())
        line = "\n".join(lines) + "\n"

        with _LOCK:
            p = _issues_path()

            # Lightweight size cap (~1.5MB): keep last ~4000 lines
            try:
                if p.exists() and p.stat().st_size > 1_500_000:
                    txt = p.read_text(encoding="utf-8", errors="ignore").splitlines()[-4000:]
                    p.write_text("\n".join(txt) + "\n", encoding="utf-8")
            except Exception as e:
                log.debug("[ISSUES] Could not trim diagnostics file: %s", e)

            with p.open("a", encoding="utf-8", errors="ignore") as f:
                f.write(line)
    except Exception as e:
        log.debug("[ISSUES] Could not write diagnostics entry %s: %s", code, e)


def read_issues_tail(*, max_lines: int = 60) -> list[str]:
    """Read the last N lines from rose_diagnostics.txt (safe, never raises)."""
    try:
        p = _issues_path()
        if not p.exists():
            return []
        with _LOCK:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        if max_lines <= 0:
            return []
        return lines[-int(max_lines):]
    except Exception as e:
        log.debug("[ISSUES] Could not read diagnostics file: %s", e)
        return []


def remove_issues(should_remove: Callable[[str, str], bool]) -> bool:
    """Remove the reports for which should_remove(message_line, fix_line) is
    true, writing the file only when one goes (safe, never raises)."""
    try:
        with _LOCK:
            p = _issues_path()
            if not p.exists():
                return True
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            kept: list[str] = []
            removed = False
            i = 0
            while i < len(lines):
                line = lines[i]
                fix = ""
                # Each report is 1-2 lines: the message line + optional "Fix:" line
                if " | " in line and i + 1 < len(lines) and lines[i + 1].startswith("Fix:"):
                    fix = lines[i + 1]
                    i += 1
                if " | " in line and should_remove(line, fix):
                    removed = True
                else:
                    kept.append(line)
                    if fix:
                        kept.append(fix)
                i += 1
            if removed:
                p.write_text("\n".join(kept) + "\n" if kept else "", encoding="utf-8")
        return True
    except Exception as e:
        log.debug("[ISSUES] Could not remove diagnostics entries: %s", e)
        return False


def clear_issues() -> bool:
    """Clear rose_diagnostics.txt (safe, never raises). Returns True if cleared."""
    try:
        with _LOCK:
            p = _issues_path()
            p.write_text("", encoding="utf-8", errors="ignore")
        return True
    except Exception as e:
        log.debug("[ISSUES] Could not clear diagnostics file: %s", e)
        return False

