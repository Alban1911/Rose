#!/usr/bin/env python3
"""
Template processing module for cleaning character templates.

Removes background white pixels and crops templates to fit tightly around the main character.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional
from utils.logging import get_logger

log = get_logger()


def find_largest_connected_component(binary_img: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """
    Find the largest connected component in a binary image and remove all others.
    
    Args:
        binary_img: Binary image (0 = black, 255 = white)
        
    Returns:
        Tuple of (cleaned_image, bounding_box) where bounding_box is (x, y, w, h)
    """
    # Find connected components
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary_img, connectivity=8)
    
    if num_labels <= 1:  # Only background
        return binary_img, (0, 0, binary_img.shape[1], binary_img.shape[0])
    
    # Find the largest component (excluding background label 0)
    largest_area = 0
    largest_label = 1
    
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area > largest_area:
            largest_area = area
            largest_label = i
    
    # Create a clean image with only the largest component
    clean_img = np.zeros_like(binary_img)
    clean_img[labels == largest_label] = 255
    
    # Get bounding box of largest component
    x = stats[largest_label, cv2.CC_STAT_LEFT]
    y = stats[largest_label, cv2.CC_STAT_TOP]
    w = stats[largest_label, cv2.CC_STAT_WIDTH]
    h = stats[largest_label, cv2.CC_STAT_HEIGHT]
    
    # Crop to the largest component
    cropped = clean_img[y:y+h, x:x+w]
    
    return cropped, (x, y, w, h)


def crop_to_character(template_img: np.ndarray, min_padding: int = 2) -> np.ndarray:
    """
    Crop template image to fit tightly around the main character.
    
    Args:
        template_img: Template image to process
        min_padding: Minimum padding to keep around the character
        
    Returns:
        Cropped template image
    """
    # Ensure image is binary
    if len(template_img.shape) == 3:
        template_img = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
    
    # Ensure binary (0 or 255)
    _, binary_img = cv2.threshold(template_img, 127, 255, cv2.THRESH_BINARY)
    
    # Find the largest connected component (the main character)
    cropped, (x, y, w, h) = find_largest_connected_component(binary_img)
    
    # Add minimum padding
    h, w = cropped.shape
    padded = np.zeros((h + 2*min_padding, w + 2*min_padding), dtype=np.uint8)
    padded[min_padding:h+min_padding, min_padding:w+min_padding] = cropped
    
    return padded


def process_template_file(input_path: Path, output_path: Path, min_padding: int = 2) -> bool:
    """
    Process a single template file to remove background pixels.
    
    Args:
        input_path: Path to input template file
        output_path: Path to save processed template
        min_padding: Minimum padding around character
        
    Returns:
        True if processing was successful
    """
    try:
        # Load template
        template_img = cv2.imread(str(input_path))
        if template_img is None:
            log.error(f"Could not load template: {input_path}")
            return False
        
        # Process template
        processed_img = crop_to_character(template_img, min_padding)
        
        # Save processed template
        success = cv2.imwrite(str(output_path), processed_img)
        if not success:
            log.error(f"Failed to save processed template: {output_path}")
            return False
        
        log.debug(f"Processed template: {input_path.name} -> {output_path.name}")
        return True
        
    except Exception as e:
        log.error(f"Error processing template {input_path.name}: {e}")
        return False


def process_all_templates(templates_dir: Path, backup: bool = True, min_padding: int = 2) -> dict:
    """
    Process all templates in a directory to remove background pixels.
    
    Args:
        templates_dir: Directory containing template files
        backup: If True, create backup of original templates
        min_padding: Minimum padding around characters
        
    Returns:
        Dictionary with processing statistics
    """
    if not templates_dir.exists():
        log.error(f"Templates directory does not exist: {templates_dir}")
        return {'processed': 0, 'errors': 0, 'skipped': 0}
    
    # Find all template files
    template_files = list(templates_dir.glob("*.png"))
    if not template_files:
        log.warning(f"No template files found in: {templates_dir}")
        return {'processed': 0, 'errors': 0, 'skipped': 0}
    
    log.info(f"Processing {len(template_files)} templates in {templates_dir}")
    
    # Create backup directory if requested
    backup_dir = None
    if backup:
        backup_dir = templates_dir / "backup_original"
        backup_dir.mkdir(exist_ok=True)
        log.info(f"Created backup directory: {backup_dir}")
    
    processed = 0
    errors = 0
    skipped = 0
    
    for template_file in template_files:
        try:
            # Create backup if requested
            if backup_dir:
                backup_path = backup_dir / template_file.name
                if not backup_path.exists():
                    import shutil
                    shutil.copy2(template_file, backup_path)
            
            # Process template (overwrite original)
            success = process_template_file(template_file, template_file, min_padding)
            
            if success:
                processed += 1
            else:
                errors += 1
                
        except Exception as e:
            log.error(f"Error processing {template_file.name}: {e}")
            errors += 1
    
    log.info(f"Template processing complete: {processed} processed, {errors} errors, {skipped} skipped")
    
    return {
        'processed': processed,
        'errors': errors,
        'skipped': skipped,
        'total': len(template_files)
    }


def main():
    """Command-line interface for template processing."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Process character templates to remove background pixels")
    parser.add_argument("--templates-dir", default="character_recognition/templates/english",
                       help="Directory containing character templates")
    parser.add_argument("--min-padding", type=int, default=2,
                       help="Minimum padding around characters")
    parser.add_argument("--no-backup", action="store_true",
                       help="Don't create backup of original templates")
    
    args = parser.parse_args()
    
    templates_dir = Path(args.templates_dir)
    
    # Process templates
    stats = process_all_templates(
        templates_dir, 
        backup=not args.no_backup, 
        min_padding=args.min_padding
    )
    
    print(f"\nTemplate Processing Results:")
    print(f"  Processed: {stats['processed']}")
    print(f"  Errors: {stats['errors']}")
    print(f"  Total: {stats['total']}")
    
    if stats['processed'] > 0:
        print(f"\nTemplates have been processed and cropped to fit characters tightly.")
        if not args.no_backup:
            print(f"Original templates backed up to: {templates_dir}/backup_original/")


if __name__ == "__main__":
    main()
