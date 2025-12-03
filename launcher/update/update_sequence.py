"""
Update Sequence
Handles the update checking and installation sequence
"""

from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from config import APP_VERSION, get_config_file_path
from utils.core.logging import get_logger, get_named_logger

from .github_client import GitHubClient
from .update_downloader import UpdateDownloader
from .update_installer import UpdateInstaller

log = get_logger()
updater_log = get_named_logger("updater", prefix="log_updater")


class UpdateSequence:
    """Handles the update checking and installation sequence"""
    
    def __init__(self):
        self.github_client = GitHubClient()
        self.downloader = UpdateDownloader()
        self.installer = UpdateInstaller()
    
    def perform_update(
        self,
        status_callback: Callable[[str], None],
        progress_callback: Callable[[int], None],
        bytes_callback: Optional[Callable[[int, Optional[int]], None]] = None,
        dev_mode: bool = False,
    ) -> bool:
        """Perform update check and installation
        
        Args:
            status_callback: Callback for status updates
            progress_callback: Callback for progress updates
            bytes_callback: Optional callback for download progress
            
        Returns:
            True if update was installed, False otherwise
        """
        status_callback("Checking for updates...")
        
        # Check for latest release
        release = self.github_client.get_latest_release()
        if not release:
            status_callback("Update check failed")
            return False
        
        remote_version = self.github_client.get_release_version(release)
        asset = self.github_client.get_zip_asset(release)
        if not asset:
            status_callback("No release asset found")
            return False
        
        download_url = asset.get("browser_download_url")
        total_size = asset.get("size", 0) or None
        
        # Check installed version
        config_path = get_config_file_path()
        config = configparser.ConfigParser()
        if config_path.exists():
            try:
                config.read(config_path)
            except Exception:
                pass
        if not config.has_section("General"):
            config.add_section("General")
        
        # Read installed version without overwriting it
        # We only update it after a successful update installation
        installed_version = config.get("General", "installed_version", fallback=APP_VERSION)
        
        # Skip updates for test versions (e.g., version 999)
        if installed_version == "999":
            status_callback("Update skipped (test version)")
            return False
        
        if remote_version and installed_version == remote_version:
            status_callback("Launcher is already up to date")
            return False
        
        if dev_mode:
            status_callback("Update skipped (dev mode)")
            return False
        
        # Download update
        updates_root = config_path.parent / "updates"
        updates_root.mkdir(parents=True, exist_ok=True)
        zip_name = asset.get("name") or "update.zip"
        zip_path = updates_root / zip_name
        
        status_callback(f"Downloading update {remote_version or ''}")
        if not self.downloader.download_update(
            download_url,
            zip_path,
            status_callback,
            bytes_callback,
            total_size,
        ):
            return False
        
        # Extract update
        status_callback("Extracting update")
        staging_dir = updates_root / "staging"
        extracted_root = self.installer.extract_update(
            zip_path,
            staging_dir,
            progress_callback,
            status_callback,
        )
        if not extracted_root:
            return False
        
        # Download hash file if available (skip in dev mode)
        if getattr(sys, "frozen", False):
            hash_asset = self.github_client.get_hash_asset(release)
            if hash_asset:
                status_callback("Downloading hash file...")
                hash_download_url = hash_asset.get("browser_download_url")
                hash_target_path = extracted_root / "injection" / "tools" / "hashes.game.txt"
                self.downloader.download_hash_file(
                    hash_download_url,
                    hash_target_path,
                    status_callback,
                )
        
        # Install update
        status_callback("Installing update")
        install_dir = Path(sys.executable).resolve().parent
        
        if not self.installer.prepare_installation(
            extracted_root,
            install_dir,
            updates_root,
            zip_path,
            staging_dir,
            status_callback,
        ):
            return False
        
        batch_path = updates_root / "apply_update.bat"
        if not self.installer.launch_installer(batch_path, status_callback):
            return False
        
        # Update installed_version in config after successful installation
        if remote_version:
            config.set("General", "installed_version", remote_version)
            try:
                with open(config_path, "w", encoding="utf-8") as fh:
                    config.write(fh)
            except Exception:
                pass
        
        progress_callback(100)
        if bytes_callback and total_size:
            bytes_callback(total_size, total_size)
        status_callback("Update installed")
        updater_log.info(f"Auto-update completed. Update installed: True")
        return True

