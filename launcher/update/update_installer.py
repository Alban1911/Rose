"""Stage a complete Windows update beside the installation before switching it."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

from config import SINGLE_INSTANCE_MUTEX_NAME
from utils.core.atomic_file import write_text_atomic
from utils.core.logging import get_named_logger
from utils.core.safe_extract import UnsafePathError, safe_extractall

updater_log = get_named_logger("updater", prefix="log_updater")

PENGU_PLUGIN_DIRS = (Path("Pengu Loader/plugins"), Path("_internal/Pengu Loader/plugins"))
PERSISTENT_FILENAMES = {"config.ini", "hashes.game.txt", "rose.cfg"}
WORKSPACE_MARKER = ".rose-update-workspace"
WORKSPACE_VERSION = b"rose-update-v1"
RECOVERY_COMMAND = r"""@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0apply.ps1" -Recover
if errorlevel 1 (
    echo Recovery failed. See "%~dp0update.log".
    pause
)
"""

# Keep this outside either application tree so Windows can rename both trees.
# A named mutex stays alive while any process has an open handle to it.
APPLY_UPDATE_SCRIPT = r"""
param([switch]$Recover, [switch]$Notify)
$ErrorActionPreference = 'Stop'
$log = Join-Path $PSScriptRoot 'update.log'
$previous = Join-Path $PSScriptRoot 'previous'
$failed = Join-Path $PSScriptRoot 'failed'
$plan = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'plan.json') | ConvertFrom-Json
$destination = $plan.destination
$executable = Join-Path $destination $plan.executable
$mutex = $null
$result = 0
$swapStarted = $false

function Write-UpdateLog([string]$message) {
    Add-Content -LiteralPath $log -Value ("[{0:u}] {1}" -f (Get-Date), $message) -Encoding UTF8 -ErrorAction SilentlyContinue
}

function Move-Directory([string]$source, [string]$target) {
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            [System.IO.Directory]::Move($source, $target)
            return
        }
        catch [System.IO.IOException] {
            if ($attempt -eq 20) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}

function Start-Rose {
    # Start-Process expands wildcards: an install path holding [ ] was not found
    $info = [System.Diagnostics.ProcessStartInfo]::new($executable)
    $info.WorkingDirectory = $destination
    $info.UseShellExecute = $true
    return [System.Diagnostics.Process]::Start($info)
}

function New-RecoveryMutex {
    $created = $false
    $handle = [System.Threading.Mutex]::new($false, $plan.mutex, [ref]$created)
    if (!$created) {
        $handle.Dispose()
        throw 'Close Rose and let any running update finish before recovering.'
    }
    return $handle
}

function Restore-PreviousInstallation {
    if (![System.IO.File]::Exists((Join-Path $previous $plan.executable))) {
        if ([System.IO.File]::Exists($executable)) {
            Write-UpdateLog 'No previous installation to restore. Rose is present.'
            return
        }
        throw 'There is no previous Rose installation to restore.'
    }
    if ([System.IO.Directory]::Exists($destination)) {
        Move-Directory $destination $failed
    }
    try {
        Move-Directory $previous $destination
    }
    catch {
        if (![System.IO.Directory]::Exists($destination) -and [System.IO.Directory]::Exists($failed)) {
            Move-Directory $failed $destination
        }
        throw
    }
    Write-UpdateLog 'Previous installation restored.'
}

try {
    if ($Recover) {
        $mutex = New-RecoveryMutex
        Restore-PreviousInstallation
    }
    else {
        $mutex = [System.Threading.Mutex]::OpenExisting($plan.mutex)
        $rose = Get-Process -Id $plan.parent_pid
        # Force the Process handle open before signalling readiness so the PID
        # cannot be reused between handoff and the wait.
        $null = $rose.Handle
        [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'ready'), '')
        if (!$rose.WaitForExit(30000)) { throw 'Timed out waiting for Rose to exit.' }

        if (![System.IO.File]::Exists((Join-Path $plan.candidate $plan.executable))) {
            throw 'The staged Rose executable is missing.'
        }
        $swapStarted = $true
        Move-Directory $destination $previous
        try {
            Move-Directory $plan.candidate $destination
        }
        catch {
            Move-Directory $previous $destination
            throw
        }
        Write-UpdateLog 'Switched installation directories. Previous installation kept for recovery.'
    }
}
catch {
    Write-UpdateLog ("Operation failed: " + $_.Exception.Message)
    $result = 1
}
finally {
    if ($null -ne $mutex) { $mutex.Dispose() }
}

