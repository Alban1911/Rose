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
from utils.normalization import normalize_text
from utils.paths import get_user_data_dir
from utils.logging import get_logger
from constants import DATA_DRAGON_API_TIMEOUT_S

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
                return json.load(open(p, "r", encoding="utf-8"))
            except Exception: 
                pass
        
        r = requests.get(url, timeout=DATA_DRAGON_API_TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
        json.dump(data, open(p, "w", encoding="utf-8"))
        return data

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
        for lang in self.langs:
            data = self._cache_json(
                f"champion_{self.ver}_{lang}.json",
                f"https://ddragon.leagueoflegends.com/cdn/{self.ver}/data/{lang}/champion.json"
            )
            lang_map: Dict[int, str] = self.champ_name_by_id_by_lang.setdefault(lang, {})
            for slug, obj in (data.get("data") or {}).items():
                try:
                    cid = int(obj.get("key"))
                    cname = obj.get("name") or slug
                    self.slug_by_id[cid] = slug
                    lang_map[cid] = cname
                    self.entries_by_champ.setdefault(slug, [])
                    self.entries_by_champ[slug].append(Entry(key=cname, kind="champion", champ_slug=slug, champ_id=cid))
                except Exception:
                    pass

    def load_champion_skins_by_id(self, champion_id: int) -> bool:
        """Load skin names for a specific champion by ID (English only, for skinId mapping)
        
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
            # Fetch champion data (English only for skinId mapping)
            lang = "en_US"
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
                        loaded_count += 1
                except Exception:
                    pass
            
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
                nk = normalize_text(e.key)
                self._norm_cache[e.key] = nk
            out.append((e, nk))
        return out
