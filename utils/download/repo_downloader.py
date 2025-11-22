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
from typing import Callable, Optional, Dict, List, Set, Tuple
from utils.core.logging import get_logger
from utils.core.paths import get_skins_dir
from config import APP_USER_AGENT, SKIN_DOWNLOAD_STREAM_TIMEOUT_S

log = get_logger()

ProgressCallback = Callable[[int, Optional[str]], None]


def _format_size(num: Optional[int]) -> str:
    if num is None or num <= 0:
        return "0B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{num}B"


class RepoDownloader:
    """Downloads entire repository as ZIP and extracts locally with incremental updates"""
    
    def __init__(
        self,
        target_dir: Path = None,
        repo_url: str = "https://github.com/Alban1911/LeagueSkins",
        progress_callback: Optional[ProgressCallback] = None,
    ):
        self.repo_url = repo_url
        # Use user data directory for skins to avoid permission issues
        self.target_dir = target_dir or get_skins_dir()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': APP_USER_AGENT,
            'Accept': 'application/vnd.github.v3+json'
        })
        self.progress_callback = progress_callback
        
        # State tracking for incremental updates
        self.state_file = self.target_dir / '.repo_state.json'
        self.api_base = "https://api.github.com/repos/Alban1911/LeagueSkins"
        
        # State tracking for resources folder (skinid_mapping)
        from utils.core.paths import get_user_data_dir
        self.resources_state_file = get_user_data_dir() / "skinid_mapping" / ".resources_state.json"
    
    def _emit_progress(self, percent: float, message: Optional[str] = None):
        if not self.progress_callback:
            return
        bounded = max(0.0, min(percent, 100.0))
        self.progress_callback(int(bounded), message)
    
    def get_repo_state(self) -> Dict:
        """Get current repository state from GitHub API (skins folder only)
        Returns Dict with 'rate_limited' key set to True if rate limited"""
        try:
            # Get the latest commit that touched the skins directory
            response = self.session.get(
                f"{self.api_base}/commits",
                params={'sha': 'main', 'path': 'skins', 'per_page': 1}
            )
            response.raise_for_status()
            commits = response.json()
            
            if commits and len(commits) > 0:
                commit_data = commits[0]
                return {
                    'last_commit_sha': commit_data['sha'],
                    'last_commit_date': commit_data['commit']['committer']['date'],
                    'last_checked': None  # Will be set when we save state
                }
            
            log.warning("No commits found for skins folder")
            return {}
        except requests.HTTPError as e:
            if e.response and e.response.status_code in (403, 429):
                log.warning(f"GitHub API rate limit exceeded: {e}")
                log.info("Will skip incremental check and use ZIP download to avoid rate limits")
                return {'rate_limited': True}
            else:
                log.error(f"Failed to get repository state: {e}")
                return {}
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
    
    def get_resources_state(self) -> Dict:
        """Get current resources folder state from GitHub API
        Returns Dict with 'rate_limited' key set to True if rate limited"""
        try:
            # Get the latest commit that touched the resources directory
            response = self.session.get(
                f"{self.api_base}/commits",
                params={'sha': 'main', 'path': 'resources', 'per_page': 1}
            )
            response.raise_for_status()
            commits = response.json()
            
            if commits and len(commits) > 0:
                commit_data = commits[0]
                return {
                    'last_commit_sha': commit_data['sha'],
                    'last_commit_date': commit_data['commit']['committer']['date'],
                    'last_checked': None  # Will be set when we save state
                }
            
            log.warning("No commits found for resources folder")
            return {}
        except requests.HTTPError as e:
            if e.response and e.response.status_code in (403, 429):
                log.warning(f"GitHub API rate limit exceeded for resources check: {e}")
                return {'rate_limited': True}
            else:
                log.error(f"Failed to get resources state: {e}")
                return {}
        except requests.RequestException as e:
            log.error(f"Failed to get resources state: {e}")
            return {}
    
    def load_resources_state(self) -> Dict:
        """Load local resources state from state file"""
        if not self.resources_state_file.exists():
            return {}
        
        try:
            with open(self.resources_state_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log.warning(f"Failed to load resources state: {e}")
            return {}
    
    def save_resources_state(self, state: Dict):
        """Save local resources state to state file"""
        try:
            self.resources_state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.resources_state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except IOError as e:
            log.warning(f"Failed to save resources state: {e}")
    
    def has_resources_changed(self) -> bool:
        """Check if resources folder has changed since last update"""
        local_state = self.load_resources_state()
        if not local_state:
            log.info("No local resources state found, resources will be downloaded")
            return True
        
        current_state = self.get_resources_state()
        if not current_state:
            log.warning("Failed to get current resources state, assuming no changes")
            return False
        
        # Check if rate limited - if so, force update via ZIP
        if current_state.get('rate_limited'):
            log.info("Rate limited detected for resources, will force ZIP download")
            return True
        
        # Compare commit SHAs
        local_sha = local_state.get('last_commit_sha')
        current_sha = current_state.get('last_commit_sha')
        
        if local_sha != current_sha:
            log.info(f"Resources folder changed: {local_sha[:8] if local_sha else 'None'} -> {current_sha[:8] if current_sha else 'None'}")
            return True
        
        log.info("Resources folder unchanged, skipping download")
        return False
    
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
        
        # Check if rate limited - if so, force update via ZIP
        if current_state.get('rate_limited'):
            log.info("Rate limited detected, will force ZIP download")
            return True
        
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
        Returns: (changed_files_list, response_object or rate_limited marker)"""
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
        except requests.HTTPError as e:
            if e.response and e.response.status_code in (403, 429):
                log.warning(f"GitHub API rate limit exceeded while getting changed files: {e}")
                log.info("Will use ZIP download to avoid rate limits")
                return [], {'rate_limited': True}
            else:
                log.error(f"Failed to get changed files: {e}")
                return [], None
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
        
    def download_repo_zip(self, progress_start: float = 0.0, progress_end: float = 70.0) -> Optional[Path]:
        """Download the entire repository as a ZIP file"""
        # GitHub's ZIP download URL format
        zip_url = f"{self.repo_url}/archive/refs/heads/main.zip"
        
        log.info(f"Downloading repository ZIP from: {zip_url}")
        
        try:
            # Create temporary file for ZIP
            temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
            temp_zip_path = Path(temp_zip.name)
            temp_zip.close()

            # Try to resolve total size via HEAD request first
            total_size: Optional[int] = None
            try:
                head_response = self.session.head(zip_url, allow_redirects=True, timeout=SKIN_DOWNLOAD_STREAM_TIMEOUT_S)
                head_response.raise_for_status()
                total_size_header = head_response.headers.get('Content-Length')
                if total_size_header:
                    total_size = int(total_size_header)
            except requests.RequestException:
                total_size = None
            except ValueError:
                total_size = None

            # Download ZIP file
            response = self.session.get(zip_url, stream=True, timeout=SKIN_DOWNLOAD_STREAM_TIMEOUT_S)
            response.raise_for_status()
            if total_size is None:
                total_size_header = response.headers.get('Content-Length')
                try:
                    total_size = int(total_size_header) if total_size_header else None
                except ValueError:
                    total_size = None
            downloaded = 0
            last_emit = -1
            last_reported_bytes = 0
            unknown_estimated_total = total_size if total_size else 200 * 1024 * 1024
            self._emit_progress(progress_start, "Downloading skins...")
            
            # Save ZIP file
            with open(temp_zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size and total_size > 0:
                            fraction = downloaded / total_size
                        else:
                            if downloaded > unknown_estimated_total:
                                unknown_estimated_total = int(downloaded * 1.25)
                            fraction = min(downloaded / max(unknown_estimated_total, 1), 0.99)
                        percent = progress_start + fraction * (progress_end - progress_start)
                        emit_value = int(percent * 10)
                        if emit_value != last_emit:
                            last_emit = emit_value
                            downloaded_mb = _format_size(downloaded)
                            total_mb = _format_size(total_size) if total_size else "?"
                            self._emit_progress(
                                percent,
                                f"Downloading skins... {downloaded_mb} / {total_mb}",
                            )
 
            log.info(f"Repository ZIP downloaded: {temp_zip_path}")
            final_total = total_size if total_size else downloaded
            self._emit_progress(progress_end, f"Download complete ({_format_size(downloaded)} / {_format_size(final_total)})")
            return temp_zip_path
            
        except requests.RequestException as e:
            log.error(f"Failed to download repository ZIP: {e}")
            return None
        except Exception as e:
            log.error(f"Error downloading repository: {e}")
            return None
    
    def extract_skins_from_zip(
        self,
        zip_path: Path,
        overwrite_existing: bool = False,
        progress_start: float = 70.0,
        progress_end: float = 100.0,
    ) -> bool:
        """Extract skins, previews, and resources folder from the LeagueSkins repository ZIP"""
        try:
            log.info("Extracting skins, previews, and resources folder from LeagueSkins repository ZIP...")
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Find all files in the skins/ directory
                skins_files = []
                zip_count = 0
                png_count = 0
                
                for file_info in zip_ref.filelist:
                    # Look for files in skins/ directory, but skip the skins directory itself
                    if (file_info.filename.startswith('LeagueSkins-main/skins/') and 
                        file_info.filename != 'LeagueSkins-main/skins/' and
                        not file_info.filename.endswith('/')):
                        skins_files.append(file_info)
                        
                        # Count file types for accurate reporting
                        if file_info.filename.endswith('.zip'):
                            zip_count += 1
                        elif file_info.filename.endswith('.png'):
                            png_count += 1
                
                # Find all files in the resources/ directory (entire folder)
                resources_files = []
                resources_count = 0
                
                for file_info in zip_ref.filelist:
                    # Look for files in resources/ directory (entire folder)
                    if (file_info.filename.startswith('LeagueSkins-main/resources/') and 
                        file_info.filename != 'LeagueSkins-main/resources/' and
                        not file_info.filename.endswith('/')):
                        resources_files.append(file_info)
                        resources_count += 1
                
                if not skins_files:
                    log.error("No skins folder found in repository ZIP")
                    return False
                
                log.info(f"Found {zip_count} skin .zip files, {png_count} preview .png files, and {resources_count} resource files in repository")
                
                # Extract all skins and resource files with byte-level progress tracking
                extracted_zip_count = 0
                extracted_png_count = 0
                extracted_resources_count = 0
                skipped_skin_count = 0
                skipped_resources_count = 0

                entries: List[Tuple[str, zipfile.ZipInfo]] = [("skin", info) for info in skins_files]
                entries.extend(("resource", info) for info in resources_files)

                def _info_size(info: zipfile.ZipInfo) -> int:
                    return info.file_size or info.compress_size or 0

                total_bytes = sum(_info_size(info) for _, info in entries)
                if total_bytes <= 0:
                    total_bytes = len(entries) or 1
                processed_bytes = 0

                from utils.core.paths import get_user_data_dir
                # Place the entire resources folder as skinid_mapping
                mapping_target_dir = get_user_data_dir() / "skinid_mapping"

                def update_progress(label: str):
                    if total_bytes <= 0:
                        return
                    fraction = min(processed_bytes / total_bytes, 1.0)
                    percent = progress_start + fraction * (progress_end - progress_start)
                    current_mb = _format_size(processed_bytes)
                    total_mb = _format_size(total_bytes)
                    self._emit_progress(percent, f"{label} {current_mb} / {total_mb}")

                for entry_type, file_info in entries:
                    try:
                        if file_info.is_dir():
                            continue

                        label = "Extracting skins..." if entry_type == "skin" else "Extracting skin ID mapping..."
                        relative_path = file_info.filename.replace('LeagueSkins-main/', '')
                        is_zip = relative_path.endswith('.zip')
                        is_png = relative_path.endswith('.png')

                        if entry_type == "skin":
                            if relative_path.startswith('skins/'):
                                relative_path = relative_path.replace('skins/', '', 1)
                            extract_path = self.target_dir / relative_path
                        else:
                            # Extract entire resources folder structure, removing 'resources/' prefix
                            # so it becomes the skinid_mapping folder
                            if relative_path.startswith('resources/'):
                                relative_path = relative_path.replace('resources/', '', 1)
                            extract_path = mapping_target_dir / relative_path

                        extract_path.parent.mkdir(parents=True, exist_ok=True)

                        file_bytes = _info_size(file_info) or 1

                        if extract_path.exists() and not overwrite_existing:
                            if entry_type == "skin":
                                skipped_skin_count += 1
                            else:
                                skipped_resources_count += 1
                            processed_bytes += file_bytes
                            update_progress(label)
                            continue

                        with zip_ref.open(file_info) as source, open(extract_path, 'wb') as target:
                            while True:
                                chunk = source.read(64 * 1024)
                                if not chunk:
                                    break
                                target.write(chunk)
                                processed_bytes += len(chunk)
                                update_progress(label)

                        if entry_type == "skin":
                            if is_zip:
                                extracted_zip_count += 1
                            elif is_png:
                                extracted_png_count += 1
                        else:
                            extracted_resources_count += 1

                    except Exception as e:
                        log.warning(f"Failed to extract {file_info.filename}: {e}")
                        processed_bytes += _info_size(file_info) or 1
                        update_progress("Extracting...")

                log.info(f"Extracted {extracted_zip_count} new skin .zip files, {extracted_png_count} preview .png files, "
                        f"and {extracted_resources_count} resource files (skipped {skipped_skin_count} existing skin files, "
                        f"{skipped_resources_count} existing resource files)")

                # Save resources state after successful extraction
                # Save state if we processed any resources files (extracted or skipped)
                # or if we found resources files in the ZIP (even if none were processed)
                if extracted_resources_count > 0 or skipped_resources_count > 0 or resources_count > 0:
                    resources_state = self.get_resources_state()
                    if resources_state and not resources_state.get('rate_limited'):
                        resources_state['last_checked'] = resources_state.get('last_commit_date')
                        self.save_resources_state(resources_state)

                total_mb = _format_size(total_bytes)
                self._emit_progress(progress_end, f"Extraction complete ({_format_size(processed_bytes)} / {total_mb})")
                return (extracted_zip_count + extracted_png_count + extracted_resources_count) > 0
                
        except zipfile.BadZipFile:
            log.error("Invalid ZIP file")
            return False
        except Exception as e:
            log.error(f"Error extracting skins: {e}")
            return False
    
    def download_incremental_updates(self, force_update: bool = False) -> bool:
        """Download only changed files since last update"""
        try:
            self._emit_progress(0, "Checking skins repository state...")
            # Check if repository has changed
            skins_changed = force_update or self.has_repository_changed()
            
            self._emit_progress(5, "Checking skin ID mapping repository state...")
            resources_changed = force_update or self.has_resources_changed()
            
            if not skins_changed and not resources_changed:
                self._emit_progress(100, "Skins and skin ID mapping already up to date")
                return True
            
            # If resources changed, we need to download ZIP to extract resources
            if resources_changed:
                log.info("Resources folder changed, will download ZIP to update resources")
                self._emit_progress(10, "Skin ID mapping needs update, downloading...")
                return self.download_and_extract_skins(force_update=force_update)
            
            # Only skins changed, continue with incremental update
            
            local_state = self.load_local_state()
            current_state = self.get_repo_state()
            
            if not current_state:
                log.error("Failed to get current repository state")
                return False
            
            # If rate limited, skip incremental and use ZIP download
            if current_state.get('rate_limited'):
                log.warning("Rate limited, skipping incremental update and using ZIP download")
                return self.download_and_extract_skins(force_update=True)
            
            # If no local state, check if we have existing skins or mappings
            if not local_state:
                existing_skins = list(self.target_dir.rglob("*.zip"))
                existing_previews = list(self.target_dir.rglob("*.png"))
                
                # Check if skinid_mapping exists
                from utils.core.paths import get_user_data_dir
                mapping_dir = get_user_data_dir() / "skinid_mapping"
                existing_mappings = list(mapping_dir.rglob("*.json")) if mapping_dir.exists() else []
                
                if existing_skins or existing_previews or existing_mappings:
                    log.warning(f"No state file found but found existing files:")
                    log.warning(f"  - {len(existing_skins)} skin .zip files")
                    log.warning(f"  - {len(existing_previews)} preview .png files")
                    log.warning(f"  - {len(existing_mappings)} skin ID mapping files")
                    log.info("Cannot track commits without state file - deleting all files and performing full ZIP download")
                    
                    # Delete all existing skins and previews
                    for file_path in existing_skins + existing_previews:
                        try:
                            file_path.unlink()
                        except Exception as e:
                            log.warning(f"Failed to delete {file_path}: {e}")
                    
                    # Delete all existing mappings
                    for mapping_file in existing_mappings:
                        try:
                            mapping_file.unlink()
                        except Exception as e:
                            log.warning(f"Failed to delete {mapping_file}: {e}")
                    
                    # Also delete empty directories
                    for dir_path in list(self.target_dir.rglob("*")):
                        if dir_path.is_dir() and not any(dir_path.iterdir()):
                            try:
                                dir_path.rmdir()
                            except Exception:
                                pass
                    
                    if mapping_dir.exists():
                        for dir_path in list(mapping_dir.rglob("*")):
                            if dir_path.is_dir() and not any(dir_path.iterdir()):
                                try:
                                    dir_path.rmdir()
                                except Exception:
                                    pass
                        # Try to remove the mapping dir itself if empty
                        try:
                            if not any(mapping_dir.iterdir()):
                                mapping_dir.rmdir()
                        except Exception:
                            pass
                    
                    # Now do full download
                    return self.download_and_extract_skins(force_update=True)
                else:
                    log.info("No local state and no existing files found, performing full download")
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
                self._emit_progress(100, "Skins already up to date")
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
            total_files = len(changed_files)
            success_count = 0
            rate_limit_hit = False
            for index, file_info in enumerate(changed_files, start=1):
                success, error_type = self.download_individual_file(file_info)
                if success:
                    success_count += 1
                    if total_files > 0:
                        progress = 10 + (index / total_files) * 80
                        self._emit_progress(progress, f"Applying updates {index}/{total_files}")
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
            
            completed = success_count > 0
            if completed:
                self._emit_progress(100, "Skins updated")
            else:
                self._emit_progress(100, "No changes applied")
            return completed
            
        except Exception as e:
            log.error(f"Failed to download incremental updates: {e}")
            self._emit_progress(100, f"Failed: {e}")
            return False
    
    def download_and_extract_skins(self, force_update: bool = False) -> bool:
        """Download repository and extract skins in one operation"""
        try:
            self._emit_progress(0, "Preparing download...")
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
                    # Still check if resources need updating
                    self._emit_progress(2, "Checking skin ID mapping...")
                    resources_need_update = self.has_resources_changed()
                    if not resources_need_update:
                        log.info(f"Found {len(existing_skins)} existing skins and resources are up to date, skipping download")
                        self._emit_progress(100, "Skins and skin ID mapping already up to date")
                        return True
                    else:
                        log.info(f"Found {len(existing_skins)} existing skins, but resources need updating")
                        self._emit_progress(5, "Skin ID mapping needs update, downloading...")
            
            # Check if resources need updating (separate from skins)
            if not force_update:
                self._emit_progress(2, "Checking skin ID mapping...")
            resources_need_update = force_update or self.has_resources_changed()
            if resources_need_update:
                log.info("Resources folder needs updating")
            else:
                log.info("Resources folder is up to date")
            
            # Download repository ZIP
            zip_path = self.download_repo_zip(progress_start=5.0, progress_end=70.0)
            if not zip_path:
                self._emit_progress(5, "Failed to start download")
                return False
            
            try:
                # Extract skins from ZIP
                success = self.extract_skins_from_zip(
                    zip_path,
                    overwrite_existing=force_update,
                    progress_start=70.0,
                    progress_end=100.0,
                )
                
                # Save state after successful full download
                if success:
                    current_state = self.get_repo_state()
                    if current_state:
                        current_state['last_checked'] = current_state['last_commit_date']
                        self.save_local_state(current_state)
                    
                    # Resources state is saved in extract_skins_from_zip if resources were extracted
                
                if success:
                    self._emit_progress(100, "Skins ready")
                    return True
                self._emit_progress(100, "Extraction failed")
                return False
                
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
            self._emit_progress(100, f"Failed: {e}")
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


def download_skins_from_repo(
    target_dir: Path = None,
    force_update: bool = False,
    tray_manager=None,
    use_incremental: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
) -> bool:
    """Download skins from repository with optional incremental updates"""
    try:
        # Note: tray_manager status is already set by caller (download_skins_on_startup)
        downloader = RepoDownloader(target_dir, progress_callback=progress_callback)
        
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
