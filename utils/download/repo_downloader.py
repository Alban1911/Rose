#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Repository Downloader
Downloads the entire repository as a ZIP file and extracts it locally
Much more efficient than individual API calls
Supports incremental updates by tracking repository changes
"""

import time
import zipfile
import tempfile
import requests
from pathlib import Path
from typing import Callable, Optional, Dict, List, Tuple
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
        repo_url: str = "https://github.com/Alban1911/RoseSkin",
        progress_callback: Optional[ProgressCallback] = None,
    ):
        self.repo_url = repo_url
        # Use user data directory for skins to avoid permission issues
        self.target_dir = target_dir or get_skins_dir()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': APP_USER_AGENT,
        })
        self.progress_callback = progress_callback

        # Version tracking
        self.version_file = self.target_dir / '.skin_version'
        self.api_base = "https://api.github.com/repos/Alban1911/RoseSkin"
        self.raw_base = "https://raw.githubusercontent.com/Alban1911/RoseSkin/main"

        # If changed files exceed this, use full ZIP instead of individual downloads
        self.incremental_file_threshold = 200
    
    def _emit_progress(self, percent: float, message: Optional[str] = None):
        if not self.progress_callback:
            return
        bounded = max(0.0, min(percent, 100.0))
        self.progress_callback(int(bounded), message)
    
    def fetch_remote_sha(self) -> Optional[str]:
        """Fetch the latest commit SHA from the skin repo via GitHub API (1 API call)."""
        try:
            response = self.session.get(
                f"{self.api_base}/commits/main",
                headers={'Accept': 'application/vnd.github.v3+json'},
                timeout=10,
            )
            response.raise_for_status()
            sha = response.json().get('sha')
            if sha:
                log.info(f"Remote skin SHA: {sha[:8]}")
            return sha
        except requests.RequestException as e:
            log.warning(f"Failed to fetch remote SHA: {e}")
            return None

    def get_local_sha(self) -> Optional[str]:
        """Read the locally stored commit SHA."""
        if not self.version_file.exists():
            return None
        try:
            return self.version_file.read_text(encoding='utf-8').strip()
        except (IOError, OSError) as e:
            log.warning(f"Failed to read local SHA: {e}")
            return None

    def save_local_sha(self, sha: str):
        """Save the commit SHA locally."""
        try:
            self.version_file.parent.mkdir(parents=True, exist_ok=True)
            self.version_file.write_text(sha, encoding='utf-8')
        except (IOError, OSError) as e:
            log.warning(f"Failed to save local SHA: {e}")

    def has_repository_changed(self) -> bool:
        """Check if repository has changed by comparing commit SHAs."""
        remote_sha = self.fetch_remote_sha()
        if remote_sha is None:
            log.warning("Could not fetch remote SHA, assuming no changes")
            return False

        local_sha = self.get_local_sha()
        if local_sha is None:
            log.info("No local SHA found, repository needs download")
            return True

        if local_sha != remote_sha:
            log.info(f"Repository changed: {local_sha[:8]} -> {remote_sha[:8]}")
            return True

        log.info("Repository unchanged, skipping download")
        return False

    def get_changed_files(self, old_sha: str, new_sha: str) -> Optional[List[Dict]]:
        """Get list of changed files between two commits using GitHub compare API.

        Returns list of changed file dicts, or None if the API call fails.
        Each dict has: 'filename', 'status' ('added'/'modified'/'removed')
        """
        try:
            response = self.session.get(
                f"{self.api_base}/compare/{old_sha}...{new_sha}",
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            files = []
            for f in data.get('files', []):
                files.append({
                    'filename': f['filename'],
                    'status': f['status'],
                    'previous_filename': f.get('previous_filename'),
                })
            log.info(f"Compare API: {len(files)} changed files between {old_sha[:8]}..{new_sha[:8]}")
            return files
        except requests.RequestException as e:
            log.warning(f"Compare API failed, will use full ZIP: {e}")
            return None

    def _resolve_local_path(self, repo_path: str) -> Optional[Path]:
        """Map a repo-relative path (skins/... or resources/...) to a local path."""
        from utils.core.paths import get_user_data_dir
        if repo_path.startswith('skins/'):
            return self.target_dir / repo_path[len('skins/'):]
        elif repo_path.startswith('resources/'):
            return get_user_data_dir() / "resources" / repo_path[len('resources/'):]
        return None

    def download_changed_files(self, changed_files: List[Dict]) -> bool:
        """Download changed files individually via raw.githubusercontent.com.

        Handles skins/ and resources/ paths. Supports add, modify, remove, rename.
        Returns True if all files were processed successfully.
        """
        total = len(changed_files)
        success_count = 0
        fail_count = 0
        dirs_to_check = set()

        for idx, file_info in enumerate(changed_files, 1):
            filename = file_info['filename']
            status = file_info['status']
            local_path = self._resolve_local_path(filename)

            if local_path is None:
                continue

            # Handle renames — delete old path, then download new
            if status == 'renamed' and file_info.get('previous_filename'):
                old_path = self._resolve_local_path(file_info['previous_filename'])
                if old_path and old_path.exists():
                    try:
                        old_path.unlink()
                        dirs_to_check.add(old_path.parent)
                        log.debug(f"Removed old path {file_info['previous_filename']}")
                    except OSError as e:
                        log.warning(f"Failed to remove old path {old_path}: {e}")

            # Handle removals
            if status == 'removed':
                if local_path.exists():
                    try:
                        local_path.unlink()
                        dirs_to_check.add(local_path.parent)
                        log.debug(f"Removed {filename}")
                    except OSError as e:
                        log.warning(f"Failed to remove {local_path}: {e}")
                success_count += 1
                progress = 10 + int(80 * idx / total)
                self._emit_progress(progress, f"Updating files... {idx}/{total}")
                continue

            # Download added/modified/renamed files
            raw_url = f"{self.raw_base}/{filename}"
            try:
                resp = self.session.get(raw_url, stream=True, timeout=SKIN_DOWNLOAD_STREAM_TIMEOUT_S)
                resp.raise_for_status()
                local_path.parent.mkdir(parents=True, exist_ok=True)
                with open(local_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                success_count += 1
                log.debug(f"Downloaded {filename}")
            except requests.RequestException as e:
                log.warning(f"Failed to download {filename}: {e}")
                fail_count += 1

            progress = 10 + int(80 * idx / total)
            self._emit_progress(progress, f"Updating files... {idx}/{total}")

        # Clean up empty directories left by removals/renames
        for dir_path in sorted(dirs_to_check, reverse=True):
            try:
                while dir_path != self.target_dir and dir_path.exists() and not any(dir_path.iterdir()):
                    dir_path.rmdir()
                    dir_path = dir_path.parent
            except OSError:
                pass

        log.info(f"Incremental update: {success_count} succeeded, {fail_count} failed out of {total}")
        return fail_count == 0
    
    def download_repo_zip(self, progress_start: float = 0.0, progress_end: float = 70.0, download_label: str = "skins") -> Optional[Path]:
        """Download the entire repository as a ZIP file with retry logic"""
        # GitHub's ZIP download URL format
        zip_url = f"{self.repo_url}/archive/refs/heads/main.zip"

        log.info(f"Downloading repository ZIP from: {zip_url}")

        # Retry configuration
        max_retries = 3
        base_delay = 2  # seconds

        for attempt in range(1, max_retries + 1):
            temp_zip_path = None
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
                unknown_estimated_total = total_size if total_size else 200 * 1024 * 1024

                # Use appropriate label based on what's being downloaded
                # Note: We must download the full ZIP, but will only extract what's needed
                if download_label == "resources":
                    progress_msg = "Downloading repository ZIP (will extract skin ID mapping only)..."
                elif download_label == "both":
                    progress_msg = "Downloading repository ZIP (skins + skin ID mapping)..."
                else:
                    progress_msg = "Downloading repository ZIP (will extract skins only)..."

                if attempt > 1:
                    progress_msg = f"[Retry {attempt}/{max_retries}] {progress_msg}"

                self._emit_progress(progress_start, progress_msg)

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
                                    f"{progress_msg} {downloaded_mb} / {total_mb}",
                                )

                log.info(f"Repository ZIP downloaded: {temp_zip_path}")
                final_total = total_size if total_size else downloaded
                self._emit_progress(progress_end, f"Download complete ({_format_size(downloaded)} / {_format_size(final_total)})")
                return temp_zip_path

            except requests.RequestException as e:
                log.warning(f"Download attempt {attempt}/{max_retries} failed: {e}")
                # Clean up partial download
                if temp_zip_path and temp_zip_path.exists():
                    try:
                        temp_zip_path.unlink()
                    except Exception:
                        pass

                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))  # Exponential backoff: 2s, 4s, 8s
                    log.info(f"Retrying in {delay} seconds...")
                    self._emit_progress(progress_start, f"Download failed, retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    log.error(f"Failed to download repository ZIP after {max_retries} attempts: {e}")
                    return None

            except Exception as e:
                log.error(f"Error downloading repository: {e}")
                # Clean up partial download
                if temp_zip_path and temp_zip_path.exists():
                    try:
                        temp_zip_path.unlink()
                    except Exception:
                        pass
                return None

        return None
    
    def _cleanup_removed_skin_files(
        self,
        zip_file_list: List[zipfile.ZipInfo],
        target_dir: Path,
    ) -> int:
        """Remove files from target directory that are no longer in the repository ZIP

        Args:
            zip_file_list: List of ZipInfo objects from the repository ZIP
            target_dir: Target directory to clean up

        Returns:
            Number of files deleted
        """
        if not target_dir.exists():
            return 0
        
        # Guard: Skip cleanup if file list is empty to prevent deleting all files
        if not zip_file_list:
            log.debug("Skipping cleanup: no files in ZIP list (empty list would delete all local files)")
            return 0
        
        # Build set of expected file paths from ZIP (as relative paths for comparison)
        expected_relative_paths = set()
        for file_info in zip_file_list:
            if file_info.is_dir():
                continue
            
            # Convert ZIP path to relative path
            relative_path = file_info.filename.replace('RoseSkin-main/', '')

            # Remove 'skins/' or 'resources/' prefix to match local structure
            if relative_path.startswith('skins/'):
                relative_path = relative_path.replace('skins/', '', 1)
            elif relative_path.startswith('resources/'):
                relative_path = relative_path.replace('resources/', '', 1)

            # Store as relative path string for comparison (normalize separators and case)
            normalized_path = relative_path.replace('\\', '/').lower()  # Case-insensitive comparison
            expected_relative_paths.add(normalized_path)
        
        # Guard: Skip cleanup if expected paths set is empty (e.g., all entries were directories)
        if not expected_relative_paths:
            log.debug("Skipping cleanup: no file entries found in ZIP list (only directories or empty)")
            return 0
        
        # Find all files in target directory
        deleted_count = 0
        for local_file in target_dir.rglob('*'):
            if not local_file.is_file():
                continue
            
            # Skip state files (like .repo_state.json) but keep other files
            if local_file.name.startswith('.') and local_file.name.endswith('_state.json'):
                continue
            
            # Get relative path from target_dir
            try:
                relative_path = local_file.relative_to(target_dir)
                # Normalize separators and case for case-insensitive comparison
                relative_path_str = str(relative_path).replace('\\', '/').lower()
            except ValueError:
                # File is not under target_dir (shouldn't happen, but skip if it does)
                continue
            
            # If file exists locally but not in expected set, delete it
            if relative_path_str not in expected_relative_paths:
                try:
                    local_file.unlink()
                    deleted_count += 1
                    log.debug(f"Removed obsolete file: {local_file}")
                except Exception as e:
                    log.warning(f"Failed to remove {local_file}: {e}")
        
        # Clean up empty directories
        try:
            for dir_path in sorted(target_dir.rglob('*'), reverse=True):
                if dir_path.is_dir() and not any(dir_path.iterdir()):
                    try:
                        dir_path.rmdir()
                    except Exception:
                        pass
        except Exception as e:
            log.debug(f"Error cleaning up empty directories: {e}")
        
        return deleted_count
    
    def extract_skins_from_zip(
        self,
        zip_path: Path,
        overwrite_existing: bool = False,
        progress_start: float = 70.0,
        progress_end: float = 100.0,
        extract_skins: bool = True,
        extract_resources: bool = True,
    ) -> bool:
        """Extract skins, previews, and resources folder from the RoseSkin repository ZIP"""
        try:
            log.info("Extracting skins, previews, and resources folder from RoseSkin repository ZIP...")

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Find all files in the skins/ directory
                skins_files = []
                zip_count = 0
                png_count = 0
                
                if extract_skins:
                    for file_info in zip_ref.filelist:
                        # Look for files in skins/ directory, but skip the skins directory itself
                        if (file_info.filename.startswith('RoseSkin-main/skins/') and 
                            file_info.filename != 'RoseSkin-main/skins/' and
                            not file_info.filename.endswith('/')):
                            skins_files.append(file_info)
                            
                            # Count file types for accurate reporting
                            if file_info.filename.endswith('.rse'):
                                zip_count += 1
                            elif file_info.filename.endswith('.png'):
                                png_count += 1
                
                # Find all files in the resources/ directory (entire folder)
                resources_files = []
                resources_count = 0
                
                if extract_resources:
                    for file_info in zip_ref.filelist:
                        # Look for files in resources/ directory (entire folder)
                        if (file_info.filename.startswith('RoseSkin-main/resources/') and 
                            file_info.filename != 'RoseSkin-main/resources/' and
                            not file_info.filename.endswith('/')):
                            resources_files.append(file_info)
                            resources_count += 1
                
                if not skins_files and not resources_files:
                    log.error("No skins or resources folder found in repository ZIP")
                    return False
                
                if extract_skins and not skins_files:
                    log.warning("No skins folder found in repository ZIP, but skins extraction was requested")
                
                if extract_resources and not resources_files:
                    log.warning("No resources folder found in repository ZIP, but resources extraction was requested")
                
                log.info(f"Found {zip_count} skin .rse files, {png_count} preview .png files, and {resources_count} resource files in repository")
                
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
                # Place the entire resources folder as resources
                mapping_target_dir = get_user_data_dir() / "resources"

                # Reserve 5% of progress range for cleanup operations
                cleanup_reserve = 5.0
                extraction_end = progress_end - cleanup_reserve
                
                def update_progress(label: str):
                    if total_bytes <= 0:
                        return
                    fraction = min(processed_bytes / total_bytes, 1.0)
                    # Cap extraction progress to leave room for cleanup
                    percent = progress_start + fraction * (extraction_end - progress_start)
                    current_mb = _format_size(processed_bytes)
                    total_mb = _format_size(total_bytes)
                    self._emit_progress(percent, f"{label} {current_mb} / {total_mb}")

                for entry_type, file_info in entries:
                    try:
                        if file_info.is_dir():
                            continue

                        label = "Extracting skins..." if entry_type == "skin" else "Extracting skin ID mapping..."
                        relative_path = file_info.filename.replace('RoseSkin-main/', '')
                        is_zip = relative_path.endswith('.rse')
                        is_png = relative_path.endswith('.png')

                        if entry_type == "skin":
                            if relative_path.startswith('skins/'):
                                relative_path = relative_path.replace('skins/', '', 1)
                            extract_path = self.target_dir / relative_path
                        else:
                            # Extract entire resources folder structure, removing 'resources/' prefix
                            # so it becomes the resources folder
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

                # Clean up files that exist locally but are no longer in the repository
                # Only perform cleanup if we have files in the ZIP to compare against
                # Use the reserved progress range (extraction_end to progress_end)
                cleanup_progress_start = extraction_end
                if extract_skins and skins_files:
                    if extract_resources and resources_files:
                        # Both cleanups: split the range
                        self._emit_progress(cleanup_progress_start + 1.0, "Cleaning up removed files...")
                    else:
                        # Only skins cleanup
                        self._emit_progress(cleanup_progress_start + 2.0, "Cleaning up removed files...")
                    deleted_count = self._cleanup_removed_skin_files(skins_files, self.target_dir)
                    if deleted_count > 0:
                        log.info(f"Removed {deleted_count} files that no longer exist in repository")
                
                if extract_resources and resources_files:
                    if extract_skins and skins_files:
                        # Both cleanups: second one
                        self._emit_progress(cleanup_progress_start + 3.0, "Cleaning up removed resource files...")
                    else:
                        # Only resources cleanup
                        self._emit_progress(cleanup_progress_start + 2.0, "Cleaning up removed resource files...")
                    deleted_resources_count = self._cleanup_removed_skin_files(resources_files, mapping_target_dir)
                    if deleted_resources_count > 0:
                        log.info(f"Removed {deleted_resources_count} resource files that no longer exist in repository")

                log.info(f"Extracted {extracted_zip_count} new skin .rse files, {extracted_png_count} preview .png files, "
                        f"and {extracted_resources_count} resource files (skipped {skipped_skin_count} existing skin files, "
                        f"{skipped_resources_count} existing resource files)")

                total_mb = _format_size(total_bytes)
                self._emit_progress(progress_end, f"Extraction complete ({_format_size(processed_bytes)} / {total_mb})")
                # Return True if extraction completed successfully, regardless of whether new files were extracted
                # (files may already be up to date, which is still a success)
                return True
                
        except zipfile.BadZipFile:
            log.error("Invalid ZIP file")
            return False
        except Exception as e:
            log.error(f"Error extracting skins: {e}")
            return False
    
    def download_incremental_updates(self, force_update: bool = False) -> bool:
        """Check for updates via commit SHA and download incrementally if possible."""
        try:
            self._emit_progress(0, "Checking for skin updates...")

            remote_sha = self.fetch_remote_sha()
            if remote_sha is None:
                log.warning("Could not fetch remote SHA, assuming no changes")
                self._emit_progress(100, "Skins already up to date")
                return True

            local_sha = self.get_local_sha()

            # No change
            if not force_update and local_sha == remote_sha:
                log.info("Repository unchanged, skipping download")
                self._emit_progress(100, "Skins already up to date")
                return True

            # Try incremental update if we have both SHAs
            if not force_update and local_sha and local_sha != remote_sha:
                self._emit_progress(5, "Checking changed files...")
                changed_files = self.get_changed_files(local_sha, remote_sha)

                if changed_files is not None and 0 < len(changed_files) <= self.incremental_file_threshold:
                    log.info(f"Incremental update: {len(changed_files)} files (threshold: {self.incremental_file_threshold})")
                    self._emit_progress(10, f"Downloading {len(changed_files)} changed files...")
                    success = self.download_changed_files(changed_files)
                    if success:
                        self.save_local_sha(remote_sha)
                        self._emit_progress(100, "Skins updated")
                        return True
                    else:
                        log.warning("Incremental update had failures, falling back to full ZIP")

                elif changed_files is not None and len(changed_files) > self.incremental_file_threshold:
                    log.info(f"Too many changed files ({len(changed_files)}), using full ZIP")

            # Fall back to full ZIP download
            return self.download_and_extract_skins(force_update=True)

        except Exception as e:
            log.error(f"Failed to check for updates: {e}")
            self._emit_progress(100, f"Failed: {e}")
            return False
    
    def download_and_extract_skins(self, force_update: bool = False) -> bool:
        """Download repository ZIP and extract skins + resources"""
        try:
            self._emit_progress(0, "Preparing download...")
            # Clean up any conflicting files
            if self.target_dir.exists():
                skins_file = self.target_dir / "skins"
                if skins_file.exists() and skins_file.is_file():
                    log.info("Removing conflicting 'skins' file...")
                    skins_file.unlink()

            # Download repository ZIP
            zip_path = self.download_repo_zip(progress_start=5.0, progress_end=70.0, download_label="both")
            if not zip_path:
                self._emit_progress(5, "Failed to start download")
                return False

            try:
                # Extract everything (skins + resources)
                success = self.extract_skins_from_zip(
                    zip_path,
                    overwrite_existing=True,
                    progress_start=70.0,
                    progress_end=100.0,
                    extract_skins=True,
                    extract_resources=True,
                )

                # Save SHA after successful download
                if success:
                    remote_sha = self.fetch_remote_sha()
                    if remote_sha:
                        self.save_local_sha(remote_sha)

                if success:
                    self._emit_progress(100, "Skins ready")
                    return True
                self._emit_progress(100, "Extraction failed")
                return False

            finally:
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
                skin_files = list(champion_dir.glob("*.zip")) + list(champion_dir.glob("*.rse"))
                stats[champion_dir.name] = len(skin_files)

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
                    skin_rse = skin_dir / f"{skin_dir.name}.rse"
                    skin_png = skin_dir / f"{skin_dir.name}.png"

                    if skin_zip.exists() or skin_rse.exists():
                        total_skins += 1
                    if skin_png.exists():
                        total_previews += 1

                    # Count chromas in this skin's chroma subdirectories
                    # Structure: {champion_id}/{skin_id}/{chroma_id}/{chroma_id}.zip or .rse
                    for chroma_dir in skin_dir.iterdir():
                        if chroma_dir.is_dir():
                            try:
                                int(chroma_dir.name)  # If this succeeds, it's a chroma ID directory

                                chroma_zip = chroma_dir / f"{chroma_dir.name}.zip"
                                chroma_rse = chroma_dir / f"{chroma_dir.name}.rse"
                                chroma_png = chroma_dir / f"{chroma_dir.name}.png"

                                if chroma_zip.exists() or chroma_rse.exists():
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
            log.info(f"{update_type.title()} database download complete (skins + previews)")
        
        return success
        
    except Exception as e:
        log.error(f"Repository download failed: {e}")
        return False
