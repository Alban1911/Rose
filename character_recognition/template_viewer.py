#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Template viewer for character recognition.

Visualizes collected character templates using matplotlib for manual
verification and correction of OCR labels.
"""

import os
import cv2
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from .template_manager import TemplateManager
from utils.logging import get_logger

log = get_logger()


class TemplateViewer:
    """Visualizes character templates for manual verification and correction."""
    
    def __init__(self, templates_dir: str = "character_recognition/templates/english"):
        """
        Initialize template viewer.
        
        Args:
            templates_dir: Directory containing character templates
        """
        self.templates_dir = Path(templates_dir)
        self.template_manager = TemplateManager(templates_dir)
        self.fig = None
        self.axes = None
        self.template_data = []
        self.current_page = 0
        self.templates_per_page = 50  # Adjust based on screen size
        
    def load_templates(self) -> bool:
        """
        Load all templates from the templates directory.
        
        Returns:
            True if templates were loaded successfully
        """
        if not self.template_manager.loaded:
            log.error("No templates loaded in template manager")
            return False
        
        # Get all template files
        template_files = list(self.templates_dir.glob("*.png"))
        if not template_files:
            log.warning(f"No template files found in: {self.templates_dir}")
            return False
        
        # Load template data
        self.template_data = []
        for template_file in template_files:
            try:
                # Parse filename to extract character label
                filename = template_file.stem
                if '_' in filename:
                    label = filename.split('_')[0]
                else:
                    label = filename
                
                # Load template image
                template_img = cv2.imread(str(template_file), cv2.IMREAD_GRAYSCALE)
                if template_img is None:
                    log.warning(f"Failed to load template: {template_file}")
                    continue
                
                self.template_data.append({
                    'label': label,
                    'image': template_img,
                    'filename': template_file.name,
                    'path': str(template_file)
                })
                
            except Exception as e:
                log.error(f"Error loading template {template_file}: {e}")
                continue
        
        log.info(f"Loaded {len(self.template_data)} templates for viewing")
        return len(self.template_data) > 0
    
    def show_templates(self, page: int = 0, templates_per_page: int = None):
        """
        Display templates in a grid layout with labels (alphabetically sorted).
        
        Args:
            page: Page number to display (0-based)
            templates_per_page: Number of templates per page
        """
        if not self.template_data:
            log.error("No template data loaded")
            return
        
        if templates_per_page is not None:
            self.templates_per_page = templates_per_page
        
        # Sort templates alphabetically by label
        self.template_data.sort(key=lambda x: (x['label'].lower(), x['label']))
        
        self.current_page = page
        total_pages = (len(self.template_data) + self.templates_per_page - 1) // self.templates_per_page
        
        if page >= total_pages:
            log.warning(f"Page {page} out of range (0-{total_pages-1})")
            return
        
        # Calculate grid dimensions
        cols = int(np.ceil(np.sqrt(self.templates_per_page)))
        rows = int(np.ceil(self.templates_per_page / cols))
        
        # Create figure
        self.fig, self.axes = plt.subplots(rows, cols, figsize=(cols * 2, rows * 2))
        if rows == 1:
            self.axes = [self.axes] if cols == 1 else self.axes
        else:
            self.axes = self.axes.flatten()
        
        # Clear all axes
        for ax in self.axes:
            ax.clear()
            ax.set_xticks([])
            ax.set_yticks([])
        
        # Calculate start and end indices for this page
        start_idx = page * self.templates_per_page
        end_idx = min(start_idx + self.templates_per_page, len(self.template_data))
        
        # Display templates
        for i, template_info in enumerate(self.template_data[start_idx:end_idx]):
            ax = self.axes[i]
            
            # Display template image
            ax.imshow(template_info['image'], cmap='gray')
            ax.set_title(f"'{template_info['label']}'\n{template_info['filename']}", 
                        fontsize=8, pad=2)
            
            # Add border
            ax.add_patch(patches.Rectangle((0, 0), template_info['image'].shape[1]-1, 
                                         template_info['image'].shape[0]-1, 
                                         linewidth=1, edgecolor='blue', facecolor='none'))
        
        # Hide unused axes
        for i in range(end_idx - start_idx, len(self.axes)):
            self.axes[i].set_visible(False)
        
        # Set title and layout
        self.fig.suptitle(f"Character Templates - Page {page + 1}/{total_pages} "
                         f"({len(self.template_data)} total templates)", 
                         fontsize=12)
        plt.tight_layout()
        
        # Show the plot
        plt.show()
        
        log.info(f"Displayed templates {start_idx+1}-{end_idx} of {len(self.template_data)}")
    
    def show_templates_sequential(self, templates_per_page: int = 50, auto_advance: bool = True):
        """
        Display templates page by page automatically.
        
        Args:
            templates_per_page: Number of templates per page
            auto_advance: If True, automatically advance to next page after a delay
        """
        if not self.template_data:
            log.error("No template data loaded")
            return
        
        # Sort templates alphabetically by label
        self.template_data.sort(key=lambda x: (x['label'].lower(), x['label']))
        
        self.templates_per_page = templates_per_page
        total_pages = (len(self.template_data) + self.templates_per_page - 1) // self.templates_per_page
        
        log.info(f"Starting sequential template viewing: {total_pages} pages, {templates_per_page} templates per page")
        
        import time
        
        for current_page in range(total_pages):
            print(f"\n{'='*60}")
            print(f"PAGE {current_page + 1} of {total_pages}")
            print(f"{'='*60}")
            
            # Show current page
            self.show_templates(current_page, templates_per_page)
            
            # Wait before showing next page (except for last page)
            if current_page < total_pages - 1:
                print(f"\nShowing next page in 2 seconds...")
                time.sleep(2)
        
        print(f"\nFinished viewing all {total_pages} pages of templates!")
    
    def show_character_templates(self, character: str):
        """
        Display all templates for a specific character.
        
        Args:
            character: Character to display templates for
        """
        # Filter templates for this character
        char_templates = [t for t in self.template_data if t['label'] == character]
        
        if not char_templates:
            log.warning(f"No templates found for character: '{character}'")
            return
        
        # Calculate grid dimensions
        cols = int(np.ceil(np.sqrt(len(char_templates))))
        rows = int(np.ceil(len(char_templates) / cols))
        
        # Create figure
        fig, axes = plt.subplots(rows, cols, figsize=(cols * 2, rows * 2))
        if rows == 1:
            axes = [axes] if cols == 1 else axes
        else:
            axes = axes.flatten()
        
        # Clear all axes
        for ax in axes:
            ax.clear()
            ax.set_xticks([])
            ax.set_yticks([])
        
        # Display templates
        for i, template_info in enumerate(char_templates):
            ax = axes[i]
            
            # Display template image
            ax.imshow(template_info['image'], cmap='gray')
            ax.set_title(f"'{template_info['label']}'\n{template_info['filename']}", 
                        fontsize=8, pad=2)
            
            # Add border
            ax.add_patch(patches.Rectangle((0, 0), template_info['image'].shape[1]-1, 
                                         template_info['image'].shape[0]-1, 
                                         linewidth=1, edgecolor='blue', facecolor='none'))
        
        # Hide unused axes
        for i in range(len(char_templates), len(axes)):
            axes[i].set_visible(False)
        
        # Set title and layout
        fig.suptitle(f"Templates for Character '{character}' ({len(char_templates)} templates)", 
                     fontsize=12)
        plt.tight_layout()
        
        # Show the plot
        plt.show()
        
        log.info(f"Displayed {len(char_templates)} templates for character '{character}'")
    
    def show_statistics(self):
        """Display template collection statistics."""
        if not self.template_data:
            log.error("No template data loaded")
            return
        
        # Count templates by character
        char_counts = {}
        for template_info in self.template_data:
            char = template_info['label']
            char_counts[char] = char_counts.get(char, 0) + 1
        
        # Sort by count (descending)
        sorted_chars = sorted(char_counts.items(), key=lambda x: x[1], reverse=True)
        
        # Create statistics plot
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        
        # Character count bar chart
        chars, counts = zip(*sorted_chars)
        ax1.bar(range(len(chars)), counts)
        ax1.set_xlabel('Character')
        ax1.set_ylabel('Number of Templates')
        ax1.set_title('Templates per Character')
        ax1.set_xticks(range(len(chars)))
        ax1.set_xticklabels(chars, rotation=45)
        
        # Template size distribution
        sizes = [template_info['image'].shape for template_info in self.template_data]
        widths = [size[1] for size in sizes]
        heights = [size[0] for size in sizes]
        
        ax2.scatter(widths, heights, alpha=0.6)
        ax2.set_xlabel('Width (pixels)')
        ax2.set_ylabel('Height (pixels)')
        ax2.set_title('Template Size Distribution')
        ax2.grid(True, alpha=0.3)
        
        # Set overall title
        fig.suptitle(f"Template Collection Statistics ({len(self.template_data)} total templates)", 
                     fontsize=14)
        
        plt.tight_layout()
        plt.show()
        
        # Print statistics
        log.info(f"Template Statistics:")
        log.info(f"  Total templates: {len(self.template_data)}")
        log.info(f"  Unique characters: {len(char_counts)}")
        log.info(f"  Average templates per character: {len(self.template_data) / len(char_counts):.1f}")
        log.info(f"  Most common character: '{sorted_chars[0][0]}' ({sorted_chars[0][1]} templates)")
    
    def rename_character(self, old_label: str, new_label: str) -> bool:
        """
        Rename all templates for a character.
        
        Args:
            old_label: Current character label
            new_label: New character label
            
        Returns:
            True if renaming was successful
        """
        if not self.template_data:
            log.error("No template data loaded")
            return False
        
        # Find templates for this character
        char_templates = [t for t in self.template_data if t['label'] == old_label]
        
        if not char_templates:
            log.warning(f"No templates found for character: '{old_label}'")
            return False
        
        renamed_count = 0
        
        for template_info in char_templates:
            try:
                old_path = Path(template_info['path'])
                old_filename = template_info['filename']
                
                # Generate new filename
                if '_' in old_filename:
                    hash_part = old_filename.split('_', 1)[1]
                    new_filename = f"{new_label}_{hash_part}"
                else:
                    new_filename = f"{new_label}.png"
                
                new_path = old_path.parent / new_filename
                
                # Rename file
                old_path.rename(new_path)
                
                # Update template info
                template_info['label'] = new_label
                template_info['filename'] = new_filename
                template_info['path'] = str(new_path)
                
                renamed_count += 1
                
            except Exception as e:
                log.error(f"Error renaming template {template_info['filename']}: {e}")
                continue
        
        log.info(f"Renamed {renamed_count} templates from '{old_label}' to '{new_label}'")
        return renamed_count > 0
    
    def delete_character_templates(self, character: str) -> bool:
        """
        Delete all templates for a character.
        
        Args:
            character: Character to delete templates for
            
        Returns:
            True if deletion was successful
        """
        if not self.template_data:
            log.error("No template data loaded")
            return False
        
        # Find templates for this character
        char_templates = [t for t in self.template_data if t['label'] == character]
        
        if not char_templates:
            log.warning(f"No templates found for character: '{character}'")
            return False
        
        deleted_count = 0
        
        for template_info in char_templates:
            try:
                template_path = Path(template_info['path'])
                
                # Delete file
                if template_path.exists():
                    template_path.unlink()
                    deleted_count += 1
                
                # Remove from template data
                self.template_data.remove(template_info)
                
            except Exception as e:
                log.error(f"Error deleting template {template_info['filename']}: {e}")
                continue
        
        log.info(f"Deleted {deleted_count} templates for character '{character}'")
        return deleted_count > 0
    
    def save_current_view(self, output_path: str):
        """
        Save the current template view to a file.
        
        Args:
            output_path: Path to save the image
        """
        if self.fig is None:
            log.error("No figure to save")
            return
        
        self.fig.savefig(output_path, dpi=300, bbox_inches='tight')
        log.info(f"Template view saved to: {output_path}")
    
    def close(self):
        """Close the template viewer and clean up resources."""
        if self.fig is not None:
            plt.close(self.fig)
            self.fig = None
            self.axes = None
        
        log.info("Template viewer closed")


def main():
    """Main function for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Character Template Viewer")
    parser.add_argument("--templates-dir", default="character_recognition/templates/english",
                       help="Directory containing character templates")
    parser.add_argument("--page", type=int, default=0,
                       help="Page number to display (0-based)")
    parser.add_argument("--per-page", type=int, default=50,
                       help="Number of templates per page")
    parser.add_argument("--character", help="Show templates for specific character")
    parser.add_argument("--stats", action="store_true",
                       help="Show template statistics")
    parser.add_argument("--sequential", action="store_true",
                       help="Show templates page by page with navigation")
    parser.add_argument("--auto-advance", action="store_true",
                       help="Automatically advance pages (use with --sequential)")
    
    args = parser.parse_args()
    
    # Create viewer
    viewer = TemplateViewer(args.templates_dir)
    
    # Load templates
    if not viewer.load_templates():
        log.error("Failed to load templates")
        return
    
    # Show templates
    if args.stats:
        viewer.show_statistics()
    elif args.character:
        viewer.show_character_templates(args.character)
    elif args.sequential:
        viewer.show_templates_sequential(args.per_page, args.auto_advance)
    else:
        viewer.show_templates(args.page, args.per_page)
        # Keep the plot open
        input("Press Enter to close...")


if __name__ == "__main__":
    main()
