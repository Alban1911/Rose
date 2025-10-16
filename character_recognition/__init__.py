#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Character Recognition Module

Pattern matching-based character recognition system that replaces OCR.
Uses template matching with normalized cross-correlation to recognize characters.
"""

from .recognizer import CharacterRecognizer
from .backend import CharacterRecognitionBackend
from .segmentation import segment_image
from .template_manager import TemplateManager
from .matcher import match_character

__all__ = [
    'CharacterRecognizer',
    'CharacterRecognitionBackend', 
    'segment_image',
    'TemplateManager',
    'match_character'
]
