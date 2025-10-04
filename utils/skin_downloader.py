#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skin Downloader
Automatically downloads skins from the GitHub repository
"""

import os
import json
import time
import requests
import zipfile
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse
from utils.logging import get_logger

log = get_logger()


class SkinDownloader:
    """Downloads skins from the GitHub repository"""
    
    def __init__(self, target_dir: Path = None, repo_url: str = "https://github.com/darkseal-org/lol-skins"):
        self.repo_url = repo_url
        self.api_base = "https://api.github.com/repos/darkseal-org/lol-skins"
        self.target_dir = target_dir or Path("skins")
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'LoLSkinChanger/1.0',
            'Accept': 'application/vnd.github.v3+json'
        })
        
    def get_repo_contents(self, path: str = "skins") -> List[Dict]:
        """Get the contents of a directory from the GitHub repository"""
        url = f"{self.api_base}/contents/{path}"
        
        try:
            response = self.session.get(url, timeout=30)
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
            response = self.session.get(download_url, timeout=60, stream=True)
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
                time.sleep(0.5)
                
            except Exception as e:
                log.error(f"Error processing {champion}: {e}")
                results[champion] = 0
        
        log.info(f"Download complete! Total skins downloaded: {total_downloaded}")
        return results
    
    def get_download_stats(self) -> Dict[str, int]:
        """Get statistics about downloaded skins"""
        if not self.target_dir.exists():
            return {}
        
        stats = {}
        for champion_dir in self.target_dir.iterdir():
            if champion_dir.is_dir():
                zip_files = list(champion_dir.glob("*.zip"))
                stats[champion_dir.name] = len(zip_files)
        
        return stats
    
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


def download_skins_on_startup(target_dir: Path = None, force_update: bool = False, 
                            max_champions: Optional[int] = None) -> bool:
    """Convenience function to download skins at startup - tries multiple methods"""
    try:
        # Method 1: Try repository ZIP download (most efficient)
        try:
            from utils.repo_downloader import download_skins_from_repo
            log.info("Using repository ZIP downloader (most efficient)...")
            return download_skins_from_repo(target_dir, force_update)
        except ImportError:
            log.debug("Repository downloader not available")
        
        # Method 2: Try smart downloader (with proper rate limiting)
        try:
            from utils.smart_skin_downloader import download_skins_smart
            log.info("Using smart skin downloader with rate limiting...")
            return download_skins_smart(target_dir, force_update, max_champions)
        except ImportError:
            log.debug("Smart downloader not available")
        
        # Method 3: Fallback to original downloader
        log.warning("Using basic downloader (may hit rate limits)")
        downloader = SkinDownloader(target_dir)
        
        # Get current stats
        current_stats = downloader.get_download_stats()
        total_current = sum(current_stats.values())
        
        if total_current > 0:
            log.info(f"Found {total_current} existing skins across {len(current_stats)} champions")
        
        # Download skins
        results = downloader.download_all_skins(force_update, max_champions)
        
        # Report results
        total_downloaded = sum(results.values())
        champions_with_new = sum(1 for count in results.values() if count > 0)
        
        if total_downloaded > 0:
            log.info(f"Downloaded {total_downloaded} new skins for {champions_with_new} champions")
        else:
            log.info("No new skins to download")
        
        return True
        
    except Exception as e:
        log.error(f"Failed to download skins: {e}")
        return False
