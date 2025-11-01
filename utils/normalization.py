#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simplified text matching utilities for UI API detection
"""

from rapidfuzz.distance import Levenshtein


def levenshtein_score(detected_text: str, skin_text: str) -> float:
    """Calculate a score based on Levenshtein distance.
    Returns a score between 0.0 and 1.0, where 1.0 = perfect match.
    """
    if not detected_text or not skin_text:
        return 0.0
    
    # Direct Levenshtein distance calculation
    distance = Levenshtein.distance(detected_text, skin_text)
    
    # Normalization: score = 1 - (distance / max(len(detected), len(skin)))
    max_len = max(len(detected_text), len(skin_text))
    if max_len == 0:
        return 1.0
    
    score = 1.0 - (distance / max_len)
    return max(0.0, score)  # Ensure score is not negative
