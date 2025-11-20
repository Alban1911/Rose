#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mod Manager
Handles mod extraction, installation, and management
"""

import zipfile
import shutil
from pathlib import Path
from typing import List

from utils.logging import get_logger, log_success
from utils.paths import get_user_data_dir

log = get_logger()


class ModManager:
    """Manages mod extraction and installation"""
    
    def __init__(self, mods_dir: Path):
        self.mods_dir = mods_dir
        self.mods_dir.mkdir(parents=True, exist_ok=True)
    
    def clean_mods_dir(self):
        """Clean the mods directory"""
        if not self.mods_dir.exists():
            self.mods_dir.mkdir(parents=True, exist_ok=True)
            return
        for p in self.mods_dir.iterdir():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except Exception:
                    pass
    
    def clean_overlay_dir(self):
        """Clean the overlay directory to prevent file lock issues"""
        overlay_dir = self.mods_dir.parent / "overlay"
        if overlay_dir.exists():
            try:
                shutil.rmtree(overlay_dir, ignore_errors=True)
                log.debug("[INJECT] Cleaned overlay directory")
            except Exception as e:
                log.warning(f"[INJECT] Failed to clean overlay directory: {e}")
        overlay_dir.mkdir(parents=True, exist_ok=True)
    
    def extract_zip_to_mod(self, zp: Path) -> Path:
        """Extract ZIP to mod directory"""
        target = self.mods_dir / zp.stem
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "r") as zf:
            zf.extractall(target)
        log_success(log, f"Extracted {zp.name}", "📦")
        return target
    
    def _get_user_mods_dir(self) -> Path:
        """Get the user mods directory (AppData\\Local\\Rose\\mods)"""
        return get_user_data_dir() / "mods"
    
    def _get_installed_mods_dir(self) -> Path:
        """Get the installed mods directory (AppData\\Local\\Rose\\mods\\installed)"""
        return self._get_user_mods_dir() / "installed"
    
    def extract_user_mods(self) -> List[str]:
        """Check for ZIPs and .fantome files in AppData\\Local\\Rose\\mods and extract them to installed subfolder.
        
        Returns:
            List of extracted mod folder names (relative to mods_dir)
        """
        user_mods_dir = self._get_user_mods_dir()
        installed_dir = self._get_installed_mods_dir()
        
        # Create directories if they don't exist
        user_mods_dir.mkdir(parents=True, exist_ok=True)
        installed_dir.mkdir(parents=True, exist_ok=True)
        
        # Find all ZIP and .fantome files in the user mods directory
        zip_files = list(user_mods_dir.glob("*.zip"))
        fantome_files = list(user_mods_dir.glob("*.fantome"))
        all_files = zip_files + fantome_files
        
        if not all_files:
            log.debug("[INJECT] No ZIP or .fantome files found in user mods directory")
            return []
        
        log.info(f"[INJECT] Found {len(zip_files)} ZIP file(s) and {len(fantome_files)} .fantome file(s) in user mods directory")
        extracted_mods = []
        
        for mod_file in all_files:
            try:
                # Extract to installed directory
                target = installed_dir / mod_file.stem
                if target.exists():
                    # Remove existing extraction if it exists
                    shutil.rmtree(target, ignore_errors=True)
                target.mkdir(parents=True, exist_ok=True)
                
                # .fantome files are like ZIP files, so we can extract them the same way
                with zipfile.ZipFile(mod_file, "r") as zf:
                    zf.extractall(target)
                
                file_type = "ZIP" if mod_file.suffix == ".zip" else ".fantome"
                log_success(log, f"Extracted user mod ({file_type}): {mod_file.name}", "📦")
                extracted_mods.append(target.name)
                
                # Delete the source file after successful extraction to avoid re-extracting every game
                try:
                    mod_file.unlink()
                    log.debug(f"[INJECT] Deleted source file: {mod_file.name}")
                except Exception as e:
                    log.warning(f"[INJECT] Failed to delete source file {mod_file.name}: {e}")
                
            except Exception as e:
                log.warning(f"[INJECT] Failed to extract {mod_file.name}: {e}")
                continue
        
        return extracted_mods
    
    def copy_installed_mods_to_mods_dir(self) -> List[str]:
        """Copy mods from installed directory to the injection mods directory.
        
        Returns:
            List of mod folder names that were copied (for use in mkoverlay)
        """
        installed_dir = self._get_installed_mods_dir()
        
        if not installed_dir.exists():
            log.debug("[INJECT] Installed mods directory does not exist")
            return []
        
        # Find all directories in installed folder
        mod_dirs = [d for d in installed_dir.iterdir() if d.is_dir()]
        
        if not mod_dirs:
            log.debug("[INJECT] No mods found in installed directory")
            return []
        
        log.info(f"[INJECT] Copying {len(mod_dirs)} mod(s) from installed directory")
        copied_mods = []
        
        for mod_dir in mod_dirs:
            try:
                # Copy to injection mods directory
                target = self.mods_dir / mod_dir.name
                if target.exists():
                    # Remove existing mod if it exists
                    shutil.rmtree(target, ignore_errors=True)
                
                shutil.copytree(mod_dir, target)
                copied_mods.append(mod_dir.name)
                log.debug(f"[INJECT] Copied mod: {mod_dir.name}")
                
            except Exception as e:
                log.warning(f"[INJECT] Failed to copy mod {mod_dir.name}: {e}")
                continue
        
        if copied_mods:
            log_success(log, f"Copied {len(copied_mods)} mod(s) to injection directory", "📦")
        
        return copied_mods

