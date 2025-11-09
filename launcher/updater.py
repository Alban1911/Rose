"""Launcher auto-update logic for LeagueUnlocked.

Downloads the latest release ZIP from GitHub, stages it under the
user data directory, and replaces the current installation when running
as a frozen executable.
"""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable, Optional

import requests

from config import APP_VERSION, get_config_file_path

GITHUB_RELEASE_API = "https://api.github.com/repos/FlorentTariolle/LeagueUnlockedDev/releases/latest"


def auto_update(
    status_callback: Callable[[str], None],
    progress_callback: Callable[[int], None],
    bytes_callback: Optional[Callable[[int, Optional[int]], None]] = None,
) -> bool:
    """Download and install the latest release if a new version is available.

    Returns True when an update was installed, False otherwise.
    """

    status_callback("Checking for updates...")
    try:
        response = requests.get(GITHUB_RELEASE_API, timeout=20)
        response.raise_for_status()
        release = response.json()
    except Exception as exc:  # noqa: BLE001
        status_callback(f"Update check failed: {exc}")
        return False

    remote_version = release.get("tag_name") or release.get("name") or ""
    assets = release.get("assets", [])
    asset = next((a for a in assets if a.get("name", "").lower().endswith(".zip")), None)
    if not asset:
        status_callback("No release asset found")
        return False

    download_url = asset.get("browser_download_url")
    total_size = asset.get("size", 0) or None

    config_path = get_config_file_path()
    config = configparser.ConfigParser()
    if config_path.exists():
        try:
            config.read(config_path)
        except Exception:
            pass
    if not config.has_section("General"):
        config.add_section("General")
    config.set("General", "installed_version", APP_VERSION)
    try:
        with open(config_path, "w", encoding="utf-8") as fh:
            config.write(fh)
    except Exception:
        pass

    installed_version = config.get("General", "installed_version", fallback=APP_VERSION)

    if remote_version and installed_version == remote_version:
        status_callback("Launcher is already up to date")
        return False

    if not getattr(sys, "frozen", False):
        status_callback("Update skipped (dev environment)")
        return False

    updates_root = config_path.parent / "updates"
    updates_root.mkdir(parents=True, exist_ok=True)
    zip_name = asset.get("name") or "update.zip"
    zip_path = updates_root / zip_name

    status_callback(f"Downloading update {remote_version or ''}")
    try:
        with requests.get(download_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            bytes_read = 0
            chunk_size = 1024 * 128
            with open(zip_path, "wb") as fh:
                for chunk in r.iter_content(chunk_size):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    bytes_read += len(chunk)
                    if bytes_callback:
                        bytes_callback(bytes_read, total_size)
    except Exception as exc:  # noqa: BLE001
        status_callback(f"Download failed: {exc}")
        return False

    status_callback("Extracting update")
    staging_dir = updates_root / "staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            members = zip_file.infolist()
            total_members = max(len(members), 1)
            for index, member in enumerate(members, start=1):
                zip_file.extract(member, staging_dir)
                progress = 40 + int(20 * index / total_members)
                progress_callback(min(progress, 60))
    except Exception as exc:  # noqa: BLE001
        status_callback(f"Extraction failed: {exc}")
        return False

    extracted_root = _resolve_extracted_root(staging_dir)
    if extracted_root is None:
        status_callback("Invalid update package")
        return False

    status_callback("Installing update")
    install_dir = Path(sys.executable).resolve().parent
    exe_name = Path(sys.executable).name

    if not (extracted_root / exe_name).exists():
        status_callback("Update aborted: executable missing in package")
        return False

    batch_path = updates_root / "apply_update.bat"
    zip_path_str = str(zip_path)
    staging_path_str = str(staging_dir)
    updates_root_str = str(updates_root)
    log_path_str = str(updates_root / "update.log")
    try:
        with open(batch_path, "w", encoding="utf-8") as batch:
            batch.write("@echo off\n")
            batch.write("setlocal enableextensions\n")
            batch.write(f'set "SOURCE={extracted_root}"\n')
            batch.write(f'set "DEST={install_dir}"\n')
            batch.write(f'set "ZIPFILE={zip_path_str}"\n')
            batch.write(f'set "STAGING={staging_path_str}"\n')
            batch.write(f'set "UPDATES={updates_root_str}"\n')
            batch.write(f'set "LOG={log_path_str}"\n')
            batch.write('echo [%date% %time%] Update start > "%LOG%"\n')
            batch.write("ping 127.0.0.1 -n 4 >nul\n")
            batch.write('echo [%date% %time%] Mirroring files >> "%LOG%"\n')
            batch.write('robocopy "%SOURCE%" "%DEST%" /MIR /NFL /NDL /NJH /NJS /XD __pycache__ /XF config.ini license.dat >> "%LOG%" 2>&1\n')
            batch.write("if %ERRORLEVEL% GEQ 8 goto :robofail\n")
            batch.write(f'start "" /D "{install_dir}" "{install_dir / exe_name}"\n')
            batch.write('echo [%date% %time%] Cleaning staging >> "%LOG%"\n')
            batch.write('if exist "%STAGING%" rd /s /q "%STAGING%" >> "%LOG%" 2>&1\n')
            batch.write('if exist "%ZIPFILE%" del "%ZIPFILE%" >> "%LOG%" 2>&1\n')
            batch.write("del \"%~f0\" >nul 2>&1\n")
            batch.write("exit\n")
            batch.write("")
            batch.write(":robofail\n")
            batch.write('echo [%date% %time%] Update failed >> "%LOG%"\n')
            batch.write("echo Update failed. Press any key to close.\n")
            batch.write("pause >nul\n")
            batch.write("exit 1\n")
    except Exception as exc:  # noqa: BLE001
        status_callback(f"Failed to prepare updater: {exc}")
        return False

    try:
        subprocess.Popen(["cmd", "/c", str(batch_path), str(os.getpid())], close_fds=True)
    except Exception as exc:  # noqa: BLE001
        status_callback(f"Failed to launch updater: {exc}")
        return False

    progress_callback(100)
    if bytes_callback and total_size:
        bytes_callback(total_size, total_size)
    status_callback("Update installed")
    return True


def _resolve_extracted_root(staging_dir: Path) -> Optional[Path]:
    """Return the directory that contains the update payload."""
    candidates = [p for p in staging_dir.iterdir() if not p.name.startswith("__MACOSX")]
    if not candidates:
        return None
    if len(candidates) == 1 and candidates[0].is_dir():
        return candidates[0]
    return staging_dir


def _replace_tree(src: Path, dest: Path) -> None:
    raise NotImplementedError("_replace_tree is deprecated in favour of batch updater")
