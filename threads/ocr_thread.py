#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR skin detection thread - Optimized version with hardcoded ROI
"""

import os
import re
import time
import threading
from typing import Optional, Tuple
import numpy as np
import cv2
from ocr.backend import OCR
from ocr.image_processing import choose_band, preprocess_band_for_ocr
from database.name_db import NameDB
from database.multilang_db import MultiLanguageDB
from state.shared_state import SharedState
from lcu.client import LCU
from utils.normalization import normalize_text, levenshtein_score
from utils.logging import get_logger
from utils.window_capture import find_league_window_rect

log = get_logger()

# ROI proportions - these are constant for League of Legends
# Based on exact measurements: 455px from top, 450px from left/right, 230px from bottom
ROI_PROPORTIONS = {
    'x1_ratio': 0.352,  # 450/1280
    'y1_ratio': 0.632,  # 455/720  
    'x2_ratio': 0.648,  # 830/1280
    'y2_ratio': 0.681   # 490/720
}


class OCRSkinThread(threading.Thread):
    """OCR thread: Optimized with hardcoded ROI proportions"""
    
    def __init__(self, state: SharedState, db: NameDB, ocr: OCR, args, lcu: Optional[LCU] = None, multilang_db: Optional[MultiLanguageDB] = None):
        super().__init__(daemon=True)
        self.state = state
        self.db = db
        self.multilang_db = multilang_db
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
        
        # Window and ROI state (calculated once, cached)
        self.window_rect = None
        self.roi_abs = None  # ROI calculé une seule fois puis caché
        self.window_rect_cache_time = 0.0
        self.window_rect_cache_duration = 30.0  # Cache window rect for 30 seconds

    def _get_window_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """Get League window rectangle with caching"""
        now = time.time()
        
        # Use cached window rect if available and recent
        if (self.window_rect is None or 
            (now - self.window_rect_cache_time) > self.window_rect_cache_duration):
            
            if self.args.capture == "window" and os.name == "nt":
                rect = find_league_window_rect(self.args.window_hint)
                if not rect:
                    log.debug("[ocr] League window not found")
                    return None
                
                self.window_rect = rect
                self.window_rect_cache_time = now
                log.debug(f"[ocr] League window found: {rect[0]},{rect[1]},{rect[2]},{rect[3]} (size: {rect[2]-rect[0]}x{rect[3]-rect[1]})")
            else:
                # Monitor capture mode - use monitor dimensions
                import mss
                with mss.mss() as sct:
                    monitor = sct.monitors[self.monitor_index]
                    self.window_rect = (monitor["left"], monitor["top"], 
                                       monitor["left"] + monitor["width"], 
                                       monitor["top"] + monitor["height"])
                    self.window_rect_cache_time = now
                    log.debug(f"[ocr] Using monitor capture (mode: {self.args.capture})")
        
        return self.window_rect
    

    def _get_roi_abs(self) -> Optional[Tuple[int, int, int, int]]:
        """Get absolute ROI coordinates using FIXED proportions - CACHED"""
        # Si on a déjà le ROI calculé et la fenêtre n'a pas changé, on le retourne
        if self.roi_abs is not None and self.window_rect is not None:
            return self.roi_abs
        
        # Sinon on calcule une seule fois
        window_rect = self._get_window_rect()
        if not window_rect:
            return None
        
        l, t, r, b = window_rect
        width = r - l
        height = b - t
        
        # Les proportions sont FIXES ! On les multiplie juste par la résolution
        self.roi_abs = (
            int(l + width * ROI_PROPORTIONS['x1_ratio']),
            int(t + height * ROI_PROPORTIONS['y1_ratio']),
            int(l + width * ROI_PROPORTIONS['x2_ratio']),
            int(t + height * ROI_PROPORTIONS['y2_ratio'])
        )
        
        log.debug(f"[ocr] ROI calculated ONCE using FIXED proportions: {self.roi_abs}")
        return self.roi_abs

    def _reset_ocr_state(self):
        """Reset OCR state variables"""
        self.last_small = None
        self.last_key = None
        self.motion_until = 0.0
        self.last_ocr_t = 0.0
        self.second_shot_at = 0.0
        # Reset ROI cache aussi (au cas où la fenêtre change)
        self.roi_abs = None
        self.window_rect = None
        self.window_rect_cache_time = 0.0

    def _should_run_ocr(self) -> bool:
        """Check if OCR should be running based on conditions"""
        # Must be in ChampSelect
        if self.state.phase != "ChampSelect":
            return False
        
        # Must have locked a champion
        if not getattr(self.state, "locked_champ_id", None):
            return False
        
        # Check if we're within the injection threshold (2 seconds)
        # This would need to be implemented based on your injection timing logic
        # For now, we'll assume OCR should run until injection happens
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
                    elif not should_run and ocr_running:
                        log.info("[ocr] OCR stopped - waiting for champion lock")
                        ocr_running = False
                        self._reset_ocr_state()
                    
                    if not should_run:
                        time.sleep(0.15)
                        continue
                    
                    # Get ROI coordinates (uses hardcoded proportions)
                    roi_abs = self._get_roi_abs()
                    if not roi_abs:
                        time.sleep(0.05)
                        continue
                    
                    L, T, R, B = roi_abs
                    mon = {"left": L, "top": T, "width": max(8, R - L), "height": max(8, B - T)}
                    
                    try:
                        shot = sct.grab(mon)
                        band = np.array(shot, dtype=np.uint8)[:, :, :3]
                    except Exception:
                        time.sleep(0.05)
                        continue
                    
                    # Process image for OCR
                    band_bin = preprocess_band_for_ocr(band)
                    small = cv2.resize(band_bin, (96, 20), interpolation=cv2.INTER_AREA)
                    changed = True
                    
                    if self.last_small is not None:
                        diff = np.mean(np.abs(small.astype(np.int16) - self.last_small.astype(np.int16))) / 255.0
                        changed = diff > self.diff_threshold
                    
                    self.last_small = small
                    
                    # Run OCR if image changed or in burst mode
                    if changed:
                        self.motion_until = now + (self.burst_ms / 1000.0)
                        if now - self.last_ocr_t >= self.min_ocr_interval:
                            self._run_ocr_and_match(band_bin)
                            self.last_ocr_t = now
                            self.second_shot_at = now + (self.second_shot_ms / 1000.0)
                    
                    # Second shot for better accuracy
                    if self.second_shot_at and now >= self.second_shot_at:
                        if now - self.last_ocr_t >= (self.min_ocr_interval * 0.6):
                            self._run_ocr_and_match(band_bin)
                            self.last_ocr_t = now
                        self.second_shot_at = 0.0
                    
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
                        sleep_time = 1.0 / max(10.0, self.args.burst_hz)
                    else:
                        sleep_time = 1.0 / max(5.0, self.args.idle_hz) if self.args.idle_hz > 0 else 0.1
                    
                    time.sleep(sleep_time)
        finally:
            pass

    def _run_ocr_and_match(self, band_bin: np.ndarray):
        """Run OCR and match against database using raw Levenshtein distance"""
        from rapidfuzz.distance import Levenshtein
        
        txt = self.ocr.recognize(band_bin)
        
        # Save raw OCR text for writing
        prev_txt = getattr(self.state, 'ocr_last_text', None)
        self.state.ocr_last_text = txt
        
        if txt and txt != prev_txt:
            log.debug(f"[ocr:text] {txt}")
        
        if not txt or not any(c.isalpha() for c in txt):
            return
        
        champ_id = self.state.hovered_champ_id or self.state.locked_champ_id
        
        # Use multilang database if available, otherwise fallback to regular database
        if self.multilang_db:
            # Use multilang database with automatic language detection
            entry = self.multilang_db.find_skin_by_text(txt, champ_id)
            if entry:
                # Get English names for the matched entry
                english_champ, english_full = self.multilang_db.get_english_name(entry)
                
                if entry.key != self.last_key:
                    if entry.kind == "champion":
                        log.info(f"[hover:skin] {english_full} (skinId=0, champ={entry.champ_slug}, multilang_match)")
                        self.state.last_hovered_skin_key = english_full
                        self.state.last_hovered_skin_id = 0  # 0 = base skin
                        self.state.last_hovered_skin_slug = entry.champ_slug
                    else:
                        log.info(f"[hover:skin] {english_full} (skinId={entry.skin_id}, champ={entry.champ_slug}, multilang_match)")
                        self.state.last_hovered_skin_key = english_full
                        self.state.last_hovered_skin_id = entry.skin_id
                        self.state.last_hovered_skin_slug = entry.champ_slug
                    self.last_key = entry.key
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
            
            # Calculate raw Levenshtein distance
            distance = Levenshtein.distance(txt, skin_name)
            
            if distance < best_distance:
                best_distance = distance
                best_entry = entry
                best_skin_name = skin_name
        
        # Check if the best match meets confidence threshold
        # Convert distance to a score: 1.0 - (distance / max_length)
        max_len = max(len(txt), len(best_skin_name)) if best_skin_name else 1
        score = 1.0 - (best_distance / max_len) if max_len > 0 else 0.0
        
        if best_entry is None or score < self.args.min_conf:
            return
        
        if best_entry.key != self.last_key:
            # Log with raw distance and score
            if best_entry.kind == "champion":
                log.info(f"[hover:skin] {best_skin_name} (skinId=0, champ={best_entry.champ_slug}, distance={best_distance}, score={score:.3f})")
                self.state.last_hovered_skin_key = best_skin_name
                self.state.last_hovered_skin_id = 0  # 0 = base skin
                self.state.last_hovered_skin_slug = best_entry.champ_slug
            else:
                log.info(f"[hover:skin] {best_skin_name} (skinId={best_entry.skin_id}, champ={best_entry.champ_slug}, distance={best_distance}, score={score:.3f})")
                self.state.last_hovered_skin_key = best_skin_name
                self.state.last_hovered_skin_id = best_entry.skin_id
                self.state.last_hovered_skin_slug = best_entry.champ_slug
            self.last_key = best_entry.key
