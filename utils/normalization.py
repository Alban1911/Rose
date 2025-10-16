#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Normalization utilities for text matching
"""

import unicodedata
import re
from rapidfuzz.distance import Levenshtein


def normalize_text(s: str) -> str:
    """Normalize text for robust matching while preserving Unicode characters"""
    if not s: 
        return ""
    s = s.replace("\u00A0", " ").replace("：", ":")
    # Use NFC normalization to preserve composed characters (Korean, Greek, etc.)
    s = unicodedata.normalize("NFC", s)
    # Only remove combining marks that are not part of composed characters
    # This preserves Korean jamo composition and Greek accents
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ["Mn", "Me"])
    s = s.lower()
    # Preserve Unicode characters instead of removing them
    # Only remove control characters and excessive whitespace
    s = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", s)  # Remove control characters
    s = re.sub(r"\s+", " ", s).strip()
    return s


def levenshtein_score(ocr_text: str, skin_text: str) -> float:
    """Calculate a score based on normalized Levenshtein distance.
    Returns a score between 0.0 and 1.0, where 1.0 = perfect match.
    """
    if not ocr_text or not skin_text:
        return 0.0
    
    # Remove spaces and convert to lowercase before comparison
    ocr_text_no_spaces = ocr_text.replace(" ", "").replace("l", "").replace("i", "").replace("1", "").replace("'", "").lower()
    skin_text_no_spaces = skin_text.replace(" ", "").replace("l", "").replace("i", "").replace("1", "").replace("'", "").lower()

    # Levenshtein distance
    distance = Levenshtein.distance(ocr_text_no_spaces, skin_text_no_spaces)
    
    # Normalization: score = 1 - (distance / max(len(ocr), len(skin)))
    max_len = max(len(ocr_text_no_spaces), len(skin_text_no_spaces))
    if max_len == 0:
        return 1.0
    
    score = 1.0 - (distance / max_len)
    return max(0.0, score)  # Ensure score is not negative
