#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Repository Downloader
Downloads the entire repository as a ZIP file and extracts it locally
Much more efficient than individual API calls
Supports incremental updates by tracking repository changes
"""

import json
import zipfile
import tempfile
import requests
from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple
from utils.logging import get_logger
from utils.paths import get_skins_dir
from config import APP_USER_AGENT, SKIN_DOWNLOAD_STREAM_TIMEOUT_S

log = get_logger()


class RepoDownloader:
    """Downloads entire repository as ZIP and extracts locally with incremental updates"""
    
    def __init__(self, target_dir: Path = None, repo_url: str = "https://github.com/AlbanCliquet/lolskins"):
        self.repo_url = repo_url
        # Use user data directory for skins to avoid permission issues
        self.target_dir = target_dir or get_skins_dir()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': APP_USER_AGENT,
            'Accept': 'application/vnd.github.v3+json'
        })
        
        # State tracking for incremental updates
        self.state_file = self.target_dir / '.repo_state.json'
        self.api_base = "https://api.github.com/repos/AlbanCliquet/lolskins"
    
    def get_repo_state(self) -> Dict:
        """Get current repository state from GitHub API"""
        try:
            # Get the latest commit info
            response = self.session.get(f"{self.api_base}/commits/main")
            response.raise_for_status()
            commit_data = response.json()
            
            return {
                'last_commit_sha': commit_data['sha'],
                'last_commit_date': commit_data['commit']['committer']['date'],
                'last_checked': None  # Will be set when we save state
            }
        except requests.RequestException as e:
            log.error(f"Failed to get repository state: {e}")
            return {}
    
    def get_remaining_api_calls(self, response: requests.Response) -> int:
        """Get remaining API calls from GitHub response headers"""
        try:
            remaining = int(response.headers.get('X-RateLimit-Remaining', '0'))
            limit = int(response.headers.get('X-RateLimit-Limit', '60'))
            log.debug(f"GitHub API rate limit: {remaining}/{limit} remaining")
            return remaining
        except (ValueError, AttributeError):
            return 0
    
    def load_local_state(self) -> Dict:
        """Load local state from state file"""
        if not self.state_file.exists():
            return {}
        
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log.warning(f"Failed to load local state: {e}")
            return {}
    
    def save_local_state(self, state: Dict):
        """Save local state to state file"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except IOError as e:
            log.warning(f"Failed to save local state: {e}")
    
    def has_repository_changed(self) -> bool:
        """Check if repository has changed since last update"""
        local_state = self.load_local_state()
        if not local_state:
            log.info("No local state found, repository will be downloaded")
            return True
        
        current_state = self.get_repo_state()
        if not current_state:
            log.warning("Failed to get current repository state, assuming no changes")
            return False
        
        # Compare commit SHAs
        local_sha = local_state.get('last_commit_sha')
        current_sha = current_state.get('last_commit_sha')
        
        if local_sha != current_sha:
            log.info(f"Repository changed: {local_sha[:8] if local_sha else 'None'} -> {current_sha[:8] if current_sha else 'None'}")
            return True
        
        log.info("Repository unchanged, skipping download")
        return False
    
    def get_changed_files(self, since_commit: str) -> Tuple[List[Dict], Optional[requests.Response]]:
        """Get list of files that changed since a specific commit
        Returns: (changed_files_list, response_object)"""
        try:
            # Get commits since the specified commit
            response = self.session.get(f"{self.api_base}/compare/{since_commit}...main")
            response.raise_for_status()
            compare_data = response.json()
            
            changed_files = []
            for file_info in compare_data.get('files', []):
                # Only include files in the skins/ directory
                if file_info['filename'].startswith('skins/'):
                    # Get download URL using the file's SHA
                    download_url = None
                    if file_info.get('sha'):
                        download_url = f"{self.api_base}/contents/{file_info['filename']}?ref=main"
                    
                    changed_files.append({
                        'filename': file_info['filename'],
                        'status': file_info['status'],  # 'added', 'modified', 'removed'
                        'sha': file_info.get('sha'),
                        'download_url': download_url
                    })
            
            return changed_files, response
        except requests.RequestException as e:
            log.error(f"Failed to get changed files: {e}")
            return [], None
    
    def download_individual_file(self, file_info: Dict) -> Tuple[bool, Optional[str]]:
        """Download a single file from GitHub
        Returns: (success, error_type) where error_type can be 'rate_limit', 'network', or None"""
        if not file_info.get('download_url'):
            log.warning(f"No download URL for {file_info['filename']}")
            return False, None
        
        try:
            # Calculate local path
            relative_path = file_info['filename'].replace('skins/', '')
            local_path = self.target_dir / relative_path
            
            # Handle file removal
            if file_info['status'] == 'removed':
                if local_path.exists():
                    local_path.unlink()
                    log.info(f"Removed {local_path}")
                return True, None
            
            # Create directory if needed
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            # First, get the file contents from GitHub API
            response = self.session.get(file_info['download_url'])
            response.raise_for_status()
            file_data = response.json()
            
            # Check if we got the expected response structure
            if 'download_url' not in file_data:
                log.error(f"Unexpected response format for {file_info['filename']}")
                return False, None
            
            # Download the actual file content
            download_response = self.session.get(file_data['download_url'], stream=True, timeout=SKIN_DOWNLOAD_STREAM_TIMEOUT_S)
            download_response.raise_for_status()
            
            with open(local_path, 'wb') as f:
                for chunk in download_response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            log.info(f"Downloaded {file_info['filename']}")
            return True, None
            
        except requests.HTTPError as e:
            if e.response and e.response.status_code == 429:
                log.warning(f"Rate limit hit while downloading {file_info['filename']}")
                return False, 'rate_limit'
            else:
                log.error(f"Failed to download {file_info['filename']}: {e}")
                return False, 'network'
        except requests.RequestException as e:
            log.error(f"Failed to download {file_info['filename']}: {e}")
            return False, 'network'
        except Exception as e:
            log.error(f"Error saving {file_info['filename']}: {e}")
            return False, None
        
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
        """Extract skins, previews, and skin_id mappings from the new merged lolskins repository ZIP"""
        try:
            log.info("Extracting skins, previews, and skin_id mappings from merged lolskins repository ZIP...")
            
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
                
                # Find all files in the resources/skinid_mapping/ directory
                mapping_files = []
                json_count = 0
                
                for file_info in zip_ref.filelist:
                    # Look for files in resources/skinid_mapping/ directory
                    if (file_info.filename.startswith('lolskins-main/resources/skinid_mapping/') and 
                        file_info.filename != 'lolskins-main/resources/skinid_mapping/' and
                        not file_info.filename.endswith('/')):
                        mapping_files.append(file_info)
                        
                        # Count JSON files
                        if file_info.filename.endswith('.json'):
                            json_count += 1
                
                if not skins_files:
                    log.error("No skins folder found in repository ZIP")
                    return False
                
                log.info(f"Found {zip_count} skin .zip files, {png_count} preview .png files, and {json_count} skin ID mapping files in repository")
                
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
                
                # Extract skin ID mapping files to user data directory
                extracted_json_count = 0
                skipped_json_count = 0
                
                if mapping_files:
                    from utils.paths import get_user_data_dir
                    mapping_target_dir = get_user_data_dir() / "skinid_mapping"
                    
                    for file_info in mapping_files:
                        try:
                            # Skip directories
                            if file_info.is_dir():
                                continue
                            
                            # Remove the 'lolskins-main/' prefix from the path
                            relative_path = file_info.filename.replace('lolskins-main/', '')
                            
                            # Remove the 'resources/skinid_mapping/' prefix since target_dir is the mapping directory
                            if relative_path.startswith('resources/skinid_mapping/'):
                                relative_path = relative_path.replace('resources/skinid_mapping/', '', 1)
                            
                            # Extract to mapping target directory
                            extract_path = mapping_target_dir / relative_path
                            extract_path.parent.mkdir(parents=True, exist_ok=True)
                            
                            # Skip if file already exists
                            if extract_path.exists():
                                skipped_json_count += 1
                                continue
                            
                            # Extract the file
                            with zip_ref.open(file_info) as source:
                                with open(extract_path, 'wb') as target:
                                    target.write(source.read())
                            
                            extracted_json_count += 1
                            
                        except Exception as e:
                            log.warning(f"Failed to extract {file_info.filename}: {e}")
                
                log.info(f"Extracted {extracted_zip_count} new skin .zip files, {extracted_png_count} preview .png files, "
                        f"and {extracted_json_count} skin ID mapping files (skipped {skipped_count} existing skin files, "
                        f"{skipped_json_count} existing mapping files)")
                
                return (extracted_zip_count + extracted_png_count + extracted_json_count) > 0
                
        except zipfile.BadZipFile:
            log.error("Invalid ZIP file")
            return False
        except Exception as e:
            log.error(f"Error extracting skins: {e}")
            return False
    
    def download_incremental_updates(self, force_update: bool = False) -> bool:
        """Download only changed files since last update"""
        try:
            # Check if repository has changed
            if not force_update and not self.has_repository_changed():
                return True
            
            local_state = self.load_local_state()
            current_state = self.get_repo_state()
            
            if not current_state:
                log.error("Failed to get current repository state")
                return False
            
            # If no local state, check if we have existing skins
            if not local_state:
                existing_skins = list(self.target_dir.rglob("*.zip"))
                if existing_skins:
                    log.info(f"No local state found, but found {len(existing_skins)} existing skins")
                    log.info("Creating state file and checking for updates...")
                    # Create a minimal state and try incremental update
                    # We'll use the current commit as the "last known" state
                    current_state['last_checked'] = current_state['last_commit_date']
                    self.save_local_state(current_state)
                    # Now check for changes since current commit (should be none)
                    changed_files, response = self.get_changed_files(current_state['last_commit_sha'])
                    if not changed_files:
                        log.info("No changes found since current commit")
                        return True
                    else:
                        log.info(f"Found {len(changed_files)} changed files")
                        # Check if we have enough API calls remaining
                        if response:
                            remaining_calls = self.get_remaining_api_calls(response)
                            # Need at least 2 API calls per file (get file info + download)
                            estimated_calls = len(changed_files) * 2
                            if remaining_calls < estimated_calls + 10:  # 10 calls buffer
                                log.warning(f"Not enough API calls remaining ({remaining_calls}), falling back to ZIP download")
                                return self.download_and_extract_skins(force_update=True)
                        
                        # Download changed files
                        success_count = 0
                        rate_limit_hit = False
                        for file_info in changed_files:
                            success, error_type = self.download_individual_file(file_info)
                            if success:
                                success_count += 1
                            elif error_type == 'rate_limit':
                                rate_limit_hit = True
                                log.warning("Rate limit hit during download, falling back to ZIP download")
                                break
                        
                        if rate_limit_hit:
                            log.info("Switching to ZIP download due to rate limit")
                            return self.download_and_extract_skins(force_update=True)
                        
                        log.info(f"Downloaded {success_count}/{len(changed_files)} changed files")
                        return success_count > 0
                else:
                    log.info("No local state and no existing skins found, performing full download")
                    return self.download_and_extract_skins(force_update=True)
            
            # Get changed files since last update
            last_commit = local_state.get('last_commit_sha')
            if not last_commit:
                log.info("No previous commit found, performing full download")
                return self.download_and_extract_skins(force_update=True)
            
            changed_files, response = self.get_changed_files(last_commit)
            if not changed_files:
                log.info("No skin files changed")
                # Update state even if no changes
                current_state['last_checked'] = current_state['last_commit_date']
                self.save_local_state(current_state)
                return True
            
            log.info(f"Found {len(changed_files)} changed files")
            
            # Check if we have enough API calls remaining
            if response:
                remaining_calls = self.get_remaining_api_calls(response)
                # Need at least 2 API calls per file (get file info + download)
                estimated_calls = len(changed_files) * 2
                log.info(f"Remaining API calls: {remaining_calls}, estimated needed: {estimated_calls}")
                if remaining_calls < estimated_calls + 10:  # 10 calls buffer
                    log.warning(f"Not enough API calls remaining ({remaining_calls}), falling back to ZIP download")
                    return self.download_and_extract_skins(force_update=True)
            
            # Download changed files
            success_count = 0
            rate_limit_hit = False
            for file_info in changed_files:
                success, error_type = self.download_individual_file(file_info)
                if success:
                    success_count += 1
                elif error_type == 'rate_limit':
                    rate_limit_hit = True
                    log.warning("Rate limit hit during download, falling back to ZIP download")
                    break
            
            if rate_limit_hit:
                log.info("Switching to ZIP download due to rate limit")
                return self.download_and_extract_skins(force_update=True)
            
            log.info(f"Downloaded {success_count}/{len(changed_files)} changed files")
            
            # Update local state
            current_state['last_checked'] = current_state['last_commit_date']
            self.save_local_state(current_state)
            
            return success_count > 0
            
        except Exception as e:
            log.error(f"Failed to download incremental updates: {e}")
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
                
                # Save state after successful full download
                if success:
                    current_state = self.get_repo_state()
                    if current_state:
                        current_state['last_checked'] = current_state['last_commit_date']
                        self.save_local_state(current_state)
                
                return success
                
            finally:
                # Clean up temporary ZIP file
                try:
                    zip_path.unlink()
                    log.debug("Cleaned up temporary ZIP file")
                except (OSError, FileNotFoundError) as e:
                    log.debug(f"Could not remove temporary ZIP file: {e}")
                except Exception as e:
                    log.debug(f"Unexpected error cleaning up ZIP file: {e}")
            
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


def download_skins_from_repo(target_dir: Path = None, force_update: bool = False, tray_manager=None, use_incremental: bool = True) -> bool:
    """Download skins from repository with optional incremental updates"""
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
        
        # Choose download method based on preferences
        if use_incremental and not force_update:
            log.info("Using incremental update mode")
            success = downloader.download_incremental_updates(force_update)
        else:
            log.info("Using full download mode")
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
            update_type = "incremental" if use_incremental and not force_update else "full"
            log.info(f"✓ {update_type.title()} database download complete (skins + previews)")
        
        return success
        
    except Exception as e:
        log.error(f"Repository download failed: {e}")
        return False
