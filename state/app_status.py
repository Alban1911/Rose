#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Application Status Manager
Manages the app state and tray icon status based on initialization checks
"""

from utils.logging import get_logger
from utils.paths import get_skins_dir

log = get_logger()


class AppStatus:
    """
    Manages application status based on skin download state.
    
    Checks:
    - Skins downloaded from repository
    - Skin previews downloaded
    
    Status:
    - locked.png: Skins not downloaded OR previews not downloaded
    - golden unlocked.png: Skins and previews downloaded
    """
    
    def __init__(self, tray_manager=None):
        """
        Initialize the AppStatus manager
        
        Args:
            tray_manager: TrayManager instance to update status icon
        """
        self.tray_manager = tray_manager
        self._skins_downloaded = False
        self._previews_downloaded = False
        self._download_process_complete = False  # Track if download process is complete
        self._last_status = None  # Track last status to avoid duplicate logging
        self._last_update_time = 0  # Throttle updates
        
    def check_previews_downloaded(self) -> bool:
        """
        Check if skin previews are downloaded
        
        Returns:
            True if previews are downloaded, False otherwise
        """
        try:
            from utils.paths import get_appdata_dir
            # Check if previews directory exists and has content
            previews_dir = get_appdata_dir() / "SkinPreviews"
            if not previews_dir.exists():
                return False
            
            # Check if there are preview image files
            preview_files = list(previews_dir.rglob("*.png"))
            return len(preview_files) > 0
        except Exception as e:
            log.debug(f"Failed to check previews directory: {e}")
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
    
    
    def update_status(self, force=False):
        """
        Update the application status by checking skin download state
        
        Args:
            force: Force update even if throttled (optional)
        """
        import time
        
        # Throttle updates to prevent spam (max once per second)
        current_time = time.time()
        if not force and (current_time - self._last_update_time) < 1.0:
            return
        
        self._last_update_time = current_time
        
        # Check each component
        self._skins_downloaded = self.check_skins_downloaded()
        self._previews_downloaded = self.check_previews_downloaded()
        
        
        # Determine status level - only show unlocked if download process is complete
        all_ready = (self._skins_downloaded and self._previews_downloaded and self._download_process_complete)
        
        # Determine current status
        if all_ready:
            current_status = "unlocked"
        else:
            current_status = "locked"
        
        # Only log and update if status changed
        if current_status != self._last_status or force:
            self._last_status = current_status
            
            # Update tray icon
            if self.tray_manager:
                self.tray_manager.set_status(current_status)
            
            # Log status change
            separator = "=" * 80
            if all_ready:
                log.info(separator)
                log.info("🔓✨ APP STATUS: READY")
                log.info("   📋 Skins: Downloaded")
                log.info("   📋 Previews: Downloaded")
                log.info("   🎯 Status: Golden Unlocked")
                log.info(separator)
            else:
                log.info(separator)
                log.info("🔒 APP STATUS: DOWNLOADING")
                log.info(f"   {'✅' if self._skins_downloaded else '⏳'} Skins: {'Downloaded' if self._skins_downloaded else 'Pending'}")
                log.info(f"   {'✅' if self._previews_downloaded else '⏳'} Previews: {'Downloaded' if self._previews_downloaded else 'Pending'}")
                log.info("   🎯 Status: Locked")
                log.info(separator)
    
    def mark_skins_downloaded(self):
        """Mark skins as downloaded and update status"""
        self._skins_downloaded = True
        self.update_status(force=True)
    
    def mark_previews_downloaded(self):
        """Mark previews as downloaded and update status"""
        self._previews_downloaded = True
        self.update_status(force=True)
    
    def mark_download_process_complete(self):
        """Mark download process as complete and update status"""
        self._download_process_complete = True
        self.update_status(force=True)
    
    
    def get_status_summary(self) -> dict:
        """
        Get a summary of the current status
        
        Returns:
            Dictionary with status of each component
        """
        return {
            'skins_downloaded': self._skins_downloaded,
            'previews_downloaded': self._previews_downloaded,
            'all_ready': (self._skins_downloaded and self._previews_downloaded)
        }
    
    @property
    def is_ready(self) -> bool:
        """Check if all components are ready"""
        return (self._skins_downloaded and self._previews_downloaded)

