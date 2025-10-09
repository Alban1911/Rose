#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Image processing utilities for OCR
Research-based preprocessing for optimal OCR accuracy
Based on academic research and best practices for text recognition
"""

import numpy as np
import cv2
from constants import IMAGE_UPSCALE_THRESHOLD


def prep_for_ocr(input_img: np.ndarray) -> np.ndarray:
    """
    Preprocess image for OCR using research-based optimal pipeline
    
    This function implements best practices from OCR research:
    1. Bilateral filtering - removes noise while preserving edges (critical for text)
    2. CLAHE - enhances contrast adaptively for varying lighting conditions
    3. Optimal scaling - ensures text is large enough for accurate recognition
    4. Advanced binarization - combines OTSU (global) + adaptive (local) thresholding
    5. Morphological cleaning - removes noise while preserving character structure
    6. Sharpening - enhances character edges for better recognition
    
    Args:
        input_img: Input image (BGR 3-channel or grayscale 1-channel)
        
    Returns:
        Preprocessed grayscale image optimized for OCR
    """
    # STEP 1: Convert to grayscale if needed
    if len(input_img.shape) == 3 and input_img.shape[2] == 3:
        # Input is BGR (3-channel), convert to grayscale
        gray = cv2.cvtColor(input_img, cv2.COLOR_BGR2GRAY)
    else:
        # Input is already grayscale (1-channel)
        gray = input_img.copy()
    
    # STEP 2: Noise Removal with Bilateral Filtering (preserves edges!)
    # This is CRUCIAL for text recognition - removes noise while keeping character structure
    # Parameters: d=9 (diameter), sigmaColor=75, sigmaSpace=75
    denoised = cv2.bilateralFilter(gray, 9, 75, 75)
    
    # STEP 3: Contrast Enhancement (CLAHE - Contrast Limited Adaptive Histogram Equalization)
    # Improves visibility of text, especially in varying lighting conditions
    # clipLimit=3.0 prevents over-amplification of noise
    # tileGridSize=(8,8) provides good local contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)
    
    # STEP 4: Image Scaling to optimal DPI (equivalent to 300 DPI for OCR)
    # Scale up if too small for better character recognition
    # Minimum height of 48 pixels ensures characters are large enough
    height, width = enhanced.shape
    if height < 48:
        scale_factor = 48 / height
        new_width = int(width * scale_factor)
        enhanced = cv2.resize(enhanced, (new_width, 48), interpolation=cv2.INTER_CUBIC)
    
    # STEP 5: Advanced Binarization (OTSU + Adaptive combined)
    # OTSU: Automatic global threshold based on histogram
    _, binary_otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Adaptive: Local threshold for varying lighting/contrast
    # GAUSSIAN_C: Uses weighted sum of neighborhood values
    # blockSize=11: Size of pixel neighborhood for threshold calculation
    # C=2: Constant subtracted from weighted mean
    binary_adaptive = cv2.adaptiveThreshold(
        enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 11, 2
    )
    
    # Combine both methods: OTSU for global structure, adaptive for local details
    combined = cv2.bitwise_and(binary_otsu, binary_adaptive)
    
    # STEP 6: Morphological Operations (clean up characters)
    # Remove small noise while preserving character structure
    # MORPH_CLOSE: Closes small holes and gaps in characters
    kernel_clean = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    cleaned = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel_clean)
    
    # STEP 7: Final sharpening (light) to enhance character edges
    # Laplacian-based sharpening kernel enhances edges without over-sharpening
    kernel_sharp = np.array([
        [ 0, -1,  0],
        [-1,  5, -1],
        [ 0, -1,  0]
    ], dtype=np.float32)
    final = cv2.filter2D(cleaned, -1, kernel_sharp)
    
    return final


def prep_for_ocr_legacy(bgr: np.ndarray) -> np.ndarray:
    """
    LEGACY preprocessing - kept for backwards compatibility
    This uses the old simple HSV-based approach
    Use prep_for_ocr() instead for better results
    """
    from constants import WHITE_TEXT_HSV_LOWER, WHITE_TEXT_HSV_UPPER
    
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(WHITE_TEXT_HSV_LOWER, np.uint8), np.array(WHITE_TEXT_HSV_UPPER, np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    mask = cv2.dilate(mask, np.ones((2, 2), np.uint8), 1)
    inv = 255 - mask
    inv = cv2.medianBlur(inv, 3)
    return inv


def preprocess_band_for_ocr(band_bgr: np.ndarray) -> np.ndarray:
    """
    Preprocess hardcoded ROI for OCR with optimal upscaling
    
    Uses research-based preprocessing pipeline for best OCR results.
    Automatically upscales small images for better character recognition.
    
    Args:
        band_bgr: Input ROI image (BGR format)
        
    Returns:
        Preprocessed grayscale image ready for OCR
    """
    # Upscale if image is too small (helps OCR accuracy significantly)
    if band_bgr.shape[0] < IMAGE_UPSCALE_THRESHOLD:
        band_bgr = cv2.resize(band_bgr, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    
    # Apply research-based preprocessing pipeline
    return prep_for_ocr(band_bgr)
