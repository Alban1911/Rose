"""
GitHub Client
Handles GitHub API interactions for release checking
"""

from __future__ import annotations

from typing import Optional

from urllib.parse import quote, unquote

import requests

from config import APP_USER_AGENT
from utils.core.logging import get_logger
from utils.download import github_rate_limit

log = get_logger()

GITHUB_RELEASE_API = "https://api.github.com/repos/Alban1911/Rose/releases/latest"
# github.com answers these without spending GitHub API calls (60 an hour per IP
# without a login): the latest release's page redirects to its tag, and the
# update package of a tag has a fixed name (scripts/create_update_package.py)
RELEASES_LATEST_URL = "https://github.com/Alban1911/Rose/releases/latest"
RELEASE_DOWNLOAD_URL = "https://github.com/Alban1911/Rose/releases/download/{tag}/{name}"
UPDATE_PACKAGE_NAME = "update_package_{version}.zip"


class GitHubClient:
    """Client for interacting with GitHub API"""
    
    def __init__(self, timeout: int = 20):
        self.timeout = timeout
    
    def get_latest_release(self) -> Optional[dict]:
        """Get the latest release information from GitHub

        Read from github.com's redirect to the latest tag (no API call); the
        API's release listing is the fallback.

        Returns:
            Release data dictionary or None if failed
        """
        release = self._latest_from_redirect()
        if release is not None:
            return release
        try:
            response = github_rate_limit.api_get(GITHUB_RELEASE_API, timeout=self.timeout)
            if response is None:
                return None
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.warning("Update check failed while fetching latest release: %s", e)
            return None

    def _latest_from_redirect(self) -> Optional[dict]:
        """The latest release as the API would list it (tag and update package),
        from github.com's redirect, or None."""
        headers = {"User-Agent": APP_USER_AGENT}
        try:
            response = requests.get(RELEASES_LATEST_URL, allow_redirects=False, timeout=self.timeout, headers=headers)
            location = response.headers.get("Location", "")
            if response.status_code not in (301, 302, 303, 307, 308) or "/releases/tag/" not in location:
                log.info("Latest release redirect unavailable (HTTP %s)", response.status_code)
                return None
            tag = unquote(location.rsplit("/releases/tag/", 1)[1].split("?", 1)[0].strip("/"))
            if not tag:
                return None
            name = UPDATE_PACKAGE_NAME.format(version=tag)
            url = RELEASE_DOWNLOAD_URL.format(tag=quote(tag), name=quote(name))
            # The package must exist under that name; its size drives the progress bar
            head = requests.head(url, allow_redirects=True, timeout=self.timeout, headers=headers)
            if head.status_code != 200:
                log.info("Release %s has no %s (HTTP %s)", tag, name, head.status_code)
                return None
            length = head.headers.get("Content-Length", "")
            size = int(length) if length.isdigit() else 0
            return {
                "tag_name": tag,
                "name": tag,
                "assets": [{"name": name, "browser_download_url": url, "size": size}],
            }
        except requests.RequestException as e:
            log.info("Latest release redirect unavailable: %s", e)
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

