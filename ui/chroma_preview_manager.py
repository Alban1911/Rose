#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma Preview Manager
Provides access to chroma preview images from downloaded SkinPreviews repository
"""

from pathlib import Path
from typing import Optional
from utils.logging import get_logger
from utils.utilities import convert_to_english_skin_name
from utils.paths import get_skins_dir

log = get_logger()


class ChromaPreviewManager:
    """Manages access to chroma preview images from merged lolskins database"""
    
    def __init__(self, db=None):
        # Merged database folder (skins + previews)
        self.skins_dir = get_skins_dir()
        self.db = db  # Kept for compatibility, not used
    
    def get_preview_path(self, champion_name: str, skin_name: str, chroma_id: Optional[int] = None, skin_id: Optional[int] = None, champion_id: Optional[int] = None) -> Optional[Path]:
        """Get path to preview image from merged database
        
        Args:
            champion_name: Champion name (for logging only)
            skin_name: Skin name (for logging only)
            chroma_id: Optional chroma ID. If None/0, returns base skin preview.
            skin_id: Optional skin ID to help find the correct directory.
            champion_id: Required champion ID for path construction.
        
        Returns:
            Path to preview image if it exists, None otherwise
        
        Structure:
            - Base skin: {champion_id}/{skin_id}/{skin_id}.png
            - Chroma: {champion_id}/{skin_id}/{chroma_id}/{chroma_id}.png
        """
        log.info(f"[CHROMA] get_preview_path called with: champion='{champion_name}', skin='{skin_name}', chroma_id={chroma_id}, skin_id={skin_id}, champion_id={champion_id}")
        
        if not self.skins_dir.exists():
            log.warning(f"[CHROMA] Skins directory does not exist: {self.skins_dir}")
            return None
        
        try:
            # Champion ID is required for path construction
            if champion_id is None:
                log.warning("[CHROMA] No champion_id provided - required for path construction")
                return None
            
            champion_dir = self.skins_dir / str(champion_id)
            if not champion_dir.exists():
                log.warning(f"[CHROMA] Champion directory not found: {champion_dir}")
                return None
            
            if chroma_id is None or chroma_id == 0:
                # Base skin preview: {champion_id}/{skin_id}/{skin_id}.png
                if not skin_id:
                    log.warning("[CHROMA] No skin_id provided for base skin preview - UIA should have resolved this")
                    return None
                
                skin_dir = champion_dir / str(skin_id)
                if not skin_dir.exists():
                    log.warning(f"[CHROMA] Skin directory not found: {skin_dir}")
                    return None
                
                preview_path = skin_dir / f"{skin_id}.png"
                log.info(f"[CHROMA] Looking for base skin preview at: {preview_path}")
            else:
                # Chroma preview: {champion_id}/{skin_id}/{chroma_id}/{chroma_id}.png
                if not skin_id:
                    log.warning("[CHROMA] No skin_id provided for chroma preview - UIA should have resolved this")
                    return None
                
                skin_dir = champion_dir / str(skin_id)
                if not skin_dir.exists():
                    log.warning(f"[CHROMA] Skin directory not found: {skin_dir}")
                    return None
                
                chroma_dir = skin_dir / str(chroma_id)
                if not chroma_dir.exists():
                    log.warning(f"[CHROMA] Chroma directory not found: {chroma_dir}")
                    return None
                
                preview_path = chroma_dir / f"{chroma_id}.png"
                log.info(f"[CHROMA] Looking for chroma preview at: {preview_path}")
            
            if preview_path.exists():
                log.info(f"[CHROMA] ✅ Found preview: {preview_path}")
                return preview_path
            else:
                log.warning(f"[CHROMA] ❌ Preview not found at: {preview_path}")
                return None
            
        except Exception as e:
            log.error(f"[CHROMA] Error building preview path: {e}")
            import traceback
            log.error(traceback.format_exc())
            return None
    


# Global instance
_preview_manager = None


def get_preview_manager(db=None) -> ChromaPreviewManager:
    """Get global preview manager instance"""
    global _preview_manager
    if _preview_manager is None:
        _preview_manager = ChromaPreviewManager(db)
    elif db is not None and _preview_manager.db is None:
        # Update existing instance with database if not already set
        _preview_manager.db = db
    return _preview_manager

