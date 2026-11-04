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
        try:
            self._countdown()
        except Exception:
            log.exception(f"[loadout #{self.ticker_id}] Ticker stopped by an unexpected error")
        finally:
            # Release even after an error: while the flag is set no new ticker
            # starts, and the champ select would end without an injection
            if getattr(self.state, 'current_ticker', 0) == self.ticker_id:
                self.state.loadout_countdown_active = False

    @staticmethod
    def _log_error_once(what: str, error: Exception, last_logged):
        """Log a tick error with its traceback once, not on every tick of the loop."""
        key = (what, repr(error))
        if key != last_logged:
            log.exception(f"[loadout] {what}: {error}")
        return key

    def _champion_name(self) -> str:
        """The locked (or hovered) champion's name, for the injection."""
        try:
            champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
            if champ_id and self.skin_scraper and self.skin_scraper.cache.is_loaded_for_champion(champ_id):
                return self.skin_scraper.cache.champion_name or ""
        except Exception:
            pass
        return ""

    def _selection(self) -> tuple:
        """What the injection's choice depends on: staging runs when it changes."""
        state = self.state
        return (
            getattr(state, 'last_hovered_skin_id', None),
            getattr(state, 'selected_chroma_id', None),
            getattr(state, 'historic_mode_active', False),
            getattr(state, 'historic_skin_id', None),
            getattr(state, 'random_mode_active', False),
            getattr(state, 'random_skin_id', None),
            state.locked_champ_id or state.hovered_champ_id,
            bool(getattr(state, 'selected_custom_mod', None)),
        )

    def _stage_selection(self, threshold_in_s: float) -> None:
        """Stage the selected skin, when the injection would install it alone.

        *threshold_in_s* is the time left before the injection threshold.
        """
        name = self.skin_name_resolver.resolve_injection_name()
        if name and self.injection_trigger.staging_target(name):
            self.injection_manager.stage_skin(
                name,
                champion_name=self._champion_name(),
                champion_id=self.state.locked_champ_id or self.state.hovered_champ_id,
                threshold_in_s=threshold_in_s,
            )

    def _countdown(self):
        # Exit immediately if another ticker has taken control
        if getattr(self.state, 'current_ticker', 0) != self.ticker_id:
            return

        # LTK Manager's patcher only overlays a game the client creates after
        # its scan started: bring LTK Manager up now, and stage the selected
        # skin while the countdown runs (see InjectionManager.stage_skin)
        if self.injection_manager:
            self.injection_manager.begin_staging()
            self.injection_manager.start_patcher_in_background()

        # Local variables to avoid cross-resets
        left0_ms = self.state.loadout_left0_ms
        t0 = self.state.loadout_t0
        deadline = t0 + (left0_ms / 1000.0)
        prev_remain_ms = 10**9
        poll_period_s = TIMER_POLL_PERIOD_S
        last_poll = 0.0
        last_bucket = None
        last_logged_name = object()
        error_logged = None
        injection_triggered = False
        staged_selection = object()
        # The selection the injection took at the threshold, and whether a
        # later change was already reported as ignored
        taken_selection, taken_name = None, None
        late_change_logged = False
        
        # Continue loop only in ChampSelect/FINALIZATION
        while (not self.state.stop) and self.state.loadout_countdown_active and (self.state.current_ticker == self.ticker_id) and (self.state.phase in ["ChampSelect", "FINALIZATION"]):
            now = time.monotonic()
            
            # Periodic LCU resync
            if (now - last_poll) >= poll_period_s:
                try:
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
                except Exception as e:
                    error_logged = self._log_error_once("LCU timer resync failed", e, error_logged)
            
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

            # Before it, stage the selection in LTK Manager each time it changes.
            # Compared on every tick (a tuple of the state's fields): a pick
            # reaches the stager within a tick, and only a change stages
            if (
                self.injection_manager
                and remain_ms > thresh
                and not self.state.last_hover_written
            ):
                selection = self._selection()
                if selection != staged_selection:
                    staged_selection = selection
                    try:
                        self._stage_selection((remain_ms - thresh) / 1000.0)
                    except Exception as e:
                        error_logged = self._log_error_once("Staging failed", e, error_logged)

            if remain_ms <= thresh and not self.state.last_hover_written:
                try:
                    # Build skin label
                    final_label = self.skin_name_resolver.build_skin_label()
                
                    # Get champion name for injection
                    cname = self._champion_name()
                
                    # Resolve injection name
                    name = self.skin_name_resolver.resolve_injection_name()
                    if name != last_logged_name:
                        log.debug(f"[INJECT] Final name variable: '{name}'")
                        last_logged_name = name
                
                    if name:
                        # Trigger injection
                        selection = self._selection()
                        self.injection_trigger.trigger_injection(name, self.ticker_id, cname)
                        # Past validation, the trigger injects or stops the patcher itself
                        injection_triggered = injection_triggered or self.state.last_hover_written
                        if self.state.last_hover_written:
                            taken_selection, taken_name = selection, name
                except Exception as e:
                    error_logged = self._log_error_once("Injection trigger failed", e, error_logged)
            elif (
                taken_selection is not None
                and not late_change_logged
                and self._selection() != taken_selection
            ):
                # Too late to install before the game: the skin taken at the
                # threshold (staged during the countdown) is the one applied
                late_change_logged = True
                log.info(
                    f"[loadout #{self.ticker_id}] Skin changed after the injection threshold - "
                    f"ignored, {taken_name} is applied"
                )

            if remain_ms <= 0:
                break
            time.sleep(1.0 / float(self.hz))

        # No injection was triggered (no skin, refused, dodge): stop the patcher
        if (
            self.injection_manager
            and not injection_triggered
            and getattr(self.state, 'current_ticker', 0) == self.ticker_id
        ):
            self.injection_manager.discard_early_patcher()
