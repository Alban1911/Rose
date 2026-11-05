#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub API calls that respect GitHub's rate limit.

Without a login, GitHub allows 60 API calls per hour per IP, and an answer that
nothing changed (304) still counts. Rose reads its updates, game hashes and
skin library from raw.githubusercontent.com and github.com instead, which do not
count; the API is only a fallback. When GitHub refuses a call for its limit,
the time it gives back is saved, and no API call is made again before it: the
launcher relaunched right away would otherwise spend its next call on the same
refusal.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from config import APP_USER_AGENT
from utils.core.atomic_file import write_text_atomic
from utils.core.logging import get_logger
from utils.core.paths import get_state_dir

log = get_logger()

# How long to wait when GitHub refuses without saying until when
DEFAULT_BACKOFF_S = 15 * 60
# The longest wait honored (a broken clock or header must not block for days)
MAX_BACKOFF_S = 2 * 60 * 60

_lock = threading.Lock()


def _state_file() -> Path:
    return get_state_dir() / "github_api_limit.json"


def blocked_until() -> float:
    """The time (epoch seconds) before which no API call is made, 0 when none."""
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        until = float(data.get("blocked_until", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0.0
    # A time far ahead comes from a broken clock: ignore it
    return until if until - time.time() <= MAX_BACKOFF_S else 0.0


def api_allowed() -> bool:
    return blocked_until() <= time.time()


def _refusal_until(response: requests.Response) -> Optional[float]:
    """Until when GitHub refuses API calls, when this answer is a rate-limit refusal."""
    if response.status_code not in (403, 429):
        return None
    headers = response.headers
    remaining = headers.get("X-RateLimit-Remaining")
    retry_after = headers.get("Retry-After")
    if response.status_code == 403 and remaining != "0" and not retry_after:
        return None  # forbidden for another reason
    now = time.time()
    if retry_after and retry_after.isdigit():
        return now + min(int(retry_after), MAX_BACKOFF_S)
    reset = headers.get("X-RateLimit-Reset")
    if reset and reset.isdigit() and remaining == "0":
        return min(float(reset), now + MAX_BACKOFF_S)
    return now + DEFAULT_BACKOFF_S


def note_response(response: requests.Response) -> None:
    """Record a rate-limit refusal from GitHub's API."""
    until = _refusal_until(response)
    if until is None:
        return
    with _lock:
        if until <= blocked_until():
            return
        try:
            write_text_atomic(_state_file(), json.dumps({"blocked_until": until}))
        except OSError as e:
            log.debug(f"[GitHub] Could not save the rate limit: {e}")
    log.warning(
        f"[GitHub] API rate limit reached - no API call before "
        f"{datetime.fromtimestamp(until).strftime('%H:%M')}"
    )


def api_get(url: str, session: Optional[requests.Session] = None, **kwargs) -> Optional[requests.Response]:
    """GET a GitHub API url, or None while GitHub's rate limit refuses calls
    (the refusal is recorded; other errors raise as requests does)."""
    if not api_allowed():
        log.info(
            f"[GitHub] API call skipped until {datetime.fromtimestamp(blocked_until()).strftime('%H:%M')} "
            f"(rate limit): {url}"
        )
        return None
    headers = {"User-Agent": APP_USER_AGENT, "Accept": "application/vnd.github+json", **kwargs.pop("headers", {})}
    response = (session or requests).get(url, headers=headers, **kwargs)
    note_response(response)
    return response
