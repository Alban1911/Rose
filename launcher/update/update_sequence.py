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


def _parse_semver_like(version: str) -> Optional[tuple[int, ...]]:
    """
    Parse a semver-like version string into an integer tuple for comparison.

    Accepts formats like:
    - "1.2.3"
    - "v1.2.3"
    - "1.2.3-beta"  (suffix ignored)
    - "1.2"         (becomes (1, 2))
    """
    if not version:
        return None

    v = version.strip()
    if v.lower().startswith("v"):
        v = v[1:].strip()

    # Drop common suffixes (e.g., "-beta", "+build", " (whatever)")
    for sep in (" ", "-", "+"):
        if sep in v:
            v = v.split(sep, 1)[0]

    parts: list[int] = []
    for raw in v.split("."):
        if not raw:
            break
        digits = ""
        for ch in raw:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits == "":
            break
        parts.append(int(digits))

    return tuple(parts) if parts else None


def _cmp_version(a: Optional[tuple[int, ...]], b: Optional[tuple[int, ...]]) -> Optional[int]:
    """Return -1/0/1 if comparable, else None."""
    if a is None or b is None:
        return None
    max_len = max(len(a), len(b))
    aa = a + (0,) * (max_len - len(a))
    bb = b + (0,) * (max_len - len(b))
    return (aa > bb) - (aa < bb)


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
        # Note: installed_version can be stale if config.ini was created by a previous build,
        # so we also check APP_VERSION (the current build's version).
        if installed_version == "999" or APP_VERSION == "999":
            status_callback("Update skipped (test version)")
            return False

        # Determine the effective local version (config can be stale, so consider APP_VERSION too).
        local_candidates = [installed_version, APP_VERSION]
        local_parsed = [_parse_semver_like(v) for v in local_candidates]
        remote_parsed = _parse_semver_like(remote_version) if remote_version else None

        # Prevent unintended downgrade: if local > remote, do not update.
        # This is especially useful for testing builds where APP_VERSION is bumped ahead.
        effective_local: Optional[tuple[int, ...]] = None
        for v in local_parsed:
            if v is None:
                continue
            if effective_local is None or _cmp_version(v, effective_local) == 1:
                effective_local = v

        if _cmp_version(effective_local, remote_parsed) == 1:
            status_callback("Update skipped (local version is newer)")
            return False

        # If versions match, we are up to date.
        if _cmp_version(effective_local, remote_parsed) == 0 or (
            remote_version and (installed_version == remote_version or APP_VERSION == remote_version)
        ):
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

