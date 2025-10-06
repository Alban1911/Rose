#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Loadout countdown ticker thread
"""

import os
import time
import threading
from typing import Optional
from lcu.client import LCU
from state.shared_state import SharedState
from database.name_db import NameDB
from utils.logging import get_logger
from utils.normalization import normalize_text
from constants import (
    TIMER_HZ_MIN, TIMER_HZ_MAX, TIMER_POLL_PERIOD_S,
    SKIN_THRESHOLD_MS_DEFAULT, HOVER_BUFFER_FILE
)

log = get_logger()


class LoadoutTicker(threading.Thread):
    """High-frequency loadout countdown ticker"""
    
    def __init__(self, lcu: LCU, state: SharedState, hz: int, fallback_ms: int, 
                 ticker_id: int, mode: str = "auto", db: Optional[NameDB] = None, 
                 injection_manager=None):
        super().__init__(daemon=True)
        self.lcu = lcu
        self.state = state
        self.hz = max(TIMER_HZ_MIN, min(TIMER_HZ_MAX, int(hz)))
        self.fallback_ms = max(0, int(fallback_ms))
        self.ticker_id = int(ticker_id)
        self.mode = mode
        self.db = db
        self.injection_manager = injection_manager

    def run(self):
        """Main ticker loop"""
        # Exit immediately if another ticker has taken control
        if getattr(self.state, 'current_ticker', 0) != self.ticker_id:
            return
        
        # Local variables to avoid cross-resets if multiple tickers existed accidentally
        left0_ms = self.state.loadout_left0_ms
        t0 = self.state.loadout_t0
        # Absolute deadline in monotonic time (strict, non-increasing)
        deadline = t0 + (left0_ms / 1000.0)
        prev_remain_ms = 10**9
        poll_period_s = TIMER_POLL_PERIOD_S
        last_poll = 0.0
        last_bucket = None
        
        while (not self.state.stop) and (self.state.phase == "ChampSelect") and self.state.loadout_countdown_active and (self.state.current_ticker == self.ticker_id):
            now = time.monotonic()
            
            # Periodic LCU resync
            if (now - last_poll) >= poll_period_s:
                last_poll = now
                sess = self.lcu.session() or {}
                t = (sess.get("timer") or {})
                phase = str((t.get("phase") or "")).upper()
                left_ms = int(t.get("adjustedTimeLeftInPhase") or 0)
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
            
            # Store remaining time in shared state for OCR thread
            self.state.last_remain_ms = remain_ms
            
            bucket = remain_ms // 1000
            if bucket != last_bucket:
                last_bucket = bucket
                log.info(f"[loadout #{self.ticker_id}] T-{int(remain_ms // 1000)}s")
            
            # Write last hovered skin at T<=threshold (configurable)
            thresh = int(getattr(self.state, 'skin_write_ms', SKIN_THRESHOLD_MS_DEFAULT) or SKIN_THRESHOLD_MS_DEFAULT)
            if remain_ms <= thresh and not self.state.last_hover_written:
                raw = self.state.last_hovered_skin_key or self.state.last_hovered_skin_slug \
                    or (str(self.state.last_hovered_skin_id) if self.state.last_hovered_skin_id else None)
                
                # Build clean label: "<Skin> <Champion>" without duplication or inversion
                final_label = None
                try:
                    champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                    cname = self.db.champ_name_by_id.get(champ_id or -1, "").strip() if self.db else ""

                    # 1) Base: prefer skin ID (Data Dragon) → ex: "Blood Lord"
                    if self.state.last_hovered_skin_id and self.db and self.state.last_hovered_skin_id in self.db.skin_name_by_id:
                        base = self.db.skin_name_by_id[self.state.last_hovered_skin_id].strip()
                    else:
                        base = (raw or "").strip()

                    # Normalize spaces and apostrophes (NBSP etc.)
                    base_clean = base.replace(" ", " ").replace("'", "'")
                    c_clean = (cname or "").replace(" ", " ").replace("'", "'")

                    # 2) If label starts with champion (ex: "Vladimir Blood Lord"), remove prefix
                    if c_clean and base_clean.lower().startswith(c_clean.lower() + " "):
                        base_clean = base_clean[len(c_clean) + 1:].lstrip()
                    # 3) If label ends with champion (rare), remove suffix
                    elif c_clean and base_clean.lower().endswith(" " + c_clean.lower()):
                        base_clean = base_clean[:-(len(c_clean) + 1)].rstrip()

                    # 4) If champion name is already included in the middle (ex: "K/DA ALL OUT Seraphine Indie"), don't add it
                    nb = normalize_text(base_clean)
                    nc = normalize_text(c_clean)
                    if nc and (nc in nb.split()):
                        final_label = base_clean
                    else:
                        final_label = (base_clean + (" " + c_clean if c_clean else "")).strip()
                except Exception:
                    final_label = raw or ""

                name = final_label if final_label else None
                if not name:
                    try:
                        with open(HOVER_BUFFER_FILE, "r", encoding="utf-8") as f:
                            s = f.read().strip()
                            if s:
                                name = s
                    except Exception:
                        pass
                
                # For injection, we need the English name from the database
                # Use the English skin name that was already processed by OCR thread
                injection_name = getattr(self.state, 'last_hovered_skin_key', None)
                if injection_name:
                    name = injection_name
                else:
                    # Fallback to OCR text if no English name available
                    name = getattr(self.state, 'ocr_last_text', None) or name
                    if name:
                        # If OCR text is like "Champion X Champion", normalize to "X Champion"
                        try:
                            champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                            cname = (self.db.champ_name_by_id.get(champ_id or -1, "") or "").strip() if self.db else ""
                            if cname:
                                low = name.strip()
                                if low.lower().startswith(cname.lower() + " ") and low.lower().endswith(" " + cname.lower()):
                                    core = low[len(cname) + 1:-(len(cname) + 1)].strip()
                                    if core:
                                        name = f"{core} {cname}".strip()
                        except Exception:
                            pass
                
                if name:
                    try:
                        # Use user data directory for state files to avoid permission issues
                        from utils.paths import get_state_dir
                        state_file = get_state_dir() / "last_hovered_skin.txt"
                        path = getattr(self.state, 'skin_file', str(state_file))
                        # Only create directory if path has a directory component
                        dir_path = os.path.dirname(path)
                        if dir_path:  # Only create directory if it's not empty
                            os.makedirs(dir_path, exist_ok=True)
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(str(name).strip())
                        self.state.last_hover_written = True
                        log.info(f"[loadout #{self.ticker_id}] wrote {path}: {name}")
                        
                        # Launch injection directly - skip for base skins
                        if self.state.last_hovered_skin_id == 0:
                            log.info(f"[inject] skipping base skin injection (skinId=0)")
                        elif self.injection_manager:
                            try:
                                log.info(f"[inject] starting injection for: {name}")
                                
                                # Track if we've been in InProgress phase
                                has_been_in_progress = False
                                
                                # Create callback to check if game ended
                                def game_ended_callback():
                                    nonlocal has_been_in_progress
                                    if self.state.phase == "InProgress":
                                        has_been_in_progress = True
                                    # Only stop after we've been in InProgress and then left it
                                    return has_been_in_progress and self.state.phase != "InProgress"
                                
                                # Check if we have a pre-built overlay available
                                champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                                champion_name = self.db.champ_name_by_id.get(champ_id or -1, "") if self.db else ""
                                
                                if champion_name and self.injection_manager.prebuilder:
                                    # Check if pre-built overlay exists for this skin
                                    prebuilt_overlay_path = self.injection_manager.prebuilder.get_prebuilt_overlay_path(champion_name, name)
                                    
                                    if prebuilt_overlay_path and prebuilt_overlay_path.exists():
                                        log.info(f"[inject] Using pre-built overlay for {name}")
                                        # Use pre-built injection (no need for stop_callback since it's instant)
                                        success = self.injection_manager.inject_prebuilt_skin(champion_name, name)
                                    else:
                                        # Pre-built overlay not ready yet, wait briefly for completion
                                        log.info(f"[inject] Pre-built overlay not ready for {name}, waiting for completion...")
                                        if self.injection_manager.prebuilder.wait_for_prebuild_completion(champion_name, timeout=2.0):
                                            # Check again after waiting
                                            prebuilt_overlay_path = self.injection_manager.prebuilder.get_prebuilt_overlay_path(champion_name, name)
                                            if prebuilt_overlay_path and prebuilt_overlay_path.exists():
                                                log.info(f"[inject] Pre-built overlay ready after wait, using for {name}")
                                                success = self.injection_manager.inject_prebuilt_skin(champion_name, name)
                                            else:
                                                log.info(f"[inject] Pre-built overlay still not available for {name}, using traditional injection")
                                                success = self.injection_manager.inject_skin_immediately(name, stop_callback=game_ended_callback)
                                        else:
                                            log.info(f"[inject] Pre-building timeout for {name}, using traditional injection")
                                            success = self.injection_manager.inject_skin_immediately(name, stop_callback=game_ended_callback)
                                else:
                                    log.info(f"[inject] No champion name or pre-builder available, using traditional injection for {name}")
                                    # Fallback to traditional injection
                                    success = self.injection_manager.inject_skin_immediately(name, stop_callback=game_ended_callback)
                                if success:
                                    log.info(f"[inject] successfully injected: {name}")
                                    # Stop overlay process after successful injection
                                    try:
                                        self.injection_manager.stop_overlay_process()
                                        log.info("Injection: Stopped overlay process after successful injection")
                                    except Exception as e:
                                        log.warning(f"Injection: Failed to stop overlay process: {e}")
                                else:
                                    log.error(f"[inject] failed to inject: {name}")
                            except Exception as e:
                                log.error(f"[inject] injection error: {e}")
                        else:
                            log.warning(f"[inject] no injection manager available")
                    except Exception as e:
                        log.warning(f"[loadout #{self.ticker_id}] write failed: {e}")

            if remain_ms <= 0:
                break
            time.sleep(1.0 / float(self.hz))
        
        # End of ticker: only release if we're still the current ticker
        if getattr(self.state, 'current_ticker', 0) == self.ticker_id:
            self.state.loadout_countdown_active = False
