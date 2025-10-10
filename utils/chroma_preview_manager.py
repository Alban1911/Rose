#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chroma Preview Manager
On-demand downloading and caching of chroma preview images
"""

import re
import requests
from pathlib import Path
from typing import Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.logging import get_logger
from utils.paths import get_skins_dir
from config import CHROMA_DOWNLOAD_TIMEOUT_S

log = get_logger()


class ChromaPreviewManager:
    """Manages on-demand download and caching of chroma preview images"""
    
    def __init__(self):
        self.skins_dir = get_skins_dir()
        self.cache_dir = self.skins_dir.parent / "previewcache"
        self.cache_dir.mkdir(exist_ok=True)
        self.completion_file = self.cache_dir / "finishedbuildingpreview.txt"
        self.completed_champions = self._load_completed_champions()
    
    def _load_completed_champions(self) -> Set[str]:
        """Load list of champions that have completed preview downloads"""
        if not self.completion_file.exists():
            return set()
        
        try:
            content = self.completion_file.read_text(encoding='utf-8')
            champions = set(line.strip() for line in content.splitlines() if line.strip())
            log.debug(f"[CHROMA] Loaded {len(champions)} champions with completed previews")
            return champions
        except Exception as e:
            log.warning(f"[CHROMA] Error loading completion file: {e}")
            return set()
    
    def _mark_champion_complete(self, champion_name: str):
        """Mark a champion as having completed preview downloads"""
        try:
            self.completed_champions.add(champion_name)
            
            # Write all completed champions to file
            with open(self.completion_file, 'w', encoding='utf-8') as f:
                for champ in sorted(self.completed_champions):
                    f.write(f"{champ}\n")
            
            log.debug(f"[CHROMA] Marked {champion_name} as complete")
        except Exception as e:
            log.warning(f"[CHROMA] Failed to mark champion complete: {e}")
    
    def is_champion_complete(self, champion_name: str) -> bool:
        """Check if champion previews are already downloaded"""
        return champion_name in self.completed_champions
    
    def download_champion_previews(self, champion_name: str) -> bool:
        """Download all chroma previews for a specific champion"""
        try:
            # Check if already complete
            if self.is_champion_complete(champion_name):
                log.debug(f"[CHROMA] {champion_name} previews already downloaded")
                return True
            
            log.info(f"[CHROMA] Downloading previews for {champion_name}...")
            
            # Find all README files for this champion
            # Check both "chromas" and "Chromas" directories (case sensitivity issue)
            chromas_base = self.skins_dir / champion_name / "chromas"
            if not chromas_base.exists():
                chromas_base = self.skins_dir / champion_name / "Chromas"
            
            if not chromas_base.exists():
                log.debug(f"[CHROMA] No chromas folder for {champion_name}")
                return False
            
            readme_files = list(chromas_base.glob("*/README.md"))
            
            if not readme_files:
                log.debug(f"[CHROMA] No READMEs found for {champion_name}")
                return False
            
            log.info(f"[CHROMA] Found {len(readme_files)} skins with chromas for {champion_name}")
            
            # Download previews for each README in parallel
            total_downloaded = 0
            total_existing = 0
            
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = {}
                for readme_idx, readme_path in enumerate(readme_files, 1):
                    future = executor.submit(self._download_readme_previews, readme_path, champion_name, readme_idx, len(readme_files))
                    futures[future] = readme_path
                
                for future in as_completed(futures):
                    try:
                        downloaded, existing = future.result()
                        total_downloaded += downloaded
                        total_existing += existing
                    except Exception as e:
                        log.debug(f"[CHROMA] Download task failed: {e}")
            
            log.info(f"[CHROMA] ✓ {champion_name}: {total_downloaded} downloaded, {total_existing} existing")
            
            # Mark as complete
            self._mark_champion_complete(champion_name)
            
            return True
            
        except Exception as e:
            log.error(f"[CHROMA] Failed to download previews for {champion_name}: {e}")
            return False
    
    def _download_readme_previews(self, readme_path: Path, champion_name: str, readme_idx: int, total_readmes: int):
        """Download previews for a single README"""
        skin_name = readme_path.parent.name
        log.info(f"[CHROMA]   {skin_name} [{readme_idx}/{total_readmes}]")
        
        downloaded = 0
        existing = 0
        
        try:
            content = readme_path.read_text(encoding='utf-8')
            
            # Find all image URLs - pattern: ![chromaId](url)
            image_pattern = r'!\[(\d+)\]\((https?://[^\)]+)\)'
            matches = re.findall(image_pattern, content, re.IGNORECASE)
            
            for alt_text, url in matches:
                try:
                    chroma_id = int(alt_text)
                    
                    # Save to cache folder
                    image_file = self.cache_dir / f"{chroma_id}.png"
                    
                    if image_file.exists():
                        existing += 1
                        continue
                    
                    # Download image
                    response = requests.get(url, timeout=CHROMA_DOWNLOAD_TIMEOUT_S)
                    response.raise_for_status()
                    image_file.write_bytes(response.content)
                    downloaded += 1
                    
                except Exception as e:
                    log.debug(f"[CHROMA] Failed to download {alt_text}: {e}")
            
            if downloaded > 0:
                log.info(f"[CHROMA]     ✓ {downloaded} previews")
        
        except Exception as e:
            log.debug(f"[CHROMA] README error: {e}")
        
        return downloaded, existing
    
    def get_preview_path(self, chroma_id: int) -> Optional[Path]:
        """Get path to cached preview image for a chroma ID"""
        image_file = self.cache_dir / f"{chroma_id}.png"
        return image_file if image_file.exists() else None


# Global instance
_preview_manager = None


def get_preview_manager() -> ChromaPreviewManager:
    """Get global preview manager instance"""
    global _preview_manager
    if _preview_manager is None:
        _preview_manager = ChromaPreviewManager()
    return _preview_manager

