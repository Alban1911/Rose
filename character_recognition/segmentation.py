#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Character segmentation module for pattern matching recognition.

Segments preprocessed binary images into individual character components
using connected components analysis and filters noise/artifacts.
"""

import cv2
import numpy as np
from typing import List, Tuple
from utils.logging import get_logger

log = get_logger()


def segment_image(binary_img: np.ndarray, 
                 min_width: int = 3, 
                 min_height: int = 8,
                 max_width: int = 100, 
                 max_height: int = 60) -> List[Tuple[int, np.ndarray]]:
    """
    Segment a binary image into individual character components.
    
    Args:
        binary_img: Preprocessed binary image (white text on black background)
        min_width: Minimum component width to consider (filters noise)
        min_height: Minimum component height to consider (filters noise)
        max_width: Maximum component width to consider (filters artifacts)
        max_height: Maximum component height to consider (filters artifacts)
        
    Returns:
        List of tuples: [(x_position, character_image), ...]
        Sorted by x-coordinate (left to right reading order)
    """
    if binary_img is None or binary_img.size == 0:
        log.warning("Empty or None image provided to segment_image")
        return []
    
    # Ensure image is binary (0 or 255)
    if len(binary_img.shape) == 3:
        binary_img = cv2.cvtColor(binary_img, cv2.COLOR_BGR2GRAY)
    
    # Convert to binary if not already
    _, binary_img = cv2.threshold(binary_img, 127, 255, cv2.THRESH_BINARY)
    
    # Find connected components
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary_img, connectivity=8
    )
    
    if num_labels <= 1:  # Only background component
        log.debug("No character components found in image")
        return []
    
    # Extract character components
    characters = []
    height, width = binary_img.shape
    
    for i in range(1, num_labels):  # Skip background (label 0)
        # Get component statistics
        x, y, w, h, area = stats[i]
        
        # Filter by size constraints
        if (w < min_width or h < min_height or 
            w > max_width or h > max_height):
            continue
            
        # Filter by area (remove very small or very large components)
        if area < (min_width * min_height) or area > (max_width * max_height):
            continue
        
        # Extract character region with some padding
        padding = 2
        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(width, x + w + padding)
        y2 = min(height, y + h + padding)
        
        # Extract character image
        char_img = binary_img[y1:y2, x1:x2]
        
        # Skip if character image is too small after padding
        if char_img.shape[0] < min_height or char_img.shape[1] < min_width:
            continue
            
        # Store character with its x-position for sorting
        characters.append((x, char_img))
    
    # Sort by x-coordinate (left to right reading order)
    characters.sort(key=lambda x: x[0])
    
    log.debug(f"Segmented {len(characters)} characters from image")
    return characters


def segment_image_with_debug(binary_img: np.ndarray, 
                           min_width: int = 3, 
                           min_height: int = 8,
                           max_width: int = 100, 
                           max_height: int = 60,
                           debug_output_path: str = None) -> List[Tuple[int, np.ndarray]]:
    """
    Segment image with optional debug visualization.
    
    Args:
        binary_img: Preprocessed binary image
        min_width: Minimum component width
        min_height: Minimum component height  
        max_width: Maximum component width
        max_height: Maximum component height
        debug_output_path: Optional path to save debug visualization
        
    Returns:
        List of character tuples sorted by x-position
    """
    characters = segment_image(binary_img, min_width, min_height, max_width, max_height)
    
    if debug_output_path and characters:
        # Create debug visualization
        debug_img = cv2.cvtColor(binary_img, cv2.COLOR_GRAY2BGR)
        
        # Draw bounding boxes around each character
        for i, (x, char_img) in enumerate(characters):
            # Find actual bounding box of character
            coords = cv2.findNonZero(char_img)
            if coords is not None:
                x, y, w, h = cv2.boundingRect(coords)
                cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 1)
                cv2.putText(debug_img, str(i), (x, y - 5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        # Save debug image
        cv2.imwrite(debug_output_path, debug_img)
        log.info(f"Debug segmentation saved to: {debug_output_path}")
    
    return characters


def filter_overlapping_characters(characters: List[Tuple[int, np.ndarray]], 
                                overlap_threshold: float = 0.3) -> List[Tuple[int, np.ndarray]]:
    """
    Remove overlapping character components.
    
    Args:
        characters: List of (x_position, character_image) tuples
        overlap_threshold: Minimum overlap ratio to consider characters as overlapping
        
    Returns:
        Filtered list of characters with overlaps removed
    """
    if len(characters) <= 1:
        return characters
    
    # Sort by x-position
    characters = sorted(characters, key=lambda x: x[0])
    
    filtered = []
    for i, (x1, char1) in enumerate(characters):
        # Check if this character overlaps significantly with any already accepted character
        is_overlapping = False
        
        for j, (x2, char2) in enumerate(filtered):
            # Calculate overlap
            char1_width = char1.shape[1]
            char2_width = char2.shape[1]
            
            # Simple overlap calculation based on x-positions
            overlap = max(0, min(x1 + char1_width, x2 + char2_width) - max(x1, x2))
            char1_coverage = overlap / char1_width if char1_width > 0 else 0
            char2_coverage = overlap / char2_width if char2_width > 0 else 0
            
            # If either character is significantly overlapped, skip this one
            if char1_coverage > overlap_threshold or char2_coverage > overlap_threshold:
                is_overlapping = True
                break
        
        if not is_overlapping:
            filtered.append((x1, char1))
    
    log.debug(f"Filtered {len(characters) - len(filtered)} overlapping characters")
    return filtered
