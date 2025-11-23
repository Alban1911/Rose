#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZIP Resolver
Handles resolution of skin and chroma ZIP files
"""

from pathlib import Path
from typing import Optional

from utils.core.logging import get_logger, log_success

log = get_logger()


class ZipResolver:
    """Resolves skin and chroma ZIP files from various naming conventions"""
    
    def __init__(self, zips_dir: Path):
        self.zips_dir = zips_dir
        self.zips_dir.mkdir(parents=True, exist_ok=True)
    
    def resolve_zip(self, zip_arg: str, chroma_id: int = None, skin_name: str = None, champion_name: str = None, champion_id: int = None) -> Optional[Path]:
        """Resolve a ZIP by name or path with fuzzy matching, supporting new merged structure
        
        Args:
            zip_arg: Skin name or path to search for
            chroma_id: Optional chroma ID to look for in chroma subdirectory
            skin_name: Optional base skin name for chroma lookup
            champion_id: Optional champion ID for path construction.
        """
        log.debug(f"[INJECT] Resolving zip for: '{zip_arg}' (chroma_id: {chroma_id}, skin_name: {skin_name})")
        cand = Path(zip_arg)
        if cand.exists():
            return cand

        # Handle ID-based naming convention from random selection
        if zip_arg.startswith('skin_'):
            # Format: skin_{skin_id} - check if this is actually a chroma
            skin_id = int(zip_arg.split('_')[1])
            if not champion_id:
                log.warning(f"[INJECT] No champion_id provided for skin ID: {skin_id}")
                return None
            
            # If chroma_id is provided, this is actually a chroma (Swiftplay case)
            if chroma_id is not None:
                return self._resolve_chroma_by_id(champion_id, chroma_id)
            
            # This is a base skin - Look for {champion_id}/{skin_id}/{skin_id}.zip or {skin_id}.fantome
            skin_dir = self.zips_dir / str(champion_id) / str(skin_id)
            skin_zip_path = skin_dir / f"{skin_id}.zip"
            skin_fantome_path = skin_dir / f"{skin_id}.fantome"
            
            if skin_zip_path.exists():
                log.debug(f"[INJECT] Found skin ZIP: {skin_zip_path}")
                return skin_zip_path
            elif skin_fantome_path.exists():
                log.debug(f"[INJECT] Found skin FANTOME: {skin_fantome_path}")
                return skin_fantome_path
            else:
                # Not found as base skin - might be a chroma that was incorrectly labeled as skin_
                # Try searching for it as a chroma in any base skin directory
                log.debug(f"[INJECT] Base skin not found, checking if {skin_id} is a chroma...")
                return self._resolve_chroma_by_id(champion_id, skin_id)
        
        elif zip_arg.startswith('chroma_'):
            # Format: chroma_{chroma_id} - this is a chroma
            chroma_id = int(zip_arg.split('_')[1])
            if not champion_id:
                log.warning(f"[INJECT] No champion_id provided for chroma ID: {chroma_id}")
                return None
            
            return self._resolve_chroma_by_id(champion_id, chroma_id)

        # For base skins (no chroma_id), we need skin_id
        if chroma_id is None and skin_name:
            if not champion_id:
                log.warning(f"[INJECT] No champion_id provided for skin lookup: {skin_name}")
                return None
            
            # The UIA system should have already resolved skin_name to skin_id
            # If we're here, it means skin_id wasn't provided, which shouldn't happen
            log.warning(f"[INJECT] No skin_id provided for skin '{skin_name}' - UIA should have resolved this")
            return None

        # If chroma_id is provided, look in chroma subdirectory structure
        if chroma_id is not None:
            # Special handling for Elementalist Lux forms (fake IDs 99991-99999)
            if 99991 <= chroma_id <= 99999:
                return self._resolve_elementalist_lux_form(chroma_id)
            
            # Special handling for Sahn Uzal Mordekaiser forms (IDs 82998, 82999)
            if chroma_id in (82998, 82999):
                return self._resolve_mordekaiser_form(chroma_id)
            
            # Special handling for Spirit Blossom Morgana forms (ID 25999)
            if chroma_id == 25999:
                return self._resolve_morgana_form(chroma_id)
            
            # Special handling for Radiant Sett forms (IDs 875998, 875999)
            if chroma_id in (875998, 875999):
                return self._resolve_sett_form(chroma_id)
            
            # For regular chromas, look for {champion_id}/{skin_id}/{chroma_id}/{chroma_id}.zip
            if not champion_id:
                log.warning(f"[INJECT] No champion_id provided for chroma lookup: {chroma_id}")
                return None
            
            return self._resolve_chroma_by_id(champion_id, chroma_id)

        # For regular skin files (no chroma_id), we need to find by skin_id
        # This is a simplified approach - in practice, you'd want to use LCU data
        log.warning(f"[INJECT] Base skin lookup by name not fully implemented for new structure: {zip_arg}")
        return None
    
    def _resolve_chroma_by_id(self, champion_id: int, chroma_id: int) -> Optional[Path]:
        """Resolve chroma ZIP by champion ID and chroma ID"""
        champion_dir = self.zips_dir / str(champion_id)
        if not champion_dir.exists():
            log.warning(f"[INJECT] Champion directory not found: {champion_dir}")
            return None
        
        # Search through all skin directories for this champion to find the chroma
        for skin_dir in champion_dir.iterdir():
            if not skin_dir.is_dir():
                continue
            
            # Check if this is a skin directory (numeric name)
            try:
                int(skin_dir.name)  # If this succeeds, it's a skin ID directory
                
                # Check if chroma directory exists
                chroma_dir = skin_dir / str(chroma_id)
                if chroma_dir.exists():
                    chroma_zip = chroma_dir / f"{chroma_id}.zip"
                    chroma_fantome = chroma_dir / f"{chroma_id}.fantome"
                    if chroma_zip.exists():
                        log_success(log, f"Found chroma: {chroma_zip.name}", "🎨")
                        return chroma_zip
                    elif chroma_fantome.exists():
                        log_success(log, f"Found chroma: {chroma_fantome.name}", "🎨")
                        return chroma_fantome
            except ValueError:
                # Not a skin directory, skip
                continue
        
        log.warning(f"[INJECT] Chroma {chroma_id} not found in any skin directory for champion {champion_id}")
        return None
    
    def _resolve_elementalist_lux_form(self, chroma_id: int) -> Optional[Path]:
        """Resolve Elementalist Lux form by fake chroma ID"""
        log.info(f"[INJECT] Detected Elementalist Lux form fake ID: {chroma_id}")
        
        # Map fake IDs to form names
        form_names = {
            99991: 'Air',
            99992: 'Dark', 
            99993: 'Ice',
            99994: 'Magma',
            99995: 'Mystic',
            99996: 'Nature',
            99997: 'Storm',
            99998: 'Water',
            99999: 'Fire'
        }
        
        form_name = form_names.get(chroma_id, 'Unknown')
        log.info(f"[INJECT] Looking for Elementalist Lux {form_name} form")
        
        # Look for the form file in the Lux directory (check both .zip and .fantome)
        form_pattern_zip = f"Lux Elementalist {form_name}.zip"
        form_pattern_fantome = f"Lux Elementalist {form_name}.fantome"
        form_files_zip = list(self.zips_dir.rglob(f"**/{form_pattern_zip}"))
        form_files_fantome = list(self.zips_dir.rglob(f"**/{form_pattern_fantome}"))
        
        if form_files_zip:
            log_success(log, f"Found Elementalist Lux {form_name} form: {form_files_zip[0].name}", "✨")
            return form_files_zip[0]
        elif form_files_fantome:
            log_success(log, f"Found Elementalist Lux {form_name} form: {form_files_fantome[0].name}", "✨")
            return form_files_fantome[0]
        else:
            log.warning(f"[INJECT] Elementalist Lux {form_name} form file not found: {form_pattern_zip} or {form_pattern_fantome}")
            return None
    
    def _resolve_mordekaiser_form(self, chroma_id: int) -> Optional[Path]:
        """Resolve Sahn Uzal Mordekaiser form by chroma ID"""
        log.info(f"[INJECT] Detected Sahn Uzal Mordekaiser form ID: {chroma_id}")
        
        # Map IDs to form names
        form_names = {
            82998: 'Form 1',
            82999: 'Form 2'
        }
        
        form_name = form_names.get(chroma_id, 'Unknown')
        log.info(f"[INJECT] Looking for Sahn Uzal Mordekaiser {form_name} form")
        
        # Look for the form file in the Mordekaiser directory (check both .zip and .fantome)
        form_pattern_zip = f"Sahn Uzal Mordekaiser {form_name}.zip"
        form_pattern_fantome = f"Sahn Uzal Mordekaiser {form_name}.fantome"
        form_files_zip = list(self.zips_dir.rglob(f"**/{form_pattern_zip}"))
        form_files_fantome = list(self.zips_dir.rglob(f"**/{form_pattern_fantome}"))
        
        if form_files_zip:
            log_success(log, f"Found Sahn Uzal Mordekaiser {form_name} form: {form_files_zip[0].name}", "✨")
            return form_files_zip[0]
        elif form_files_fantome:
            log_success(log, f"Found Sahn Uzal Mordekaiser {form_name} form: {form_files_fantome[0].name}", "✨")
            return form_files_fantome[0]
        else:
            log.warning(f"[INJECT] Sahn Uzal Mordekaiser {form_name} form file not found: {form_pattern_zip} or {form_pattern_fantome}")
            return None
    
    def _resolve_morgana_form(self, chroma_id: int) -> Optional[Path]:
        """Resolve Spirit Blossom Morgana form by chroma ID"""
        log.info(f"[INJECT] Detected Spirit Blossom Morgana form ID: {chroma_id}")
        
        # Map ID to form name
        form_name = 'Form 1' if chroma_id == 25999 else 'Unknown'
        log.info(f"[INJECT] Looking for Spirit Blossom Morgana {form_name} form")
        
        # Look for the form file in the Morgana directory (check both .zip and .fantome)
        form_pattern_zip = f"Spirit Blossom Morgana {form_name}.zip"
        form_pattern_fantome = f"Spirit Blossom Morgana {form_name}.fantome"
        form_files_zip = list(self.zips_dir.rglob(f"**/{form_pattern_zip}"))
        form_files_fantome = list(self.zips_dir.rglob(f"**/{form_pattern_fantome}"))
        
        if form_files_zip:
            log_success(log, f"Found Spirit Blossom Morgana {form_name} form: {form_files_zip[0].name}", "✨")
            return form_files_zip[0]
        elif form_files_fantome:
            log_success(log, f"Found Spirit Blossom Morgana {form_name} form: {form_files_fantome[0].name}", "✨")
            return form_files_fantome[0]
        else:
            log.warning(f"[INJECT] Spirit Blossom Morgana {form_name} form file not found: {form_pattern_zip} or {form_pattern_fantome}")
            return None
    
    def _resolve_sett_form(self, chroma_id: int) -> Optional[Path]:
        """Resolve Radiant Sett form by chroma ID"""
        log.info(f"[INJECT] Detected Radiant Sett form ID: {chroma_id}")
        
        # Map IDs to form names
        form_names = {
            875998: 'Form 2',
            875999: 'Form 3'
        }
        
        form_name = form_names.get(chroma_id, 'Unknown')
        log.info(f"[INJECT] Looking for Radiant Sett {form_name} form")
        
        # Look for the form file in the Sett directory (check both .zip and .fantome)
        form_pattern_zip = f"Radiant Sett {form_name}.zip"
        form_pattern_fantome = f"Radiant Sett {form_name}.fantome"
        form_files_zip = list(self.zips_dir.rglob(f"**/{form_pattern_zip}"))
        form_files_fantome = list(self.zips_dir.rglob(f"**/{form_pattern_fantome}"))
        
        if form_files_zip:
            log_success(log, f"Found Radiant Sett {form_name} form: {form_files_zip[0].name}", "✨")
            return form_files_zip[0]
        elif form_files_fantome:
            log_success(log, f"Found Radiant Sett {form_name} form: {form_files_fantome[0].name}", "✨")
            return form_files_fantome[0]
        else:
            log.warning(f"[INJECT] Radiant Sett {form_name} form file not found: {form_pattern_zip} or {form_pattern_fantome}")
            return None

