#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image processing utilities for OCR
Hardcoded ROI is used - no auto-detection needed
"""

import numpy as np
import cv2
from constants import (
    WHITE_TEXT_HSV_LOWER, WHITE_TEXT_HSV_UPPER,
    IMAGE_UPSCALE_THRESHOLD
)


def prep_for_ocr(bgr: np.ndarray) -> np.ndarray:
    """Preprocess image for OCR - extract white text on dark background"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(WHITE_TEXT_HSV_LOWER, np.uint8), np.array(WHITE_TEXT_HSV_UPPER, np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    mask = cv2.dilate(mask, np.ones((2, 2), np.uint8), 1)
    inv = 255 - mask
    inv = cv2.medianBlur(inv, 3)
    return inv


def preprocess_band_for_ocr(band_bgr: np.ndarray) -> np.ndarray:
    """Preprocess hardcoded ROI for OCR with upscaling if needed"""
    if band_bgr.shape[0] < IMAGE_UPSCALE_THRESHOLD:
        band_bgr = cv2.resize(band_bgr, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    return prep_for_ocr(band_bgr)