if ($result -eq 0 -and !$Recover) {
    try {
        $started = Start-Rose
        Write-UpdateLog ("Update applied. Rose relaunched (PID " + $started.Id + ").")
    }
    catch {
        Write-UpdateLog ("Could not launch the installed Rose: " + $_.Exception.Message)
        $result = 1
        try {
            $rollbackMutex = New-RecoveryMutex
            try { Restore-PreviousInstallation }
            finally { $rollbackMutex.Dispose() }
        }
        catch {
            Write-UpdateLog ("Automatic rollback could not run: " + $_.Exception.Message)
        }
    }
}
elseif ($result -ne 0 -and $swapStarted -and [System.IO.File]::Exists($executable)) {
    # The swap failed and was undone (or never moved anything): Rose has
    # exited for it, so start the installed one again
    try { $null = Start-Rose; Write-UpdateLog 'Restarted the installed Rose.' }
    catch { Write-UpdateLog ("Could not restart the installed Rose: " + $_.Exception.Message) }
}
if ($result -ne 0 -and $Notify) {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show(
        "Rose could not complete the update. The log is at " + $log +
        ". If Rose cannot start, run Recover-Rose.cmd as administrator from " + $PSScriptRoot + ".",
        'Rose update failed', 'OK', 'Error')
}
exit $result
"""


def _is_reparse_point(path: Path) -> bool:
    return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT) if os.name == "nt" else path.is_symlink()


def _copy_preserved_file(source: Path, target: Path) -> None:
    if _is_reparse_point(source) or not source.is_file():
        raise OSError(f"Cannot preserve {source}: expected an ordinary file")
    if target.exists() and not target.is_file():
        raise OSError(f"Cannot preserve {source}: the update puts a directory at {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_preserved_entry(source: Path, target: Path) -> None:
    if _is_reparse_point(source):
        raise OSError(f"Cannot preserve linked entry: {source}")
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for entry in source.iterdir():
            _copy_preserved_entry(entry, target / entry.name)
    else:
        _copy_preserved_file(source, target)


def _preserve_bundled_plugin_state(source: Path, target: Path) -> None:
    """Keep the entrypoint enabled or disabled, using the new plugin's code."""
    if _is_reparse_point(source):
        raise OSError(f"Cannot preserve linked plugin: {source}")
    enabled = "index.js"
    disabled = "index.js_"
    if (source / disabled).is_file():
        keep, drop = disabled, enabled
    elif (source / enabled).is_file():
        keep, drop = enabled, disabled
    else:
        return
    if (target / keep).is_file():
        (target / drop).unlink(missing_ok=True)
    elif (target / drop).is_file():
        (target / drop).rename(target / keep)


def _preserve_install_files(install_dir: Path, candidate: Path) -> None:
    runtime = install_dir / "_internal"
    managed_root = {"_internal", Path(sys.executable).name.casefold()}
    # An installer may share this directory with unrelated files. Only Rose's
    # executable and runtime can disappear or be replaced with the release.
    for entry in install_dir.iterdir():
        if _is_reparse_point(entry):
            raise OSError(f"Cannot update an installation with a linked root entry: {entry}")
        name = entry.name.casefold()
        if name in managed_root:
            continue
        target = candidate / entry.name
        if name in PERSISTENT_FILENAMES or name == "icon.ico" or re.fullmatch(r"unins\d+\.(exe|dat|msg)", name):
            _copy_preserved_file(entry, target)
        elif target.exists():
            # A name the release ships is Rose's: the installed copy stays in previous
            continue
        else:
            _copy_preserved_entry(entry, target)

    if not runtime.is_dir():
        raise OSError(f"The installed Rose runtime is missing: {runtime}")
    for folder, directories, files in os.walk(runtime, onerror=_raise):
        directory = Path(folder)
        directories[:] = [name for name in directories if not _is_reparse_point(directory / name)]
        relative = directory.relative_to(install_dir)
        for name in files:
            if name.casefold() in PERSISTENT_FILENAMES:
                _copy_preserved_file(directory / name, candidate / relative / name)

    for relative in PENGU_PLUGIN_DIRS:
        current_plugins = install_dir / relative
        datastore = current_plugins.parent / "datastore"
        if current_plugins.parent.exists() and _is_reparse_point(current_plugins.parent):
            raise OSError(f"Cannot preserve linked Pengu Loader directory: {current_plugins.parent}")
        if datastore.is_file():
            _copy_preserved_file(datastore, candidate / relative.parent / "datastore")
        if not current_plugins.is_dir():
            continue
        if _is_reparse_point(current_plugins):
            raise OSError(f"Cannot preserve linked plugin directory: {current_plugins}")
        for entry in current_plugins.iterdir():
            target = candidate / relative / entry.name
            # A bundled Rose plugin is replaced as a unit, removing its stale files.
            if entry.name.upper().startswith("ROSE-") and target.exists():
                _preserve_bundled_plugin_state(entry, target)
                continue
            _copy_preserved_entry(entry, target)


