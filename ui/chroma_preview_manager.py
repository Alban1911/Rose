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
            english_skin_name = self._convert_to_english_skin_name(champion_name, skin_name, skin_id)
            
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
    
    def _convert_to_english_skin_name(self, champion_name: str, skin_name: str, skin_id: Optional[int] = None) -> str:
        """Convert skin name to English for preview image lookup using database
        
        Args:
            champion_name: Champion name (e.g. "Bard")
            skin_name: Skin name in current language (e.g. "Bard fleur spirituelle")
            skin_id: Optional skin ID to help with conversion
            
        Returns:
            English skin name (e.g. "Spirit Blossom Bard")
        """
        # Special handling for Kai'Sa skins - always use "Risen Legend Kai'Sa" for preview paths
        # This must be checked BEFORE database lookup to prevent override
        log.debug(f"[CHROMA] Checking Kai'Sa special handling: champion='{champion_name}', skin_id={skin_id}")
        champion_lower = champion_name.lower().replace("'", "")
        if champion_lower == "kaisa" and skin_id in [145070, 145071]:
            log.debug(f"[CHROMA] Special handling for Kai'Sa skin ID {skin_id} - using 'Risen Legend Kai'Sa' for preview paths")
            return "Risen Legend Kai'Sa"
        
        # Special handling for Ahri skins - always use "Risen Legend Ahri" for preview paths
        # This must be checked BEFORE database lookup to prevent override
        log.debug(f"[CHROMA] Checking Ahri special handling: champion='{champion_name}', skin_id={skin_id}")
        if champion_lower == "ahri" and skin_id in [103085, 103086]:
            log.debug(f"[CHROMA] Special handling for Ahri skin ID {skin_id} - using 'Risen Legend Ahri' for preview paths")
            return "Risen Legend Ahri"
        
        # Try to get English name from database using skin ID
        if skin_id and hasattr(self, 'db') and self.db:
            try:
                log.debug(f"[CHROMA] Attempting database lookup for skin ID {skin_id}")
                english_name = self.db.get_english_skin_name_by_id(skin_id)
                if english_name:
                    log.debug(f"[CHROMA] Converted skin name via database: '{skin_name}' -> '{english_name}' (ID: {skin_id})")
                    # Override database result for Kai'Sa skins
                    if champion_name.lower() == "kaisa" and skin_id in [145070, 145071]:
                        log.debug(f"[CHROMA] Overriding database result for Kai'Sa skin ID {skin_id} - using 'Risen Legend Kai'Sa'")
                        return "Risen Legend Kai'Sa"
                    # Override database result for Ahri skins
                    if champion_name.lower() == "ahri" and skin_id in [103085, 103086]:
                        log.debug(f"[CHROMA] Overriding database result for Ahri skin ID {skin_id} - using 'Risen Legend Ahri'")
                        return "Risen Legend Ahri"
                    return english_name
                else:
                    log.debug(f"[CHROMA] No English name found in database for skin ID {skin_id}")
            except Exception as e:
                log.debug(f"[CHROMA] Database lookup failed for skin ID {skin_id}: {e}")
        else:
            log.debug(f"[CHROMA] No database available for skin ID {skin_id} (db={hasattr(self, 'db') and self.db is not None})")
        
        # Fallback: return the original name if no database conversion is available
        log.debug(f"[CHROMA] No English conversion available for '{skin_name}', using original name")
        return skin_name


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

