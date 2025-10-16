#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pattern matching module for character recognition.

Uses OpenCV's template matching with normalized cross-correlation
to match character images against template database.
"""

import cv2
import numpy as np
from typing import Tuple, Optional
from .template_manager import TemplateManager
from utils.logging import get_logger

log = get_logger()


def match_character(char_img: np.ndarray, 
                   template_manager: TemplateManager,
                   match_threshold: float = 0.6) -> Tuple[Optional[str], float]:
    """
    Match a character image against all templates in the database.
    
    Args:
        char_img: Character image to match (binary image)
        template_manager: TemplateManager instance with loaded templates
        match_threshold: Minimum correlation score to consider a match
        
    Returns:
        Tuple of (best_character_label, confidence_score)
        Returns (None, 0.0) if no match above threshold is found
    """
    if char_img is None or char_img.size == 0:
        log.warning("Empty character image provided to match_character")
        return None, 0.0
    
    if not template_manager.loaded or template_manager.get_template_count() == 0:
        log.warning("No templates loaded in template manager")
        return None, 0.0
    
    # Ensure character image is binary
    if len(char_img.shape) == 3:
        char_img = cv2.cvtColor(char_img, cv2.COLOR_BGR2GRAY)
    
    _, char_img = cv2.threshold(char_img, 127, 255, cv2.THRESH_BINARY)
    
    best_match = None
    best_confidence = 0.0
    
    # Test against all templates
    for character, templates in template_manager.templates.items():
        for template in templates:
            try:
                # Calculate correlation score
                confidence = _calculate_correlation(char_img, template)
                
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = character
                    
            except Exception as e:
                log.debug(f"Error matching character '{character}': {e}")
                continue
    
    # Check if best match meets threshold
    if best_confidence >= match_threshold:
        log.debug(f"Matched character: '{best_match}' (confidence: {best_confidence:.3f})")
        return best_match, best_confidence
    else:
        log.debug(f"No match found above threshold {match_threshold} (best: {best_confidence:.3f})")
        return None, 0.0


def _calculate_correlation(char_img: np.ndarray, template: np.ndarray) -> float:
    """
    Calculate normalized cross-correlation between character and template.
    
    Args:
        char_img: Character image
        template: Template image
        
    Returns:
        Correlation score between 0.0 and 1.0
    """
    try:
        # Resize character image to match template size if needed
        if char_img.shape != template.shape:
            char_img = cv2.resize(char_img, (template.shape[1], template.shape[0]), 
                                interpolation=cv2.INTER_AREA)
        
        # Use normalized cross-correlation
        result = cv2.matchTemplate(char_img, template, cv2.TM_CCOEFF_NORMED)
        
        # Get maximum correlation value
        _, max_val, _, _ = cv2.minMaxLoc(result)
        
        return float(max_val)
        
    except Exception as e:
        log.debug(f"Error calculating correlation: {e}")
        return 0.0


def match_character_with_multiple_scales(char_img: np.ndarray,
                                       template_manager: TemplateManager,
                                       match_threshold: float = 0.6,
                                       scale_factors: list = None) -> Tuple[Optional[str], float]:
    """
    Match character with multiple scale factors for better accuracy.
    
    Args:
        char_img: Character image to match
        template_manager: TemplateManager instance
        match_threshold: Minimum correlation score
        scale_factors: List of scale factors to try (default: [0.8, 0.9, 1.0, 1.1, 1.2])
        
    Returns:
        Tuple of (best_character_label, confidence_score)
    """
    if scale_factors is None:
        scale_factors = [0.8, 0.9, 1.0, 1.1, 1.2]
    
    if char_img is None or char_img.size == 0:
        return None, 0.0
    
    # Ensure character image is binary
    if len(char_img.shape) == 3:
        char_img = cv2.cvtColor(char_img, cv2.COLOR_BGR2GRAY)
    
    _, char_img = cv2.threshold(char_img, 127, 255, cv2.THRESH_BINARY)
    
    best_match = None
    best_confidence = 0.0
    
    # Test against all templates with multiple scales
    for character, templates in template_manager.templates.items():
        for template in templates:
            for scale in scale_factors:
                try:
                    # Scale character image
                    scaled_char = _scale_image(char_img, scale)
                    
                    # Calculate correlation
                    confidence = _calculate_correlation(scaled_char, template)
                    
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = character
                        
                except Exception as e:
                    log.debug(f"Error matching character '{character}' at scale {scale}: {e}")
                    continue
    
    # Check if best match meets threshold
    if best_confidence >= match_threshold:
        log.debug(f"Matched character: '{best_match}' (confidence: {best_confidence:.3f})")
        return best_match, best_confidence
    else:
        log.debug(f"No match found above threshold {match_threshold} (best: {best_confidence:.3f})")
        return None, 0.0


def _scale_image(img: np.ndarray, scale_factor: float) -> np.ndarray:
    """
    Scale image by the given factor.
    
    Args:
        img: Input image
        scale_factor: Scale factor (1.0 = no change)
        
    Returns:
        Scaled image
    """
    if scale_factor == 1.0:
        return img
    
    height, width = img.shape[:2]
    new_width = int(width * scale_factor)
    new_height = int(height * scale_factor)
    
    if new_width <= 0 or new_height <= 0:
        return img
    
    return cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_AREA)


def match_character_with_rotation(char_img: np.ndarray,
                                template_manager: TemplateManager,
                                match_threshold: float = 0.6,
                                rotation_angles: list = None) -> Tuple[Optional[str], float]:
    """
    Match character with multiple rotation angles for better accuracy.
    
    Args:
        char_img: Character image to match
        template_manager: TemplateManager instance
        match_threshold: Minimum correlation score
        rotation_angles: List of rotation angles in degrees (default: [-5, 0, 5])
        
    Returns:
        Tuple of (best_character_label, confidence_score)
    """
    if rotation_angles is None:
        rotation_angles = [-5, 0, 5]
    
    if char_img is None or char_img.size == 0:
        return None, 0.0
    
    # Ensure character image is binary
    if len(char_img.shape) == 3:
        char_img = cv2.cvtColor(char_img, cv2.COLOR_BGR2GRAY)
    
    _, char_img = cv2.threshold(char_img, 127, 255, cv2.THRESH_BINARY)
    
    best_match = None
    best_confidence = 0.0
    
    # Test against all templates with multiple rotations
    for character, templates in template_manager.templates.items():
        for template in templates:
            for angle in rotation_angles:
                try:
                    # Rotate character image
                    rotated_char = _rotate_image(char_img, angle)
                    
                    # Calculate correlation
                    confidence = _calculate_correlation(rotated_char, template)
                    
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = character
                        
                except Exception as e:
                    log.debug(f"Error matching character '{character}' at angle {angle}: {e}")
                    continue
    
    # Check if best match meets threshold
    if best_confidence >= match_threshold:
        log.debug(f"Matched character: '{best_match}' (confidence: {best_confidence:.3f})")
        return best_match, best_confidence
    else:
        log.debug(f"No match found above threshold {match_threshold} (best: {best_confidence:.3f})")
        return None, 0.0


def _rotate_image(img: np.ndarray, angle: float) -> np.ndarray:
    """
    Rotate image by the given angle.
    
    Args:
        img: Input image
        angle: Rotation angle in degrees
        
    Returns:
        Rotated image
    """
    if angle == 0:
        return img
    
    height, width = img.shape[:2]
    center = (width // 2, height // 2)
    
    # Get rotation matrix
    rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    
    # Calculate new dimensions to avoid cropping
    cos_angle = abs(rotation_matrix[0, 0])
    sin_angle = abs(rotation_matrix[0, 1])
    new_width = int((height * sin_angle) + (width * cos_angle))
    new_height = int((height * cos_angle) + (width * sin_angle))
    
    # Adjust rotation matrix for new center
    rotation_matrix[0, 2] += (new_width / 2) - center[0]
    rotation_matrix[1, 2] += (new_height / 2) - center[1]
    
    # Apply rotation
    rotated = cv2.warpAffine(img, rotation_matrix, (new_width, new_height), 
                            flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, 
                            borderValue=0)
    
    return rotated
