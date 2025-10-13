#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR skin detection thread - Optimized version with hardcoded ROI
"""

import os
import time
import threading
from pathlib import Path
from typing import Optional, Tuple
import numpy as np
import cv2
from ocr.backend import OCR
from ocr.image_processing import preprocess_band_for_ocr
from database.name_db import NameDB
from state.shared_state import SharedState
from lcu.client import LCU
from utils.normalization import levenshtein_score
from utils.logging import get_logger
from utils.window_utils import find_league_window_rect, get_league_window_client_size, is_league_window_active
from utils.chroma_selector import get_chroma_selector
from config import *

log = get_logger()


class OCRSkinThread(threading.Thread):
    """OCR thread: Optimized with hardcoded ROI proportions"""
    
    def __init__(self, state: SharedState, db: NameDB, ocr: OCR, args, lcu: Optional[LCU] = None, skin_scraper=None):
        super().__init__(daemon=True)
        self.state = state
        self.db = db
        self.skin_scraper = skin_scraper
        self.ocr = ocr
        self.args = args
        self.lcu = lcu
        self.monitor_index = 0 if args.monitor == "all" else 1
        self.diff_threshold = args.diff_threshold
        self.burst_ms = args.burst_ms
        self.min_ocr_interval = args.min_ocr_interval
        self.second_shot_ms = args.second_shot_ms
        
        # OCR state variables (reset on phase change)
        self.last_small = None
        self.last_key = None
        self.motion_until = 0.0
        self.last_ocr_t = 0.0
        self.second_shot_at = 0.0
        self.next_emit = time.time()
        self.emit_dt = (1.0 / max(1.0, args.idle_hz)) if args.idle_hz > 0 else None
        
        # Window state (no cache needed - client area detection is fast)
        self.last_window_log_time = 0.0
        self.window_log_interval = OCR_WINDOW_LOG_INTERVAL
        
        # Last skin shown for chroma panel (to avoid re-showing)
        self.last_chroma_panel_skin_id = None
        
        # Track skin for fade animation
        self.last_detected_skin_id = None
        self.first_skin_detected = False
        self.last_skin_had_chromas = False
        self.last_skin_was_owned = False
    
    def _trigger_chroma_fade(self, skin_id: int, current_has_chromas: bool, current_is_owned: bool):
        """Trigger chroma button and icon fade animations based on state transitions"""
        try:
            # Check if skin actually changed
            if skin_id == self.last_detected_skin_id:
                return  # Same skin, no fade needed
            
            # Update last detected skin
            previous_skin_id = self.last_detected_skin_id
            self.last_detected_skin_id = skin_id
            
            from utils.chroma_selector import get_chroma_selector
            chroma_selector = get_chroma_selector()
            if chroma_selector and chroma_selector.panel and chroma_selector.panel.reopen_button:
                button = chroma_selector.panel.reopen_button
                
                if not self.first_skin_detected:
                    # First skin of the session
                    log.info(f"[CHROMA] First skin detected - no button animation")
                    self.first_skin_detected = True
                    self.last_skin_had_chromas = current_has_chromas
                    self.last_skin_was_owned = current_is_owned
                    
                    # For UnownedFrame: only fade in if first skin is NOT owned
                    if not current_is_owned:
                        log.info(f"[CHROMA] UnownedFrame: First skin NOT owned - fade in")
                        button.unowned_frame_fade_owned_to_not_owned_first()
                    else:
                        log.debug(f"[CHROMA] UnownedFrame: First skin owned - stay at 0%")
                else:
                    # Determine button animation based on chroma state transition
                    prev_had_chromas = self.last_skin_had_chromas
                    curr_has_chromas = current_has_chromas
                    
                    if prev_had_chromas and curr_has_chromas:
                        # Has → Has: fade out 50ms, wait 100ms, fade in 50ms
                        log.info(f"[CHROMA] Button: Chromas → Chromas: fade out → wait → fade in")
                        button.fade_has_to_has()
                    elif not prev_had_chromas and curr_has_chromas:
                        # None → Has: wait 150ms, fade in 50ms
                        log.info(f"[CHROMA] Button: No chromas → Chromas: wait → fade in")
                        button.fade_none_to_has()
                    elif prev_had_chromas and not curr_has_chromas:
                        # Has → None: fade out 50ms
                        log.info(f"[CHROMA] Button: Chromas → No chromas: fade out")
                        button.fade_has_to_none()
                    else:
                        # None → None: nothing
                        log.debug(f"[CHROMA] Button: No chromas → No chromas: no animation")
                    
                    self.last_skin_had_chromas = curr_has_chromas
                    
                    # Determine UnownedFrame animation based on ownership state transition
                    # INVERTED LOGIC: UnownedFrame (Lock + OutlineGold) shows when NOT owned, hides when owned
                    prev_was_owned = self.last_skin_was_owned
                    curr_is_owned = current_is_owned
                    
                    if not prev_was_owned and not curr_is_owned:
                        # Unowned → Unowned: fade out 50ms, wait 100ms, fade in 50ms
                        log.info(f"[CHROMA] UnownedFrame: Unowned → Unowned: fade out → wait → fade in")
                        button.unowned_frame_fade_not_owned_to_not_owned()
                    elif prev_was_owned and not curr_is_owned:
                        # Owned → Unowned: wait 150ms, fade in 50ms
                        log.info(f"[CHROMA] UnownedFrame: Owned → Unowned: wait → fade in (show lock)")
                        button.unowned_frame_fade_owned_to_not_owned()
                    elif not prev_was_owned and curr_is_owned:
                        # Unowned → Owned: fade out 50ms
                        log.info(f"[CHROMA] UnownedFrame: Unowned → Owned: fade out (hide lock)")
                        button.unowned_frame_fade_not_owned_to_owned()
                    else:
                        # Owned → Owned: nothing
                        log.debug(f"[CHROMA] UnownedFrame: Owned → Owned: no animation")
                    
                    self.last_skin_was_owned = curr_is_owned
                    
        except Exception as e:
            log.debug(f"[CHROMA] Failed to trigger fade: {e}")
    
    def _should_update_hovered_skin(self, detected_skin_name: str) -> bool:
        """
        Check if we should update the hovered skin based on panel state
        
        Returns False if:
        - Panel was recently closed and detected skin name starts with the base skin name
        
        This prevents re-detecting the same base skin when panel closes and OCR resumes.
        Example: Panel opened for "Demacia Vice Garen", user selects chroma "Demacia Vice Garen Ruby",
        panel closes, OCR detects "Demacia Vice Garen" → skip update to preserve the selected chroma.
        """
        # If panel is currently open, don't update (OCR is paused anyway)
        if getattr(self.state, 'chroma_panel_open', False):
            return False
        
        # Check if we just closed the panel and detected the same base skin
        panel_skin_name = getattr(self.state, 'chroma_panel_skin_name', None)
        if panel_skin_name is not None:
            # Check if detected skin name starts with the base skin name
            # Example: "Demacia Vice Garen" starts with "Demacia Vice Garen" → match
            # Example: "Sanguine Garen" does NOT start with "Demacia Vice Garen" → different
            if detected_skin_name.startswith(panel_skin_name):
                log.debug(f"[ocr] Skipping update - same base skin as panel (base: '{panel_skin_name}', detected: '{detected_skin_name}')")
                # Clear the flag so next detection works normally
                self.state.chroma_panel_skin_name = None
                return False
            else:
                # Different skin - clear the flag and allow update
                self.state.chroma_panel_skin_name = None
        
        return True
    
    def _skin_has_displayable_chromas(self, skin_id: int) -> bool:
        """Check if skin has chromas that should show the button"""
        try:
            chroma_selector = get_chroma_selector()
            if chroma_selector:
                return chroma_selector.should_show_chroma_panel(skin_id)
        except Exception:
            pass
        return False
    
    def _trigger_chroma_panel(self, skin_id: int, skin_name: str):
        """Trigger chroma panel display if skin has any chromas (owned or unowned)"""
        try:
            chroma_selector = get_chroma_selector()
            if not chroma_selector:
                return
            
            # Load owned skins on-demand if not already loaded
            if len(self.state.owned_skin_ids) == 0 and self.lcu and self.lcu.ok:
                try:
                    owned_skins = self.lcu.owned_skins()
                    if owned_skins and isinstance(owned_skins, list):
                        self.state.owned_skin_ids = set(owned_skins)
                        log.debug(f"[CHROMA] Loaded {len(self.state.owned_skin_ids)} owned skins on-demand")
                except Exception as e:
                    log.debug(f"[CHROMA] Failed to load owned skins: {e}")
            
            # Check if user owns the skin
            # Base skins (ending in 000) are ALWAYS owned
            is_base_skin = (skin_id % 1000) == 0
            is_owned = is_base_skin or (skin_id in self.state.owned_skin_ids)
            log.info(f"[CHROMA] Checking skin_id={skin_id}, is_base={is_base_skin}, owned={is_owned}, total_owned={len(self.state.owned_skin_ids)}")
            
            # Always update button when switching skins (don't skip re-showing)
            # This ensures button always shows the correct skin's chromas
            # Button shows if there are ANY chromas (owned or unowned)
            if chroma_selector.should_show_chroma_panel(skin_id):
                log.info(f"[CHROMA] Showing button - skin has chromas")
                self.last_chroma_panel_skin_id = skin_id
                
                # Get champion name for direct path to chromas
                champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                champion_name = self.db.champ_name_by_id.get(champ_id) if champ_id and self.db else None
                
                chroma_selector.show_button_for_skin(skin_id, skin_name, champion_name)
            else:
                # No unowned chromas, hide button
                log.debug(f"[CHROMA] Skin has no unowned chromas, hiding button")
                chroma_selector.hide()
                self.last_chroma_panel_skin_id = None  # Reset to allow re-checking
        except Exception as e:
            log.debug(f"[CHROMA] Error triggering panel: {e}")

    def _get_window_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """Get League window rectangle - CLIENT AREA ONLY"""
        now = time.time()
        
        if self.args.capture == "window" and os.name == "nt":
            # Use our improved window detection
            client_size = get_league_window_client_size(self.args.window_hint)
            if not client_size:
                # Always log when window is not found
                log.debug("[ocr] League window not found")
                return None
            
            width, height = client_size
            
            # For ROI calculations, we need the full screen rectangle of the client area
            # We'll get the window position and add the client area size
            rect = find_league_window_rect(self.args.window_hint)
            if rect:
                left, top, right, bottom = rect
                # Use the client area dimensions we detected
                client_rect = (left, top, left + width, top + height)
                
                # Log window detection only every 1 second
                if (now - self.last_window_log_time) >= self.window_log_interval:
                    # Get window title for debugging
                    window_title = "Unknown"
                    if hasattr(find_league_window_rect, 'window_info') and find_league_window_rect.window_info:
                        for info in find_league_window_rect.window_info:
                            window_title = info.get('title', 'Unknown')
                            break
                    
                    log.debug(f"[ocr] League window found: '{window_title}' - {client_rect[0]},{client_rect[1]},{client_rect[2]},{client_rect[3]} (client size: {width}x{height})")
                    self.last_window_log_time = now
                
                return client_rect
            else:
                log.debug("[ocr] League window not found")
                return None
        else:
            # Monitor capture mode - use monitor dimensions
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[self.monitor_index]
                rect = (monitor["left"], monitor["top"], 
                       monitor["left"] + monitor["width"], 
                       monitor["top"] + monitor["height"])
                
                # Log monitor capture only every 1 second
                if (now - self.last_window_log_time) >= self.window_log_interval:
                    log.debug(f"[ocr] Using monitor capture (mode: {self.args.capture})")
                    self.last_window_log_time = now
                
                return rect
    

    def _get_roi_abs(self) -> Optional[Tuple[int, int, int, int]]:
        """Get absolute ROI coordinates using FIXED proportions - ALWAYS FRESH"""
        # Only search for window when OCR is actually running
        if not self._should_run_ocr():
            return None
            
        # Always recalculate with fixed proportions (to support window resizing)
        window_rect = self._get_window_rect()
        if not window_rect:
            return None
        
        l, t, r, b = window_rect
        width = r - l
        height = b - t
        
        # Proportions are FIXED! Just multiply by current resolution
        roi_abs = (
            int(l + width * ROI_PROPORTIONS['x1_ratio']),
            int(t + height * ROI_PROPORTIONS['y1_ratio']),
            int(l + width * ROI_PROPORTIONS['x2_ratio']),
            int(t + height * ROI_PROPORTIONS['y2_ratio'])
        )
        
        return roi_abs

    def _reset_ocr_state(self):
        """Reset OCR state variables"""
        self.last_small = None
        self.last_key = None
        self.motion_until = 0.0
        self.last_ocr_t = 0.0
        self.second_shot_at = 0.0
        
        # Reset fade animation tracking
        self.last_detected_skin_id = None
        self.first_skin_detected = False
        self.last_skin_had_chromas = False
        self.last_skin_was_owned = False
        
        # Reset logging flags so they can log again in next session
        if hasattr(self, '_ocr_stopped_injection_logged'):
            delattr(self, '_ocr_stopped_injection_logged')
        if hasattr(self, '_ocr_stopped_logged'):
            delattr(self, '_ocr_stopped_logged')
        if hasattr(self, '_ocr_stopped_focus_logged'):
            delattr(self, '_ocr_stopped_focus_logged')

    def _should_run_ocr(self) -> bool:
        """Check if OCR should be running based on conditions"""
        # Must be in ChampSelect
        if self.state.phase != "ChampSelect":
            # Log when window search stops due to phase change
            if not hasattr(self, '_window_search_stopped_logged'):
                log.debug("[ocr] Window search stopped - not in ChampSelect")
                self._window_search_stopped_logged = True
            return False
        
        # Must have locked a champion
        locked_champ = getattr(self.state, "locked_champ_id", None)
        if not locked_champ:
            # Debug: log when we're in ChampSelect but no champion is locked yet
            if hasattr(self, '_debug_no_lock') and self._debug_no_lock:
                pass  # Already logged
            else:
                log.debug(f"[ocr] In ChampSelect but no champion locked yet (locked_champ_id={locked_champ})")
                self._debug_no_lock = True
            return False
        else:
            # Reset debug flag when champion is locked
            if hasattr(self, '_debug_no_lock'):
                delattr(self, '_debug_no_lock')
        
        # Wait after champion lock before starting OCR
        # This gives the UI time to stabilize after the lock
        locked_timestamp = getattr(self.state, "locked_champ_timestamp", 0.0)
        if locked_timestamp > 0:
            time_since_lock = time.time() - locked_timestamp
            if time_since_lock < OCR_CHAMPION_LOCK_DELAY_S:
                # Still within the delay period, don't start OCR yet
                return False
        
        # NEW: Check if League window is active/focused
        if not is_league_window_active():
            # Log once when OCR stops due to window not being focused
            if not hasattr(self, '_ocr_stopped_focus_logged'):
                log.debug("[ocr] OCR stopped - League window not focused (Alt+Tab detected)")
                self._ocr_stopped_focus_logged = True
            return False
        else:
            # Reset the flag when window is focused again
            if hasattr(self, '_ocr_stopped_focus_logged'):
                delattr(self, '_ocr_stopped_focus_logged')
        
        # Stop OCR if injection has been completed
        if getattr(self.state, 'injection_completed', False):
            # Log once when OCR stops due to completed injection
            if not hasattr(self, '_ocr_stopped_injection_logged'):
                log.info("[ocr] OCR stopped - injection completed")
                self._ocr_stopped_injection_logged = True
            return False
        
        # Stop OCR if we're within the injection threshold (configured via SKIN_THRESHOLD_MS_DEFAULT)
        # Check if loadout countdown is active and within threshold
        if (getattr(self.state, 'loadout_countdown_active', False) and 
            hasattr(self.state, 'current_ticker')):
            
            # Get the injection threshold (default 500ms = 0.5 seconds)
            threshold_ms = int(getattr(self.state, 'skin_write_ms', SKIN_THRESHOLD_MS_DEFAULT) or SKIN_THRESHOLD_MS_DEFAULT)
            
            # If we're in the final seconds before injection, stop OCR
            # This prevents unnecessary OCR processing when injection is imminent
            if hasattr(self.state, 'last_remain_ms'):
                remain_ms = getattr(self.state, 'last_remain_ms', 0)
                if remain_ms <= threshold_ms:
                    # Log once when OCR stops due to injection threshold
                    if not hasattr(self, '_ocr_stopped_logged'):
                        log.info(f"[ocr] OCR stopped - injection threshold reached ({remain_ms}ms <= {threshold_ms}ms)")
                        self._ocr_stopped_logged = True
                    return False
                else:
                    # Reset the flag when we're outside the threshold
                    if hasattr(self, '_ocr_stopped_logged'):
                        delattr(self, '_ocr_stopped_logged')
        
        return True

    def run(self):
        """Main OCR loop - Optimized version"""
        import mss  # pyright: ignore[reportMissingImports]
        log.info("OCR: Thread ready (optimized with hardcoded ROI)")
        
        ocr_running = False
        
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[self.monitor_index]
                while not self.state.stop:
                    now = time.time()
                    
                    # Check if we should be running OCR
                    should_run = self._should_run_ocr()
                    
                    # Log state changes
                    if should_run and not ocr_running:
                        log.info("[ocr] OCR running - champion locked in ChampSelect")
                        ocr_running = True
                        # Reset window search stopped flag when OCR starts
                        if hasattr(self, '_window_search_stopped_logged'):
                            delattr(self, '_window_search_stopped_logged')
                    elif not should_run and ocr_running:
                        log.info("[ocr] OCR stopped - waiting for champion lock")
                        ocr_running = False
                        self._reset_ocr_state()
                    
                    if not should_run:
                        time.sleep(OCR_NO_CONDITION_SLEEP)
                        continue
                    
                    # Get ROI coordinates (uses hardcoded proportions)
                    roi_abs = self._get_roi_abs()
                    if not roi_abs:
                        time.sleep(OCR_NO_WINDOW_SLEEP)
                        continue
                    
                    L, T, R, B = roi_abs
                    mon = {"left": L, "top": T, "width": max(8, R - L), "height": max(8, B - T)}
                    
                    try:
                        shot = sct.grab(mon)
                        band = np.array(shot, dtype=np.uint8)[:, :, :3]
                    except Exception:
                        time.sleep(OCR_NO_WINDOW_SLEEP)
                        continue
                    
                    # Process image for OCR
                    band_bin = preprocess_band_for_ocr(band)
                    small = cv2.resize(band_bin, (OCR_SMALL_IMAGE_WIDTH, OCR_SMALL_IMAGE_HEIGHT), interpolation=cv2.INTER_AREA)
                    changed = True
                    
                    # Measure change detection time
                    change_detection_start = time.perf_counter()
                    if self.last_small is not None:
                        diff = np.mean(np.abs(small.astype(np.int16) - self.last_small.astype(np.int16))) / OCR_IMAGE_DIFF_NORMALIZATION
                        changed = diff > self.diff_threshold
                        change_detection_time = (time.perf_counter() - change_detection_start) * 1000
                        
                        if changed:
                            log.info(f"[OCR:change] Image change detected: diff={diff:.4f} (threshold={self.diff_threshold}) | Detection time: {change_detection_time:.2f}ms")
                    
                    self.last_small = small
                    
                    # Run OCR if image changed or in burst mode
                    if changed:
                        self.motion_until = now + (self.burst_ms / 1000.0)
                        if now - self.last_ocr_t >= self.min_ocr_interval:
                            self._run_ocr_and_match(band_bin)
                            self.last_ocr_t = now
                            # Disable second shot to avoid duplicate processing
                            # self.second_shot_at = now + (self.second_shot_ms / 1000.0)
                    
                    # Continue OCR during motion burst
                    if now < self.motion_until and (now - self.last_ocr_t >= self.min_ocr_interval):
                        self._run_ocr_and_match(band_bin)
                        self.last_ocr_t = now
                    
                    # Emit periodic updates if configured
                    if self.emit_dt is not None and now >= self.next_emit and self.last_key:
                        log.info(f"[hover:skin] {self.last_key}")
                        self.next_emit = now + self.emit_dt
                    
                    # Sleep based on motion state
                    if now < self.motion_until:
                        sleep_time = 1.0 / max(OCR_MOTION_SLEEP_DIVISOR, self.args.burst_hz)
                    else:
                        sleep_time = 1.0 / max(OCR_IDLE_SLEEP_MIN, self.args.idle_hz) if self.args.idle_hz > 0 else OCR_IDLE_SLEEP_DEFAULT
                    
                    time.sleep(sleep_time)
        finally:
            pass

    def _run_ocr_and_match(self, band_bin: np.ndarray):
        """Run OCR and match against database using raw Levenshtein distance"""
        from rapidfuzz.distance import Levenshtein
        from datetime import datetime
        
        # Skip if OCR is not yet initialized (waiting for WebSocket connection)
        if self.ocr is None:
            return
        
        # Start timing for total OCR+matching pipeline
        pipeline_start = time.perf_counter()
        
        # ALWAYS log OCR timing (even for cached/duplicate skins)
        ocr_start = time.perf_counter()
        txt = self.ocr.recognize(band_bin)
        ocr_recognition_time = (time.perf_counter() - ocr_start) * 1000
        
        # Log EVERY OCR call to see cache performance
        log.debug(f"[OCR:PERF] Recognition time: {ocr_recognition_time:.2f}ms | Text: '{txt}'")
        
        # DEBUG: Save OCR image to debug folder (if enabled)
        if self.args.debug_ocr:
            try:
                # Use project directory for debug folder (where main.py is)
                project_root = Path(__file__).resolve().parent.parent
                debug_folder = project_root / "ocr_debug"
                if not debug_folder.exists():
                    debug_folder.mkdir(parents=True, exist_ok=True)
                    log.info(f"[ocr:debug] Created debug folder: {debug_folder}")
                
                # Create filename with timestamp and counter
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                counter = getattr(self, '_debug_counter', 0) + 1
                self._debug_counter = counter
                filename = f"ocr_{timestamp}_{counter:04d}.png"
                filepath = str(debug_folder / filename)
                
                # Save the image that was sent to OCR
                success = cv2.imwrite(filepath, band_bin)
                if success:
                    if txt:
                        log.info(f"[ocr:debug] Saved #{counter}: '{txt}'")
                    else:
                        log.info(f"[ocr:debug] Saved #{counter}: (no text detected)")
                else:
                    log.warning(f"[ocr:debug] Failed to write image #{counter}")
            except Exception as e:
                log.warning(f"[ocr:debug] Failed to save debug image: {e}")
        
        # Save raw OCR text for writing
        prev_txt = getattr(self.state, 'ocr_last_text', None)
        self.state.ocr_last_text = txt
        
        if txt and txt != prev_txt:
            log.debug(f"[ocr:text] {txt}")
        
        if not txt or not any(c.isalpha() for c in txt):
            return
        
        champ_id = self.state.hovered_champ_id or self.state.locked_champ_id
        
        # SECURE PIPELINE: Always match against English database for validation
        # Check if OCR is configured for English only (not mixed with other languages)
        is_english_only = (
            self.ocr.lang == "eng" or 
            (hasattr(self.ocr, 'lang_mapping') and self.ocr.lang_mapping.get(self.ocr.lang) == ["en"])
        )
        
        if is_english_only and champ_id:
            # ENGLISH OPTIMIZATION: OCR → English DB → ZIP (secure matching)
            champ_slug = self.db.slug_by_id.get(champ_id)
            log.debug(f"[DEBUG] English pipeline: champ_id={champ_id}, champ_slug={champ_slug}, txt='{txt}'")
            if champ_slug:
                # Load champion skins if not already loaded
                if champ_slug not in self.db.champion_skins:
                    self.db.load_champion_skins_by_id(champ_id)
                
                # Match against English skin names for validation
                best_match = None
                best_similarity = 0.0
                
                available_skins = self.db.champion_skins.get(champ_slug, {})
                log.debug(f"[DEBUG] Available skins for {champ_slug}: {list(available_skins.values())}")
                
                for skin_id, skin_name in available_skins.items():
                    similarity = levenshtein_score(txt, skin_name)
                    if similarity > best_similarity and similarity >= OCR_FUZZY_MATCH_THRESHOLD:
                        best_match = (skin_id, skin_name, similarity)
                        best_similarity = similarity
                
                log.debug(f"[DEBUG] Best match: {best_match}, threshold: {OCR_FUZZY_MATCH_THRESHOLD}")
                if best_match:
                    skin_id, skin_name, similarity = best_match
                    skin_key = f"{champ_slug}_{skin_id}"
                    
                    if skin_key != self.last_key:
                        # Check if we should update (handles panel close + same base skin detection)
                        if not self._should_update_hovered_skin(skin_name):
                            return
                        
                        is_base = (skin_id % 1000 == 0)
                        
                        # ✨ ULTRA VISIBLE SKIN DETECTION ✨
                        log.info("=" * LOG_SEPARATOR_WIDTH)
                        if is_base:
                            log.info(f"🎨 SKIN DETECTED >>> {skin_name.upper()} <<<")
                            log.info(f"   📋 Champion: {champ_slug} | SkinID: 0 (Base) | Match: {similarity:.1%}")
                            log.info(f"   🔍 Source: English DB (direct match)")
                            self.state.last_hovered_skin_id = 0
                        else:
                            log.info(f"🎨 SKIN DETECTED >>> {skin_name.upper()} <<<")
                            log.info(f"   📋 Champion: {champ_slug} | SkinID: {skin_id} | Match: {similarity:.1%}")
                            log.info(f"   🔍 Source: English DB (direct match)")
                            self.state.last_hovered_skin_id = skin_id
                        
                        # Log timing information
                        total_pipeline_time = (time.perf_counter() - pipeline_start) * 1000
                        matching_time = total_pipeline_time - ocr_recognition_time
                        log.info(f"   ⏱️  OCR: {ocr_recognition_time:.2f}ms | Matching: {matching_time:.2f}ms | Total: {total_pipeline_time:.2f}ms")
                        log.info("=" * LOG_SEPARATOR_WIDTH)
                        
                        self.last_key = skin_key
                        self.state.last_hovered_skin_name = skin_name
                        self.state.last_hovered_champ_id = champ_id
                        self.state.last_hovered_champ_slug = champ_slug
                        self.state.last_hovered_skin_id = skin_id
                        self.state.hovered_skin_timestamp = time.time()
                        
                        # Check if current skin has chromas and is owned
                        has_chromas = self._skin_has_displayable_chromas(skin_id)
                        # Base skins (ending in 000) are ALWAYS owned
                        is_base_skin = (skin_id % 1000) == 0
                        is_owned = is_base_skin or (skin_id in self.state.owned_skin_ids)
                        
                        # Show chroma panel if skin has chromas (including base skins)
                        self._trigger_chroma_panel(skin_id, skin_name)
                        
                        # Trigger fade animation AFTER button is shown/hidden
                        self._trigger_chroma_fade(skin_id, has_chromas, is_owned)
                    return
        
        # STANDARD PIPELINE: Use LCU scraper + English DB matching (for non-English)
        elif self.skin_scraper and champ_id:
            # STEP 1: Match OCR text with LCU scraped skins (in client language)
            match_result = self.skin_scraper.find_skin_by_text(txt)
            
            if match_result:
                skin_id, skin_name_client_lang, similarity = match_result
                
                # STEP 2: Get English name from database using skinId
                english_skin_name = self.db.skin_name_by_id.get(skin_id)
                champ_slug = self.db.slug_by_id.get(champ_id)
                
                if english_skin_name and champ_slug:
                    # Create unique key for tracking
                    skin_key = f"{champ_slug}_{skin_id}"
                    
                    if skin_key != self.last_key:
                        # Check if we should update (handles panel close + same base skin detection)
                        if not self._should_update_hovered_skin(english_skin_name):
                            return
                        
                        # Determine if this is base skin
                        is_base = (skin_id % 1000 == 0)  # Base skins have skinId ending in 000
                        
                        # ✨ ULTRA VISIBLE SKIN DETECTION ✨
                        log.info("=" * LOG_SEPARATOR_WIDTH)
                        if is_base:
                            log.info(f"🎨 SKIN DETECTED >>> {english_skin_name.upper()} <<<")
                            log.info(f"   📋 Champion: {champ_slug} | SkinID: 0 (Base) | Match: {similarity:.1%}")
                            log.info(f"   🔍 Source: LCU API + English DB")
                            self.state.last_hovered_skin_id = 0
                        else:
                            log.info(f"🎨 SKIN DETECTED >>> {english_skin_name.upper()} <<<")
                            log.info(f"   📋 Champion: {champ_slug} | SkinID: {skin_id} | Match: {similarity:.1%}")
                            log.info(f"   🔍 Source: LCU API + English DB")
                            self.state.last_hovered_skin_id = skin_id
                        
                        # Log timing information
                        total_pipeline_time = (time.perf_counter() - pipeline_start) * 1000
                        matching_time = total_pipeline_time - ocr_recognition_time
                        log.info(f"   ⏱️  OCR: {ocr_recognition_time:.2f}ms | Matching: {matching_time:.2f}ms | Total: {total_pipeline_time:.2f}ms")
                        log.info("=" * LOG_SEPARATOR_WIDTH)
                        
                        self.state.last_hovered_skin_key = english_skin_name
                        self.state.last_hovered_skin_slug = champ_slug
                        self.last_key = skin_key
                        
                        # Check if current skin has chromas and is owned
                        has_chromas = self._skin_has_displayable_chromas(skin_id)
                        # Base skins (ending in 000) are ALWAYS owned
                        is_base_skin = (skin_id % 1000) == 0
                        is_owned = is_base_skin or (skin_id in self.state.owned_skin_ids)
                        
                        # Show chroma panel if skin has chromas (including base skins)
                        self._trigger_chroma_panel(skin_id, english_skin_name)
                        
                        # Trigger fade animation AFTER button is shown/hidden
                        self._trigger_chroma_fade(skin_id, has_chromas, is_owned)
                else:
                    log.debug(f"[ocr] Matched skin {skin_name_client_lang} (ID: {skin_id}) but not found in English DB")
            
            return
        
        # Fallback to regular database matching (original logic)
        # Get all skin entries for this champion (no normalization)
        pairs = self.db.normalized_entries(champ_id) or []
        if not pairs and champ_id:
            slug = self.db.slug_by_id.get(champ_id)
            if slug:
                self.db._ensure_champ(slug, champ_id)
                pairs = self.db.normalized_entries(champ_id) or []
        
        if not pairs:
            return
        
        # Find best match using raw Levenshtein distance
        best_distance = float('inf')
        best_entry = None
        best_skin_name = None
        
        for entry, normalized_key in pairs:
            if entry.kind not in ["skin", "champion"]:
                continue
                
            # Get the original skin name (not normalized)
            if entry.kind == "skin":
                skin_name = self.db.skin_name_by_id.get(entry.skin_id) or entry.key
            else:  # champion (base skin)
                skin_name = self.db.champ_name_by_id.get(entry.champ_id) or entry.key
            
            # Remove spaces from both texts before comparison
            txt_no_spaces = txt.replace(" ", "")
            skin_name_no_spaces = skin_name.replace(" ", "")
            
            # Calculate raw Levenshtein distance
            distance = Levenshtein.distance(txt_no_spaces, skin_name_no_spaces)
            
            if distance < best_distance:
                best_distance = distance
                best_entry = entry
                best_skin_name = skin_name
        
        # Check if the best match meets confidence threshold
        # Convert distance to a score: 1.0 - (distance / max_length)
        # Use no-spaces versions for consistency with distance calculation
        txt_no_spaces = txt.replace(" ", "")
        best_skin_name_no_spaces = best_skin_name.replace(" ", "") if best_skin_name else ""
        max_len = max(len(txt_no_spaces), len(best_skin_name_no_spaces)) if best_skin_name else 1
        score = 1.0 - (best_distance / max_len) if max_len > 0 else 0.0
        
        if best_entry is None or score < self.args.min_conf:
            return
        
        if best_entry.key != self.last_key:
            # Check if we should update (handles panel close + same base skin detection)
            if not self._should_update_hovered_skin(best_skin_name):
                return
            
            # ✨ ULTRA VISIBLE SKIN DETECTION ✨
            log.info("=" * LOG_SEPARATOR_WIDTH)
            if best_entry.kind == "champion":
                log.info(f"🎨 SKIN DETECTED >>> {best_skin_name.upper()} <<<")
                log.info(f"   📋 Champion: {best_entry.champ_slug} | SkinID: 0 (Base) | Score: {score:.1%}")
                log.info(f"   🔍 Source: Fallback DB (Levenshtein distance: {best_distance})")
                self.state.last_hovered_skin_key = best_skin_name
                self.state.last_hovered_skin_id = 0  # 0 = base skin
                self.state.last_hovered_skin_slug = best_entry.champ_slug
            else:
                log.info(f"🎨 SKIN DETECTED >>> {best_skin_name.upper()} <<<")
                log.info(f"   📋 Champion: {best_entry.champ_slug} | SkinID: {best_entry.skin_id} | Score: {score:.1%}")
                log.info(f"   🔍 Source: Fallback DB (Levenshtein distance: {best_distance})")
                self.state.last_hovered_skin_key = best_skin_name
                self.state.last_hovered_skin_id = best_entry.skin_id
                self.state.last_hovered_skin_slug = best_entry.champ_slug
                
                # Check if current skin has chromas and is owned
                skin_id_for_check = best_entry.skin_id if best_entry.kind == "skin" else 0
                has_chromas = self._skin_has_displayable_chromas(skin_id_for_check)
                # Base skins (ending in 000) are ALWAYS owned
                is_base_skin = (skin_id_for_check % 1000) == 0
                is_owned = is_base_skin or (skin_id_for_check in self.state.owned_skin_ids)
                
                # Show chroma panel if skin has chromas
                self._trigger_chroma_panel(best_entry.skin_id, best_skin_name)
            
            # Trigger fade animation AFTER button is shown/hidden
            self._trigger_chroma_fade(skin_id_for_check, has_chromas, is_owned)
            
            # Log timing information
            total_pipeline_time = (time.perf_counter() - pipeline_start) * 1000
            matching_time = total_pipeline_time - ocr_recognition_time
            log.info(f"   ⏱️  OCR: {ocr_recognition_time:.2f}ms | Matching: {matching_time:.2f}ms | Total: {total_pipeline_time:.2f}ms")
            log.info("=" * LOG_SEPARATOR_WIDTH)
            
            self.last_key = best_entry.key
