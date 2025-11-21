"""
GitHub Client
Handles GitHub API interactions for release checking
"""

from __future__ import annotations

from typing import Optional

import requests

GITHUB_RELEASE_API = "https://api.github.com/repos/Alban1911/Rose/releases/latest"


class GitHubClient:
    """Client for interacting with GitHub API"""
    
    def __init__(self, timeout: int = 20):
        self.timeout = timeout
    
    def get_latest_release(self) -> Optional[dict]:
        """Get the latest release information from GitHub
        
        Returns:
            Release data dictionary or None if failed
        """
        try:
            response = requests.get(GITHUB_RELEASE_API, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None
    
    def get_release_version(self, release: dict) -> str:
        """Extract version string from release data"""
        return release.get("tag_name") or release.get("name") or ""
    
    def get_zip_asset(self, release: dict) -> Optional[dict]:
        """Get the ZIP asset from release data"""
        assets = release.get("assets", [])
        return next((a for a in assets if a.get("name", "").lower().endswith(".zip")), None)
    
    def get_hash_asset(self, release: dict) -> Optional[dict]:
        """Get the hash file asset from release data"""
        assets = release.get("assets", [])
        return next((a for a in assets if a.get("name", "").lower() == "hashes.game.txt"), None)

