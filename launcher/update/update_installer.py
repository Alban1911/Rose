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
from utils.core.safe_extract import safe_extract, is_safe_path

updater_log = get_named_logger("updater", prefix="log_updater")

PERSISTENT_ROOT_FILES = ("icon.ico", "unins000.exe", "unins000.dat")

# Standalone updater executable name
UPDATER_EXE_NAME = "updater.exe"


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
                    # Security: Use safe extraction to prevent path traversal attacks
                    safe_extract(zip_path, member.filename, staging_dir)
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
                batch.write('robocopy "%SOURCE%" "%DEST%" /MIR /NFL /NDL /NJH /NJS /XD __pycache__ "Pengu Loader\\plugins" /XF config.ini >> "%LOG%" 2>&1\n')
                batch.write("if %ERRORLEVEL% GEQ 8 goto :robofail\n")
                batch.write('echo [%date% %time%] Updating ROSE plugins (preserving user-installed) >> "%LOG%"\n')
                batch.write('if exist "%SOURCE%\\Pengu Loader\\plugins" (\n')
                batch.write('    if not exist "%DEST%\\Pengu Loader\\plugins" mkdir "%DEST%\\Pengu Loader\\plugins"\n')
                batch.write('    for /d %%D in ("%SOURCE%\\Pengu Loader\\plugins\\ROSE-*") do (\n')
                batch.write('        echo [%date% %time%]   Sync plugin %%~nxD >> "%LOG%"\n')
                batch.write('        robocopy "%%D" "%DEST%\\Pengu Loader\\plugins\\%%~nxD" /MIR /NFL /NDL /NJH /NJS /XD __pycache__ >> "%LOG%" 2>&1\n')
                batch.write('    )\n')
                batch.write(')\n')
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
        """Launch the update installer batch script (legacy method)

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

    def prepare_updater_launch(
        self,
        extracted_root: Path,
        install_dir: Path,
        updates_root: Path,
        zip_path: Path,
        staging_dir: Path,
        status_callback: Callable[[str], None],
    ) -> Optional[dict]:
        """Prepare parameters for launching the standalone updater

        Args:
            extracted_root: Root directory of extracted update
            install_dir: Directory where application is installed
            updates_root: Root directory for updates
            zip_path: Path to the update ZIP file
            staging_dir: Staging directory
            status_callback: Callback for status updates

        Returns:
            Dictionary with updater arguments, or None if preparation failed
        """
        exe_name = Path(sys.executable).name

        if not (extracted_root / exe_name).exists():
            status_callback("Update aborted: executable missing in package")
            updater_log.error(f"Executable {exe_name} not found in {extracted_root}")
            return None

        # Preserve persistent root files by copying to staging
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
                updater_log.warning(f"Failed to preserve {relative_name}: {exc}")

        # Return updater parameters
        return {
            "pid": os.getpid(),
            "install_dir": str(install_dir),
            "staging_dir": str(extracted_root),
            "log_file": str(updates_root / "updater.log"),
            "zip_file": str(zip_path),
        }

    def launch_updater(
        self,
        updater_params: dict,
        install_dir: Path,
        updates_root: Path,
        zip_path: Path,
        staging_dir: Path,
        status_callback: Callable[[str], None],
    ) -> bool:
        """Launch the standalone updater executable

        If updater.exe is not found, falls back to the batch script method.

        Args:
            updater_params: Dictionary of parameters for updater
            install_dir: Installation directory
            updates_root: Root directory for updates
            zip_path: Path to the update ZIP file
            staging_dir: Staging directory
            status_callback: Callback for status updates

        Returns:
            True if updater launched successfully
        """
        updater_path = install_dir / UPDATER_EXE_NAME

        if not updater_path.exists():
            updater_log.warning(f"Updater not found at {updater_path}, falling back to batch mode")
            status_callback("Updater not found, using fallback method...")
            return self._launch_batch_fallback(
                updater_params, install_dir, updates_root, zip_path, staging_dir, status_callback
            )

        try:
            cmd = [
                str(updater_path),
                "--pid", str(updater_params["pid"]),
                "--install-dir", updater_params["install_dir"],
                "--staging-dir", updater_params["staging_dir"],
            ]

            if updater_params.get("log_file"):
                cmd.extend(["--log-file", updater_params["log_file"]])

            if updater_params.get("zip_file"):
                cmd.extend(["--zip-file", updater_params["zip_file"]])

            updater_log.info(f"Launching standalone updater: {' '.join(cmd)}")
            subprocess.Popen(cmd, close_fds=True)
            return True

        except Exception as exc:  # noqa: BLE001
            status_callback(f"Failed to launch updater: {exc}")
            updater_log.error(f"Failed to launch standalone updater: {exc}")
            # Try batch fallback
            return self._launch_batch_fallback(
                updater_params, install_dir, updates_root, zip_path, staging_dir, status_callback
            )

    def _launch_batch_fallback(
        self,
        updater_params: dict,
        install_dir: Path,
        updates_root: Path,
        zip_path: Path,
        staging_dir: Path,
        status_callback: Callable[[str], None],
    ) -> bool:
        """Fallback method using batch script for legacy installations

        Args:
            updater_params: Dictionary of parameters (for extracted_root path)
            install_dir: Installation directory
            updates_root: Root directory for updates
            zip_path: Path to the update ZIP file
            staging_dir: Staging directory
            status_callback: Callback for status updates

        Returns:
            True if batch script launched successfully
        """
        updater_log.info("Using batch script fallback for update installation")
        extracted_root = Path(updater_params["staging_dir"])

        # Use the existing prepare_installation method
        if not self.prepare_installation(
            extracted_root, install_dir, updates_root, zip_path, staging_dir, status_callback
        ):
            return False

        batch_path = updates_root / "apply_update.bat"
        return self.launch_installer(batch_path, status_callback)

    @staticmethod
    def _resolve_extracted_root(staging_dir: Path) -> Optional[Path]:
        """Return the directory that contains the update payload."""
        candidates = [p for p in staging_dir.iterdir() if not p.name.startswith("__MACOSX")]
        if not candidates:
            return None
        if len(candidates) == 1 and candidates[0].is_dir():
            return candidates[0]
        return staging_dir

