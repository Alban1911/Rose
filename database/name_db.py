#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data Dragon name database
"""

import os
import json
import requests
from dataclasses import dataclass
from typing import Optional, List, Dict
# Note: normalize_text removed - using simple normalization instead
from utils.paths import get_user_data_dir
from utils.logging import get_logger
from config import DATA_DRAGON_API_TIMEOUT_S

log = get_logger()


# Use user data directory for cache to avoid permission issues
CACHE = str(get_user_data_dir() / "cache")
os.makedirs(CACHE, exist_ok=True)


@dataclass
class Entry:
    key: str
    kind: str  # "skin" | "champion"
    champ_slug: str
    champ_id: int
    skin_id: Optional[int] = None


class NameDB:
    """Data Dragon name database"""
    
    def __init__(self, lang: str = "fr_FR", load_all_skins: bool = False):
        self.ver: Optional[str] = None
        self.langs: List[str] = self._resolve_langs_spec(lang)
        self.canonical_lang: Optional[str] = "en_US" if "en_US" in self.langs else (self.langs[0] if self.langs else "en_US")
        self.slug_by_id: Dict[int, str] = {}
        self.champ_name_by_id_by_lang: Dict[str, Dict[int, str]] = {}
        self.champ_name_by_id: Dict[int, str] = {}
        self.entries_by_champ: Dict[str, List[Entry]] = {}
        self.skin_name_by_id: Dict[int, str] = {}
        self.champion_skins: Dict[str, Dict[int, str]] = {}  # champ_slug -> {skin_id: skin_name}
        self._skins_loaded: set = set()
        self._norm_cache: Dict[str, str] = {}
        self._load_versions()
        self._load_index()
        self.champ_name_by_id = self.champ_name_by_id_by_lang.get(self.canonical_lang, {})
        
        # Note: Skins are now loaded on-demand per champion (lazy loading)
        # Preloading all skins is disabled by default as it's too slow (171 HTTP requests)

    def _cache_json(self, name: str, url: str):
        """Cache JSON data locally"""
        p = os.path.join(CACHE, name)
        if os.path.isfile(p):
            try: 
                log.debug(f"[NameDB] Using cached data: {name}")
                return json.load(open(p, "r", encoding="utf-8"))
            except Exception: 
                log.debug(f"[NameDB] Cached file corrupted, re-downloading: {name}")
                pass
        
        log.info(f"[NameDB] Downloading language data: {name}")
        log.debug(f"[NameDB] Download URL: {url}")
        
        try:
            r = requests.get(url, timeout=DATA_DRAGON_API_TIMEOUT_S)
            r.raise_for_status()
            data = r.json()
            json.dump(data, open(p, "w", encoding="utf-8"))
            log.info(f"[NameDB] ✓ Language data downloaded and cached: {name}")
            return data
        except Exception as e:
            log.error(f"[NameDB] ✗ Failed to download language data {name}: {e}")
            raise

    def _load_versions(self):
        """Load Data Dragon versions"""
        versions = self._cache_json("versions.json", "https://ddragon.leagueoflegends.com/api/versions.json")
        self.ver = versions[0]

    def _fetch_languages(self) -> List[str]:
        """Fetch available languages"""
        data = self._cache_json("languages.json", "https://ddragon.leagueoflegends.com/cdn/languages.json")
        return [str(x) for x in data if isinstance(x, str)]

    def _resolve_langs_spec(self, spec: str) -> List[str]:
        """Resolve language specification"""
        if not spec or spec.strip().lower() in ("default", "auto"):
            return ["fr_FR"]
        s = spec.strip()
        if s.lower() == "all":
            try: 
                return self._fetch_languages()
            except Exception: 
                return ["en_US", "fr_FR"]
        if "," in s:
            return [x.strip() for x in s.split(",") if x.strip()]
        return [s]

    def _load_index(self):
        """Load champion index"""
        log.info(f"[NameDB] Loading champion data for {len(self.langs)} language(s): {', '.join(self.langs)}")
        
        for lang in self.langs:
            log.info(f"[NameDB] Loading champion data for language: {lang}")
            data = self._cache_json(
                f"champion_{self.ver}_{lang}.json",
                f"https://ddragon.leagueoflegends.com/cdn/{self.ver}/data/{lang}/champion.json"
            )
            lang_map: Dict[int, str] = self.champ_name_by_id_by_lang.setdefault(lang, {})
            champion_count = 0
            for slug, obj in (data.get("data") or {}).items():
                try:
                    cid = int(obj.get("key"))
                    cname = obj.get("name") or slug
                    self.slug_by_id[cid] = slug
                    lang_map[cid] = cname
                    self.entries_by_champ.setdefault(slug, [])
                    self.entries_by_champ[slug].append(Entry(key=cname, kind="champion", champ_slug=slug, champ_id=cid))
                    champion_count += 1
                except Exception:
                    pass
            
            log.info(f"[NameDB] ✓ Loaded {champion_count} champions for language: {lang}")
        
        log.info(f"[NameDB] ✓ Champion data loading complete for all languages")

    def load_champion_skins_by_id(self, champion_id: int) -> bool:
        """Load skin names for a specific champion by ID (in current database language)
        
        Args:
            champion_id: Champion ID to load skins for
            
        Returns:
            True if skins were loaded successfully
        """
        slug = self.slug_by_id.get(champion_id)
        if not slug:
            log.debug(f"[NameDB] Champion ID {champion_id} not found in slug mapping")
            return False
        
        # Check if already loaded
        if slug in self._skins_loaded:
            return True
        
        try:
            # Fetch champion data using current database language
            lang = self.canonical_lang
            data = self._cache_json(
                f"champion_{self.ver}_{lang}_{slug}.json",
                f"https://ddragon.leagueoflegends.com/cdn/{self.ver}/data/{lang}/champion/{slug}.json"
            )
            
            champ_data = (data.get("data") or {}).get(slug)
            if not champ_data:
                return False
            
            skins = champ_data.get("skins") or []
            loaded_count = 0
            champ_name = champ_data.get("name", slug)
            
            # Load all skins for this champion
            champion_skins = {}  # Local dict for this champion
            for s in skins:
                try:
                    sid = int(s.get("id", 0))
                    num = int(s.get("num", -1))
                    sname = s.get("name") or "default"
                    
                    # For base skin (num=0), use champion name
                    if num == 0 or sname == "default":
                        sname = champ_name
                    
                    # Store skin name by ID (English only)
                    if sid > 0:
                        self.skin_name_by_id[sid] = sname
                        champion_skins[sid] = sname  # Also store in champion-specific dict
                        loaded_count += 1
                except Exception:
                    pass
            
            # Store champion skins for direct matching
            self.champion_skins[slug] = champion_skins
            
            self._skins_loaded.add(slug)
            log.debug(f"[NameDB] Loaded {loaded_count} skins for {slug}")
            return True
            
        except Exception as e:
            log.debug(f"[NameDB] Failed to load skins for {slug}: {e}")
            return False
    
    def _ensure_champ(self, slug: str, champ_id: int) -> None:
        """Ensure champion data is loaded"""
        if slug in self._skins_loaded:
            return
        
        out = self.entries_by_champ.setdefault(slug, [])
        keys_seen: set = set()
        
        for lang in self.langs:
            try:
                data = self._cache_json(
                    f"champ_{slug}_{self.ver}_{lang}.json",
                    f"https://ddragon.leagueoflegends.com/cdn/{self.ver}/data/{lang}/champion/{slug}.json",
                )
                champ = ((data.get("data") or {}).get(slug, {}) or {})
                skins = champ.get("skins") or []
                cname = (
                    self.champ_name_by_id_by_lang.get(lang, {}).get(champ_id)
                    or self.champ_name_by_id.get(champ_id)
                    or slug
                )
                
                for s in skins:
                    try:
                        sid = int(s.get("id"))
                        sname = (s.get("name") or "").strip()
                        num = int(s.get("num") or 0)
                        if sid:
                            self.skin_name_by_id[sid] = sname
                        if num == 0 or not sname:
                            continue
                        full = f"{cname} {sname}"
                        for label in (full, sname):
                            if label in keys_seen:
                                continue
                            out.append(
                                Entry(key=label, kind="skin", champ_slug=slug, champ_id=champ_id, skin_id=sid)
                            )
                            keys_seen.add(label)
                    except Exception:
                        pass
            except Exception:
                pass
        self._skins_loaded.add(slug)

    def candidates_for_champ(self, champ_id: Optional[int]) -> List[Entry]:
        """Get candidates for a champion"""
        if champ_id and champ_id in self.slug_by_id:
            slug = self.slug_by_id[champ_id]
            self._ensure_champ(slug, champ_id)
            return self.entries_by_champ.get(slug, [])
        
        if not hasattr(self, "_global_entries") or self._global_entries is None:
            glb = []
            for lang, mp in self.champ_name_by_id_by_lang.items():
                for cid, nm in mp.items():
                    slug = self.slug_by_id.get(cid)
                    if not slug: 
                        continue
                    glb.append(Entry(key=nm, kind="champion", champ_slug=slug, champ_id=cid))
            self._global_entries = glb
        return self._global_entries

    def normalized_entries(self, champ_id: Optional[int]) -> List[tuple]:
        """Get normalized entries for a champion"""
        entries = self.candidates_for_champ(champ_id)
        out = []
        for e in entries:
            nk = getattr(self, "_norm_cache", {}).get(e.key)
            if nk is None:
                # Simple normalization: just lowercase and strip
                nk = e.key.lower().strip() if e.key else ""
                self._norm_cache[e.key] = nk
            out.append((e, nk))
        return out
    
    def get_english_skin_name_by_id(self, skin_id: int) -> Optional[str]:
        """Get English skin name by skin ID
        
        Args:
            skin_id: The skin ID to look up
            
        Returns:
            English skin name if found, None otherwise
        """
        # First check if we already have it cached
        if skin_id in self.skin_name_by_id:
            cached_name = self.skin_name_by_id[skin_id]
            # If it's already English (from canonical_lang), return it
            if self.canonical_lang == "en_US":
                return cached_name
        
        # Find the champion for this skin ID
        champion_slug = None
        for slug, skins in self.champion_skins.items():
            if skin_id in skins:
                champion_slug = slug
                break
        
        if not champion_slug:
            log.debug(f"[NameDB] No champion found for skin ID {skin_id}")
            return None
        
        # Load English skin data for this champion
        try:
            if "en_US" not in self.langs:
                log.debug(f"[NameDB] English not loaded, loading champion {champion_slug}")
                # Temporarily add English to languages if not already loaded
                self.langs.append("en_US")
            
            data = self._cache_json(
                f"champion_{self.ver}_en_US_{champion_slug}.json",
                f"https://ddragon.leagueoflegends.com/cdn/{self.ver}/data/en_US/champion/{champion_slug}.json"
            )
            
            champ_data = (data.get("data") or {}).get(champion_slug)
            if not champ_data:
                return None
            
            skins = champ_data.get("skins") or []
            champ_name = champ_data.get("name", champion_slug)
            
            for s in skins:
                try:
                    sid = int(s.get("id", 0))
                    num = int(s.get("num", -1))
                    sname = s.get("name") or "default"
                    
                    if sid == skin_id:
                        # For base skin (num=0), use champion name
                        if num == 0 or sname == "default":
                            return champ_name
                        return sname
                except Exception:
                    pass
            
            return None
            
        except Exception as e:
            log.debug(f"[NameDB] Failed to load English skin name for {skin_id}: {e}")
            return None
    
    def get_english_skin_names_for_champion(self, champion_slug: str) -> Dict[int, str]:
        """Get English skin names for a specific champion
        
        Args:
            champion_slug: The champion slug (e.g., 'ezreal')
            
        Returns:
            Dictionary mapping skin_id to English skin name
        """
        try:
            # If we're already using English, return current skins
            if self.canonical_lang == "en_US":
                return self.champion_skins.get(champion_slug, {})
            
            # Load English skins for this champion
            lang = "en_US"
            data = self._cache_json(
                f"champion_{self.ver}_{lang}_{champion_slug}.json",
                f"https://ddragon.leagueoflegends.com/cdn/{self.ver}/data/{lang}/champion/{champion_slug}.json"
            )
            
            champ_data = (data.get("data") or {}).get(champion_slug)
            if not champ_data:
                return {}
            
            english_skins = {}
            skins = champ_data.get("skins", [])
            for skin in skins:
                skin_id = skin.get("id")
                skin_name = skin.get("name")
                if skin_id and skin_name:
                    english_skins[skin_id] = skin_name
            
            return english_skins
            
        except Exception as e:
            log.debug(f"[NameDB] Failed to load English skins for {champion_slug}: {e}")
            return {}
    
    def update_language(self, new_lang: str) -> bool:
        """Update the database language and reload data
        
        Args:
            new_lang: New language code (e.g., 'fr_FR', 'en_US')
            
        Returns:
            True if language was updated successfully
        """
        try:
            if new_lang == self.canonical_lang:
                log.debug(f"[NameDB] Language already set to {new_lang}")
                return True
            
            log.info(f"[NameDB] 🔄 Starting language update: {self.canonical_lang} → {new_lang}")
            
            # Update language settings
            self.langs = self._resolve_langs_spec(new_lang)
            old_canonical = self.canonical_lang
            self.canonical_lang = "en_US" if "en_US" in self.langs else (self.langs[0] if self.langs else "en_US")
            
            log.info(f"[NameDB] Clearing cached data for language change...")
            
            # Clear cached data that needs to be reloaded
            self.champion_skins.clear()
            self._skins_loaded.clear()
            self._norm_cache.clear()
            
            # Reload entries for the new language
            self._load_index()
            
            # Update champion names AFTER loading the data
            self.champ_name_by_id = self.champ_name_by_id_by_lang.get(self.canonical_lang, {})
            
            log.info(f"[NameDB] ✅ Language update complete: {self.canonical_lang}")
            return True
            
        except Exception as e:
            log.error(f"[NameDB] ❌ Failed to update language to {new_lang}: {e}")
            return False