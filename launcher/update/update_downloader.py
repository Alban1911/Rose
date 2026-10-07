"""
Update Downloader
Handles downloading update files from GitHub releases
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

import requests

from utils.core.logging import get_named_logger

updater_log = get_named_logger("updater", prefix="log_updater")


class UpdateDownloader:
    """Handles downloading update files"""
    
    def __init__(self, chunk_size: int = 1024 * 128, timeout: int = 60):
        self.chunk_size = chunk_size
        self.timeout = timeout
    
    def _download(
        self,
        url: str,
        target: Path,
        timeout: int,
        expected_size: Optional[int] = None,
        bytes_callback: Optional[Callable[[int, Optional[int]], None]] = None,
    ) -> None:
        """Stream url into target, raising if the download is incomplete.

        The data goes to a .part file that only replaces target once it is
        complete: an interrupted download used to leave a truncated file where
        the update package already had a good one.
        """
        part = target.with_name(target.name + ".part")
        try:
            with requests.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                expected = expected_size
                length = r.headers.get("Content-Length", "")
                # A compressed response is decoded, so its length would not match
                if expected is None and length.isdigit() and not r.headers.get("Content-Encoding"):
                    expected = int(length)
                bytes_read = 0
                with open(part, "wb") as fh:
                    for chunk in r.iter_content(self.chunk_size):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        bytes_read += len(chunk)
                        if bytes_callback:
                            bytes_callback(bytes_read, expected_size)
            if expected is not None and bytes_read != expected:
                raise IOError(f"incomplete download: got {bytes_read} of {expected} bytes")
            os.replace(part, target)
        finally:
            part.unlink(missing_ok=True)

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
            self._download(download_url, zip_path, self.timeout, total_size, bytes_callback)
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
            self._download(download_url, target_path, 30)
            return True
        except Exception as exc:  # noqa: BLE001
            status_callback(f"Warning: failed to download hash file: {exc}")
            updater_log.warning(f"Hash file download failed: {exc}")
            return False

