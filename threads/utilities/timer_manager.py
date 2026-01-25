#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Timer Manager
Manages loadout countdown timer lifecycle
"""

import logging
import time
from typing import Optional

from config import WS_PROBE_ITERATIONS, WS_PROBE_SLEEP_MS, TIMER_HZ_DEFAULT, FALLBACK_LOADOUT_MS_DEFAULT
from lcu import LCU
from state import SharedState
from .loadout_ticker import LoadoutTicker
from utils.core.logging import get_logger, log_event

log = get_logger()


class TimerManager:
    """Manages loadout countdown timer lifecycle"""
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        timer_hz: int = TIMER_HZ_DEFAULT,
        fallback_ms: int = FALLBACK_LOADOUT_MS_DEFAULT,
        injection_manager=None,
        skin_scraper=None,
    ):
        """Initialize timer manager
        
        Args:
            lcu: LCU client instance
            state: Shared application state
            timer_hz: Timer frequency in Hz
            fallback_ms: Fallback timer duration in milliseconds
            injection_manager: Injection manager instance
            skin_scraper: Skin scraper instance
        """
        self.lcu = lcu
        self.state = state
        self.timer_hz = timer_hz
        self.fallback_ms = fallback_ms
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
        self.ticker: Optional[LoadoutTicker] = None
    
    def maybe_start_timer(self, sess: dict):
        """Start timer if conditions are met - ONLY on FINALIZATION phase"""
        t = (sess.get("timer") or {})
        phase_timer = str((t.get("phase") or "")).upper()
        left_ms = int(t.get("adjustedTimeLeftInPhase") or 0)
        should_start = False
        probe_used = False
        
        # ONLY start timer on FINALIZATION phase
        if phase_timer == "FINALIZATION":
            # Update phase to FINALIZATION if we're currently in ChampSelect
            if self.state.phase == "ChampSelect":
                if self.state.phase != "FINALIZATION":
                    from utils.core.logging import log_status
                    log_status(log, "Phase", "FINALIZATION", "")
                    self.state.phase = "FINALIZATION"
            
            # If timer value is not ready yet, probe a few times
            if left_ms <= 0:
                for _ in range(WS_PROBE_ITERATIONS):
                    s2 = self.lcu.session or {}
                    t2 = (s2.get("timer") or {})
                    phase_timer_probe = str((t2.get("phase") or "")).upper()
                    left_ms = int(t2.get("adjustedTimeLeftInPhase") or 0)
                    if phase_timer_probe == "FINALIZATION" and left_ms > 0:
                        probe_used = True
                        break
                    time.sleep(WS_PROBE_SLEEP_MS / 1000.0)
            
            # Start timer only if we have a positive value
            if left_ms > 0:
                should_start = True
        
        if should_start:
            with self.state.timer_lock:
                if not self.state.loadout_countdown_active:
                    self.state.loadout_left0_ms = left_ms
                    self.state.loadout_t0 = time.monotonic()
                    self.state.ticker_seq = (self.state.ticker_seq or 0) + 1
                    self.state.current_ticker = self.state.ticker_seq
                    self.state.loadout_countdown_active = True
                    mode = "finalization"
                    log_event(log, f"Loadout ticker started", "⏰", {
                        "ID": self.state.current_ticker,
                        "Mode": mode,
                        "Remaining": f"{left_ms}ms ({left_ms/1000:.3f}s)",
                        "Hz": self.timer_hz,
                        "Phase": phase_timer
                    })
                    if self.ticker is None or not self.ticker.is_alive():
                        self.ticker = LoadoutTicker(
                            self.lcu,
                            self.state,
                            self.timer_hz,
                            self.fallback_ms,
                            ticker_id=self.state.current_ticker,
                            mode=mode,
                            injection_manager=self.injection_manager,
                            skin_scraper=self.skin_scraper
                        )
                        self.ticker.start()

