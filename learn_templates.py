#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Independent template learning script.

Processes accumulated OCR debug images to learn character templates
using OCR auto-labeling and matplotlib for human verification.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Dict
import argparse
from character_recognition.template_collector import TemplateCollector
from character_recognition.segmentation import segment_image
from utils.logging import get_logger

log = get_logger()


def process_debug_images(debug_dir: str = "pcr_debug", 
                        templates_dir: str = "character_recognition/templates/english",
                        min_confidence: float = 0.5) -> Dict[str, int]:
    """
    Process all OCR debug images to learn character templates.
    
    Args:
        debug_dir: Directory containing OCR debug images
        templates_dir: Directory to save character templates
        min_confidence: Minimum OCR confidence for character labeling
        
    Returns:
        Dictionary with processing statistics
    """
    debug_path = Path(debug_dir)
    if not debug_path.exists():
        log.error(f"Debug directory does not exist: {debug_dir}")
        return {'processed': 0, 'errors': 0}
    
    # Find all PNG files in debug directory
    debug_images = list(debug_path.glob("*.png"))
    if not debug_images:
        log.warning(f"No PNG files found in debug directory: {debug_dir}")
        return {'processed': 0, 'errors': 0}
    
    log.info(f"Found {len(debug_images)} debug images to process")
    
    # Initialize template collector
    collector = TemplateCollector(templates_dir, min_confidence)
    
    processed = 0
    errors = 0
    
    for i, img_path in enumerate(debug_images):
        try:
            log.info(f"Processing image {i+1}/{len(debug_images)}: {img_path.name}")
            
            # Load image
            img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                log.warning(f"Failed to load image: {img_path}")
                errors += 1
                continue
            
            # Collect templates from this image
            stats = collector.collect_from_image(img, img_path.name)
            
            if stats['collected'] > 0 or stats['duplicates'] > 0:
                log.info(f"  → Collected: {stats['collected']}, Duplicates: {stats['duplicates']}, Errors: {stats['errors']}")
            
            processed += 1
            
        except Exception as e:
            log.error(f"Error processing {img_path}: {e}")
            errors += 1
            continue
    
    # Get final statistics
    final_stats = collector.get_collection_stats()
    log.info(f"\nTemplate learning complete!")
    log.info(f"Processed images: {processed}")
    log.info(f"Errors: {errors}")
    log.info(f"Total templates collected: {final_stats['total_collected']}")
    log.info(f"Total duplicates: {final_stats['total_duplicates']}")
    log.info(f"Unique characters: {final_stats['unique_labels']}")
    log.info(f"Templates in database: {final_stats['templates_in_db']}")
    
    return {
        'processed': processed,
        'errors': errors,
        'total_collected': final_stats['total_collected'],
        'total_duplicates': final_stats['total_duplicates'],
        'unique_characters': final_stats['unique_labels'],
        'templates_in_db': final_stats['templates_in_db']
    }




def analyze_character_coverage(templates_dir: str = "character_recognition/templates/english"):
    """
    Analyze character coverage and provide recommendations.
    
    Args:
        templates_dir: Directory containing character templates
    """
    log.info("Analyzing character coverage...")
    
    # Analyze coverage
    template_files = list(Path(templates_dir).glob("*.png"))
    if not template_files:
        log.warning("No template files found")
        return
    
    # Count templates per character
    char_counts = {}
    for template_file in template_files:
        # Extract character from filename
        char_name = template_file.stem
        if char_name.startswith('upper_'):
            char = char_name[6:]  # Remove 'upper_' prefix
        elif char_name.startswith('lower_'):
            char = char_name[6:]  # Remove 'lower_' prefix
        else:
            char = char_name
        
        char_counts[char] = char_counts.get(char, 0) + 1
    
    # Find missing characters
    all_chars = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789')
    present_chars = set(char_counts.keys())
    missing_chars = sorted(all_chars - present_chars)
    
    # Find low coverage characters
    low_coverage = [char for char, count in char_counts.items() if count < 3]
    
    log.info(f"Character Coverage Analysis:")
    log.info(f"  Total templates: {len(template_files)}")
    log.info(f"  Unique characters: {len(char_counts)}")
    log.info(f"  Missing characters: {''.join(missing_chars)}")
    log.info(f"  Low coverage characters (< 3 templates): {''.join(low_coverage)}")
    
    if missing_chars:
        log.info("Consider collecting more debug images with these characters")
    if low_coverage:
        log.info("Consider collecting more debug images with these characters")


def main():
    """Main function for template learning script."""
    parser = argparse.ArgumentParser(
        description="Learn character templates from OCR debug images",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Learn templates from debug images
  python learn_templates.py
  
  # Learn with custom directories
  python learn_templates.py --debug-dir my_debug --templates-dir my_templates
  
  # Learn and verify templates
  python learn_templates.py --verify
  
  # Analyze coverage only
  python learn_templates.py --analyze-only
        """
    )
    
    parser.add_argument("--debug-dir", default="pcr_debug",
                       help="Directory containing PCR debug images (default: pcr_debug)")
    parser.add_argument("--templates-dir", default="character_recognition/templates/english",
                       help="Directory to save character templates (default: character_recognition/templates/english)")
    parser.add_argument("--min-confidence", type=float, default=0.5,
                       help="Minimum OCR confidence for character labeling (default: 0.5)")
    parser.add_argument("--analyze-only", action="store_true",
                       help="Only analyze existing templates without learning new ones")
    parser.add_argument("--clear-templates", action="store_true",
                       help="Clear existing templates before learning new ones")
    
    args = parser.parse_args()
    
    log.info("=" * 60)
    log.info("CHARACTER TEMPLATE LEARNING SCRIPT")
    log.info("=" * 60)
    
    # Clear templates if requested
    if args.clear_templates:
        templates_path = Path(args.templates_dir)
        if templates_path.exists():
            import shutil
            shutil.rmtree(templates_path)
            log.info(f"Cleared existing templates: {templates_path}")
    
    if not args.analyze_only:
        # Process debug images to learn templates
        log.info(f"Learning templates from: {args.debug_dir}")
        log.info(f"Saving templates to: {args.templates_dir}")
        log.info(f"Minimum OCR confidence: {args.min_confidence}")
        
        stats = process_debug_images(args.debug_dir, args.templates_dir, args.min_confidence)
        
        if stats['processed'] == 0:
            log.error("No images were processed successfully")
            return
        
        log.info(f"\nLearning complete! Processed {stats['processed']} images")
    
    # Analyze character coverage
    analyze_character_coverage(args.templates_dir)
    
    # Process templates to remove background pixels
    if not args.analyze_only:
        print("\nProcessing templates to remove background pixels...")
        log.info("\nProcessing templates to remove background pixels...")
        from character_recognition.template_processor import process_all_templates
        
        templates_path = Path(args.templates_dir)
        process_stats = process_all_templates(templates_path, backup=True, min_padding=2)
        print(f"Template processing complete: {process_stats['processed']} processed, {process_stats['errors']} errors")
        log.info(f"Template processing complete: {process_stats['processed']} processed, {process_stats['errors']} errors")
    
    
    log.info("\nTemplate learning script complete!")


if __name__ == "__main__":
    main()
