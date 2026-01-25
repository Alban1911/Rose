#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Game Hash File Updater
Checks for updates to CommunityDragon game hash files and downloads/combines them
"""

import json
import requests
from pathlib import Path
from typing import Optional, Dict, Callable
from utils.core.logging import get_logger, get_named_logger, log_success
from config import APP_USER_AGENT, get_config_file_path

log = get_logger()
updater_log = get_named_logger("updater", prefix="log_updater")

# GitHub API endpoints
GITHUB_API_BASE = "https://api.github.com/repos/CommunityDragon/Data"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/CommunityDragon/Data/master"
HASHES_DIR = "hashes/lol"
HASH_FILE_0 = "hashes.game.txt.0"
HASH_FILE_1 = "hashes.game.txt.1"
TARGET_FILE = "hashes.game.txt"


def get_state_file() -> Path:
    """Get the path to the hash updater state file"""
    config_dir = get_config_file_path().parent
    return config_dir / "hash_updater_state.json"


def load_state() -> Dict:
    """Load local state from state file"""
    state_file = get_state_file()
    if not state_file.exists():
        return {}
    
    try:
        with open(state_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log.warning(f"Failed to load hash updater state: {e}")
        return {}


def save_state(state: Dict):
    """Save local state to state file"""
    state_file = get_state_file()
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)
    except IOError as e:
        log.warning(f"Failed to save hash updater state: {e}")


def check_file_commits(file_path: str, session: requests.Session) -> Optional[Dict]:
    """Check the latest commit for a specific file
    
    Returns:
        Dict with 'sha' and 'date' keys, or None on error
    """
    try:
        # Get commits for the specific file
        url = f"{GITHUB_API_BASE}/commits"
        params = {
            'path': file_path,
            'sha': 'master',
            'per_page': 1
        }
        response = session.get(url, params=params, timeout=10)
        
        if response.status_code == 404:
            log.debug(f"File {file_path} not found in repository")
            return None
        
        response.raise_for_status()
        commits = response.json()
        
        if not commits:
            log.debug(f"No commits found for {file_path}")
            return None
        
        latest_commit = commits[0]
        return {
            'sha': latest_commit['sha'],
            'date': latest_commit['commit']['committer']['date']
        }
    except requests.HTTPError as e:
        if e.response and e.response.status_code in (403, 429):
            log.warning(f"GitHub API rate limit exceeded while checking {file_path}")
            return {'rate_limited': True}
        else:
            log.error(f"Failed to check commits for {file_path}: {e}")
            return None
    except requests.RequestException as e:
        log.error(f"Failed to check commits for {file_path}: {e}")
        return None


def check_for_updates() -> bool:
    """Check if hash files have been updated on GitHub
    
    Returns:
        True if updates are available, False otherwise
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': APP_USER_AGENT,
        'Accept': 'application/vnd.github.v3+json'
    })
    
    local_state = load_state()
    
    # Check commits for both files
    file_0_path = f"{HASHES_DIR}/{HASH_FILE_0}"
    file_1_path = f"{HASHES_DIR}/{HASH_FILE_1}"
    
    file_0_commits = check_file_commits(file_0_path, session)
    file_1_commits = check_file_commits(file_1_path, session)
    
    if file_0_commits is None and file_1_commits is None:
        log.warning("Failed to check commits for both hash files")
        return False
    
    if file_0_commits and file_0_commits.get('rate_limited'):
        log.warning("Rate limited, cannot check for updates")
        return False
    
    if file_1_commits and file_1_commits.get('rate_limited'):
        log.warning("Rate limited, cannot check for updates")
        return False
    
    # Get the latest commit SHA for each file
    file_0_sha = file_0_commits['sha'] if file_0_commits else None
    file_1_sha = file_1_commits['sha'] if file_1_commits else None
    
    # Check if we have local state
    local_file_0_sha = local_state.get('file_0_sha')
    local_file_1_sha = local_state.get('file_1_sha')
    
    # If no local state, we should update
    if not local_file_0_sha and not local_file_1_sha:
        log.info("No local state found, hash files will be downloaded")
        return True
    
    # Check if either file has been updated
    file_0_updated = file_0_sha and file_0_sha != local_file_0_sha
    file_1_updated = file_1_sha and file_1_sha != local_file_1_sha
    
    if file_0_updated or file_1_updated:
        if file_0_updated:
            log.info(f"File 0 updated: {local_file_0_sha[:8] if local_file_0_sha else 'None'} -> {file_0_sha[:8]}")
        if file_1_updated:
            log.info(f"File 1 updated: {local_file_1_sha[:8] if local_file_1_sha else 'None'} -> {file_1_sha[:8]}")
        return True
    
    log.debug("Hash files are up to date")
    return False


