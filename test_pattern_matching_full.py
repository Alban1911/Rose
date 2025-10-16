#!/usr/bin/env python3
"""
Comprehensive test of pattern matching character recognition on all OCR debug images
Uses Levenshtein distance for evaluation instead of exact matching
"""
import cv2
import os
import time
import argparse
from pathlib import Path
from character_recognition.backend import CharacterRecognitionBackend
from ocr.backend import OCR
from utils.normalization import levenshtein_score

def test_pattern_matching_full(use_cpu=False):
    """Test pattern matching on all OCR debug images with Levenshtein evaluation"""
    debug_dir = Path("ocr_debug")
    if not debug_dir.exists():
        print("No ocr_debug directory found")
        return
    
    # Get all PNG files
    png_files = sorted([f for f in debug_dir.glob("*.png")])
    print(f"Testing pattern matching on {len(png_files)} images:")
    
    # Initialize character recognition backend
    print("Initializing character recognition backend...")
    char_recognizer = CharacterRecognitionBackend(measure_time=True)
    
    # Initialize OCR for comparison
    print("Initializing OCR backend for comparison...")
    if use_cpu:
        print("  Forcing CPU mode...")
        ocr = OCR("eng", use_gpu=False)
    else:
        print("  Using GPU mode (if available)...")
        ocr = OCR("eng", use_gpu=True)
    
    results = []
    total_ocr_time = 0
    total_pattern_time = 0
    
    for i, png_file in enumerate(png_files, 1):
        print(f"\n[{i:3d}/{len(png_files)}] {png_file.name}")
        
        try:
            # Load image
            img = cv2.imread(str(png_file))
            if img is None:
                print(f"  [ERROR] Failed to load image")
                continue
            
            # Convert to grayscale if needed
            if len(img.shape) == 3:
                gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray_img = img
            
            # Ensure binary image
            _, binary_img = cv2.threshold(gray_img, 127, 255, cv2.THRESH_BINARY)
            
            # Test OCR (for comparison)
            ocr_start = time.perf_counter()
            ocr_text = ocr.recognize(binary_img)
            ocr_time = (time.perf_counter() - ocr_start) * 1000
            total_ocr_time += ocr_time
            
            # Test Pattern Matching
            pattern_start = time.perf_counter()
            pattern_text = char_recognizer.recognize(binary_img)
            pattern_time = (time.perf_counter() - pattern_start) * 1000
            total_pattern_time += pattern_time
            
            # Calculate Levenshtein similarity score
            if ocr_text and pattern_text:
                similarity = levenshtein_score(ocr_text, pattern_text)
                # Convert to percentage
                similarity_pct = similarity * 100
            else:
                similarity_pct = 0.0
            
            # Determine quality level
            if similarity_pct >= 95:
                quality = "EXCELLENT"
            elif similarity_pct >= 85:
                quality = "GOOD"
            elif similarity_pct >= 70:
                quality = "FAIR"
            elif similarity_pct >= 50:
                quality = "POOR"
            else:
                quality = "FAIL"
            
            print(f"  OCR: '{ocr_text}' ({ocr_time:.1f}ms)")
            print(f"  PAT: '{pattern_text}' ({pattern_time:.1f}ms)")
            print(f"  SIM: {similarity_pct:.1f}% ({quality})")
            
            # Store results
            results.append({
                'file': png_file.name,
                'ocr_text': ocr_text,
                'pattern_text': pattern_text,
                'ocr_time': ocr_time,
                'pattern_time': pattern_time,
                'similarity': similarity,
                'similarity_pct': similarity_pct,
                'quality': quality
            })
            
        except Exception as e:
            print(f"  [ERROR] Processing {png_file.name}: {e}")
            continue
    
    # Comprehensive Summary
    print(f"\n{'='*80}")
    print("COMPREHENSIVE PATTERN MATCHING EVALUATION")
    print(f"{'='*80}")
    
    total_tests = len(results)
    if total_tests == 0:
        print("No valid results to analyze")
        return
    
    # Basic statistics
    ocr_success = sum(1 for r in results if r['ocr_text'])
    pattern_success = sum(1 for r in results if r['pattern_text'])
    
    # Quality distribution
    quality_counts = {}
    for r in results:
        quality = r['quality']
        quality_counts[quality] = quality_counts.get(quality, 0) + 1
    
    # Similarity statistics
    similarities = [r['similarity_pct'] for r in results if r['similarity_pct'] > 0]
    avg_similarity = sum(similarities) / len(similarities) if similarities else 0
    max_similarity = max(similarities) if similarities else 0
    min_similarity = min(similarities) if similarities else 0
    
    # Timing statistics
    avg_ocr_time = total_ocr_time / total_tests
    avg_pattern_time = total_pattern_time / total_tests
    speedup = avg_ocr_time / avg_pattern_time if avg_pattern_time > 0 else 0
    
    print(f"Total images processed: {total_tests}")
    print(f"OCR success rate: {ocr_success}/{total_tests} ({ocr_success/total_tests*100:.1f}%)")
    print(f"Pattern success rate: {pattern_success}/{total_tests} ({pattern_success/total_tests*100:.1f}%)")
    print()
    
    print("QUALITY DISTRIBUTION:")
    for quality in ["EXCELLENT", "GOOD", "FAIR", "POOR", "FAIL"]:
        count = quality_counts.get(quality, 0)
        pct = count / total_tests * 100
        print(f"  {quality:8s}: {count:3d} ({pct:5.1f}%)")
    print()
    
    print("SIMILARITY STATISTICS:")
    print(f"  Average similarity: {avg_similarity:.1f}%")
    print(f"  Best similarity:    {max_similarity:.1f}%")
    print(f"  Worst similarity:   {min_similarity:.1f}%")
    print()
    
    print("PERFORMANCE STATISTICS:")
    print(f"  Average OCR time:     {avg_ocr_time:.2f}ms")
    print(f"  Average Pattern time: {avg_pattern_time:.2f}ms")
    print(f"  Speedup factor:       {speedup:.1f}x faster")
    print()
    
    # Show best and worst results
    if similarities:
        # Sort by similarity
        sorted_results = sorted(results, key=lambda x: x['similarity_pct'], reverse=True)
        
        print("BEST RESULTS (Top 5):")
        for i, r in enumerate(sorted_results[:5], 1):
            print(f"  {i}. {r['file']}")
            print(f"     OCR: '{r['ocr_text']}'")
            print(f"     PAT: '{r['pattern_text']}'")
            print(f"     SIM: {r['similarity_pct']:.1f}% ({r['quality']})")
            print()
        
        print("WORST RESULTS (Bottom 5):")
        for i, r in enumerate(sorted_results[-5:], 1):
            print(f"  {i}. {r['file']}")
            print(f"     OCR: '{r['ocr_text']}'")
            print(f"     PAT: '{r['pattern_text']}'")
            print(f"     SIM: {r['similarity_pct']:.1f}% ({r['quality']})")
            print()
    
    # Character-level analysis
    print("CHARACTER-LEVEL ANALYSIS:")
    char_errors = {}
    for r in results:
        if r['ocr_text'] and r['pattern_text']:
            ocr_chars = list(r['ocr_text'].replace(' ', ''))
            pat_chars = list(r['pattern_text'].replace(' ', ''))
            
            # Find character mismatches
            min_len = min(len(ocr_chars), len(pat_chars))
            for i in range(min_len):
                if ocr_chars[i] != pat_chars[i]:
                    error_key = f"{ocr_chars[i]}->{pat_chars[i]}"
                    char_errors[error_key] = char_errors.get(error_key, 0) + 1
    
    if char_errors:
        print("  Most common character confusions:")
        sorted_errors = sorted(char_errors.items(), key=lambda x: x[1], reverse=True)
        for error, count in sorted_errors[:10]:  # Top 10
            print(f"    {error}: {count} times")
    else:
        print("  No character-level errors detected")
    
    print(f"\n{'='*80}")
    print("EVALUATION COMPLETE")
    print(f"{'='*80}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Comprehensive test of pattern matching character recognition",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--cpu", action="store_true",
                        help="Force OCR to use CPU mode instead of GPU")
    
    args = parser.parse_args()
    test_pattern_matching_full(use_cpu=args.cpu)
