#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Template collection tool for character recognition.

Segments preprocessed images into characters and uses OCR to auto-label them,
saving unique character templates for pattern matching recognition.
"""

import os
import cv2
import numpy as np
import hashlib
from pathlib import Path
from typing import List, Tuple, Dict, Set
from .segmentation import segment_image
from .template_manager import TemplateManager
from utils.logging import get_logger

log = get_logger()


class TemplateCollector:
    """Collects character templates using OCR auto-labeling."""
    
    def __init__(self, templates_dir: str = "character_recognition/templates/english",
                 min_confidence: float = 0.5):
        """
        Initialize template collector.
        
        Args:
            templates_dir: Directory to save character templates
            min_confidence: Minimum OCR confidence for character labeling
        """
        self.templates_dir = templates_dir
        self.min_confidence = min_confidence
        self.template_manager = TemplateManager(templates_dir)
        
        # Track collected characters to avoid duplicates
        # Store ONE template per character case (both 'a' and 'A' allowed)
        self.collected_labels: Set[str] = set()
        self.collected_count = 0
        self.duplicate_count = 0
        
        # Initialize OCR for character labeling
        self.ocr = None
        self._initialize_ocr()
    
    def _initialize_ocr(self):
        """Initialize OCR for character labeling."""
        try:
            from ocr.backend import OCR
            self.ocr = OCR(lang="eng", use_gpu=True, measure_time=False)
            log.info("OCR initialized for template collection")
        except Exception as e:
            log.error(f"Failed to initialize OCR for template collection: {e}")
            self.ocr = None
    
    def collect_from_image(self, binary_img: np.ndarray, 
                          image_name: str = "unknown") -> Dict[str, int]:
        """
        Collect character templates from a preprocessed binary image.
        
        Args:
            binary_img: Preprocessed binary image
            image_name: Name of the source image (for logging)
            
        Returns:
            Dictionary with collection statistics
        """
        if self.ocr is None:
            log.warning("OCR not available - cannot collect templates")
            return {'collected': 0, 'duplicates': 0, 'errors': 0}
        
        if binary_img is None or binary_img.size == 0:
            log.warning(f"Empty image provided for template collection: {image_name}")
            return {'collected': 0, 'duplicates': 0, 'errors': 0}
        
        log.info(f"Collecting templates from image: {image_name}")
        
        # First, get the full text using OCR on the whole image for better accuracy
        try:
            full_text = self.ocr.recognize(binary_img)
            if not full_text or len(full_text.strip()) == 0:
                log.debug(f"No text found in image: {image_name}")
                return {'collected': 0, 'duplicates': 0, 'errors': 0}
            
            # Clean the text (remove spaces for mapping)
            clean_text = full_text.strip().replace(" ", "")
            log.debug(f"Full text from OCR: '{full_text}' -> cleaned: '{clean_text}'")
            
        except Exception as e:
            log.error(f"Error getting full text from image {image_name}: {e}")
            return {'collected': 0, 'duplicates': 0, 'errors': 1}
        
        # Segment image into characters
        characters = segment_image(binary_img)
        log.info(f"Found {len(characters)} character segments, OCR text has {len(clean_text)} characters")
        
        collected = 0
        duplicates = 0
        errors = 0
        
        # Map characters by position to OCR text
        for i, (x_pos, char_img) in enumerate(characters):
            try:
                # Use position-based mapping to OCR text for better accuracy
                if i < len(clean_text):
                    char_label = clean_text[i]
                    confidence = 0.9  # High confidence since we used whole-sentence OCR
                    log.debug(f"Character {i+1}: Position {i} -> '{char_label}' from OCR text")
                else:
                    # Fallback to individual character OCR if we have more segments than text
                    char_label, confidence = self._label_character(char_img)
                    log.debug(f"Character {i+1}: Fallback OCR -> '{char_label}' (confidence: {confidence:.3f})")
                
                if char_label and confidence >= self.min_confidence:
                    # Check if we already have a template for this exact character case
                    if char_label in self.collected_labels:
                        duplicates += 1
                        log.debug(f"Character {i+1}: '{char_label}' - Already collected, skipping")
                        continue
                    
                    # Save template (one per character case - both 'a' and 'A' allowed)
                    # Add case prefix to handle Windows case-insensitivity
                    if char_label.isupper():
                        filename = f"upper_{char_label}.png"
                    elif char_label.islower():
                        filename = f"lower_{char_label}.png"
                    else:
                        filename = f"{char_label}.png"
                    success = self.template_manager.add_template(char_label, char_img, filename)
                    
                    if success:
                        self.collected_labels.add(char_label)
                        collected += 1
                        log.debug(f"Character {i+1}: '{char_label}' (confidence: {confidence:.3f}) - Saved")
                    else:
                        errors += 1
                        log.warning(f"Character {i+1}: Failed to save template")
                else:
                    log.debug(f"Character {i+1}: Low confidence ({confidence:.3f}) or no label - Skipped")
                    
            except Exception as e:
                errors += 1
                log.error(f"Error processing character {i+1}: {e}")
                continue
        
        # Update statistics
        self.collected_count += collected
        self.duplicate_count += duplicates
        
        stats = {
            'collected': collected,
            'duplicates': duplicates,
            'errors': errors,
            'total_collected': self.collected_count,
            'total_duplicates': self.duplicate_count
        }
        
        log.info(f"Collection complete: {collected} new, {duplicates} duplicates, {errors} errors")
        return stats
    
    def _label_character(self, char_img: np.ndarray) -> Tuple[str, float]:
        """
        Use OCR to label a character image.
        
        Args:
            char_img: Character image to label
            
        Returns:
            Tuple of (label, confidence)
        """
        try:
            # Ensure character image is properly sized for OCR
            char_img = self._prepare_char_for_ocr(char_img)
            
            # Use OCR to recognize the character
            text = self.ocr.recognize(char_img)
            
            if not text or len(text.strip()) == 0:
                return None, 0.0
            
            # Clean up the text (remove spaces, take first character)
            clean_text = text.strip().replace(" ", "")
            if len(clean_text) == 0:
                return None, 0.0
            
            # Take the first character as the label
            label = clean_text[0]
            
            # Keep case - uppercase and lowercase have different visual patterns
            # Clean the label to make it filesystem-safe
            # Remove or replace invalid characters for filenames
            import re
            original_label = label
            label = re.sub(r'[<>:"/\\|?*]', '_', label)
            label = label.strip()
            
            # If label is empty or just special characters, use a fallback
            if not label or label == '_':
                label = 'UNKNOWN'
            
            # Debug logging for character labeling
            if original_label != label:
                log.debug(f"Character label cleaned: '{original_label}' -> '{label}'")
            
            # For now, use a default confidence since EasyOCR doesn't provide per-character confidence
            # In a real implementation, you might want to use a different OCR engine that provides this
            confidence = 0.8  # Default confidence for single character recognition
            
            return label, confidence
            
        except Exception as e:
            log.debug(f"Error labeling character: {e}")
            return None, 0.0
    
    def _prepare_char_for_ocr(self, char_img: np.ndarray) -> np.ndarray:
        """
        Prepare character image for OCR recognition.
        
        Args:
            char_img: Character image
            
        Returns:
            Prepared character image
        """
        # Ensure image is grayscale
        if len(char_img.shape) == 3:
            char_img = cv2.cvtColor(char_img, cv2.COLOR_BGR2GRAY)
        
        # Ensure binary image
        _, char_img = cv2.threshold(char_img, 127, 255, cv2.THRESH_BINARY)
        
        # Add padding around the character
        padding = 10
        h, w = char_img.shape
        padded = np.zeros((h + 2*padding, w + 2*padding), dtype=np.uint8)
        padded[padding:h+padding, padding:w+padding] = char_img
        
        # Resize to minimum size for better OCR accuracy
        min_size = 32
        if padded.shape[0] < min_size or padded.shape[1] < min_size:
            scale = max(min_size / padded.shape[0], min_size / padded.shape[1])
            new_h = int(padded.shape[0] * scale)
            new_w = int(padded.shape[1] * scale)
            padded = cv2.resize(padded, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        
        return padded
    
    def collect_from_directory(self, input_dir: str, 
                             file_pattern: str = "*.png") -> Dict[str, int]:
        """
        Collect templates from all images in a directory.
        
        Args:
            input_dir: Directory containing preprocessed images
            file_pattern: File pattern to match (default: "*.png")
            
        Returns:
            Dictionary with collection statistics
        """
        input_path = Path(input_dir)
        if not input_path.exists():
            log.error(f"Input directory does not exist: {input_dir}")
            return {'collected': 0, 'duplicates': 0, 'errors': 0}
        
        image_files = list(input_path.glob(file_pattern))
        if not image_files:
            log.warning(f"No image files found in: {input_dir}")
            return {'collected': 0, 'duplicates': 0, 'errors': 0}
        
        log.info(f"Collecting templates from {len(image_files)} images in: {input_dir}")
        
        total_collected = 0
        total_duplicates = 0
        total_errors = 0
        
        for image_file in image_files:
            try:
                # Load image
                img = cv2.imread(str(image_file), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    log.warning(f"Failed to load image: {image_file}")
                    total_errors += 1
                    continue
                
                # Collect templates from this image
                stats = self.collect_from_image(img, image_file.name)
                total_collected += stats['collected']
                total_duplicates += stats['duplicates']
                total_errors += stats['errors']
                
            except Exception as e:
                log.error(f"Error processing image {image_file}: {e}")
                total_errors += 1
                continue
        
        log.info(f"Directory collection complete: {total_collected} new templates, "
                f"{total_duplicates} duplicates, {total_errors} errors")
        
        return {
            'collected': total_collected,
            'duplicates': total_duplicates,
            'errors': total_errors,
            'total_collected': self.collected_count,
            'total_duplicates': self.duplicate_count
        }
    
    def get_collection_stats(self) -> Dict[str, int]:
        """
        Get template collection statistics.
        
        Returns:
            Dictionary with collection statistics
        """
        return {
            'total_collected': self.collected_count,
            'total_duplicates': self.duplicate_count,
            'unique_labels': len(self.collected_labels),
            'templates_in_db': self.template_manager.get_template_count()
        }
    
    def clear_collection_stats(self):
        """Clear collection statistics."""
        self.collected_labels.clear()
        self.collected_count = 0
        self.duplicate_count = 0
        log.info("Collection statistics cleared")
    
    def reload_templates(self):
        """Reload templates from disk."""
        self.template_manager.reload_templates()
        log.info("Templates reloaded from disk")
