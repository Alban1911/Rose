#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Base Skin Confirmation Tracker

Tracks the time between forcing a base skin (LCU PATCH) and receiving
the WebSocket confirmation that the skin was applied. Persists samples
to disk so the troubleshooting UI can recommend a threshold value based
on real historical data instead of guessing.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

from utils.core.logging import get_logger
from utils.core.paths import get_user_data_dir

log = get_logger()

_LOCK = threading.Lock()
_MAX_SAMPLES = 50  # Keep last N samples
_MAX_CONFIRMATION_S = 10.0  # Discard confirmations longer than this (likely stale tracking)

# Singleton state
_pending_skin_id: Optional[int] = None
_pending_start: float = 0.0


def _data_path() -> Path:
    return get_user_data_dir() / "base_skin_samples.json"


def _load_samples() -> list[dict]:
    try:
        p = _data_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[-_MAX_SAMPLES:]
    except Exception as e:
        log.warning("[TRACKER] Could not load base skin samples: %s", e)
    return []


def _save_samples(samples: list[dict]) -> None:
    try:
        p = _data_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(samples[-_MAX_SAMPLES:]), encoding="utf-8")
    except Exception as e:
        log.debug(f"[TRACKER] Failed to save samples: {e}")


def start_tracking(target_skin_id: int) -> None:
    """Call after PATCHing the base skin. Records what we're waiting for."""
    global _pending_skin_id, _pending_start
    with _LOCK:
        _pending_skin_id = target_skin_id
        _pending_start = time.perf_counter()
    log.debug(f"[TRACKER] Tracking base skin confirmation for skinId={target_skin_id}")


def on_skin_confirmed(skin_id: int) -> Optional[float]:
    """Call from WebSocket session handler when selectedSkinId updates.

    Returns the elapsed time in seconds if this was the pending confirmation,
    otherwise None.
    """
    global _pending_skin_id, _pending_start
    with _LOCK:
        if _pending_skin_id is None or skin_id != _pending_skin_id:
            return None

        elapsed_s = time.perf_counter() - _pending_start
        target = _pending_skin_id
        _pending_skin_id = None
        _pending_start = 0.0

    # Discard impossibly late confirmations — likely stale tracking from a previous champ select
    if elapsed_s > _MAX_CONFIRMATION_S:
        log.warning(f"[TRACKER] Discarding stale confirmation (skinId={target}) after {elapsed_s:.1f}s (>{_MAX_CONFIRMATION_S}s)")
        return None

    log.info(f"[TRACKER] Base skin confirmed (skinId={target}) in {elapsed_s:.3f}s")

    sample = {
        "elapsed_ms": round(elapsed_s * 1000),
        "confirmed": True,
        "ts": int(time.time()),
    }
    try:
        samples = _load_samples()
        samples.append(sample)
        _save_samples(samples)
    except Exception as e:
        log.warning("[TRACKER] Could not record base skin sample: %s", e, exc_info=True)
    return elapsed_s


def on_champ_select_exit() -> Optional[float]:
    """Call when leaving ChampSelect with a pending confirmation.

    Records a timeout sample. Returns the elapsed time, or None if nothing
    was pending.
    """
    global _pending_skin_id, _pending_start
    with _LOCK:
        if _pending_skin_id is None:
            return None

        elapsed_s = time.perf_counter() - _pending_start
        target = _pending_skin_id
        _pending_skin_id = None
        _pending_start = 0.0

    log.warning(f"[TRACKER] Base skin confirmation TIMED OUT (skinId={target}) after {elapsed_s:.3f}s")

    sample = {
        "elapsed_ms": round(elapsed_s * 1000),
        "confirmed": False,
        "ts": int(time.time()),
    }
    try:
        samples = _load_samples()
        samples.append(sample)
        _save_samples(samples)
    except Exception as e:
        log.warning("[TRACKER] Could not record base skin sample: %s", e, exc_info=True)
    return elapsed_s


def get_stats() -> dict:
    """Compute statistics from historical samples.

    Returns dict with keys:
        total_samples, confirmed_count, timeout_count,
        avg_ms, p90_ms, max_ms, recommended_threshold_ms,
        samples (raw list for frontend display)
    """
    samples = _load_samples()
    confirmed = [s for s in samples if s.get("confirmed")]
    timeouts = [s for s in samples if not s.get("confirmed")]

    if not confirmed:
        return {
            "total_samples": len(samples),
            "confirmed_count": 0,
            "timeout_count": len(timeouts),
            "avg_ms": None,
            "p90_ms": None,
            "max_ms": None,
            "recommended_threshold_ms": None,
        }

    times = sorted(s["elapsed_ms"] for s in confirmed)
    avg = sum(times) / len(times)
    p90_idx = max(0, int(len(times) * 0.9) - 1)
    p90 = times[p90_idx]
    max_ms = times[-1]

    # Recommended = p90 + 30% buffer, floored at 300ms (slider min), capped at 2000ms
    recommended = int(min(2000, max(300, p90 * 1.3)))

    return {
        "total_samples": len(samples),
        "confirmed_count": len(confirmed),
        "timeout_count": len(timeouts),
        "avg_ms": round(avg),
        "p90_ms": p90,
        "max_ms": max_ms,
        "recommended_threshold_ms": recommended,
    }


def clear_samples() -> None:
    """Clear all saved samples."""
    try:
        p = _data_path()
        if p.exists():
            p.write_text("[]", encoding="utf-8")
    except Exception as e:
        log.warning("[TRACKER] Could not clear base skin samples: %s", e)
    log.info("[TRACKER] Samples cleared")
