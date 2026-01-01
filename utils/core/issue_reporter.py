#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Issue Reporter

Writes a small, human-friendly diagnostics file that summarizes important
errors and "non-error failure reasons" (e.g., timeouts, settings mismatches).

File: %LOCALAPPDATA%\\Rose\\rose_issues.txt
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from utils.core.paths import get_user_data_dir

_LOCK = threading.Lock()
_LAST: Dict[str, float] = {}  # naive dedupe: key -> last timestamp


def _issues_path():
    base_dir = get_user_data_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "rose_issues.txt"


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
        now = time.time()
        details = details or {}

        # Dedupe spammy repeats (same code+message) for a short window
        key = f"{code}|{message}"
        last = _LAST.get(key, 0.0)
        if (now - last) < float(dedupe_window_s):
            return
        _LAST[key] = now

        # Novice-friendly formatting:
        #   Dec 15 00:39 | Something happened...
        #   Fix: Do this...
        ts_short = time.strftime("%b %d %H:%M", time.localtime(now))
        lines = [f"{ts_short} | {message}".rstrip()]
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
            except Exception:
                pass

            with p.open("a", encoding="utf-8", errors="ignore") as f:
                f.write(line)
    except Exception:
        return


