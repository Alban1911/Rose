#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Downloader
Automatically downloads skins from the GitHub repository
"""

import time
import requests
from pathlib import Path
from typing import Callable, List, Dict, Optional
from utils.logging import get_logger
from utils.paths import get_skins_dir
from config import (
    API_POLITENESS_DELAY_S, APP_USER_AGENT,
    DEFAULT_SKIN_DOWNLOAD_TIMEOUT_S, SKIN_DOWNLOAD_STREAM_TIMEOUT_S
)

log = get_logger()

ProgressCallback = Callable[[int, Optional[str]], None]


class SkinDownloader:
    """Downloads skins from the GitHub repository"""
    
    def __init__(self, target_dir: Path = None, repo_url: str = "https://github.com/darkseal-org/lol-skins"):
        self.repo_url = repo_url
        self.api_base = "https://api.github.com/repos/darkseal-org/lol-skins"
        # Use user data directory for skins to avoid permission issues
        self.target_dir = target_dir or get_skins_dir()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': APP_USER_AGENT,
            'Accept': 'application/vnd.github.v3+json'
        })
        
    def get_repo_contents(self, path: str = "skins") -> List[Dict]:
        """Get the contents of a directory from the GitHub repository"""
        url = f"{self.api_base}/contents/{path}"
        
        try:
            response = self.session.get(url, timeout=DEFAULT_SKIN_DOWNLOAD_TIMEOUT_S)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            log.error(f"Failed to fetch repository contents: {e}")
            return []
    
    def get_champion_directories(self) -> List[str]:
        """Get list of champion directories from the skins folder"""
        contents = self.get_repo_contents("skins")
        if not contents:
            return []
        
        champion_dirs = []
        for item in contents:
            if item.get('type') == 'dir':
                champion_dirs.append(item['name'])
        
        log.info(f"Found {len(champion_dirs)} champion directories")
        return champion_dirs
    
    def get_skin_files(self, champion: str) -> List[Dict]:
        """Get list of skin files for a specific champion"""
        contents = self.get_repo_contents(f"skins/{champion}")
        if not contents:
            return []
        
        skin_files = []
        for item in contents:
            if item.get('type') == 'file' and item['name'].endswith('.zip'):
                skin_files.append(item)
        
        return skin_files
    
    def download_file(self, download_url: str, local_path: Path) -> bool:
        """Download a file from GitHub"""
        try:
            response = self.session.get(download_url, timeout=SKIN_DOWNLOAD_STREAM_TIMEOUT_S, stream=True)
            response.raise_for_status()
            
            # Create directory if it doesn't exist
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            return True
        except requests.RequestException as e:
            log.error(f"Failed to download {download_url}: {e}")
            return False
        except Exception as e:
            log.error(f"Error saving file {local_path}: {e}")
            return False
    
    def download_champion_skins(self, champion: str, force_update: bool = False) -> int:
        """Download all skins for a specific champion"""
        champion_dir = self.target_dir / champion
        champion_dir.mkdir(parents=True, exist_ok=True)
        
        skin_files = self.get_skin_files(champion)
        if not skin_files:
            log.warning(f"No skin files found for {champion}")
            return 0
        
        downloaded_count = 0
        for skin_file in skin_files:
            filename = skin_file['name']
            local_path = champion_dir / filename
            
            # Skip if file exists and we're not forcing update
            if local_path.exists() and not force_update:
                log.debug(f"Skipping existing file: {filename}")
                continue
            
            log.info(f"Downloading {champion}/{filename}...")
            if self.download_file(skin_file['download_url'], local_path):
                downloaded_count += 1
                log.info(f"Successfully downloaded: {filename}")
            else:
                log.error(f"Failed to download: {filename}")
        
        return downloaded_count
    
    def download_all_skins(self, force_update: bool = False, max_champions: Optional[int] = None) -> Dict[str, int]:
        """Download skins for all champions"""
        champion_dirs = self.get_champion_directories()
        if not champion_dirs:
            log.error("No champion directories found")
            return {}
        
        if max_champions:
            champion_dirs = champion_dirs[:max_champions]
            log.info(f"Limiting to first {max_champions} champions")
        
        results = {}
        total_downloaded = 0
        
        log.info(f"Starting download for {len(champion_dirs)} champions...")
        
        for i, champion in enumerate(champion_dirs, 1):
            log.info(f"[{i}/{len(champion_dirs)}] Processing {champion}...")
            
            try:
                downloaded = self.download_champion_skins(champion, force_update)
                results[champion] = downloaded
                total_downloaded += downloaded
                
                if downloaded > 0:
                    log.info(f"Downloaded {downloaded} skins for {champion}")
                else:
                    log.info(f"No new skins for {champion}")
                
                # Small delay to be respectful to GitHub API
                time.sleep(API_POLITENESS_DELAY_S)
                
            except Exception as e:
                log.error(f"Error processing {champion}: {e}")
                results[champion] = 0
        
        # Get detailed statistics
        detailed_stats = self.get_detailed_stats()
        log.info(f"Download complete!")
        log.info(f"  Total base skins: {detailed_stats['total_skins']}")
        log.info(f"  Total chromas: {detailed_stats['total_chromas']}")
        log.info(f"  Total skin IDs: {detailed_stats['total_ids']}")
        
        return results
    
    @property
    def download_stats(self) -> Dict[str, int]:
        """Get statistics about downloaded skins (total IDs per champion)"""
        if not self.target_dir.exists():
            return {}
        
        stats = {}
        for champion_dir in self.target_dir.iterdir():
            if champion_dir.is_dir():
                zip_files = list(champion_dir.glob("*.zip"))
                stats[champion_dir.name] = len(zip_files)
        
        return stats
    
    def get_detailed_stats(self) -> Dict[str, int]:
        """
        Get detailed statistics categorizing base skins and chromas
        
        Structure:
        - Base skin: Champion/Skin Name.zip
        - Chroma: Champion/chromas/Skin Name/Skin Name CHROMAID.zip
        
        Returns:
            Dict with keys: 'total_skins', 'total_chromas', 'total_ids'
        """
        if not self.target_dir.exists():
            return {'total_skins': 0, 'total_chromas': 0, 'total_ids': 0}
        
        total_skins = 0  # Base skins only
        total_chromas = 0  # Chromas only
        
        for champion_dir in self.target_dir.iterdir():
            if not champion_dir.is_dir():
                continue
            
            # Count base skins (zip files in champion root)
            base_skins = list(champion_dir.glob("*.zip"))
            total_skins += len(base_skins)
            
            # Count chromas (zip files in chromas/*/  subdirectories)
            # Structure: Champion/chromas/SkinName/SkinName CHROMAID.zip
            chromas_dir = champion_dir / "chromas"
            if chromas_dir.exists() and chromas_dir.is_dir():
                # Chromas are in subdirectories under chromas/
                for skin_chroma_dir in chromas_dir.iterdir():
                    if skin_chroma_dir.is_dir():
                        chroma_files = list(skin_chroma_dir.glob("*.zip"))
                        total_chromas += len(chroma_files)
        
        return {
            'total_skins': total_skins,
            'total_chromas': total_chromas,
            'total_ids': total_skins + total_chromas
        }
    
    def cleanup_old_skins(self, days_old: int = 30) -> int:
        """Remove skin files older than specified days"""
        if not self.target_dir.exists():
            return 0
        
        cutoff_time = time.time() - (days_old * 24 * 60 * 60)
        removed_count = 0
        
        for champion_dir in self.target_dir.iterdir():
            if champion_dir.is_dir():
                for skin_file in champion_dir.glob("*.zip"):
                    if skin_file.stat().st_mtime < cutoff_time:
                        try:
                            skin_file.unlink()
                            removed_count += 1
                            log.debug(f"Removed old skin: {skin_file}")
                        except Exception as e:
                            log.error(f"Failed to remove {skin_file}: {e}")
        
        if removed_count > 0:
            log.info(f"Cleaned up {removed_count} old skin files")
        
        return removed_count


def download_skins_on_startup(
    target_dir: Path = None,
    force_update: bool = False,
    max_champions: Optional[int] = None,
    tray_manager=None,
    injection_manager=None,
    progress_callback: Optional[ProgressCallback] = None,
) -> bool:
    """Download skins using repository ZIP download (most efficient method)"""
    try:
        # Note: Tray status is now managed by AppStatus class in main.py
        # This function just downloads and returns success/failure
        
        from utils.repo_downloader import download_skins_from_repo
        log.info("Downloading skins from repository ZIP...")
        result = download_skins_from_repo(
            target_dir,
            force_update,
            tray_manager,
            progress_callback=progress_callback,
        )
        if injection_manager:
            injection_manager.initialize_when_ready()
        return result
        
    except Exception as e:
        log.error(f"Failed to download skins: {e}")
        if injection_manager:
            injection_manager.initialize_when_ready()
        return False
