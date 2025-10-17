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
    
    # All l and i related characters are removed (None)
    # Everything else is normalized to base letter
    trans_table = str.maketrans({
        # Remove spaces, apostrophes, and l/i related characters
        ' ': None, "'": None, '1': None, '-': None, '_': None,
        'l': None, 'i': None, 'í': None, 'ì': None, 'î': None, 'ï': None,
        
        
        # Normalize to base letters
        'à': 'a', 'á': 'a', 'â': 'a', 'ã': 'a', 'ä': 'a', 'å': 'a', 'æ': 'a',
        'À': 'A', 'Á': 'A', 'Â': 'A', 'Ã': 'A', 'Ä': 'A', 'Å': 'A', 'Æ': 'A',
        
        'ç': 'c', 'Ç': 'C',
        
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
        
        'ñ': 'n', 'Ñ': 'N',
        
        'ò': 'o', 'ó': 'o', 'ô': 'o', 'õ': 'o', 'ö': 'o', 'ø': 'o', 'œ': 'o',
        'Ò': 'O', 'Ó': 'O', 'Ô': 'O', 'Õ': 'O', 'Ö': 'O', 'Ø': 'O', 'Œ': 'O',
        
        'ù': 'u', 'ú': 'u', 'û': 'u', 'ü': 'u',
        'Ù': 'U', 'Ú': 'U', 'Û': 'U', 'Ü': 'U',
        
        'ý': 'y', 'ÿ': 'y',
        'Ý': 'Y', 'Ÿ': 'Y'
    })

    # Apply transformation and convert to lowercase
    ocr_text_no_spaces = ocr_text.translate(trans_table).lower()
    skin_text_no_spaces = skin_text.translate(trans_table).lower()

    # Levenshtein distance
    distance = Levenshtein.distance(ocr_text_no_spaces, skin_text_no_spaces)
    
    # Normalization: score = 1 - (distance / max(len(ocr), len(skin)))
    max_len = max(len(ocr_text_no_spaces), len(skin_text_no_spaces))
    if max_len == 0:
        return 1.0
    
    score = 1.0 - (distance / max_len)
    return max(0.0, score)  # Ensure score is not negative
