#!/usr/bin/env python3
"""
Template verification script for character recognition.

Allows viewing and verification of collected character templates using matplotlib.
"""

import argparse
from pathlib import Path
from utils.logging import get_logger, setup_logging
from character_recognition.template_viewer import TemplateViewer

log = get_logger()


def verify_templates(templates_dir: str = "character_recognition/templates/english"):
    """
    Open template viewer for human verification of character labels.
    
    Args:
        templates_dir: Directory containing character templates
    """
    log.info("Opening template viewer for human verification...")
    
    viewer = TemplateViewer(templates_dir)
    
    if not viewer.load_templates():
        log.error("No templates loaded - cannot open viewer")
        return False
    
    # Show statistics first
    log.info("Template statistics:")
    viewer.show_statistics()
    
    # Show templates in pages
    log.info("Showing character templates for verification...")
    log.info("Review the templates and correct any wrong labels if needed.")
    log.info("Pages will advance automatically every 2 seconds.")
    
    viewer.show_templates_sequential(templates_per_page=50, auto_advance=True)
    
    return True


def analyze_character_coverage(templates_dir: str = "character_recognition/templates/english"):
    """
    Analyze character coverage in the template collection.
    
    Args:
        templates_dir: Directory containing character templates
    """
    log.info("Analyzing character coverage...")
    
    viewer = TemplateViewer(templates_dir)
    
    if not viewer.load_templates():
        log.error("No templates loaded - cannot analyze coverage")
        return
    
    # Show statistics
    viewer.show_statistics()
    
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


def main():
    """Main function for template verification."""
    parser = argparse.ArgumentParser(description="Verify character templates")
    parser.add_argument("--templates-dir", default="character_recognition/templates/english",
                       help="Directory containing character templates")
    parser.add_argument("--analyze-only", action="store_true",
                       help="Only show statistics and analysis, don't open viewer")
    parser.add_argument("--character", help="Show templates for specific character")
    parser.add_argument("--stats", action="store_true",
                       help="Show template statistics")
    parser.add_argument("--page", type=int, default=0,
                       help="Page number to display (0-based)")
    parser.add_argument("--per-page", type=int, default=50,
                       help="Number of templates per page")
    parser.add_argument("--sequential", action="store_true",
                       help="Show templates page by page with navigation")
    parser.add_argument("--auto-advance", action="store_true",
                       help="Automatically advance pages (use with --sequential)")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging()
    
    log.info(f"Template verification starting...")
    log.info(f"Templates directory: {args.templates_dir}")
    
    # Check if templates directory exists
    templates_path = Path(args.templates_dir)
    if not templates_path.exists():
        log.error(f"Templates directory does not exist: {args.templates_dir}")
        return
    
    # Create viewer
    viewer = TemplateViewer(args.templates_dir)
    
    # Load templates
    if not viewer.load_templates():
        log.error("Failed to load templates")
        return
    
    # Show templates based on arguments
    if args.stats:
        viewer.show_statistics()
    elif args.character:
        viewer.show_character_templates(args.character)
    elif args.sequential:
        viewer.show_templates_sequential(args.per_page, args.auto_advance)
    elif args.analyze_only:
        analyze_character_coverage(args.templates_dir)
    else:
        # Default: show templates with verification
        verify_templates(args.templates_dir)
    
    log.info("Template verification complete!")


if __name__ == "__main__":
    main()
