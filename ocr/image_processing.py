#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image processing utilities for OCR with palette-based preprocessing
"""

import numpy as np
import cv2


def create_palette_mask(input_img: np.ndarray, tolerance: int = 33) -> np.ndarray:
    """
    Create binary mask based on specific color palette
    
    Args:
        input_img: Input BGR image
        tolerance: Color matching tolerance (default: 33)
        
    Returns:
        Binary mask where palette colors are white (255), others are black (0)
    """
    # Define the specific colors from the palette that should be considered "white"
    # Color 1: RGB(229, 224, 214) / #E5E0D6
    # Color 2: RGB(186, 178, 164) / #BAB2A4  
    # Color 3: RGB(240, 236, 227) / #F0ECE3
    
    # Define the palette colors in BGR format (OpenCV uses BGR, not RGB)
    palette_colors = [
        [214, 224, 229],  # Color 1: #E5E0D6 converted to BGR
        [164, 178, 186],  # Color 2: #BAB2A4 converted to BGR
        [227, 236, 240]   # Color 3: #F0ECE3 converted to BGR
    ]
    
    # Initialize the binary mask
    height, width = input_img.shape[:2]
    binary_mask = np.zeros((height, width), dtype=np.uint8)
    
    # For each palette color, create a mask and combine them
    for color in palette_colors:
        # Define lower and upper bounds for this color with tolerance
        lower = np.array([max(0, c - tolerance) for c in color])
        upper = np.array([min(255, c + tolerance) for c in color])
        
        # Create mask for this color
        color_mask = cv2.inRange(input_img, lower, upper)
        
        # Add to the combined binary mask
        binary_mask = cv2.bitwise_or(binary_mask, color_mask)
    
    return binary_mask


def prep_for_ocr_palette(input_img: np.ndarray, tolerance: int = 33) -> np.ndarray:
    """
    Preprocess image for OCR using palette-based binarization (optimized)
    
    Streamlined pipeline - palette does 99% of the work:
    1. Palette-based binarization - uses specific colors to identify text/background
    2. Optimal scaling - ensures text is large enough for accurate recognition
    3. Optional morphological cleaning - fills small gaps in characters (if needed)
    
    Args:
        input_img: Input image (BGR 3-channel)
        tolerance: Color matching tolerance for palette (default: 33)
        
    Returns:
        Preprocessed binary image optimized for OCR
    """
    # STEP 1: Create palette-based binary mask (does 99% of the work!)
    binary_mask = create_palette_mask(input_img, tolerance)
    
    # STEP 2: Scale up if too small for better character recognition
    height, width = binary_mask.shape
    if height < 48:
        scale_factor = 48 / height
        new_width = int(width * scale_factor)
        binary_mask = cv2.resize(binary_mask, (new_width, 48), interpolation=cv2.INTER_NEAREST)
    
    # STEP 3 (OPTIONAL): Morphological close to fill small gaps in characters
    # Remove this if palette is already clean enough
    kernel_clean = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    final = cv2.morphologyEx(binary_mask, cv2.MORPH_CLOSE, kernel_clean)
    
    return final


def prep_for_ocr_legacy(bgr: np.ndarray) -> np.ndarray:
    """
    LEGACY preprocessing - kept for backwards compatibility
    This uses the old simple HSV-based approach
    Use prep_for_ocr_palette() instead for better results
    """
    # HSV-based approach (legacy)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # Define HSV range for light colors (adjust as needed)
    lower_hsv = np.array([0, 0, 160])
    upper_hsv = np.array([179, 80, 255])
    mask = cv2.inRange(hsv, lower_hsv, upper_hsv)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    mask = cv2.dilate(mask, np.ones((2, 2), np.uint8), 1)
    inv = 255 - mask
    inv = cv2.medianBlur(inv, 3)
    return inv


def preprocess_band_for_ocr(band_bgr: np.ndarray, tolerance: int = 33) -> np.ndarray:
    """
    Preprocess hardcoded ROI for OCR with palette-based optimal upscaling
    
    Uses research-based preprocessing pipeline with custom palette for best OCR results.
    Automatically upscales small images for better character recognition.
    
    Args:
        band_bgr: Input ROI image (BGR format)
        tolerance: Color matching tolerance for palette (default: 33)
        
    Returns:
        Preprocessed grayscale image ready for OCR
    """
    # Upscale if image is too small (helps OCR accuracy significantly)
    if band_bgr.shape[0] < 48:  # IMAGE_UPSCALE_THRESHOLD
        band_bgr = cv2.resize(band_bgr, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    
    # Apply palette-based preprocessing pipeline
    return prep_for_ocr_palette(band_bgr, tolerance)