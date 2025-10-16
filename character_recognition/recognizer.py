#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Character recognizer for pattern matching-based text recognition.

Replaces OCR with template matching approach using character segmentation
and normalized cross-correlation matching.
"""

import time
import numpy as np
import cv2
from typing import Optional
from .template_manager import TemplateManager
from .segmentation import segment_image
from .matcher import match_character
from utils.logging import get_logger

log = get_logger()


class CharacterRecognizer:
    """Character recognition using pattern matching with template database."""
    
    def __init__(self, templates_dir: str = "character_recognition/templates/english", 
                 measure_time: bool = True):
        """
        Initialize character recognizer.
        
        Args:
            templates_dir: Path to directory containing character templates
            measure_time: Enable timing measurements for recognition operations
        """
        self.templates_dir = templates_dir
        self.measure_time = measure_time
        self.template_manager = None
        self.cache = {}  # Cache for recognition results
        
        # Timing statistics
        self.last_recognition_time = 0.0
        self.avg_recognition_time = 0.0
        self.recognition_call_count = 0
        
        # Initialize template manager
        self._initialize_templates()
    
    def _initialize_templates(self):
        """Initialize template manager and load templates."""
        try:
            self.template_manager = TemplateManager(self.templates_dir)
            
            if self.template_manager.loaded:
                stats = self.template_manager.get_statistics()
                log.info(f"Character recognizer initialized: {stats['character_count']} characters, "
                        f"{stats['total_templates']} templates")
                
                if self.measure_time:
                    log.info("⏱️  Character recognition timing measurements: ENABLED")
            else:
                log.warning("No templates loaded - character recognition will not work")
                
        except Exception as e:
            log.error(f"Failed to initialize character recognizer: {e}")
            self.template_manager = None
    
    def recognize(self, img: np.ndarray) -> str:
        """
        Recognize text in image using pattern matching.
        
        Args:
            img: Input image (grayscale or BGR)
            
        Returns:
            Recognized text string
        """
        start_time = time.perf_counter() if self.measure_time else 0
        
        try:
            # Check if template manager is available
            if not self.template_manager or not self.template_manager.loaded:
                log.warning("Template manager not available - returning empty string")
                return ""
            
            # Create a simple hash of the image for caching
            img_hash = hash(img.tobytes())
            
            # Check cache first
            if img_hash in self.cache:
                cached_text = self.cache[img_hash]
                if self.measure_time:
                    cache_time = (time.perf_counter() - start_time) * 1000
                    log.info(f"[CHAR:CACHE-HIT] Instant return: {cache_time:.2f}ms | Text: '{cached_text}'")
                    # Update timing stats for cache hits too
                    self.last_recognition_time = cache_time
                    self.recognition_call_count += 1
                    self.avg_recognition_time = ((self.avg_recognition_time * (self.recognition_call_count - 1)) + cache_time) / self.recognition_call_count
                return cached_text
            
            # Preprocess image for character recognition
            preprocess_start = time.perf_counter() if self.measure_time else 0
            processed_img = self._preprocess_image(img)
            
            if self.measure_time:
                preprocess_time = (time.perf_counter() - preprocess_start) * 1000
                log.debug(f"[CHAR:timing] Image preprocessing: {preprocess_time:.2f}ms")
            
            # Segment image into characters
            segmentation_start = time.perf_counter() if self.measure_time else 0
            characters = segment_image(processed_img)
            
            if self.measure_time:
                segmentation_time = (time.perf_counter() - segmentation_start) * 1000
                log.debug(f"[CHAR:timing] Character segmentation: {segmentation_time:.2f}ms")
            
            if not characters:
                return ""
            
            # Recognize each character
            recognition_start = time.perf_counter() if self.measure_time else 0
            recognized_chars = []
            
            for x_pos, char_img in characters:
                try:
                    # Match character against templates
                    char_label, confidence = match_character(
                        char_img, 
                        self.template_manager,
                        match_threshold=0.6  # Use config value
                    )
                    
                    if char_label:
                        recognized_chars.append((x_pos, char_label, confidence))
                        
                except Exception as e:
                    log.debug(f"Error recognizing character at x={x_pos}: {e}")
                    continue
            
            if self.measure_time:
                recognition_time = (time.perf_counter() - recognition_start) * 1000
                log.debug(f"[CHAR:timing] Character recognition: {recognition_time:.2f}ms")
            
            # Sort characters by x-position and concatenate
            postprocess_start = time.perf_counter() if self.measure_time else 0
            recognized_chars.sort(key=lambda x: x[0])  # Sort by x-position
            text = "".join(char[1] for char in recognized_chars)  # Concatenate labels
            
            if self.measure_time:
                postprocess_time = (time.perf_counter() - postprocess_start) * 1000
                total_time = (time.perf_counter() - start_time) * 1000
                
                # Update statistics
                self.last_recognition_time = total_time
                self.recognition_call_count += 1
                self.avg_recognition_time = ((self.avg_recognition_time * (self.recognition_call_count - 1)) + total_time) / self.recognition_call_count
                
                log.debug(f"[CHAR:timing] Text postprocessing: {postprocess_time:.2f}ms")
                log.info(f"[CHAR:timing] Total recognition time: {total_time:.2f}ms | Avg: {self.avg_recognition_time:.2f}ms | Count: {self.recognition_call_count}")
                if text:
                    log.info(f"[CHAR:timing] Detected text: '{text}'")
            
            # Cache the result
            if text and len(text.strip()) > 0:
                self.cache[img_hash] = text
                # Limit cache size to prevent memory issues
                if len(self.cache) > 100:
                    # Remove oldest entry
                    oldest_key = next(iter(self.cache))
                    del self.cache[oldest_key]
            
            return text
            
        except Exception as e:
            # Log error but don't crash - return empty string to continue recognition loop
            if not hasattr(self, '_error_logged'):
                log.warning(f"Character recognition error (will continue): {e}")
                self._error_logged = True
            return ""
    
    def _preprocess_image(self, img: np.ndarray) -> np.ndarray:
        """
        Preprocess image for character recognition.
        
        Args:
            img: Input image
            
        Returns:
            Preprocessed binary image
        """
        # Convert to grayscale if needed
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Apply threshold to create binary image
        _, binary_img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
        
        # Apply morphological operations to clean up the image
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        binary_img = cv2.morphologyEx(binary_img, cv2.MORPH_CLOSE, kernel)
        
        return binary_img
    
    def get_timing_stats(self) -> dict:
        """
        Get recognition timing statistics.
        
        Returns:
            Dictionary with timing statistics:
            - last_recognition_time: Time of last recognition operation (ms)
            - avg_recognition_time: Average recognition operation time (ms)
            - recognition_call_count: Total number of recognition calls
        """
        return {
            'last_recognition_time': self.last_recognition_time,
            'avg_recognition_time': self.avg_recognition_time,
            'recognition_call_count': self.recognition_call_count,
            'measure_time': self.measure_time
        }
    
    def reset_timing_stats(self):
        """Reset recognition timing statistics."""
        self.last_recognition_time = 0.0
        self.avg_recognition_time = 0.0
        self.recognition_call_count = 0
        log.info("[CHAR:timing] Timing statistics reset")
    
    def reload_templates(self):
        """Reload character templates from disk."""
        if self.template_manager:
            self.template_manager.reload_templates()
            log.info("Character templates reloaded")
        else:
            log.warning("Template manager not available - cannot reload templates")
    
    def get_template_stats(self) -> dict:
        """
        Get template database statistics.
        
        Returns:
            Dictionary with template statistics
        """
        if self.template_manager:
            return self.template_manager.get_statistics()
        else:
            return {'loaded': False, 'total_templates': 0, 'character_count': 0}
    
    def add_template(self, character: str, template_img: np.ndarray, 
                    filename: str = None) -> bool:
        """
        Add a new template for a character.
        
        Args:
            character: Character label
            template_img: Template image
            filename: Optional filename to save as
            
        Returns:
            True if template was added successfully
        """
        if self.template_manager:
            return self.template_manager.add_template(character, template_img, filename)
        else:
            log.warning("Template manager not available - cannot add template")
            return False
