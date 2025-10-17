#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Application Status Manager
Manages the app state and tray icon status based on initialization checks
"""

from typing import Optional
from pathlib import Path
from utils.logging import get_logger
from utils.paths import get_skins_dir

log = get_logger()


class AppStatus:
    """
    Manages application status based on initialization state of core components.
    
    Checks:
    - Chroma selector initialization
    - Skins downloaded from repository
    - PCR (Pattern Character Recognition) initialization
    
    Status:
    - locked.png: Chroma not initialized OR Skins not downloaded OR PCR not initialized
    - golden locked.png: Chroma initialized AND Skins downloaded BUT PCR not initialized
    - golden unlocked.png: All components ready (Chroma AND Skins AND PCR initialized)
    """
    
    def __init__(self, tray_manager=None):
        """
        Initialize the AppStatus manager
        
        Args:
            tray_manager: TrayManager instance to update status icon
        """
        self.tray_manager = tray_manager
        self._chroma_initialized = False
        self._skins_downloaded = False
        self._ocr_initialized = False
        
    def check_chroma_initialized(self) -> bool:
        """
        Check if Chroma selector is initialized
        
        Returns:
            True if chroma selector is initialized, False otherwise
        """
        try:
            from utils.chroma_selector import get_chroma_selector
            chroma_selector = get_chroma_selector()
            return chroma_selector is not None
        except Exception as e:
            log.debug(f"Failed to check chroma initialization: {e}")
            return False
    
    def check_skins_downloaded(self) -> bool:
        """
        Check if skins are downloaded from the repository
        
        Returns:
            True if skins directory exists and has content, False otherwise
        """
        try:
            skins_dir = get_skins_dir()
            
            # Check if directory exists
            if not skins_dir.exists():
                return False
            
            # Check if directory has any champion folders with skin files
            champion_dirs = [d for d in skins_dir.iterdir() if d.is_dir()]
            if not champion_dirs:
                return False
            
            # Check if at least one champion has skin files
            for champion_dir in champion_dirs:
                # Check for base skins
                if list(champion_dir.glob("*.zip")):
                    return True
                
                # Check for chromas
                chromas_dir = champion_dir / "chromas"
                if chromas_dir.exists() and chromas_dir.is_dir():
                    for skin_chroma_dir in chromas_dir.iterdir():
                        if skin_chroma_dir.is_dir() and list(skin_chroma_dir.glob("*.zip")):
                            return True
            
            return False
        except Exception as e:
            log.debug(f"Failed to check skins directory: {e}")
            return False
    
    def check_ocr_initialized(self, ocr=None) -> bool:
        """
        Check if PCR (Pattern Character Recognition) is initialized
        
        Args:
            ocr: PCR instance to check (if None, returns current cached state)
        
        Returns:
            True if PCR is initialized, False otherwise
        """
        if ocr is None:
            return self._ocr_initialized
        
        try:
            # Check if PCR has the required attributes
            return (hasattr(ocr, 'recognize') and 
                   callable(getattr(ocr, 'recognize', None)) and
                   hasattr(ocr, 'recognizer') and 
                   ocr.recognizer is not None)
        except Exception as e:
            log.debug(f"Failed to check PCR initialization: {e}")
            return False
    
    def update_status(self, ocr=None):
        """
        Update the application status by checking all components
        
        Args:
            ocr: OCR instance to check (optional)
        """
        # Check each component
        self._chroma_initialized = self.check_chroma_initialized()
        self._skins_downloaded = self.check_skins_downloaded()
        self._ocr_initialized = self.check_ocr_initialized(ocr)
        
        # Determine status level
        chroma_and_skins_ready = (self._chroma_initialized and self._skins_downloaded)
        all_ready = (chroma_and_skins_ready and self._ocr_initialized)
        
        # Log status for debugging
        log.debug(f"[APP STATUS] Chroma: {self._chroma_initialized}, "
                 f"Skins: {self._skins_downloaded}, "
                 f"PCR: {self._ocr_initialized}")
        
        # Update tray icon based on status level
        if self.tray_manager:
            separator = "=" * 80
            if all_ready:
                # All components ready - golden unlocked
                self.tray_manager.set_status("unlocked")
                log.info(separator)
                log.info("🔓✨ APP STATUS: ALL COMPONENTS READY")
                log.info("   📋 Chroma Selector: Initialized")
                log.info("   📋 Skins: Downloaded")
                log.info("   📋 PCR: Initialized")
                log.info("   🎯 Status: Golden Unlocked")
                log.info(separator)
            elif chroma_and_skins_ready:
                # Chroma and skins ready, but OCR not ready - golden locked
                self.tray_manager.set_status("golden_locked")
                log.info(separator)
                log.info("🔓 APP STATUS: READY (PCR PENDING)")
                log.info("   📋 Chroma Selector: Initialized")
                log.info("   📋 Skins: Downloaded")
                log.info("   ⏳ PCR: Pending")
                log.info("   🎯 Status: Golden Locked")
                log.info(separator)
            else:
                # Some components not ready - locked
                self.tray_manager.set_status("locked")
                log.info(separator)
                log.info("🔒 APP STATUS: INITIALIZING")
                log.info(f"   {'✅' if self._chroma_initialized else '⏳'} Chroma Selector: {'Initialized' if self._chroma_initialized else 'Pending'}")
                log.info(f"   {'✅' if self._skins_downloaded else '⏳'} Skins: {'Downloaded' if self._skins_downloaded else 'Pending'}")
                log.info(f"   {'✅' if self._ocr_initialized else '⏳'} PCR: {'Initialized' if self._ocr_initialized else 'Pending'}")
                log.info("   🎯 Status: Locked")
                log.info(separator)
    
    def mark_chroma_initialized(self):
        """Mark chroma selector as initialized and update status"""
        self._chroma_initialized = True
        log.info("[APP STATUS] Chroma selector initialized")
        self.update_status()
    
    def mark_skins_downloaded(self):
        """Mark skins as downloaded and update status"""
        self._skins_downloaded = True
        log.info("[APP STATUS] Skins downloaded")
        self.update_status()
    
    def mark_ocr_initialized(self, ocr=None):
        """Mark PCR as initialized and update status"""
        if ocr is not None:
            self._ocr_initialized = self.check_ocr_initialized(ocr)
        else:
            self._ocr_initialized = True
        log.info("[APP STATUS] PCR initialized")
        self.update_status()
    
    def get_status_summary(self) -> dict:
        """
        Get a summary of the current status
        
        Returns:
            Dictionary with status of each component
        """
        return {
            'chroma_initialized': self._chroma_initialized,
            'skins_downloaded': self._skins_downloaded,
            'ocr_initialized': self._ocr_initialized,
            'all_ready': (self._chroma_initialized and 
                         self._skins_downloaded and 
                         self._ocr_initialized)
        }
    
    @property
    def is_ready(self) -> bool:
        """Check if all components are ready"""
        return (self._chroma_initialized and 
               self._skins_downloaded and 
               self._ocr_initialized)

