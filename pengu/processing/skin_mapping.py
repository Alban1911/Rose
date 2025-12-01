#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin ID Mapping
Handles loading and finding skin IDs by name
"""

import json
import logging
from typing import Optional
from pathlib import Path

from utils.core.paths import get_user_data_dir

log = logging.getLogger(__name__)


class SkinMapping:
    """Manages skin ID to name mappings"""
    
    def __init__(self, shared_state):
        """Initialize skin mapping
        
        Args:
            shared_state: Shared application state
        """
        self.shared_state = shared_state
        self.skin_id_mapping: dict[str, int] = {}
        self.skin_id_name_mapping: dict[int, str] = {}  # Normalized (lowercase) names for backward compatibility
        self.skin_id_original_name_mapping: dict[int, str] = {}  # Original names with proper case
        self.skin_mapping_loaded = False
    
    def load_mapping(self) -> bool:
        """Load skin ID mapping from file
        
        Returns:
            True if loaded successfully, False otherwise
        """
        language = getattr(self.shared_state, "current_language", None)
        if not language:
            log.warning("[SkinMonitor] No language detected; cannot load mapping")
            return False
        
        mapping_path = (
            get_user_data_dir()
            / "skinid_mapping"
            / language
            / "skin_ids.json"
        )
        
        if not mapping_path.exists():
            log.warning(
                "[SkinMonitor] Skin mapping file missing: %s", mapping_path
            )
            return False
        
        try:
            with open(mapping_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "[SkinMonitor] Failed to load skin mapping %s: %s",
                mapping_path,
                exc,
            )
            return False
        
        self.skin_id_mapping.clear()
        self.skin_id_original_name_mapping.clear()
        for skin_id_str, name in data.items():
            try:
                skin_id = int(skin_id_str)
            except (TypeError, ValueError):
                continue
            original_name = (name or "").strip()
            normalized = original_name.lower()
            if normalized and normalized not in self.skin_id_mapping:
                self.skin_id_mapping[normalized] = skin_id
                self.skin_id_name_mapping[skin_id] = normalized
                self.skin_id_original_name_mapping[skin_id] = original_name  # Store original case
        
        self.skin_mapping_loaded = True
        log.info(
            "[SkinMonitor] Loaded %s skin mappings for '%s'",
            len(self.skin_id_mapping),
            language,
        )
        return True
    
    def find_skin_id_by_name(self, skin_name: str) -> Optional[int]:
        """Find skin ID by name using mapping
        
        Args:
            skin_name: Skin name to look up
            
        Returns:
            Skin ID if found, None otherwise
        """
        if not self.skin_mapping_loaded:
            if not self.load_mapping():
                return None
        
        normalized = skin_name.strip().lower()
        if normalized in self.skin_id_mapping:
            return self.skin_id_mapping[normalized]
        
        # Try partial matching
        for mapped_name, skin_id in self.skin_id_mapping.items():
            if normalized in mapped_name or mapped_name in normalized:
                return skin_id
        
        return None
    def find_skin_name_by_skin_id(self, skin_id: int) -> Optional[str]:
        """Find skin name by id using mapping

        Args:
            skin_id: Skin id to look up

        Returns:
            Skin name with original case if found, None otherwise
        """
        if not self.skin_mapping_loaded:
            if not self.load_mapping():
                return None

        # Return original name with proper case
        if skin_id in self.skin_id_original_name_mapping:
            return self.skin_id_original_name_mapping[skin_id]
        # Fallback to normalized name if original not available (for backward compatibility)
        if skin_id in self.skin_id_name_mapping:
            return self.skin_id_name_mapping[skin_id]
        return None

    def clear(self) -> None:
        """Clear mapping cache"""
        self.skin_mapping_loaded = False
        self.skin_id_mapping.clear()
        self.skin_id_original_name_mapping.clear()

