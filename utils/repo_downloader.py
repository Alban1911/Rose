#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Repository Downloader
Downloads the entire repository as a ZIP file and extracts it locally
Much more efficient than individual API calls
"""

import os
import zipfile
import tempfile
import requests
from pathlib import Path
from typing import Optional
from utils.logging import get_logger

log = get_logger()


class RepoDownloader:
    """Downloads entire repository as ZIP and extracts locally"""
    
    def __init__(self, target_dir: Path = None, repo_url: str = "https://github.com/darkseal-org/lol-skins"):
        self.repo_url = repo_url
        self.target_dir = target_dir or Path("skins")
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'LoLSkinChanger/1.0'
        })
        
    def download_repo_zip(self) -> Optional[Path]:
        """Download the entire repository as a ZIP file"""
        # GitHub's ZIP download URL format
        zip_url = f"{self.repo_url}/archive/refs/heads/main.zip"
        
        log.info(f"Downloading repository ZIP from: {zip_url}")
        
        try:
            # Create temporary file for ZIP
            temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
            temp_zip_path = Path(temp_zip.name)
            temp_zip.close()
            
            # Download ZIP file
            response = self.session.get(zip_url, stream=True, timeout=60)
            response.raise_for_status()
            
            # Save ZIP file
            with open(temp_zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            log.info(f"Repository ZIP downloaded: {temp_zip_path}")
            return temp_zip_path
            
        except requests.RequestException as e:
            log.error(f"Failed to download repository ZIP: {e}")
            return None
        except Exception as e:
            log.error(f"Error downloading repository: {e}")
            return None
    
    def extract_skins_from_zip(self, zip_path: Path) -> bool:
        """Extract only the skins folder from the repository ZIP"""
        try:
            log.info("Extracting skins from repository ZIP...")
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Find the skins folder in the ZIP
                skins_files = []
                for file_info in zip_ref.filelist:
                    # Look for files in skins/ directory, but skip the skins directory itself
                    if (file_info.filename.startswith('lol-skins-main/skins/') and 
                        file_info.filename != 'lol-skins-main/skins/' and
                        not file_info.filename.endswith('/')):
                        skins_files.append(file_info)
                
                if not skins_files:
                    log.error("No skins folder found in repository ZIP")
                    return False
                
                log.info(f"Found {len(skins_files)} skin files in repository")
                
                # Extract only the skins files
                extracted_count = 0
                for file_info in skins_files:
                    try:
                        # Skip directories
                        if file_info.is_dir():
                            continue
                        
                        # Remove the 'lol-skins-main/' prefix from the path
                        relative_path = file_info.filename.replace('lol-skins-main/', '')
                        
                        # Skip if it's not a zip file
                        if not relative_path.endswith('.zip'):
                            continue
                        
                        # Extract to target directory
                        extract_path = self.target_dir / relative_path
                        extract_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # Skip if file already exists
                        if extract_path.exists():
                            continue
                        
                        # Extract the file
                        with zip_ref.open(file_info) as source:
                            with open(extract_path, 'wb') as target:
                                target.write(source.read())
                        
                        extracted_count += 1
                        
                    except Exception as e:
                        log.warning(f"Failed to extract {file_info.filename}: {e}")
                
                log.info(f"Extracted {extracted_count} skin files")
                return extracted_count > 0
                
        except zipfile.BadZipFile:
            log.error("Invalid ZIP file")
            return False
        except Exception as e:
            log.error(f"Error extracting skins: {e}")
            return False
    
    def download_and_extract_skins(self, force_update: bool = False) -> bool:
        """Download repository and extract skins in one operation"""
        try:
            # Clean up any conflicting files/directories
            if self.target_dir.exists():
                # Remove any file named "skins" that might conflict
                skins_file = self.target_dir / "skins"
                if skins_file.exists() and skins_file.is_file():
                    log.info("Removing conflicting 'skins' file...")
                    skins_file.unlink()
            
            # Check if skins already exist and we're not forcing update
            if not force_update and self.target_dir.exists():
                existing_skins = list(self.target_dir.rglob("*.zip"))
                if existing_skins:
                    log.info(f"Found {len(existing_skins)} existing skins, skipping download")
                    return True
            
            # Download repository ZIP
            zip_path = self.download_repo_zip()
            if not zip_path:
                return False
            
            try:
                # Extract skins from ZIP
                success = self.extract_skins_from_zip(zip_path)
                return success
                
            finally:
                # Clean up temporary ZIP file
                try:
                    zip_path.unlink()
                    log.debug("Cleaned up temporary ZIP file")
                except:
                    pass
            
        except Exception as e:
            log.error(f"Failed to download and extract skins: {e}")
            return False
    
    def get_skin_stats(self) -> dict:
        """Get statistics about downloaded skins"""
        if not self.target_dir.exists():
            return {}
        
        stats = {}
        for champion_dir in self.target_dir.iterdir():
            if champion_dir.is_dir():
                zip_files = list(champion_dir.glob("*.zip"))
                stats[champion_dir.name] = len(zip_files)
        
        return stats


def download_skins_from_repo(target_dir: Path = None, force_update: bool = False) -> bool:
    """Download all skins from repository in one operation"""
    try:
        downloader = RepoDownloader(target_dir)
        
        # Get current stats
        current_stats = downloader.get_skin_stats()
        total_current = sum(current_stats.values())
        
        if total_current > 0:
            log.info(f"Found {total_current} existing skins across {len(current_stats)} champions")
        
        # Download and extract skins
        success = downloader.download_and_extract_skins(force_update)
        
        if success:
            # Get updated stats
            updated_stats = downloader.get_skin_stats()
            total_updated = sum(updated_stats.values())
            
            if total_updated > total_current:
                new_skins = total_updated - total_current
                log.info(f"Downloaded {new_skins} new skins from repository")
            else:
                log.info("No new skins to download")
        
        return success
        
    except Exception as e:
        log.error(f"Repository download failed: {e}")
        return False
