#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Template manager for character recognition.

Loads and caches character templates from the templates directory,
providing efficient access for pattern matching.
"""

import os
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from utils.logging import get_logger

log = get_logger()


class TemplateManager:
    """Manages character templates for pattern matching recognition."""
    
    def __init__(self, templates_dir: str = "character_recognition/templates/english"):
        """
        Initialize template manager.
        
        Args:
            templates_dir: Path to directory containing character templates
        """
        self.templates_dir = Path(templates_dir)
        self.templates: Dict[str, List[np.ndarray]] = {}
        self.template_metadata: Dict[str, List[Dict]] = {}
        self.loaded = False
        
        # Ensure templates directory exists
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        
        # Load templates
        self._load_templates()
    
    def _load_templates(self):
        """Load all character templates from the templates directory."""
        if not self.templates_dir.exists():
            log.warning(f"Templates directory does not exist: {self.templates_dir}")
            return
        
        template_files = list(self.templates_dir.glob("*.png"))
        if not template_files:
            log.warning(f"No template files found in: {self.templates_dir}")
            return
        
        log.info(f"Loading {len(template_files)} character templates...")
        
        for template_file in template_files:
            try:
                # Parse filename to extract character label
                # Handle case prefixes: upper_A.png -> A, lower_a.png -> a
                filename = template_file.stem
                if filename.startswith('upper_'):
                    label = filename[6:]  # Remove 'upper_' prefix
                elif filename.startswith('lower_'):
                    label = filename[6:]  # Remove 'lower_' prefix
                elif '_' in filename:
                    label = filename.split('_')[0]
                else:
                    label = filename
                
                # Load template image
                template_img = cv2.imread(str(template_file), cv2.IMREAD_GRAYSCALE)
                if template_img is None:
                    log.warning(f"Failed to load template: {template_file}")
                    continue
                
                # Ensure binary image
                _, template_img = cv2.threshold(template_img, 127, 255, cv2.THRESH_BINARY)
                
                # Store template
                if label not in self.templates:
                    self.templates[label] = []
                    self.template_metadata[label] = []
                
                self.templates[label].append(template_img)
                self.template_metadata[label].append({
                    'filename': template_file.name,
                    'size': template_img.shape,
                    'path': str(template_file)
                })
                
            except Exception as e:
                log.error(f"Error loading template {template_file}: {e}")
                continue
        
        self.loaded = True
        total_templates = sum(len(templates) for templates in self.templates.values())
        log.info(f"Loaded {total_templates} templates for {len(self.templates)} characters")
        
        # Log character statistics
        for label, templates in self.templates.items():
            log.debug(f"Character '{label}': {len(templates)} templates")
    
    def get_templates_for_character(self, character: str) -> List[np.ndarray]:
        """
        Get all templates for a specific character.
        
        Args:
            character: Character to get templates for
            
        Returns:
            List of template images for the character
        """
        return self.templates.get(character, [])
    
    def get_all_characters(self) -> List[str]:
        """
        Get list of all available character labels.
        
        Returns:
            List of character labels
        """
        return list(self.templates.keys())
    
    def get_template_count(self) -> int:
        """
        Get total number of loaded templates.
        
        Returns:
            Total number of templates
        """
        return sum(len(templates) for templates in self.templates.values())
    
    def get_character_count(self) -> int:
        """
        Get number of unique characters.
        
        Returns:
            Number of unique character labels
        """
        return len(self.templates)
    
    def has_character(self, character: str) -> bool:
        """
        Check if templates exist for a character.
        
        Args:
            character: Character to check
            
        Returns:
            True if templates exist for the character
        """
        return character in self.templates and len(self.templates[character]) > 0
    
    def get_template_info(self, character: str) -> List[Dict]:
        """
        Get metadata for all templates of a character.
        
        Args:
            character: Character to get info for
            
        Returns:
            List of template metadata dictionaries
        """
        return self.template_metadata.get(character, [])
    
    def reload_templates(self):
        """Reload all templates from disk."""
        log.info("Reloading character templates...")
        self.templates.clear()
        self.template_metadata.clear()
        self.loaded = False
        self._load_templates()
    
    def add_template(self, character: str, template_img: np.ndarray, 
                    filename: str = None) -> bool:
        """
        Add a new template for a character.
        
        Args:
            character: Character label
            template_img: Template image
            filename: Optional filename to save as
            
        Returns:
            True if template was added successfully
        """
        try:
            # Ensure templates directory exists
            self.templates_dir.mkdir(parents=True, exist_ok=True)
            
            # Ensure binary image
            if len(template_img.shape) == 3:
                template_img = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
            _, template_img = cv2.threshold(template_img, 127, 255, cv2.THRESH_BINARY)
            
            # Generate filename if not provided
            if filename is None:
                import hashlib
                img_hash = hashlib.md5(template_img.tobytes()).hexdigest()[:8]
                filename = f"{character}_{img_hash}.png"
            
            # Save template to disk
            template_path = self.templates_dir / filename
            success = cv2.imwrite(str(template_path), template_img)
            if not success:
                log.error(f"Failed to save template: {template_path}")
                return False
            
            # Add to memory cache
            if character not in self.templates:
                self.templates[character] = []
                self.template_metadata[character] = []
            
            self.templates[character].append(template_img)
            self.template_metadata[character].append({
                'filename': filename,
                'size': template_img.shape,
                'path': str(template_path)
            })
            
            log.debug(f"Added template for character '{character}': {filename}")
            return True
            
        except Exception as e:
            log.error(f"Error adding template for character '{character}': {e}")
            return False
    
    def remove_template(self, character: str, template_index: int = 0) -> bool:
        """
        Remove a template for a character.
        
        Args:
            character: Character label
            template_index: Index of template to remove (default: 0)
            
        Returns:
            True if template was removed successfully
        """
        try:
            if character not in self.templates or len(self.templates[character]) <= template_index:
                log.warning(f"No template at index {template_index} for character '{character}'")
                return False
            
            # Remove from disk
            template_info = self.template_metadata[character][template_index]
            template_path = Path(template_info['path'])
            if template_path.exists():
                template_path.unlink()
                log.debug(f"Removed template file: {template_path}")
            
            # Remove from memory
            self.templates[character].pop(template_index)
            self.template_metadata[character].pop(template_index)
            
            # Clean up empty character entries
            if not self.templates[character]:
                del self.templates[character]
                del self.template_metadata[character]
            
            log.debug(f"Removed template for character '{character}' at index {template_index}")
            return True
            
        except Exception as e:
            log.error(f"Error removing template for character '{character}': {e}")
            return False
    
    def get_statistics(self) -> Dict:
        """
        Get statistics about loaded templates.
        
        Returns:
            Dictionary with template statistics
        """
        total_templates = self.get_template_count()
        character_count = self.get_character_count()
        
        # Calculate average templates per character
        avg_templates = total_templates / character_count if character_count > 0 else 0
        
        # Get character distribution
        char_distribution = {char: len(templates) for char, templates in self.templates.items()}
        
        return {
            'total_templates': total_templates,
            'character_count': character_count,
            'average_templates_per_character': avg_templates,
            'character_distribution': char_distribution,
            'templates_directory': str(self.templates_dir),
            'loaded': self.loaded
        }
