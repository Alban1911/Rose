#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preview Repository Downloader
Downloads the SkinPreviews repository (chroma preview images) as a ZIP and extracts it
"""

import zipfile
import tempfile
import requests
from pathlib import Path
from typing import Optional
from utils.logging import get_logger
from utils.paths import get_appdata_dir
from config import APP_USER_AGENT, SKIN_DOWNLOAD_STREAM_TIMEOUT_S

log = get_logger()


class PreviewRepoDownloader:
    """Downloads SkinPreviews repository as ZIP and extracts locally"""
    
    def __init__(self, repo_url: str = "https://github.com/AlbanCliquet/SkinPreviews"):
        self.repo_url = repo_url
        # Extract to AppData/LeagueUnlocked/SkinPreviews/
        appdata_dir = get_appdata_dir()
        self.target_dir = appdata_dir / "SkinPreviews"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': APP_USER_AGENT
        })
    
    def download_repo_zip(self) -> Optional[Path]:
        """Download the entire SkinPreviews repository as a ZIP file"""
        # GitHub's ZIP download URL format
        zip_url = f"{self.repo_url}/archive/refs/heads/main.zip"
        
        log.info(f"Downloading SkinPreviews repository from: {zip_url}")
        
        try:
            # Create temporary file for ZIP
            temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
            temp_zip_path = Path(temp_zip.name)
            temp_zip.close()
            
            # Download ZIP file
            response = self.session.get(zip_url, stream=True, timeout=SKIN_DOWNLOAD_STREAM_TIMEOUT_S)
            response.raise_for_status()
            
            # Save ZIP file with progress
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(temp_zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
            
            log.info(f"SkinPreviews ZIP downloaded: {temp_zip_path} ({downloaded / (1024*1024):.1f} MB)")
            return temp_zip_path
            
        except requests.RequestException as e:
            log.error(f"Failed to download SkinPreviews ZIP: {e}")
            return None
        except Exception as e:
            log.error(f"Error downloading SkinPreviews: {e}")
            return None
    
    def extract_previews_from_zip(self, zip_path: Path) -> bool:
        """Extract preview images from the repository ZIP"""
        try:
            log.info("Extracting preview images from SkinPreviews ZIP...")
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Find preview files in the ZIP
                preview_files = []
                
                for file_info in zip_ref.filelist:
                    # Look for files in chroma_previews/ directory
                    if (file_info.filename.startswith('SkinPreviews-main/chroma_previews/') and 
                        not file_info.filename.endswith('/') and
                        file_info.filename.endswith('.png')):
                        preview_files.append(file_info)
                
                if not preview_files:
                    log.warning("No chroma_previews folder found in SkinPreviews ZIP")
                    return False
                
                log.info(f"Found {len(preview_files)} preview images in repository")
                
                # Extract preview files
                extracted_count = 0
                skipped_count = 0
                
                for file_info in preview_files:
                    try:
                        # Skip directories
                        if file_info.is_dir():
                            continue
                        
                        # Remove the 'SkinPreviews-main/' prefix from the path
                        relative_path = file_info.filename.replace('SkinPreviews-main/', '')
                        
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
                        
                        extracted_count += 1
                        
                    except Exception as e:
                        log.warning(f"Failed to extract {file_info.filename}: {e}")
                
                log.info(f"Extracted {extracted_count} new preview images (skipped {skipped_count} existing)")
                return extracted_count > 0 or skipped_count > 0
                
        except zipfile.BadZipFile:
            log.error("Invalid SkinPreviews ZIP file")
            return False
        except Exception as e:
            log.error(f"Error extracting previews: {e}")
            return False
    
    def download_and_extract_previews(self, force_update: bool = False) -> bool:
        """Download SkinPreviews repository and extract preview images"""
        try:
            # Check if previews already exist and we're not forcing update
            if not force_update and self.target_dir.exists():
                existing_previews = list(self.target_dir.rglob("*.png"))
                if existing_previews:
                    log.info(f"Found {len(existing_previews)} existing preview images, skipping download")
                    return True
            
            # Download repository ZIP
            zip_path = self.download_repo_zip()
            if not zip_path:
                return False
            
            try:
                # Extract previews from ZIP
                success = self.extract_previews_from_zip(zip_path)
                return success
                
            finally:
                # Clean up temporary ZIP file
                try:
                    zip_path.unlink()
                    log.debug("Cleaned up temporary SkinPreviews ZIP file")
                except:
                    pass
            
        except Exception as e:
            log.error(f"Failed to download and extract SkinPreviews: {e}")
            return False
    
    def get_preview_count(self) -> int:
        """Get count of downloaded preview images"""
        if not self.target_dir.exists():
            return 0
        
        previews = list(self.target_dir.rglob("*.png"))
        return len(previews)


def download_skin_previews(force_update: bool = False) -> bool:
    """Download all skin preview images from SkinPreviews repository"""
    try:
        downloader = PreviewRepoDownloader()
        
        # Get current count
        current_count = downloader.get_preview_count()
        if current_count > 0:
            log.info(f"Found {current_count} existing preview images")
        
        # Download and extract previews
        success = downloader.download_and_extract_previews(force_update)
        
        if success:
            # Get updated count
            final_count = downloader.get_preview_count()
            new_count = final_count - current_count
            
            if new_count > 0:
                log.info(f"Downloaded {new_count} new preview images")
                log.info(f"Total preview images: {final_count}")
            else:
                log.info("No new preview images to download")
        
        return success
        
    except Exception as e:
        log.error(f"SkinPreviews download failed: {e}")
        return False

