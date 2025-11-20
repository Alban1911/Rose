#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simplified text matching utilities for UI API detection
"""


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Levenshtein distance between two strings.
    
    Args:
        s1: First string
        s2: Second string
        
    Returns:
        The Levenshtein distance (minimum number of single-character edits
        needed to transform s1 into s2)
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    # Create distance matrix
    previous_row = list(range(len(s2) + 1))
    
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, and substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def levenshtein_score(detected_text: str, skin_text: str) -> float:
    """Calculate a score based on Levenshtein distance.
    Returns a score between 0.0 and 1.0, where 1.0 = perfect match.
    """
    if not detected_text or not skin_text:
        return 0.0
    
    # Direct Levenshtein distance calculation
    distance = levenshtein_distance(detected_text, skin_text)
    
    # Normalization: score = 1 - (distance / max(len(detected), len(skin)))
    max_len = max(len(detected_text), len(skin_text))
    if max_len == 0:
        return 1.0
    
    score = 1.0 - (distance / max_len)
    return max(0.0, score)  # Ensure score is not negative
