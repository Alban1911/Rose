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
        """Run OCR and match against database"""
        txt = self.ocr.recognize(band_bin)
        
        # Save EXACT OCR text (normalized spaces)
        try:
            cleaned_txt = re.sub(r"\s+", " ", txt.replace("\u00A0", " ").strip())
        except Exception:
            cleaned_txt = txt.strip()
        
        prev_txt = getattr(self.state, 'ocr_last_text', None)
        self.state.ocr_last_text = cleaned_txt
        
        if cleaned_txt and cleaned_txt != prev_txt:
            log.debug(f"[ocr:text] {cleaned_txt}")
        
        if not txt or not any(c.isalpha() for c in txt):
            return
        
        # Keep exact OCR (cleaned of multiple spaces) for writing
        try:
            cleaned_txt = re.sub(r"\s+", " ", txt.replace("\u00A0", " ").strip())
            self.state.ocr_last_text = cleaned_txt
        except Exception:
            self.state.ocr_last_text = txt.strip()
        
        norm_txt = normalize_text(txt)
        champ_id = self.state.hovered_champ_id or self.state.locked_champ_id
        
        # Try multi-language database first
        entry = None
        if self.multilang_db:
            entry = self.multilang_db.find_skin_by_text(txt, champ_id)
        
        # Fallback to original database if multi-language fails
        if not entry:
            pairs = self.db.normalized_entries(champ_id) or []
            skin_pairs = [(e, nk) for (e, nk) in pairs if e.kind == "skin"]
            champ_pairs = [(e, nk) for (e, nk) in pairs if e.kind == "champion"]
            
            # Combine skins and champions for search
            all_pairs = skin_pairs + champ_pairs
            entries = None
            labels = None
            
            if champ_id and all_pairs:
                entries, labels = zip(*all_pairs)
            else:
                if not all_pairs and champ_id:
                    slug = self.db.slug_by_id.get(champ_id)
                    if slug:
                        self.db._ensure_champ(slug, champ_id)
                        pairs = self.db.normalized_entries(champ_id) or []
                        skin_pairs = [(e, nk) for (e, nk) in pairs if e.kind == "skin"]
                        champ_pairs = [(e, nk) for (e, nk) in pairs if e.kind == "champion"]
                        all_pairs = skin_pairs + champ_pairs
                        if all_pairs:
                            entries, labels = zip(*all_pairs)
            
            if not entries: 
                return
        
        # Handle scoring based on whether we found a multi-language match
        if entry:
            # Multi-language database found a match
            score = 0.9  # High confidence for multi-language matches
            # log.debug(f"[debug] Multi-language match found: '{norm_txt}' -> '{entry.key}' (score: {score:.3f})")  # Disabled for cleaner logs
        else:
            # Use our Levenshtein distance-based scoring system for fallback
            best_score = 0.0
            best_idx = None
            best_entry = None
            
            for i, (entry, label) in enumerate(all_pairs):
                score = levenshtein_score(norm_txt, label)
                if score > best_score:
                    best_score = score
                    best_idx = i
                    best_entry = entry
            
            if best_idx is None or best_score < self.args.min_conf:
                # log.debug(f"[debug] No match found for OCR text: '{norm_txt}' (best score: {best_score:.3f} < {self.args.min_conf})")  # Disabled for cleaner logs
                return
            
            idx = best_idx
            score = best_score
            entry = best_entry
            # log.debug(f"[debug] Fallback match found: '{norm_txt}' -> '{labels[idx]}' (levenshtein score: {score:.3f})")  # Disabled for cleaner logs
        
        # If it's a champion (base skin), verify it's an exact match
        if entry.kind == "champion":
            champ_nm = self.db.champ_name_by_id.get(champ_id or -1, "")
            if champ_nm:
                champ_tokens = set(normalize_text(champ_nm).split())
                txt_tokens = set(norm_txt.split())
                # For base skins, we want an exact match
                if not (champ_tokens == txt_tokens or 
                       (champ_tokens and txt_tokens.issubset(champ_tokens) and len(norm_txt.split()) == len(champ_tokens))):
                    # log.debug(f"[debug] Champion match not exact enough: '{norm_txt}' vs '{champ_nm}'")  # Disabled for cleaner logs
                    return
        elif entry.kind != "skin":
            return
        
        if entry.key != self.last_key:
            # Use multi-language database if available
            if self.multilang_db:
                english_champ, english_full = self.multilang_db.get_english_name(entry)
                
                if entry.kind == "champion":
                    # For base skins, use English champion name
                    log.info(f"[hover:skin] {english_champ} (skinId=0, champ={entry.champ_slug}, score={score:.3f})")
                    self.state.last_hovered_skin_key = english_champ
                    self.state.last_hovered_skin_id = 0  # 0 = base skin
                    self.state.last_hovered_skin_slug = entry.champ_slug
                else:
                    # For normal skins, use English skin name
                    log.info(f"[hover:skin] {english_full} (skinId={entry.skin_id}, champ={entry.champ_slug}, score={score:.3f})")
                    self.state.last_hovered_skin_key = english_full
                    self.state.last_hovered_skin_id = entry.skin_id
                    self.state.last_hovered_skin_slug = entry.champ_slug
            else:
                # Fallback to original behavior
                if entry.kind == "champion":
                    # For base skins, use champion name
                    champ_name = self.db.champ_name_by_id.get(entry.champ_id, entry.key)
                    log.info(f"[hover:skin] {champ_name} (skinId=0, champ={entry.champ_slug}, score={score:.3f})")
                    self.state.last_hovered_skin_key = champ_name
                    self.state.last_hovered_skin_id = 0  # 0 = base skin
                    self.state.last_hovered_skin_slug = entry.champ_slug
                else:
                    # For normal skins, use skin name
                    disp = self.db.skin_name_by_id.get(entry.skin_id) or entry.key
                    log.info(f"[hover:skin] {disp} (skinId={entry.skin_id}, champ={entry.champ_slug}, score={score:.3f})")
                    self.state.last_hovered_skin_key = disp
                    self.state.last_hovered_skin_id = entry.skin_id
                    self.state.last_hovered_skin_slug = entry.champ_slug
            self.last_key = entry.key
