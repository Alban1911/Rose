"""
Update Installer
Handles extracting and installing updates
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable, Optional

from utils.core.logging import get_named_logger

updater_log = get_named_logger("updater", prefix="log_updater")

PERSISTENT_ROOT_FILES = ("icon.ico", "unins000.exe", "unins000.dat")


class UpdateInstaller:
    """Handles update extraction and installation"""
    
    def __init__(self):
        pass
    
    def extract_update(
        self,
        zip_path: Path,
        staging_dir: Path,
        progress_callback: Callable[[int], None],
        status_callback: Callable[[str], None],
    ) -> Optional[Path]:
        """Extract update ZIP to staging directory
        
        Args:
            zip_path: Path to the update ZIP file
            staging_dir: Directory to extract to
            progress_callback: Callback for progress updates
            status_callback: Callback for status updates
            
        Returns:
            Path to extracted root directory, or None if failed
        """
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
            
            extracted_root = self._resolve_extracted_root(staging_dir)
            if extracted_root is None:
                status_callback("Invalid update package")
                return None
            return extracted_root
        except Exception as exc:  # noqa: BLE001
            status_callback(f"Extraction failed: {exc}")
            updater_log.error(f"Update extraction failed: {exc}")
            return None
    
    def prepare_installation(
        self,
        extracted_root: Path,
        install_dir: Path,
        updates_root: Path,
        zip_path: Path,
        staging_dir: Path,
        status_callback: Callable[[str], None],
    ) -> bool:
        """Prepare update installation by creating batch script
        
        Args:
            extracted_root: Root directory of extracted update
            install_dir: Directory where application is installed
            updates_root: Root directory for updates
            zip_path: Path to the update ZIP file
            staging_dir: Staging directory
            status_callback: Callback for status updates
            
        Returns:
            True if successful, False otherwise
        """
        exe_name = Path(sys.executable).name

        if not (extracted_root / exe_name).exists():
            status_callback("Update aborted: executable missing in package")
            return False

        # Preserve persistent root files
        for relative_name in PERSISTENT_ROOT_FILES:
            source_path = install_dir / relative_name
            if not source_path.exists():
                continue
            target_path = extracted_root / relative_name
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
            except Exception as exc:  # noqa: BLE001
                status_callback(f"Warning: failed to preserve {relative_name}: {exc}")

        # Create batch script for installation
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
                batch.write('robocopy "%SOURCE%" "%DEST%" /MIR /NFL /NDL /NJH /NJS /XD __pycache__ /XF config.ini >> "%LOG%" 2>&1\n')
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
            return True
        except Exception as exc:  # noqa: BLE001
            status_callback(f"Failed to prepare updater: {exc}")
            updater_log.error(f"Failed to create batch script: {exc}")
            return False
    
    def launch_installer(self, batch_path: Path, status_callback: Callable[[str], None]) -> bool:
        """Launch the update installer batch script
        
        Args:
            batch_path: Path to the batch script
            status_callback: Callback for status updates
            
        Returns:
            True if successful, False otherwise
        """
        try:
            subprocess.Popen(["cmd", "/c", str(batch_path), str(os.getpid())], close_fds=True)
            return True
        except Exception as exc:  # noqa: BLE001
            status_callback(f"Failed to launch updater: {exc}")
            updater_log.error(f"Failed to launch installer: {exc}")
            return False
    
    @staticmethod
    def _resolve_extracted_root(staging_dir: Path) -> Optional[Path]:
        """Return the directory that contains the update payload."""
        candidates = [p for p in staging_dir.iterdir() if not p.name.startswith("__MACOSX")]
        if not candidates:
            return None
        if len(candidates) == 1 and candidates[0].is_dir():
            return candidates[0]
        return staging_dir

