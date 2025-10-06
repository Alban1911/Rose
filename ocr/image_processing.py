#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image processing utilities for OCR
"""

import numpy as np
import cv2
from typing import Tuple
from constants import (
    BAND_CENTER_PCT, BAND_SPAN_PCT, BAND_CANDIDATES_STEPS, BAND_MIN_HEIGHT,
    TEXT_DETECTION_LEFT_PCT, TEXT_DETECTION_RIGHT_PCT,
    WHITE_TEXT_HSV_LOWER, WHITE_TEXT_HSV_UPPER,
    CANNY_THRESHOLD_LOW, CANNY_THRESHOLD_HIGH,
    SCORE_WEIGHT_MASK, SCORE_WEIGHT_EDGES, IMAGE_UPSCALE_THRESHOLD
)


def band_candidates(h: int, centre_pct: Tuple[float, float] = BAND_CENTER_PCT, 
                   span: Tuple[float, float] = BAND_SPAN_PCT, steps: int = BAND_CANDIDATES_STEPS) -> list:
    """Generate band candidates for text detection"""
    height = max(4.0, min(centre_pct[1], 12.0))
    ts = np.linspace(span[0], span[1] - height, steps)
    return [(float(t), float(t + height)) for t in ts]


def score_white_text(bgr_band: np.ndarray) -> float:
    """Score band for white text content"""
    hsv = cv2.cvtColor(bgr_band, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(WHITE_TEXT_HSV_LOWER, np.uint8), np.array(WHITE_TEXT_HSV_UPPER, np.uint8))
    g = cv2.cvtColor(bgr_band, cv2.COLOR_BGR2GRAY)
    e = cv2.Canny(g, CANNY_THRESHOLD_LOW, CANNY_THRESHOLD_HIGH)
    return SCORE_WEIGHT_MASK * (mask > 0).mean() + SCORE_WEIGHT_EDGES * (e > 0).mean()


def choose_band(frame: np.ndarray) -> Tuple[int, int, int, int]:
    """Choose the best band for text detection"""
    h, w = frame.shape[:2]
    Lpct, Rpct = TEXT_DETECTION_LEFT_PCT, TEXT_DETECTION_RIGHT_PCT
    x1 = int(w * (Lpct / 100.0))
    x2 = int(w * (Rpct / 100.0))
    best = (-1.0, 0, 0)
    
    for T, B in band_candidates(h, BAND_CENTER_PCT, BAND_SPAN_PCT, steps=BAND_CANDIDATES_STEPS):
        y1 = int(h * (T / 100.0))
        y2 = int(h * (B / 100.0))
        if y2 - y1 < BAND_MIN_HEIGHT: 
            continue
        sc = score_white_text(frame[y1:y2, x1:x2])
        if sc > best[0]: 
            best = (sc, y1, y2)
    
    y1, y2 = (int(h * 0.58), int(h * 0.66)) if best[0] < 0 else (best[1], best[2])
    return x1, y1, x2, y2


def prep_for_ocr(bgr: np.ndarray) -> np.ndarray:
    """Preprocess image for OCR"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(WHITE_TEXT_HSV_LOWER, np.uint8), np.array(WHITE_TEXT_HSV_UPPER, np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    mask = cv2.dilate(mask, np.ones((2, 2), np.uint8), 1)
    inv = 255 - mask
    inv = cv2.medianBlur(inv, 3)
    return inv


def preprocess_band_for_ocr(band_bgr: np.ndarray) -> np.ndarray:
    """Preprocess band for OCR with upscaling if needed"""
    if band_bgr.shape[0] < IMAGE_UPSCALE_THRESHOLD:
        band_bgr = cv2.resize(band_bgr, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    return prep_for_ocr(band_bgr)
