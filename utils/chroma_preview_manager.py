#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma Preview Manager
Provides access to chroma preview images from downloaded SkinPreviews repository
"""

from pathlib import Path
from typing import Optional
from utils.logging import get_logger
from utils.paths import get_appdata_dir

log = get_logger()


class ChromaPreviewManager:
    """Manages access to chroma preview images from SkinPreviews repository"""
    
    def __init__(self):
        # SkinPreviews repository folder (downloaded previews)
        self.skin_previews_dir = get_appdata_dir() / "SkinPreviews" / "chroma_previews"
    
    def get_preview_path(self, champion_name: str, skin_name: str, chroma_id: Optional[int] = None) -> Optional[Path]:
        """Get path to preview image
        
        Args:
            champion_name: Champion name (e.g. "Garen")
            skin_name: Skin name (e.g. "Demacia Vice")
            chroma_id: Optional chroma ID. If None/0, returns base skin preview.
        
        Returns:
            Path to preview image if it exists, None otherwise
        
        Structure:
            - Base skin: Champion/{Skin_Name} {Champion}/{Skin_Name} {Champion}.png
              Example: Garen/Demacia Vice Garen/Demacia Vice Garen.png
            - Chroma: Champion/{Skin_Name} {Champion}/chromas/{ID}.png
              Example: Garen/Demacia Vice Garen/chromas/86047.png
        """
        log.info(f"[CHROMA] get_preview_path called with: champion='{champion_name}', skin='{skin_name}', chroma_id={chroma_id}")
        
        if not self.skin_previews_dir.exists():
            log.warning(f"[CHROMA] SkinPreviews directory does not exist: {self.skin_previews_dir}")
            return None
        
        try:
            # Normalize skin name: remove colons, slashes, and other special characters that might not match filesystem
            # (e.g., "PROJECT: Naafiri" becomes "PROJECT Naafiri", "K/DA" becomes "KDA")
            normalized_skin_name = skin_name.replace(":", "").replace("/", "")
            
            if normalized_skin_name != skin_name:
                log.info(f"[CHROMA] Normalized skin name: '{skin_name}' -> '{normalized_skin_name}'")
            
            # skin_name already includes champion (e.g. "Demacia Vice Garen")
            # Build path: Champion/{skin_name}/...
            skin_dir = self.skin_previews_dir / champion_name / normalized_skin_name
            log.info(f"[CHROMA] Skin directory: {skin_dir}")
            
            if chroma_id is None or chroma_id == 0:
                # Base skin preview: {normalized_skin_name}.png
                preview_path = skin_dir / f"{normalized_skin_name}.png"
                log.info(f"[CHROMA] Looking for base skin preview at: {preview_path}")
            else:
                # Chroma preview: chromas/{ID}.png
                chromas_dir = skin_dir / "chromas"
                preview_path = chromas_dir / f"{chroma_id}.png"
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


def get_preview_manager() -> ChromaPreviewManager:
    """Get global preview manager instance"""
    global _preview_manager
    if _preview_manager is None:
        _preview_manager = ChromaPreviewManager()
    return _preview_manager

