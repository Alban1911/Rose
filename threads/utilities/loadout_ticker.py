#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Loadout countdown ticker thread
"""

import time
import threading
from lcu import LCU
from state import SharedState
from utils.core.logging import get_logger
from config import (
    TIMER_HZ_MIN, TIMER_HZ_MAX, TIMER_POLL_PERIOD_S,
    SKIN_THRESHOLD_MS_DEFAULT,
)

from ..handlers.injection_trigger import InjectionTrigger
from .skin_name_resolver import SkinNameResolver

log = get_logger()


class LoadoutTicker(threading.Thread):
    """High-frequency loadout countdown ticker"""
    
    def __init__(
        self,
        lcu: LCU,
        state: SharedState,
        hz: int,
        fallback_ms: int,
        ticker_id: int,
        mode: str = "auto",
        injection_manager=None,
        skin_scraper=None,
    ):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.state = state
        self.hz = max(TIMER_HZ_MIN, min(TIMER_HZ_MAX, int(hz)))
        self.fallback_ms = max(0, int(fallback_ms))
        self.ticker_id = int(ticker_id)
        self.mode = mode
        self.injection_manager = injection_manager
        self.skin_scraper = skin_scraper
        
        # Initialize handlers
        self.injection_trigger = InjectionTrigger(lcu, state, injection_manager, skin_scraper)
        self.skin_name_resolver = SkinNameResolver(state, skin_scraper)

    def run(self):
        """Main ticker loop"""
        # Exit immediately if another ticker has taken control
        if getattr(self.state, 'current_ticker', 0) != self.ticker_id:
            return
        
        # Local variables to avoid cross-resets
        left0_ms = self.state.loadout_left0_ms
        t0 = self.state.loadout_t0
        deadline = t0 + (left0_ms / 1000.0)
        prev_remain_ms = 10**9
        poll_period_s = TIMER_POLL_PERIOD_S
        last_poll = 0.0
        last_bucket = None
        
        # Continue loop only in ChampSelect/FINALIZATION
        while (not self.state.stop) and self.state.loadout_countdown_active and (self.state.current_ticker == self.ticker_id) and (self.state.phase in ["ChampSelect", "FINALIZATION"]):
            now = time.monotonic()
            
            # Periodic LCU resync
            if (now - last_poll) >= poll_period_s:
                last_poll = now
                sess = self.lcu.session or {}
                t = (sess.get("timer") or {})
                phase = str((t.get("phase") or "")).upper()
                left_ms = int(t.get("adjustedTimeLeftInPhase") or 0)
                
                # Check if phase changed to FINALIZATION
                if phase == "FINALIZATION" and self.state.phase != "FINALIZATION":
                    log.info(f"[loadout] Phase transition detected: {self.state.phase} → FINALIZATION")
                    self.state.phase = "FINALIZATION"
                
                if phase == "FINALIZATION" and left_ms > 0:
                    cand_deadline = time.monotonic() + (left_ms / 1000.0)
                    if cand_deadline < deadline:
                        deadline = cand_deadline
            
            # Local countdown
            remain_ms = int((deadline - time.monotonic()) * 1000.0)
            if remain_ms < 0:
                remain_ms = 0
            
            # Anti-jitter clamp: never go up
            if remain_ms > prev_remain_ms:
                remain_ms = prev_remain_ms
            prev_remain_ms = remain_ms
            
            # Store remaining time in shared state
            self.state.last_remain_ms = remain_ms
            
            bucket = remain_ms // 1000
            if bucket != last_bucket:
                last_bucket = bucket
                seconds_remaining = int(remain_ms // 1000)
                log.info(f"[loadout #{self.ticker_id}] T-{seconds_remaining}s")
                
                # Notify injection manager of countdown
                if self.injection_manager:
                    try:
                        self.injection_manager.on_loadout_countdown(seconds_remaining)
                    except Exception as e:
                        log.debug(f"[loadout] countdown notification failed: {e}")
            
            # Write last hovered skin at T<=threshold
            thresh = int(getattr(self.state, 'skin_write_ms', SKIN_THRESHOLD_MS_DEFAULT) or SKIN_THRESHOLD_MS_DEFAULT)
            if remain_ms <= thresh and not self.state.last_hover_written:
                # Build skin label
                final_label = self.skin_name_resolver.build_skin_label()
                
                # Get champion name for injection
                cname = ""
                try:
                    champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                    if champ_id and self.skin_scraper and self.skin_scraper.cache.is_loaded_for_champion(champ_id):
                        cname = self.skin_scraper.cache.champion_name or ""
                except Exception:
                    pass
                
                # Resolve injection name
                name = self.skin_name_resolver.resolve_injection_name()
                
                log.debug(f"[INJECT] Final name variable: '{name}'")
                
                if name:
                    # Trigger injection
                    self.injection_trigger.trigger_injection(name, self.ticker_id, cname)

            if remain_ms <= 0:
                break
            time.sleep(1.0 / float(self.hz))
        
        # End of ticker: only release if we're still the current ticker
        if getattr(self.state, 'current_ticker', 0) == self.ticker_id:
            self.state.loadout_countdown_active = False
