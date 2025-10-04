#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-language database for League of Legends skins
Handles language detection and mapping to English names
"""

import os
import json
import requests
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
from utils.normalization import normalize_text
from .name_db import NameDB, Entry

# League of Legends supported languages
SUPPORTED_LANGUAGES = [
    "en_US",  # English (United States)
    "es_ES",  # Spanish (Spain)
    "es_MX",  # Spanish (Mexico)
    "fr_FR",  # French
    "de_DE",  # German
    "it_IT",  # Italian
    "pl_PL",  # Polish
    "ro_RO",  # Romanian
    "el_GR",  # Greek
    "pt_BR",  # Portuguese (Brazil)
    "hu_HU",  # Hungarian
    "ru_RU",  # Russian
    "tr_TR",  # Turkish
    "zh_CN",  # Chinese (Simplified)
    "zh_TW",  # Chinese (Traditional)
    "ja_JP",  # Japanese
    "ko_KR",  # Korean
]

# Language detection patterns (common words/characters)
LANGUAGE_PATTERNS = {
    "zh_CN": ["皮肤", "英雄", "冠军"],  # Chinese Simplified
    "zh_TW": ["皮膚", "英雄", "冠軍"],  # Chinese Traditional
    "ja_JP": ["スキン", "チャンピオン", "ヒーロー"],  # Japanese
    "ko_KR": ["스킨", "챔피언", "영웅"],  # Korean
    "ru_RU": ["скин", "чемпион", "герой"],  # Russian
    "de_DE": ["haut", "champion", "held"],  # German
    "fr_FR": ["peau", "champion", "héros"],  # French
    "es_ES": ["piel", "campeón", "héroe"],  # Spanish
    "pt_BR": ["pele", "campeão", "herói"],  # Portuguese
    "it_IT": ["pelle", "campione", "eroe", "campionessa", "skin"],  # Italian
    "tr_TR": ["cilt", "şampiyon", "kahraman"],  # Turkish
    "pl_PL": ["skóra", "mistrz", "bohater"],  # Polish
    "hu_HU": ["bőr", "bajnok", "hős"],  # Hungarian
    "ro_RO": ["piele", "campion", "erou"],  # Romanian
    "el_GR": ["δέρμα", "πρωταθλητής", "ήρωας"],  # Greek
}


@dataclass
class LanguageMatch:
    """Result of language detection"""
    language: str
    confidence: float
    matched_patterns: List[str]


class MultiLanguageDB:
    """Multi-language database with automatic language detection"""
    
    def __init__(self, auto_detect: bool = True, fallback_lang: str = "en_US", lcu_client=None):
        self.auto_detect = auto_detect
        self.fallback_lang = fallback_lang
        self.current_language = fallback_lang
        self.manual_language = None if auto_detect else fallback_lang
        self.lcu_client = lcu_client
        
        # Initialize only necessary databases
        self.databases: Dict[str, NameDB] = {}
        self._initialize_necessary_databases()
        
        # English database for final mapping
        self.english_db = self.databases.get("en_US")
        if not self.english_db:
            raise RuntimeError("Failed to initialize English database")
    
    def _initialize_necessary_databases(self):
        """Initialize only necessary databases (English + specified language)"""
        # Always load English database
        try:
            self.databases["en_US"] = NameDB(lang="en_US")
            print(f"[MULTILANG] Initialized English database")
        except Exception as e:
            print(f"[MULTILANG] Failed to initialize English database: {e}")
            raise
        
        # Load specified language if different from English
        if self.auto_detect:
            # In auto-detect mode, wait for LCU connection to get language
            # The LCU connection should be established by the time this is called
            lcu_lang = self._get_lcu_language()
            if lcu_lang and lcu_lang != "en_US":
                try:
                    self.databases[lcu_lang] = NameDB(lang=lcu_lang)
                    self.current_language = lcu_lang
                    print(f"[MULTILANG] Auto-detect mode: loaded LCU language '{lcu_lang}'")
                except Exception as e:
                    print(f"[MULTILANG] Failed to load LCU language '{lcu_lang}': {e}")
                    print(f"[MULTILANG] Auto-detect mode: languages will be loaded on-demand")
            else:
                print(f"[MULTILANG] Auto-detect mode: LCU language not available, will load on-demand")
        else:
            # In manual mode, load the specified language
            if self.manual_language and self.manual_language != "en_US":
                try:
                    self.databases[self.manual_language] = NameDB(lang=self.manual_language)
                    print(f"[MULTILANG] Initialized database for {self.manual_language}")
                except Exception as e:
                    print(f"[MULTILANG] Failed to initialize {self.manual_language}: {e}")
                    # Fallback to English only
                    self.manual_language = "en_US"
    
    def _get_lcu_language(self) -> Optional[str]:
        """Get client language from LCU API"""
        if not self.lcu_client:
            return None
        
        try:
            lcu_lang = self.lcu_client.get_client_language()
            if lcu_lang and lcu_lang in SUPPORTED_LANGUAGES:
                return lcu_lang
            return None
        except Exception as e:
            print(f"[MULTILANG] Failed to get LCU language: {e}")
            return None
    
    def detect_language(self, text: str) -> LanguageMatch:
        """Detect language from OCR text"""
        if not self.auto_detect and self.manual_language:
            return LanguageMatch(self.manual_language, 1.0, ["manual"])
        
        text_lower = text.lower()
        matches = {}
        
        # Check for language-specific patterns
        for lang, patterns in LANGUAGE_PATTERNS.items():
            score = 0
            matched = []
            for pattern in patterns:
                if pattern.lower() in text_lower:
                    score += 1
                    matched.append(pattern)
            if score > 0:
                matches[lang] = (score, matched)
        
        if not matches:
            # No specific patterns found, try character-based detection
            return self._character_based_detection(text)
        
        # Return best match
        best_lang = max(matches.keys(), key=lambda k: matches[k][0])
        score, matched = matches[best_lang]
        confidence = min(score / len(LANGUAGE_PATTERNS[best_lang]), 1.0)
        
        return LanguageMatch(best_lang, confidence, matched)
    
    def _character_based_detection(self, text: str) -> LanguageMatch:
        """Fallback character-based language detection"""
        # Check for Chinese characters
        if any('\u4e00' <= char <= '\u9fff' for char in text):
            return LanguageMatch("zh_CN", 0.7, ["Chinese characters"])
        
        # Check for Japanese characters
        if any('\u3040' <= char <= '\u309f' or '\u30a0' <= char <= '\u30ff' for char in text):
            return LanguageMatch("ja_JP", 0.7, ["Japanese characters"])
        
        # Check for Korean characters
        if any('\uac00' <= char <= '\ud7af' for char in text):
            return LanguageMatch("ko_KR", 0.7, ["Korean characters"])
        
        # Check for Cyrillic characters
        if any('\u0400' <= char <= '\u04ff' for char in text):
            return LanguageMatch("ru_RU", 0.7, ["Cyrillic characters"])
        
        # Check for Greek characters
        if any('\u0370' <= char <= '\u03ff' for char in text):
            return LanguageMatch("el_GR", 0.7, ["Greek characters"])
        
        # Default to English
        return LanguageMatch("en_US", 0.5, ["Default"])
    
    def find_skin_by_text(self, text: str, champ_id: Optional[int] = None) -> Optional[Entry]:
        """Find skin entry by text with automatic language detection"""
        # In auto-detect mode, prefer LCU language over pattern detection
        if self.auto_detect and self.current_language and self.current_language != "en_US":
            detected_lang = self.current_language
        else:
            # Fallback to pattern-based detection
            lang_match = self.detect_language(text)
            detected_lang = lang_match.language
        
        # Get database for detected language
        db = self.databases.get(detected_lang)
        if not db:
            # Try to load the detected language on-demand
            if detected_lang in SUPPORTED_LANGUAGES:
                try:
                    self.databases[detected_lang] = NameDB(lang=detected_lang)
                    db = self.databases[detected_lang]
                    # print(f"[MULTILANG] Loaded database for {detected_lang} on-demand")  # Disabled for cleaner logs
                except Exception as e:
                    print(f"[MULTILANG] Failed to load {detected_lang}: {e}")
                    db = self.databases.get(self.fallback_lang)
            else:
                db = self.databases.get(self.fallback_lang)
        
        if not db:
            print(f"[MULTILANG] No fallback database available")
            return None
        
        # Find entry in detected language
        entry = self._find_entry_in_db(db, text, champ_id)
        if not entry:
            # print(f"[MULTILANG] No match found in {detected_lang}")  # Disabled for cleaner logs
            return None
        
        # print(f"[MULTILANG] Found match in {detected_lang}: {entry.key}")  # Disabled for cleaner logs
        return entry
    
    def _find_entry_in_db(self, db: NameDB, text: str, champ_id: Optional[int] = None) -> Optional[Entry]:
        """Find entry in specific database"""
        norm_txt = normalize_text(text)
        pairs = db.normalized_entries(champ_id) or []
        
        if not pairs:
            return None
        
        # Find best match
        best_entry = None
        best_score = 0.0
        
        for entry, norm_key in pairs:
            # Calculate similarity score
            if norm_txt == norm_key:
                return entry  # Exact match
            
            # Fuzzy matching
            similarity = self._calculate_similarity(norm_txt, norm_key)
            if similarity > best_score and similarity > 0.7:  # Threshold
                best_score = similarity
                best_entry = entry
        
        return best_entry
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts"""
        if not text1 or not text2:
            return 0.0
        
        # Simple similarity based on common substrings
        common_chars = sum(1 for c in text1 if c in text2)
        max_len = max(len(text1), len(text2))
        
        if max_len == 0:
            return 0.0
        
        return common_chars / max_len
    
    def get_english_name(self, entry: Entry) -> Tuple[str, str]:
        """Get English names for champion and skin"""
        if not self.english_db:
            return entry.key, entry.key
        
        # Ensure English database has loaded skins for this champion
        if entry.champ_id and entry.champ_id in self.english_db.slug_by_id:
            slug = self.english_db.slug_by_id[entry.champ_id]
            self.english_db._ensure_champ(slug, entry.champ_id)
        
        # Get English champion name
        english_champ = self.english_db.champ_name_by_id.get(entry.champ_id, entry.champ_slug)
        
        # Get English skin name
        if entry.skin_id and entry.skin_id > 0:
            english_skin = self.english_db.skin_name_by_id.get(entry.skin_id, "")
            if english_skin:
                # Check if skin name already contains champion name to avoid duplication
                if english_champ.lower() in english_skin.lower():
                    english_full = english_skin
                else:
                    english_full = f"{english_champ} {english_skin}"
            else:
                # Fallback: try to find skin name from champion data
                english_full = english_champ
                # print(f"[MULTILANG] Warning: Skin ID {entry.skin_id} not found in English database")  # Disabled for cleaner logs
        else:
            english_full = english_champ
        
        return english_champ, english_full
    
    def get_available_languages(self) -> List[str]:
        """Get list of available languages"""
        return list(self.databases.keys())
    
    def get_loaded_languages(self) -> List[str]:
        """Get list of currently loaded languages"""
        return list(self.databases.keys())
    
    def set_language(self, language: str):
        """Manually set language (disables auto-detection)"""
        if language in SUPPORTED_LANGUAGES:
            # Load the language if not already loaded
            if language not in self.databases:
                try:
                    self.databases[language] = NameDB(lang=language)
                    print(f"[MULTILANG] Loaded database for {language}")
                except Exception as e:
                    print(f"[MULTILANG] Failed to load {language}: {e}")
                    return
            
            self.current_language = language
            self.manual_language = language
            self.auto_detect = False
            # print(f"[MULTILANG] Language set to {language}")  # Disabled for cleaner logs
        else:
            print(f"[MULTILANG] Language {language} not supported")
    
    def enable_auto_detection(self):
        """Enable automatic language detection"""
        self.auto_detect = True
        self.manual_language = None
        # print("[MULTILANG] Auto-detection enabled")  # Disabled for cleaner logs
