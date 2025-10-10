#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Repository Downloader
Downloads the entire repository as a ZIP file and extracts it locally
Much more efficient than individual API calls
"""

import os
import re
import zipfile
import tempfile
import requests
from pathlib import Path
from typing import Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.logging import get_logger
from utils.paths import get_skins_dir
from config import APP_USER_AGENT, SKIN_DOWNLOAD_STREAM_TIMEOUT_S

log = get_logger()


class RepoDownloader:
    """Downloads entire repository as ZIP and extracts locally"""
    
    def __init__(self, target_dir: Path = None, repo_url: str = "https://github.com/darkseal-org/lol-skins"):
        self.repo_url = repo_url
        # Use user data directory for skins to avoid permission issues
        self.target_dir = target_dir or get_skins_dir()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': APP_USER_AGENT
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
            response = self.session.get(zip_url, stream=True, timeout=SKIN_DOWNLOAD_STREAM_TIMEOUT_S)
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
                zip_count = 0
                readme_count_total = 0
                blade_variants_count = 0
                
                for file_info in zip_ref.filelist:
                    # Look for files in skins/ directory, but skip the skins directory itself
                    if (file_info.filename.startswith('lol-skins-main/skins/') and 
                        file_info.filename != 'lol-skins-main/skins/' and
                        not file_info.filename.endswith('/')):
                        skins_files.append(file_info)
                        
                        # Check if this is a blade variant (special weapon mods, not counted as skins)
                        is_blade_variant = '/Blades/' in file_info.filename
                        
                        # Count file types for accurate reporting
                        if file_info.filename.endswith('.zip'):
                            if is_blade_variant:
                                blade_variants_count += 1
                            else:
                                zip_count += 1
                        elif file_info.filename.endswith('README.md'):
                            readme_count_total += 1
                
                if not skins_files:
                    log.error("No skins folder found in repository ZIP")
                    return False
                
                log.info(f"Found {zip_count} skin .zip files and {readme_count_total} README files in repository")
                
                # Extract only the skins files AND chroma READMEs
                extracted_count = 0
                readme_count = 0
                skipped_count = 0
                blade_extracted_count = 0
                
                for file_info in skins_files:
                    try:
                        # Skip directories
                        if file_info.is_dir():
                            continue
                        
                        # Remove the 'lol-skins-main/' prefix from the path
                        relative_path = file_info.filename.replace('lol-skins-main/', '')
                        
                        # Check if it's a zip file or a README in chromas directory
                        is_zip = relative_path.endswith('.zip')
                        is_chroma_readme = 'chromas/' in relative_path and relative_path.endswith('README.md')
                        is_blade_variant = '/Blades/' in relative_path
                        
                        # Skip if it's neither a zip nor a chroma README
                        if not is_zip and not is_chroma_readme:
                            continue
                        
                        # Remove the 'skins/' prefix since target_dir is already the skins directory
                        if relative_path.startswith('skins/'):
                            relative_path = relative_path.replace('skins/', '', 1)
                        
                        # Extract to target directory
                        extract_path = self.target_dir / relative_path
                        extract_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # Skip if file already exists
                        if extract_path.exists():
                            skipped_count += 1
                            continue
                        
                        # Extract the file
                        with zip_ref.open(file_info) as source:
                            with open(extract_path, 'wb') as target:
                                target.write(source.read())
                        
                        # Count by type (blade variants counted separately)
                        if is_chroma_readme:
                            readme_count += 1
                        elif is_blade_variant:
                            blade_extracted_count += 1
                        else:
                            extracted_count += 1
                        
                    except Exception as e:
                        log.warning(f"Failed to extract {file_info.filename}: {e}")
                
                log.info(f"Extracted {extracted_count} new skin files and {readme_count} new chroma READMEs "
                        f"(skipped {skipped_count} existing files)")
                if blade_extracted_count > 0:
                    log.debug(f"Also extracted {blade_extracted_count} blade variant files (not counted as skins)")
                
                # Don't download previews here - will be done on-demand when champion is locked
                
                return extracted_count > 0 or readme_count > 0
                
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


def download_skins_from_repo(target_dir: Path = None, force_update: bool = False, tray_manager=None) -> bool:
    """Download all skins from repository in one operation"""
    try:
        # Note: tray_manager status is already set by caller (download_skins_on_startup)
        downloader = RepoDownloader(target_dir)
        
        # Get current detailed stats
        current_detailed = downloader.get_detailed_stats()
        
        if current_detailed['total_ids'] > 0:
            log.info(f"Found {current_detailed['total_skins']} base skins + "
                    f"{current_detailed['total_chromas']} chromas = "
                    f"{current_detailed['total_ids']} total skin IDs")
        
        # Download and extract skins (includes chroma preview download)
        success = downloader.download_and_extract_skins(force_update)
        
        if success:
            # Get updated detailed stats
            final_detailed = downloader.get_detailed_stats()
            new_ids = final_detailed['total_ids'] - current_detailed['total_ids']
            
            if new_ids > 0:
                log.info(f"Downloaded {new_ids} new skin IDs")
                log.info(f"Final totals: {final_detailed['total_skins']} base skins + "
                        f"{final_detailed['total_chromas']} chromas = "
                        f"{final_detailed['total_ids']} total skin IDs")
            else:
                log.info("No new skins to download")
            
            # Log completion
            log.info("✓ Repository download and chroma preview caching complete")
        
        return success
        
    except Exception as e:
        log.error(f"Repository download failed: {e}")
        return False
