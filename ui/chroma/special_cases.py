#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma Special Cases Handler
Handles special cases for chromas (Elementalist Lux forms, HOL chromas, etc.)
"""

from typing import List, Dict, Optional
from utils.core.logging import get_logger

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
    def get_mordekaiser_forms() -> List[Dict]:
        """Get Sahn Uzal Mordekaiser Forms data structure (equivalent to chromas)"""
        forms = [
            {'id': 82998, 'name': 'Form 1', 'colors': [], 'is_owned': False, 'form_path': 'Mordekaiser/Forms/Sahn Uzal Mordekaiser Form 1.zip'},
            {'id': 82999, 'name': 'Form 2', 'colors': [], 'is_owned': False, 'form_path': 'Mordekaiser/Forms/Sahn Uzal Mordekaiser Form 2.zip'},
        ]
        log.debug(f"[CHROMA] Created {len(forms)} Sahn Uzal Mordekaiser Forms with real IDs (82998, 82999)")
        return forms
    
    @staticmethod
    def get_morgana_forms() -> List[Dict]:
        """Get Spirit Blossom Morgana Forms data structure (equivalent to chromas)"""
        forms = [
            {'id': 25999, 'name': 'Form 1', 'colors': [], 'is_owned': False, 'form_path': 'Morgana/Forms/Spirit Blossom Morgana Form 1.zip'},
        ]
        log.debug(f"[CHROMA] Created {len(forms)} Spirit Blossom Morgana Forms with real ID (25999)")
        return forms
    
    @staticmethod
    def get_sett_forms() -> List[Dict]:
        """Get Radiant Sett Forms data structure (equivalent to chromas)"""
        forms = [
            {'id': 875998, 'name': 'Form 2', 'colors': [], 'is_owned': False, 'form_path': 'Sett/Forms/Radiant Sett Form 2.zip'},
            {'id': 875999, 'name': 'Form 3', 'colors': [], 'is_owned': False, 'form_path': 'Sett/Forms/Radiant Sett Form 3.zip'},
        ]
        log.debug(f"[CHROMA] Created {len(forms)} Radiant Sett Forms with real IDs (875998, 875999)")
        return forms
    
    @staticmethod
    def get_seraphine_forms() -> List[Dict]:
        """Get KDA Seraphine Forms data structure (equivalent to chromas)"""
        forms = [
            {'id': 147002, 'name': 'Form 1', 'colors': [], 'is_owned': False, 'form_path': 'Seraphine/Forms/KDA Seraphine Form 1.zip'},
            {'id': 147003, 'name': 'Form 2', 'colors': [], 'is_owned': False, 'form_path': 'Seraphine/Forms/KDA Seraphine Form 2.zip'},
        ]
        log.debug(f"[CHROMA] Created {len(forms)} KDA Seraphine Forms with real IDs (147002, 147003)")
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
            {'id': 103087, 'skinId': 103085, 'name': 'Form 2', 'colors': [], 'is_owned': False},
        ]
        log.debug(f"[CHROMA] Created {len(chromas)} Risen Legend Ahri HOL chromas with real skin IDs (103086, 103087)")
        return chromas
    
    @staticmethod
    def is_elementalist_form(chroma_id: int) -> bool:
        """Check if chroma_id is an Elementalist Lux form"""
        return 99991 <= chroma_id <= 99999
    
    @staticmethod
    def is_mordekaiser_form(chroma_id: int) -> bool:
        """Check if chroma_id is a Sahn Uzal Mordekaiser form"""
        return chroma_id in (82998, 82999)
    
    @staticmethod
    def is_morgana_form(chroma_id: int) -> bool:
        """Check if chroma_id is a Spirit Blossom Morgana form"""
        return chroma_id == 25999
    
    @staticmethod
    def is_sett_form(chroma_id: int) -> bool:
        """Check if chroma_id is a Radiant Sett form"""
        return chroma_id in (875998, 875999)
    
    @staticmethod
    def is_seraphine_form(chroma_id: int) -> bool:
        """Check if chroma_id is a KDA Seraphine form"""
        return chroma_id in (147002, 147003)
    
    @staticmethod
    def is_hol_chroma(chroma_id: int) -> bool:
        """Check if chroma_id is a HOL chroma"""
        return chroma_id in (145071, 103086, 103087)
    
    @staticmethod
    def get_chromas_for_special_skin(skin_id: int) -> Optional[List[Dict]]:
        """Get chromas for special skins (Elementalist Lux, HOL chromas, Sahn Uzal Mordekaiser)
        
        Returns:
            List of chroma dicts or None if not a special skin
        """
        # Special case: Elementalist Lux (skin ID 99007) has Forms instead of chromas
        if skin_id == 99007:
            return ChromaSpecialCases.get_elementalist_forms()
        
        # Special case: Sahn Uzal Mordekaiser (skin ID 82054) has Forms instead of chromas
        elif skin_id == 82054:
            return ChromaSpecialCases.get_mordekaiser_forms()
        
        # Special case: Spirit Blossom Morgana (skin ID 25080) has Forms instead of chromas
        elif skin_id == 25080:
            return ChromaSpecialCases.get_morgana_forms()
        
        # Special case: Radiant Sett (skin ID 875066) has Forms instead of chromas
        elif skin_id == 875066:
            return ChromaSpecialCases.get_sett_forms()
        
        # Special case: Radiant Sett forms (IDs 875998, 875999) are treated as forms of base skin
        elif skin_id in (875998, 875999):
            return ChromaSpecialCases.get_sett_forms()
        
        # Special case: KDA Seraphine (skin ID 147001) has Forms instead of chromas
        elif skin_id == 147001:
            return ChromaSpecialCases.get_seraphine_forms()
        
        # Special case: KDA Seraphine forms (IDs 147002, 147003) are treated as forms of base skin
        elif skin_id in (147002, 147003):
            return ChromaSpecialCases.get_seraphine_forms()
        
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
        
        # Special case: Form 2 Ahri (skin ID 103087) is treated as a chroma of Risen Legend Ahri
        elif skin_id == 103087:
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
        
        if ChromaSpecialCases.is_mordekaiser_form(chroma_id):
            return 82054  # Sahn Uzal Mordekaiser base skin ID
        
        if ChromaSpecialCases.is_morgana_form(chroma_id):
            return 25080  # Spirit Blossom Morgana base skin ID
        
        if ChromaSpecialCases.is_sett_form(chroma_id):
            return 875066  # Radiant Sett base skin ID
        
        if ChromaSpecialCases.is_seraphine_form(chroma_id):
            return 147001  # KDA Seraphine base skin ID
        
        if chroma_id == 145071:
            return 145070  # Risen Legend Kai'Sa base skin ID
        
        if chroma_id == 103086:
            return 103085  # Risen Legend Ahri base skin ID
        
        if chroma_id == 103087:
            return 103085  # Risen Legend Ahri base skin ID
        
        return None