def _raise(error: OSError) -> None:
    raise error


def _has_executable_header(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        return handle.read(2) == b"MZ"


def _has_runtime(root: Path) -> bool:
    internal = root / "_internal"
    if not zipfile.is_zipfile(internal / "base_library.zip"):
        return False
    return any(
        re.fullmatch(r"python3\d{2}t?\.dll", path.name, re.IGNORECASE) and _has_executable_header(path)
        for path in internal.glob("python*.dll")
    )


class UpdateInstaller:
    def workspace(self, install_dir: Path) -> Path:
        """Use a sibling directory on the same volume, normally in Program Files."""
        if not install_dir.name:
            raise OSError("Rose cannot update an installation in the root of a volume")
        root = install_dir.with_name(f"{install_dir.name}.update")
        root.mkdir(exist_ok=True)
        if _is_reparse_point(root):
            raise OSError(f"Update workspace is a link: {root}")
        marker = root / WORKSPACE_MARKER
        if not any(root.iterdir()):
            marker.write_bytes(WORKSPACE_VERSION)
        if not marker.is_file() or _is_reparse_point(marker) or marker.read_bytes() != WORKSPACE_VERSION:
            raise OSError(f"Update workspace was not created by Rose: {root}")
        return root

    def discard_snapshots(self, install_dir: Path) -> None:
        """Rose started from the swapped-in tree: drop the recovery trees.

        Recover-Rose.cmd is for a Rose that cannot start; one that got this far
        can update itself. An uninstall left them behind otherwise (a full old
        Rose, beside the install).
        """
        root = install_dir.with_name(f"{install_dir.name}.update")
        try:
            if _is_reparse_point(root) or (root / WORKSPACE_MARKER).read_bytes() != WORKSPACE_VERSION:
                return
        except OSError:
            return
        for name in ("previous", "failed", "staging"):
            tree = root / name
            try:
                if tree.exists() and not _is_reparse_point(tree):
                    shutil.rmtree(tree)
            except OSError as exc:
                updater_log.debug("Could not remove %s: %s", tree, exc)

    def extract_update(
        self,
        zip_path: Path,
        staging_dir: Path,
        progress_callback: Callable[[int], None],
        status_callback: Callable[[str], None],
    ) -> Optional[Path]:
        """Extract and validate the release payload without touching the installation."""
        try:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            safe_extractall(zip_path, staging_dir)
            candidates = [p for p in staging_dir.iterdir() if p.name != "__MACOSX"]
            root = candidates[0] if len(candidates) == 1 and candidates[0].is_dir() else staging_dir
            if not _has_executable_header(root / Path(sys.executable).name) or not _has_runtime(root):
                raise ValueError("The update is missing Rose.exe or its Python runtime")
            progress_callback(60)
            return root
        except (OSError, ValueError, RuntimeError, UnsafePathError, zipfile.BadZipFile) as exc:
            status_callback(f"Extraction failed: {exc}")
            updater_log.error("Update extraction failed: %s", exc)
            return None

    def install(
        self,
        candidate: Path,
        install_dir: Path,
        updates_root: Path,
        status_callback: Callable[[str], None],
    ) -> bool:
        """Hand off the prepared update to a helper before the current Rose exits."""
        ready = updates_root / "ready"
        script = updates_root / "apply.ps1"
        try:
            _preserve_install_files(install_dir, candidate)
            # A prior completed or rolled-back update may leave recovery trees.
            # Keep the previous build until the next version is ready to install.
            for name in ("previous", "failed"):
                old_tree = updates_root / name
                if old_tree.exists():
                    shutil.rmtree(old_tree)
            ready.unlink(missing_ok=True)
            write_text_atomic(script, APPLY_UPDATE_SCRIPT)
            write_text_atomic(updates_root / "Recover-Rose.cmd", RECOVERY_COMMAND)
            write_text_atomic(updates_root / "plan.json", json.dumps({
                "destination": str(install_dir),
                "executable": Path(sys.executable).name,
                "candidate": str(candidate),
                "parent_pid": os.getpid(),
                "mutex": SINGLE_INSTANCE_MUTEX_NAME,
            }))
            powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            process = subprocess.Popen(
                [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(script), "-Notify"],
                cwd=updates_root,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            status_callback(f"Could not prepare update: {exc}")
            updater_log.error("Could not prepare update: %s", exc)
            return False

        # A cold PowerShell start behind a busy antivirus can take a while
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and process.poll() is None:
            if ready.is_file():
                updater_log.info("Update helper is ready. Update log and recovery tool: %s", updates_root)
                return True
            time.sleep(0.05)

        if process.poll() is None:
            process.terminate()
            process.wait()
        status_callback("The update helper could not start")
        updater_log.error("Update helper did not acknowledge handoff. See %s", updates_root)
        return False

