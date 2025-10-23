#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Repository Downloader
Downloads the entire repository as a ZIP file and extracts it locally
Much more efficient than individual API calls
"""

import zipfile
import tempfile
import requests
from pathlib import Path
from typing import Optional, Dict
from utils.logging import get_logger
from utils.paths import get_skins_dir
from config import APP_USER_AGENT, SKIN_DOWNLOAD_STREAM_TIMEOUT_S

log = get_logger()


class RepoDownloader:
    """Downloads entire repository as ZIP and extracts locally"""
    
    def __init__(self, target_dir: Path = None, repo_url: str = "https://github.com/AlbanCliquet/lolskins"):
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
        """Extract skins and previews from the new merged lolskins repository ZIP"""
        try:
            log.info("Extracting skins and previews from merged lolskins repository ZIP...")
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Find all files in the skins/ directory
                skins_files = []
                zip_count = 0
                png_count = 0
                
                for file_info in zip_ref.filelist:
                    # Look for files in skins/ directory, but skip the skins directory itself
                    if (file_info.filename.startswith('lolskins-main/skins/') and 
                        file_info.filename != 'lolskins-main/skins/' and
                        not file_info.filename.endswith('/')):
                        skins_files.append(file_info)
                        
                        # Count file types for accurate reporting
                        if file_info.filename.endswith('.zip'):
                            zip_count += 1
                        elif file_info.filename.endswith('.png'):
                            png_count += 1
                
                if not skins_files:
                    log.error("No skins folder found in repository ZIP")
                    return False
                
                log.info(f"Found {zip_count} skin .zip files and {png_count} preview .png files in repository")
                
                # Extract all skins files (both .zip and .png)
                extracted_zip_count = 0
                extracted_png_count = 0
                skipped_count = 0
                
                for file_info in skins_files:
                    try:
                        # Skip directories
                        if file_info.is_dir():
                            continue
                        
                        # Remove the 'lolskins-main/' prefix from the path
                        relative_path = file_info.filename.replace('lolskins-main/', '')
                        
                        # Check file type
                        is_zip = relative_path.endswith('.zip')
                        is_png = relative_path.endswith('.png')
                        
                        # Skip if it's not a skin file
                        if not (is_zip or is_png):
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
                        
                        # Count by type
                        if is_zip:
                            extracted_zip_count += 1
                        elif is_png:
                            extracted_png_count += 1
                        
                    except Exception as e:
                        log.warning(f"Failed to extract {file_info.filename}: {e}")
                
                log.info(f"Extracted {extracted_zip_count} new skin .zip files and {extracted_png_count} preview .png files "
                        f"(skipped {skipped_count} existing files)")
                
                return (extracted_zip_count + extracted_png_count) > 0
                
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
        Get detailed statistics categorizing base skins and chromas from new merged format
        
        Structure:
        - Base skin: {champion_id}/{skin_id}/{skin_id}.zip and {skin_id}.png
        - Chroma: {champion_id}/{skin_id}/{chroma_id}/{chroma_id}.zip and {chroma_id}.png
        
        Returns:
            Dict with keys: 'total_skins', 'total_chromas', 'total_ids', 'total_previews'
        """
        if not self.target_dir.exists():
            return {'total_skins': 0, 'total_chromas': 0, 'total_ids': 0, 'total_previews': 0}
        
        total_skins = 0  # Base skins only (zip files in skin subdirectories)
        total_chromas = 0  # Chromas only (zip files in chroma subdirectories)
        total_previews = 0  # All preview images (png files)
        
        for champion_dir in self.target_dir.iterdir():
            if not champion_dir.is_dir():
                continue
            
            # Count skins and chromas in skin subdirectories
            # Structure: {champion_id}/{skin_id}/{skin_id}.zip and {skin_id}.png
            for skin_dir in champion_dir.iterdir():
                if not skin_dir.is_dir():
                    continue
                
                # Check if this is a skin directory (contains only numeric name)
                try:
                    int(skin_dir.name)  # If this succeeds, it's a skin ID directory
                    
                    # Count base skin files
                    skin_zip = skin_dir / f"{skin_dir.name}.zip"
                    skin_png = skin_dir / f"{skin_dir.name}.png"
                    
                    if skin_zip.exists():
                        total_skins += 1
                    if skin_png.exists():
                        total_previews += 1
                    
                    # Count chromas in this skin's chroma subdirectories
                    # Structure: {champion_id}/{skin_id}/{chroma_id}/{chroma_id}.zip and {chroma_id}.png
                    for chroma_dir in skin_dir.iterdir():
                        if chroma_dir.is_dir():
                            try:
                                int(chroma_dir.name)  # If this succeeds, it's a chroma ID directory
                                
                                chroma_zip = chroma_dir / f"{chroma_dir.name}.zip"
                                chroma_png = chroma_dir / f"{chroma_dir.name}.png"
                                
                                if chroma_zip.exists():
                                    total_chromas += 1
                                if chroma_png.exists():
                                    total_previews += 1
                            except ValueError:
                                # Not a chroma directory, skip
                                continue
                except ValueError:
                    # Not a skin directory, skip
                    continue
        
        return {
            'total_skins': total_skins,
            'total_chromas': total_chromas,
            'total_ids': total_skins + total_chromas,
            'total_previews': total_previews
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
                    f"{current_detailed['total_ids']} total skin IDs + "
                    f"{current_detailed['total_previews']} preview images")
        
        # Download and extract skins and previews from merged database
        success = downloader.download_and_extract_skins(force_update)
        
        if success:
            # Get updated detailed stats
            final_detailed = downloader.get_detailed_stats()
            new_ids = final_detailed['total_ids'] - current_detailed['total_ids']
            new_previews = final_detailed['total_previews'] - current_detailed['total_previews']
            
            if new_ids > 0 or new_previews > 0:
                log.info(f"Downloaded {new_ids} new skin IDs and {new_previews} new preview images")
                log.info(f"Final totals: {final_detailed['total_skins']} base skins + "
                        f"{final_detailed['total_chromas']} chromas = "
                        f"{final_detailed['total_ids']} total skin IDs + "
                        f"{final_detailed['total_previews']} preview images")
            else:
                log.info("No new skins or previews to download")
            
            # Log completion
            log.info("✓ Merged database download complete (skins + previews)")
        
        return success
        
    except Exception as e:
        log.error(f"Repository download failed: {e}")
        return False
