#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Character recognition backend for compatibility with existing OCR interface.

Provides the same interface as ocr.backend.OCR for drop-in replacement.
"""

from .recognizer import CharacterRecognizer
from utils.logging import get_logger

log = get_logger()


class CharacterRecognitionBackend:
    """Character recognition backend using pattern matching."""
    
    def __init__(self, lang: str = "eng", use_gpu: bool = True, measure_time: bool = True):
        """
        Initialize character recognition backend.
        
        Args:
            lang: Language code (kept for compatibility, only "eng" supported)
            use_gpu: Not used (kept for compatibility)
            measure_time: Enable timing measurements for recognition operations
        """
        self.lang = lang
        self.backend = "character_recognition"
        self.use_gpu = False  # Not applicable for pattern matching
        self.measure_time = measure_time
        
        # Initialize character recognizer
        self.recognizer = CharacterRecognizer(measure_time=measure_time)
        
        # Timing statistics (for compatibility with OCR interface)
        self.last_ocr_time = 0.0
        self.avg_ocr_time = 0.0
        self.ocr_call_count = 0
        
        log.info(f"Character recognition backend initialized (lang: {lang})")
    
    def recognize(self, img) -> str:
        """
        Recognize text in image using character recognition.
        
        Args:
            img: Input image (grayscale or BGR)
            
        Returns:
            Recognized text string
        """
        # Delegate to character recognizer
        text = self.recognizer.recognize(img)
        
        # Update timing stats for compatibility
        self.last_ocr_time = self.recognizer.last_recognition_time
        self.avg_ocr_time = self.recognizer.avg_recognition_time
        self.ocr_call_count = self.recognizer.recognition_call_count
        
        return text
    
    def get_timing_stats(self) -> dict:
        """
        Get recognition timing statistics.
        
        Returns:
            Dictionary with timing statistics (compatible with OCR interface)
        """
        return {
            'last_ocr_time': self.last_ocr_time,
            'avg_ocr_time': self.avg_ocr_time,
            'ocr_call_count': self.ocr_call_count,
            'measure_time': self.measure_time
        }
    
    def reset_timing_stats(self):
        """Reset recognition timing statistics."""
        self.recognizer.reset_timing_stats()
        self.last_ocr_time = 0.0
        self.avg_ocr_time = 0.0
        self.ocr_call_count = 0
        log.info("[CHAR:timing] Timing statistics reset")
    
    def reload_templates(self):
        """Reload character templates from disk."""
        self.recognizer.reload_templates()
    
    def get_template_stats(self) -> dict:
        """
        Get template database statistics.
        
        Returns:
            Dictionary with template statistics
        """
        return self.recognizer.get_template_stats()
    
    def add_template(self, character: str, template_img, filename: str = None) -> bool:
        """
        Add a new template for a character.
        
        Args:
            character: Character label
            template_img: Template image
            filename: Optional filename to save as
            
        Returns:
            True if template was added successfully
        """
        return self.recognizer.add_template(character, template_img, filename)


# Alias for compatibility
OCR = CharacterRecognitionBackend
