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
from utils.paths import get_appdata_dir

log = get_logger()


class ChromaPreviewManager:
    """Manages access to chroma preview images from SkinPreviews repository"""
    
    def __init__(self, db=None):
        # SkinPreviews repository folder (downloaded previews)
        self.skin_previews_dir = get_appdata_dir() / "SkinPreviews" / "chroma_previews"
        self.db = db  # Database instance for cross-language lookups
    
    def get_preview_path(self, champion_name: str, skin_name: str, chroma_id: Optional[int] = None, skin_id: Optional[int] = None) -> Optional[Path]:
        """Get path to preview image
        
        Args:
            champion_name: Champion name (e.g. "Garen")
            skin_name: Skin name (e.g. "Demacia Vice")
            chroma_id: Optional chroma ID. If None/0, returns base skin preview.
            skin_id: Optional skin ID to help find English name for preview lookup.
        
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
            # Convert skin name to English if needed (preview images are stored with English names)
            # Note: chroma_preview_manager doesn't have access to chroma_id_map, so we pass None
            english_skin_name = convert_to_english_skin_name(skin_id, skin_name, self.db, champion_name, chroma_id_map=None) if skin_id else skin_name
            
            # Special handling for Elementalist Lux forms - always use base skin name for preview paths
            if 99991 <= chroma_id <= 99999 or chroma_id == 99007:
                # For Elementalist Lux forms, use the base skin name instead of the current form name
                if champion_name.lower() == "lux" and "elementalist" in english_skin_name.lower():
                    # Extract the base skin name (e.g., "Elementalist Lux Dark" -> "Elementalist Lux")
                    base_skin_name = "Elementalist Lux"
                    if champion_name not in base_skin_name:
                        base_skin_name = f"{base_skin_name} {champion_name}"
                    english_skin_name = base_skin_name
                    log.debug(f"[CHROMA] Using base skin name for Elementalist Lux form preview: '{base_skin_name}'")
            
            # Special handling for Risen Legend Kai'Sa HOL chroma - use base skin name for preview paths
            if chroma_id == 145070 or chroma_id == 145071 or (champion_name.lower() == "kaisa" and skin_id in [145070, 145071]):
                # For Risen Legend Kai'Sa HOL chroma, use the base skin name instead of the HOL chroma name
                if champion_name.lower() == "kaisa" and ("risen" in english_skin_name.lower() or "immortalized" in english_skin_name.lower()):
                    # Always use "Risen Legend Kai'Sa" as the base skin name for preview paths
                    base_skin_name = "Risen Legend Kai'Sa"
                    if champion_name not in base_skin_name:
                        base_skin_name = f"{base_skin_name} {champion_name}"
                    english_skin_name = base_skin_name
                    log.debug(f"[CHROMA] Using base skin name for Risen Legend Kai'Sa HOL chroma preview: '{base_skin_name}'")
            
            # Normalize skin name: remove colons, slashes, and other special characters that might not match filesystem
            # (e.g., "PROJECT: Naafiri" becomes "PROJECT Naafiri", "K/DA" becomes "KDA")
            normalized_skin_name = english_skin_name.replace(":", "").replace("/", "")
            
            if normalized_skin_name != english_skin_name:
                log.info(f"[CHROMA] Normalized skin name: '{english_skin_name}' -> '{normalized_skin_name}'")
            
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


def get_preview_manager(db=None) -> ChromaPreviewManager:
    """Get global preview manager instance"""
    global _preview_manager
    if _preview_manager is None:
        _preview_manager = ChromaPreviewManager(db)
    elif db is not None and _preview_manager.db is None:
        # Update existing instance with database if not already set
        _preview_manager.db = db
    return _preview_manager