def download_file(url: str, session: requests.Session, status_callback: Optional[Callable[[str], None]] = None) -> Optional[bytes]:
    """Download a file from URL
    
    Args:
        url: URL to download from
        session: Requests session to use
        status_callback: Optional callback for status updates
    
    Returns:
        File contents as bytes, or None on error
    """
    try:
        filename = url.split('/')[-1]
        if status_callback:
            status_callback(f"Downloading {filename}...")
        
        response = session.get(url, timeout=30, stream=True)
        response.raise_for_status()
        
        # Get total size if available
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        chunks = []
        
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                chunks.append(chunk)
                downloaded += len(chunk)
                
                # Update status with progress if callback provided
                if status_callback:
                    size_mb = downloaded / (1024 * 1024)
                    status_callback(f"Downloading {filename}... ({size_mb:.1f} MB)")
        
        content = b''.join(chunks)
        
        size_mb = len(content) / (1024 * 1024)
        updater_log.info(f"Downloaded {filename} ({size_mb:.1f} MB)")
        if status_callback:
            status_callback(f"Downloaded {filename} ({size_mb:.1f} MB)")
        
        return content
    except requests.RequestException as e:
        filename = url.split('/')[-1]
        log.error(f"Failed to download {url}: {e}")
        updater_log.error(f"Failed to download {filename}: {e}")
        if status_callback:
            status_callback(f"Failed to download {filename}")
        return None


def combine_hash_files(file_0_content: bytes, file_1_content: bytes) -> bytes:
    """Combine two hash files into one
    
    Args:
        file_0_content: Content of hashes.game.txt.0
        file_1_content: Content of hashes.game.txt.1
    
    Returns:
        Combined file content
    """
    # Decode to strings
    file_0_text = file_0_content.decode('utf-8')
    file_1_text = file_1_content.decode('utf-8')
    
    # Combine: file 0 first, then file 1
    combined = file_0_text
    if not combined.endswith('\n'):
        combined += '\n'
    combined += file_1_text
    
    return combined.encode('utf-8')


