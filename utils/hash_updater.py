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
from utils.logging import get_logger, log_success
from config import APP_USER_AGENT, get_config_file_path

log = get_logger()

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


def download_file(url: str, session: requests.Session) -> Optional[bytes]:
    """Download a file from URL
    
    Returns:
        File contents as bytes, or None on error
    """
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        log.error(f"Failed to download {url}: {e}")
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


def update_hash_files(status_callback: Optional[Callable[[str], None]] = None) -> bool:
    """Check for updates and download/combine hash files if needed
    
    Args:
        status_callback: Optional callback function to report status messages
    
    Returns:
        True if files were updated, False otherwise
    """
    if status_callback:
        status_callback("Checking game hashes…")
    
    # Check if updates are available
    if not check_for_updates():
        if status_callback:
            status_callback("Game hashes are valid")
        return False
    
    log.info("Hash files have been updated, downloading...")
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
    file_0_content = download_file(file_0_url, session)
    if file_0_content is None:
        log.error(f"Failed to download {HASH_FILE_0}")
        return False
    
    log.info(f"Downloading {HASH_FILE_1}...")
    file_1_content = download_file(file_1_url, session)
    if file_1_content is None:
        log.error(f"Failed to download {HASH_FILE_1}")
        return False
    
    # Combine files
    log.info("Combining hash files...")
    combined_content = combine_hash_files(file_0_content, file_1_content)
    
    # Get target path
    tools_dir = Path(__file__).parent.parent / "injection" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    target_path = tools_dir / TARGET_FILE
    
    # Write combined file
    try:
        with open(target_path, 'wb') as f:
            f.write(combined_content)
        log_success(log, f"Successfully updated {TARGET_FILE}", "📥")
    except IOError as e:
        log.error(f"Failed to write {TARGET_FILE}: {e}")
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
    
    if status_callback:
        status_callback("Game hashes updated successfully")
    
    return True

