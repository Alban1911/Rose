#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR skin detection thread
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


class OCRSkinThread(threading.Thread):
    """OCR thread: locked ROI + burst"""
    
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
        self.last_small = None
        self.last_key = None
        self.motion_until = 0.0
        self.last_ocr_t = 0.0
        self.next_emit = time.time()
        self.emit_dt = (1.0 / max(1.0, args.idle_hz)) if args.idle_hz > 0 else None
        self.roi_abs = None
        self.roi_lock_until = 0.0
        self.roi_lock_s = args.roi_lock_s
        self.second_shot_at = 0.0

    def _calc_band_roi_abs(self, sct, monitor) -> Optional[Tuple[int, int, int, int]]:
        """Calculate band ROI in absolute coordinates"""
        try:
            import mss  # pyright: ignore[reportMissingImports]
            if self.args.capture == "window" and os.name == "nt":
                rect = find_league_window_rect(self.args.window_hint)
                if not rect: 
                    log.debug("[ocr] League window not found, falling back to monitor capture")
                    return None
                l, t, r, b = rect
                log.debug(f"[ocr] League window found: {l},{t},{r},{b} (size: {r-l}x{b-t})")
                mon = {"left": l, "top": t, "width": r - l, "height": b - t}
                full = np.array(sct.grab(mon), dtype=np.uint8)[:, :, :3]
                x1, y1, x2, y2 = choose_band(full)
                roi_abs = (l + x1, t + y1, l + x2, t + y2)
                log.debug(f"[ocr] ROI calculated: {roi_abs}")
                return roi_abs
            else:
                log.debug(f"[ocr] Using monitor capture (mode: {self.args.capture})")
                shot = sct.grab(monitor)
                full = np.array(shot, dtype=np.uint8)[:, :, :3]
                x1, y1, x2, y2 = choose_band(full)
                return (monitor["left"] + x1, monitor["top"] + y1, monitor["left"] + x2, monitor["top"] + y2)
        except Exception as e:
            log.debug(f"[ocr] Error calculating ROI: {e}")
            return None

    def run(self):
        """Main OCR loop"""
        import mss  # pyright: ignore[reportMissingImports]
        log.info("[ocr] thread prêt (actif uniquement en ChampSelect).")
        
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[self.monitor_index]
                while not self.state.stop:
                    now = time.time()
                    if self.state.phase != "ChampSelect":
                        self.last_small = None
                        self.last_key = None
                        self.motion_until = 0.0
                        self.last_ocr_t = 0.0
                        self.roi_abs = None
                        self.roi_lock_until = 0.0
                        time.sleep(0.15)
                        continue
                    
                    if self.roi_abs is None or now >= self.roi_lock_until:
                        roi = self._calc_band_roi_abs(sct, monitor)
                        if roi:
                            self.roi_abs = roi
                            self.roi_lock_until = now + self.roi_lock_s
                        else:
                            time.sleep(0.05)
                            continue
                    
                    L, T, R, B = self.roi_abs
                    mon = {"left": L, "top": T, "width": max(8, R - L), "height": max(8, B - T)}
                    
                    try:
                        shot = sct.grab(mon)
                        band = np.array(shot, dtype=np.uint8)[:, :, :3]
                    except Exception:
                        time.sleep(0.05)
                        continue
                    
                    if not getattr(self.state, "locked_champ_id", None):
                        self.last_small = None
                        self.last_key = None
                        self.motion_until = 0.0
                        self.last_ocr_t = 0.0
                        self.roi_abs = None
                        self.roi_lock_until = 0.0
                        time.sleep(0.10)
                        continue
                    
                    band_bin = preprocess_band_for_ocr(band)
                    small = cv2.resize(band_bin, (96, 20), interpolation=cv2.INTER_AREA)
                    changed = True
                    
                    if self.last_small is not None:
                        diff = np.mean(np.abs(small.astype(np.int16) - self.last_small.astype(np.int16))) / 255.0
                        changed = diff > self.diff_threshold
                    
                    self.last_small = small
                    
                    if changed:
                        self.motion_until = now + (self.burst_ms / 1000.0)
                        if now - self.last_ocr_t >= self.min_ocr_interval:
                            self._run_ocr_and_match(band_bin)
                            self.last_ocr_t = now
                            self.second_shot_at = now + (self.second_shot_ms / 1000.0)
                    
                    if self.second_shot_at and now >= self.second_shot_at:
                        if now - self.last_ocr_t >= (self.min_ocr_interval * 0.6):
                            self._run_ocr_and_match(band_bin)
                            self.last_ocr_t = now
                        self.second_shot_at = 0.0
                    
                    if now < self.motion_until and (now - self.last_ocr_t >= self.min_ocr_interval):
                        self._run_ocr_and_match(band_bin)
                        self.last_ocr_t = now
                    
                    if self.emit_dt is not None and now >= self.next_emit and self.last_key:
                        log.info(f"[hover:skin] {self.last_key}")
                        self.next_emit = now + self.emit_dt
                    
                    time.sleep(1.0 / max(10.0, self.args.burst_hz) if now < self.motion_until else 1.0 / max(5.0, self.args.idle_hz))
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
