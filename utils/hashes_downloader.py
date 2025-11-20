#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hashes Downloader
Downloads hashes.game.txt from CommunityDragon/Data repository
Checks for updates based on latest commit SHA
"""

import json
import requests
from pathlib import Path
from typing import Optional, Dict
from utils.logging import get_logger
from config import APP_USER_AGENT, RATE_LIMIT_REQUEST_TIMEOUT

log = get_logger()


class HashesDownloader:
    """Downloads and manages hashes.game.txt from CommunityDragon/Data repository"""
    
    def __init__(self, tools_dir: Path):
        self.tools_dir = tools_dir
        self.hashes_file = tools_dir / "hashes.game.txt"
        self.state_file = tools_dir / ".hashes_state.json"
        
        # GitHub repository info
        self.repo_owner = "CommunityDragon"
        self.repo_name = "Data"
        self.branch = "master"
        self.api_base = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}"
        self.raw_base = f"https://raw.githubusercontent.com/{self.repo_owner}/{self.repo_name}/{self.branch}"
        self.hashes_path = "hashes/lol"
        
        # Create session for API requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': APP_USER_AGENT,
            'Accept': 'application/vnd.github.v3+json'
        })
    
    def get_latest_commit_sha(self) -> Optional[str]:
        """Get the latest commit SHA for the hashes/lol directory"""
        try:
            # Get the latest commit that touched the hashes/lol directory
            # We'll check the commits API for commits that modified files in this path
            response = self.session.get(
                f"{self.api_base}/commits",
                params={'sha': self.branch, 'path': self.hashes_path, 'per_page': 1},
                timeout=RATE_LIMIT_REQUEST_TIMEOUT
            )
            response.raise_for_status()
            commits = response.json()
            
            if commits and len(commits) > 0:
                latest_sha = commits[0]['sha']
                log.debug(f"Latest commit SHA for {self.hashes_path}: {latest_sha[:8]}")
                return latest_sha
            
            log.warning(f"No commits found for path {self.hashes_path}")
            return None
            
        except requests.HTTPError as e:
            if e.response and e.response.status_code in (403, 429):
                log.warning(f"GitHub API rate limit exceeded: {e}")
                return None
            else:
                log.error(f"Failed to get latest commit SHA: {e}")
                return None
        except requests.RequestException as e:
            log.error(f"Failed to get latest commit SHA: {e}")
            return None
    
    def load_local_state(self) -> Dict:
        """Load local state from state file"""
        if not self.state_file.exists():
            return {}
        
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log.warning(f"Failed to load local state: {e}")
            return {}
    
    def save_local_state(self, state: Dict):
        """Save local state to state file"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except IOError as e:
            log.warning(f"Failed to save local state: {e}")
    
    def has_hashes_changed(self) -> bool:
        """Check if hashes have changed since last update"""
        local_state = self.load_local_state()
        if not local_state:
            log.info("No local state found, hashes will be downloaded")
            return True
        
        # Check if file exists
        if not self.hashes_file.exists():
            log.info("hashes.game.txt not found, will download")
            return True
        
        # Get latest commit SHA
        latest_sha = self.get_latest_commit_sha()
        if not latest_sha:
            # If we can't get the SHA, assume no changes (to avoid unnecessary downloads)
            log.warning("Could not get latest commit SHA, assuming no changes")
            return False
        
        # Compare with local state
        local_sha = local_state.get('last_commit_sha')
        if local_sha != latest_sha:
            log.info(f"Hashes changed: {local_sha[:8] if local_sha else 'None'} -> {latest_sha[:8]}")
            return True
        
        log.debug("Hashes unchanged, skipping download")
        return False
    
    def download_hashes_file(self, filename: str) -> Optional[bytes]:
        """Download a single hashes file from GitHub raw content"""
        url = f"{self.raw_base}/{self.hashes_path}/{filename}"
        
        try:
            log.info(f"Downloading {filename}...")
            response = self.session.get(url, timeout=RATE_LIMIT_REQUEST_TIMEOUT)
            response.raise_for_status()
            log.info(f"Downloaded {filename} ({len(response.content)} bytes)")
            return response.content
        except requests.HTTPError as e:
            if e.response and e.response.status_code == 404:
                log.error(f"File not found: {filename}")
            elif e.response and e.response.status_code in (403, 429):
                log.error(f"GitHub API rate limit exceeded while downloading {filename}")
            else:
                log.error(f"Failed to download {filename}: {e}")
            return None
        except requests.RequestException as e:
            log.error(f"Failed to download {filename}: {e}")
            return None
    
    def merge_hashes_files(self, content_0: bytes, content_1: bytes) -> bytes:
        """Merge hashes.game.txt.0 and hashes.game.txt.1 into hashes.game.txt"""
        try:
            # Decode both files as text
            text_0 = content_0.decode('utf-8', errors='replace')
            text_1 = content_1.decode('utf-8', errors='replace')
            
            # Combine them with a newline separator
            merged = text_0 + '\n' + text_1
            
            return merged.encode('utf-8')
        except Exception as e:
            log.error(f"Failed to merge hashes files: {e}")
            raise
    
    def download_and_merge_hashes(self) -> bool:
        """Download and merge hashes files into hashes.game.txt"""
        try:
            # Download both files
            content_0 = self.download_hashes_file("hashes.game.txt.0")
            if content_0 is None:
                log.error("Failed to download hashes.game.txt.0")
                return False
            
            content_1 = self.download_hashes_file("hashes.game.txt.1")
            if content_1 is None:
                log.error("Failed to download hashes.game.txt.1")
                return False
            
            # Merge the files
            log.info("Merging hashes files...")
            merged_content = self.merge_hashes_files(content_0, content_1)
            
            # Ensure tools directory exists
            self.tools_dir.mkdir(parents=True, exist_ok=True)
            
            # Write merged file
            log.info(f"Writing hashes.game.txt to {self.hashes_file}...")
            with open(self.hashes_file, 'wb') as f:
                f.write(merged_content)
            
            log.info(f"Successfully created hashes.game.txt ({len(merged_content)} bytes)")
            
            # Update state
            latest_sha = self.get_latest_commit_sha()
            if latest_sha:
                state = {
                    'last_commit_sha': latest_sha,
                    'file_size': len(merged_content)
                }
                self.save_local_state(state)
            
            return True
            
        except Exception as e:
            log.error(f"Failed to download and merge hashes: {e}")
            return False
    
    def ensure_hashes_file(self) -> bool:
        """Ensure hashes.game.txt exists and is up to date"""
        try:
            # Check if file needs to be downloaded/updated
            if self.has_hashes_changed():
                log.info("Updating hashes.game.txt...")
                return self.download_and_merge_hashes()
            else:
                log.debug("hashes.game.txt is up to date")
                return True
                
        except Exception as e:
            log.error(f"Failed to ensure hashes file: {e}")
            return False


def ensure_hashes_file(tools_dir: Path) -> bool:
    """
    Ensure hashes.game.txt exists in the tools directory and is up to date.
    
    Args:
        tools_dir: Path to the injection/tools directory
        
    Returns:
        True if the file exists and is up to date, False otherwise
    """
    downloader = HashesDownloader(tools_dir)
    return downloader.ensure_hashes_file()

