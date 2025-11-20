"""
Update Downloader
Handles downloading update files from GitHub releases
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import requests

from utils.logging import get_named_logger

updater_log = get_named_logger("updater", prefix="log_updater")


class UpdateDownloader:
    """Handles downloading update files"""
    
    def __init__(self, chunk_size: int = 1024 * 128, timeout: int = 60):
        self.chunk_size = chunk_size
        self.timeout = timeout
    
    def download_update(
        self,
        download_url: str,
        zip_path: Path,
        status_callback: Callable[[str], None],
        bytes_callback: Optional[Callable[[int, Optional[int]], None]] = None,
        total_size: Optional[int] = None,
    ) -> bool:
        """Download update ZIP file
        
        Args:
            download_url: URL to download from
            zip_path: Path to save the ZIP file
            status_callback: Callback for status updates
            bytes_callback: Optional callback for download progress
            total_size: Optional total file size
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with requests.get(download_url, stream=True, timeout=self.timeout) as r:
                r.raise_for_status()
                bytes_read = 0
                with open(zip_path, "wb") as fh:
                    for chunk in r.iter_content(self.chunk_size):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        bytes_read += len(chunk)
                        if bytes_callback:
                            bytes_callback(bytes_read, total_size)
            return True
        except Exception as exc:  # noqa: BLE001
            status_callback(f"Download failed: {exc}")
            updater_log.error(f"Update download failed: {exc}")
            return False
    
    def download_hash_file(
        self,
        download_url: str,
        target_path: Path,
        status_callback: Callable[[str], None],
    ) -> bool:
        """Download hash file from release assets
        
        Args:
            download_url: URL to download from
            target_path: Path to save the hash file
            status_callback: Callback for status updates
            
        Returns:
            True if successful, False otherwise
        """
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with requests.get(download_url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(target_path, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            fh.write(chunk)
            return True
        except Exception as exc:  # noqa: BLE001
            status_callback(f"Warning: failed to download hash file: {exc}")
            updater_log.warning(f"Hash file download failed: {exc}")
            return False

