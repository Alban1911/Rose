#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma Special Cases Handler
Handles special cases for chromas (Elementalist Lux forms, HOL chromas, etc.)
"""

from typing import List, Dict, Optional
from utils.logging import get_logger

log = get_logger()


class ChromaSpecialCases:
    """Handles special cases for chromas"""
    
    @staticmethod
    def get_elementalist_forms() -> List[Dict]:
        """Get Elementalist Lux Forms data structure (equivalent to chromas)"""
        forms = [
            {'id': 99991, 'name': 'Air', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Air.zip'},
            {'id': 99992, 'name': 'Dark', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Dark.zip'},
            {'id': 99993, 'name': 'Ice', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Ice.zip'},
            {'id': 99994, 'name': 'Magma', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Magma.zip'},
            {'id': 99995, 'name': 'Mystic', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Mystic.zip'},
            {'id': 99996, 'name': 'Nature', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Nature.zip'},
            {'id': 99997, 'name': 'Storm', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Storm.zip'},
            {'id': 99998, 'name': 'Water', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Lux Elementalist Water.zip'},
            {'id': 99999, 'name': 'Fire', 'colors': [], 'is_owned': False, 'form_path': 'Lux/Forms/Elementalist Lux Fire.zip'},
        ]
        log.debug(f"[CHROMA] Created {len(forms)} Elementalist Lux Forms with fake IDs (99991-99999)")
        return forms
    
    @staticmethod
    def get_hol_chromas() -> List[Dict]:
        """Get Risen Legend Kai'Sa HOL chroma data structure (equivalent to chromas)"""
        chromas = [
            {'id': 145071, 'skinId': 145070, 'name': 'Immortalized Legend', 'colors': [], 'is_owned': False},
        ]
        log.debug(f"[CHROMA] Created {len(chromas)} Risen Legend Kai'Sa HOL chromas with real skin ID (145071)")
        return chromas
    
    @staticmethod
    def get_ahri_hol_chromas() -> List[Dict]:
        """Get Risen Legend Ahri HOL chroma data structure (equivalent to chromas)"""
        chromas = [
            {'id': 103086, 'skinId': 103085, 'name': 'Immortalized Legend', 'colors': [], 'is_owned': False},
        ]
        log.debug(f"[CHROMA] Created {len(chromas)} Risen Legend Ahri HOL chromas with real skin ID (103086)")
        return chromas
    
    @staticmethod
    def is_elementalist_form(chroma_id: int) -> bool:
        """Check if chroma_id is an Elementalist Lux form"""
        return 99991 <= chroma_id <= 99999
    
    @staticmethod
    def is_hol_chroma(chroma_id: int) -> bool:
        """Check if chroma_id is a HOL chroma"""
        return chroma_id in (145071, 103086)
    
    @staticmethod
    def get_chromas_for_special_skin(skin_id: int) -> Optional[List[Dict]]:
        """Get chromas for special skins (Elementalist Lux, HOL chromas)
        
        Returns:
            List of chroma dicts or None if not a special skin
        """
        # Special case: Elementalist Lux (skin ID 99007) has Forms instead of chromas
        if skin_id == 99007:
            return ChromaSpecialCases.get_elementalist_forms()
        
        # Special case: Risen Legend Kai'Sa (skin ID 145070) has HOL chroma instead of regular chromas
        elif skin_id == 145070:
            return ChromaSpecialCases.get_hol_chromas()
        
        # Special case: Immortalized Legend Kai'Sa (skin ID 145071) is treated as a chroma of Risen Legend
        elif skin_id == 145071:
            return ChromaSpecialCases.get_hol_chromas()
        
        # Special case: Risen Legend Ahri (skin ID 103085) has HOL chroma instead of regular chromas
        elif skin_id == 103085:
            return ChromaSpecialCases.get_ahri_hol_chromas()
        
        # Special case: Immortalized Legend Ahri (skin ID 103086) is treated as a chroma of Risen Legend Ahri
        elif skin_id == 103086:
            return ChromaSpecialCases.get_ahri_hol_chromas()
        
        return None
    
    @staticmethod
    def get_base_skin_id_for_special(chroma_id: int) -> Optional[int]:
        """Get base skin ID for special chromas
        
        Returns:
            Base skin ID or None if not a special chroma
        """
        if ChromaSpecialCases.is_elementalist_form(chroma_id):
            return 99007  # Elementalist Lux base skin ID
        
        if chroma_id == 145071:
            return 145070  # Risen Legend Kai'Sa base skin ID
        
        if chroma_id == 103086:
            return 103085  # Risen Legend Ahri base skin ID
        
        return None