def update_hash_files(status_callback: Optional[Callable[[str], None]] = None, dev_mode: bool = False) -> bool:
    """Check for updates and download/combine hash files if needed
    
    Args:
        status_callback: Optional callback function to report status messages
        dev_mode: If True, skip hash check (for development)
    
    Returns:
        True if files were updated, False otherwise
    """
    import sys
    
    # Skip hash download/verification in dev mode
    if dev_mode:
        log.info("Hash file update skipped (dev mode)")
        updater_log.info("Hash file update skipped (dev mode)")
        if status_callback:
            status_callback("Hash check skipped (dev mode)")
        return False
    
    if status_callback:
        status_callback("Checking game hashes…")
    updater_log.info("Checking game hashes…")
    
    # Check if updates are available
    if not check_for_updates():
        updater_log.info("Game hashes are valid (no update needed)")
        if status_callback:
            status_callback("Game hashes are valid")
        return False
    
    log.info("Hash files have been updated, downloading...")
    updater_log.info("Hash files have been updated, downloading...")
    if status_callback:
        status_callback("Updating game hashes…")
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': APP_USER_AGENT,
        'Accept': 'application/vnd.github.v3+json'
    })
    
    # Download both files
    file_0_url = f"{GITHUB_RAW_BASE}/{HASHES_DIR}/{HASH_FILE_0}"
    file_1_url = f"{GITHUB_RAW_BASE}/{HASHES_DIR}/{HASH_FILE_1}"
    
    log.info(f"Downloading {HASH_FILE_0}...")
    updater_log.info(f"Downloading {HASH_FILE_0}...")
    if status_callback:
        status_callback(f"Downloading {HASH_FILE_0}...")
    file_0_content = download_file(file_0_url, session, status_callback)
    if file_0_content is None:
        log.error(f"Failed to download {HASH_FILE_0}")
        updater_log.error(f"Failed to download {HASH_FILE_0}")
        if status_callback:
            status_callback(f"Failed to download {HASH_FILE_0}")
        return False
    
    log.info(f"Downloading {HASH_FILE_1}...")
    updater_log.info(f"Downloading {HASH_FILE_1}...")
    if status_callback:
        status_callback(f"Downloading {HASH_FILE_1}...")
    file_1_content = download_file(file_1_url, session, status_callback)
    if file_1_content is None:
        log.error(f"Failed to download {HASH_FILE_1}")
        updater_log.error(f"Failed to download {HASH_FILE_1}")
        if status_callback:
            status_callback(f"Failed to download {HASH_FILE_1}")
        return False
    
    # Combine files
    log.info("Merging hashes files...")
    updater_log.info("Merging hashes files...")
    if status_callback:
        status_callback("Merging hashes files...")
    combined_content = combine_hash_files(file_0_content, file_1_content)
    
    # Get target path (same logic as injection manager)
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        if hasattr(sys, '_MEIPASS'):
            # One-file mode: tools are in _MEIPASS
            base_path = Path(sys._MEIPASS)
            tools_dir = base_path / "injection" / "tools"
        else:
            # One-dir mode: tools are alongside executable
            base_dir = Path(sys.executable).parent
            possible_tools_dirs = [
                base_dir / "injection" / "tools",
                base_dir / "_internal" / "injection" / "tools",
            ]
            tools_dir = None
            for dir_path in possible_tools_dirs:
                if dir_path.exists():
                    tools_dir = dir_path
                    break
            if not tools_dir:
                tools_dir = possible_tools_dirs[0]
    else:
        # Running as Python script
        tools_dir = Path(__file__).parent.parent.parent / "injection" / "tools"
    
    tools_dir.mkdir(parents=True, exist_ok=True)
    target_path = tools_dir / TARGET_FILE
    
    # Write combined file
    try:
        updater_log.info(f"Writing {TARGET_FILE}...")
        if status_callback:
            status_callback(f"Writing {TARGET_FILE}...")
        with open(target_path, 'wb') as f:
            f.write(combined_content)
        size_mb = len(combined_content) / (1024 * 1024)
        log_success(log, f"Successfully created {TARGET_FILE} ({size_mb:.1f} MB)", "")
        updater_log.info(f"Successfully created {TARGET_FILE} ({size_mb:.1f} MB)")
        if status_callback:
            status_callback(f"Successfully created {TARGET_FILE} ({size_mb:.1f} MB)")
    except IOError as e:
        log.error(f"Failed to write {TARGET_FILE}: {e}")
        updater_log.error(f"Failed to write {TARGET_FILE}: {e}")
        if status_callback:
            status_callback(f"Failed to write {TARGET_FILE}")
        return False
    
    # Update state with new commit SHAs
    session_state = requests.Session()
    session_state.headers.update({
        'User-Agent': APP_USER_AGENT,
        'Accept': 'application/vnd.github.v3+json'
    })
    
    file_0_path = f"{HASHES_DIR}/{HASH_FILE_0}"
    file_1_path = f"{HASHES_DIR}/{HASH_FILE_1}"
    
    file_0_commits = check_file_commits(file_0_path, session_state)
    file_1_commits = check_file_commits(file_1_path, session_state)
    
    new_state = {}
    if file_0_commits and not file_0_commits.get('rate_limited'):
        new_state['file_0_sha'] = file_0_commits['sha']
        new_state['file_0_date'] = file_0_commits['date']
    if file_1_commits and not file_1_commits.get('rate_limited'):
        new_state['file_1_sha'] = file_1_commits['sha']
        new_state['file_1_date'] = file_1_commits['date']
    
    if new_state:
        save_state(new_state)
    
    updater_log.info("Game hashes updated successfully")
    if status_callback:
        status_callback("Game hashes updated successfully")
    
    return True

