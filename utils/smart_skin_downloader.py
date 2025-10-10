#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smart Skin Downloader
Downloads skins efficiently with proper API rate limiting and batch operations
"""

import os
import json
import time
import requests
import zipfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse
from utils.logging import get_logger
from config import (
    RATE_LIMIT_MIN_INTERVAL, RATE_LIMIT_REQUEST_TIMEOUT, RATE_LIMIT_STREAM_TIMEOUT,
    RATE_LIMIT_LOW_THRESHOLD, RATE_LIMIT_WARNING_50, RATE_LIMIT_WARNING_100,
    RATE_LIMIT_INITIAL, RATE_LIMIT_DELAY_LOW, RATE_LIMIT_DELAY_MEDIUM,
    RATE_LIMIT_DELAY_HIGH, RATE_LIMIT_BACKOFF_MULTIPLIER, LOG_CHUNK_SIZE,
    APP_USER_AGENT
)

log = get_logger()


class SmartSkinDownloader:
    """Smart skin downloader with rate limiting and batch operations"""
    
    def __init__(self, target_dir: Path = None, repo_url: str = "https://github.com/darkseal-org/lol-skins"):
        self.repo_url = repo_url
        self.api_base = "https://api.github.com/repos/darkseal-org/lol-skins"
        self.target_dir = target_dir or Path("skins")
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': APP_USER_AGENT,
            'Accept': 'application/vnd.github.v3+json'
        })
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = RATE_LIMIT_MIN_INTERVAL
        self.rate_limit_remaining = RATE_LIMIT_INITIAL
        self.rate_limit_reset = 0
        
    def _wait_for_rate_limit(self):
        """Wait if we're hitting rate limits"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            log.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def _handle_rate_limit_response(self, response: requests.Response):
        """Handle rate limit information from response headers"""
        if 'X-RateLimit-Remaining' in response.headers:
            self.rate_limit_remaining = int(response.headers['X-RateLimit-Remaining'])
        
        if 'X-RateLimit-Reset' in response.headers:
            self.rate_limit_reset = int(response.headers['X-RateLimit-Reset'])
        
        if self.rate_limit_remaining < RATE_LIMIT_LOW_THRESHOLD:
            log.warning(f"Rate limit low: {self.rate_limit_remaining} requests remaining")
            # Increase delay when rate limit is low
            self.min_request_interval = max(RATE_LIMIT_DELAY_LOW, self.min_request_interval * RATE_LIMIT_BACKOFF_MULTIPLIER)
    
    def _make_request(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make a rate-limited request"""
        self._wait_for_rate_limit()
        
        try:
            response = self.session.get(url, timeout=RATE_LIMIT_REQUEST_TIMEOUT, **kwargs)
            self._handle_rate_limit_response(response)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            log.error(f"Request failed for {url}: {e}")
            return None
    
    def get_repo_contents_batch(self, paths: List[str]) -> Dict[str, List[Dict]]:
        """Get contents of multiple directories in batch"""
        results = {}
        
        for path in paths:
            url = f"{self.api_base}/contents/{path}"
            response = self._make_request(url)
            
            if response:
                try:
                    results[path] = response.json()
                except json.JSONDecodeError:
                    log.error(f"Failed to parse JSON for {path}")
                    results[path] = []
            else:
                results[path] = []
        
        return results
    
    def get_repo_contents(self, path: str = "skins") -> List[Dict]:
        """Get the contents of a directory from the GitHub repository"""
        url = f"{self.api_base}/contents/{path}"
        
        response = self._make_request(url)
        if response:
            try:
                return response.json()
            except json.JSONDecodeError:
                log.error(f"Failed to parse JSON for {path}")
                return []
        return []
    
    def get_all_champion_data(self) -> Dict[str, List[Dict]]:
        """Get all champion data in one batch operation"""
        log.info("Fetching all champion data in batch...")
        
        # First get all champion directories
        champion_dirs = self.get_repo_contents("skins")
        if not champion_dirs:
            return {}
        
        champion_names = [item['name'] for item in champion_dirs if item.get('type') == 'dir']
        log.info(f"Found {len(champion_names)} champion directories")
        
        # Get all champion skin data in batch
        champion_paths = [f"skins/{champion}" for champion in champion_names]
        champion_data = self.get_repo_contents_batch(champion_paths)
        
        return champion_data
    
    def download_file_batch(self, download_urls: List[str], local_paths: List[Path]) -> List[bool]:
        """Download multiple files efficiently"""
        results = []
        
        for url, local_path in zip(download_urls, local_paths):
            try:
                # Create directory if it doesn't exist
                local_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Download with streaming for large files
                response = self._make_request(url, stream=True, timeout=RATE_LIMIT_STREAM_TIMEOUT)
                if not response:
                    results.append(False)
                    continue
                
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=LOG_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                
                results.append(True)
                log.debug(f"Downloaded: {local_path.name}")
                
            except Exception as e:
                log.error(f"Failed to download {url}: {e}")
                results.append(False)
        
        return results
    
    def download_champion_skins_smart(self, champion: str, skin_files: List[Dict], 
                                    force_update: bool = False) -> int:
        """Download all skins for a champion efficiently"""
        champion_dir = self.target_dir / champion
        champion_dir.mkdir(parents=True, exist_ok=True)
        
        if not skin_files:
            log.warning(f"No skin files found for {champion}")
            return 0
        
        # Filter out existing files if not forcing update
        files_to_download = []
        local_paths = []
        
        for skin_file in skin_files:
            filename = skin_file['name']
            local_path = champion_dir / filename
            
            if not local_path.exists() or force_update:
                files_to_download.append(skin_file)
                local_paths.append(local_path)
            else:
                log.debug(f"Skipping existing file: {filename}")
        
        if not files_to_download:
            log.info(f"All skins for {champion} are already downloaded")
            return 0
        
        log.info(f"Downloading {len(files_to_download)} skins for {champion}...")
        
        # Download all files for this champion in batch
        download_urls = [skin_file['download_url'] for skin_file in files_to_download]
        results = self.download_file_batch(download_urls, local_paths)
        
        downloaded_count = sum(results)
        log.info(f"Successfully downloaded {downloaded_count}/{len(files_to_download)} skins for {champion}")
        
        return downloaded_count
    
    def download_all_skins_smart(self, force_update: bool = False, 
                                max_champions: Optional[int] = None) -> Dict[str, int]:
        """Download all skins efficiently with smart batching"""
        log.info("Starting smart skin download...")
        
        # Get all champion data in one batch operation
        champion_data = self.get_all_champion_data()
        if not champion_data:
            log.error("No champion data found")
            return {}
        
        # Filter champions if limit specified
        champion_names = list(champion_data.keys())
        if max_champions:
            champion_names = champion_names[:max_champions]
            log.info(f"Limiting to first {max_champions} champions")
        
        results = {}
        total_downloaded = 0
        
        log.info(f"Processing {len(champion_names)} champions...")
        
        for i, champion_path in enumerate(champion_names, 1):
            champion = champion_path.replace("skins/", "")
            log.info(f"[{i}/{len(champion_names)}] Processing {champion}...")
            
            try:
                # Extract skin files from the batch data
                skin_files = []
                for item in champion_data[champion_path]:
                    if item.get('type') == 'file' and item['name'].endswith('.zip'):
                        skin_files.append(item)
                
                # Download all skins for this champion
                downloaded = self.download_champion_skins_smart(champion, skin_files, force_update)
                results[champion] = downloaded
                total_downloaded += downloaded
                
                if downloaded > 0:
                    log.info(f"Downloaded {downloaded} skins for {champion}")
                else:
                    log.info(f"No new skins for {champion}")
                
                # Adaptive delay based on rate limit status
                if self.rate_limit_remaining < RATE_LIMIT_WARNING_50:
                    delay = RATE_LIMIT_DELAY_LOW
                elif self.rate_limit_remaining < RATE_LIMIT_WARNING_100:
                    delay = RATE_LIMIT_DELAY_MEDIUM
                else:
                    delay = RATE_LIMIT_DELAY_HIGH
                
                time.sleep(delay)
                
            except Exception as e:
                log.error(f"Error processing {champion}: {e}")
                results[champion] = 0
        
        # Get detailed statistics
        detailed_stats = self.get_detailed_stats()
        log.info(f"Smart download complete!")
        log.info(f"  Total base skins: {detailed_stats['total_skins']}")
        log.info(f"  Total chromas: {detailed_stats['total_chromas']}")
        log.info(f"  Total skin IDs: {detailed_stats['total_ids']}")
        log.info(f"  Rate limit remaining: {self.rate_limit_remaining}")
        
        return results
    
    def get_download_stats(self) -> Dict[str, int]:
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


def download_skins_smart(target_dir: Path = None, force_update: bool = False, 
                        max_champions: Optional[int] = None, tray_manager=None) -> bool:
    """Smart skin download with proper rate limiting"""
    try:
        # Note: tray_manager status is already set by caller (download_skins_on_startup)
        downloader = SmartSkinDownloader(target_dir)
        
        # Get current detailed stats
        current_detailed = downloader.get_detailed_stats()
        
        if current_detailed['total_ids'] > 0:
            log.info(f"Found {current_detailed['total_skins']} base skins + "
                    f"{current_detailed['total_chromas']} chromas = "
                    f"{current_detailed['total_ids']} total skin IDs")
        
        # Download skins with smart batching
        results = downloader.download_all_skins_smart(force_update, max_champions)
        
        # Report final results with detailed stats
        final_detailed = downloader.get_detailed_stats()
        new_ids = final_detailed['total_ids'] - current_detailed['total_ids']
        
        if new_ids > 0:
            log.info(f"Downloaded {new_ids} new skin IDs")
            log.info(f"Final totals: {final_detailed['total_skins']} base skins + "
                    f"{final_detailed['total_chromas']} chromas = "
                    f"{final_detailed['total_ids']} total skin IDs")
        else:
            log.info("No new skins to download")
        
        return True
        
    except Exception as e:
        log.error(f"Smart download failed: {e}")
        return False
