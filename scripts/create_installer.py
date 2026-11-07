#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create Windows installer for Rose using Inno Setup
"""

import os
import re
import sys
import subprocess
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

MIN_PYTHON = (3, 11)
if sys.version_info < MIN_PYTHON:
    sys.stderr.write(
        f"Rose build scripts require Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.\n"
        "Please re-run using an updated interpreter.\n"
    )
    sys.exit(1)

 # Avoid UnicodeEncodeError on Windows consoles configured with legacy code pages
 # (e.g. cp1252 from some Python distributions). This makes output safe.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


ISCC_NAME = "ISCC.exe"
# Escape hatch for installs we cannot see (a zip/portable ISCC, an unusual target)
ISCC_ENV_VARS = ("INNO_SETUP_PATH", "ISCC")


def _version_key(path: Path) -> tuple[int, ...]:
    """Order two ISCC candidates: "Inno Setup 6" outranks "Inno Setup 5"."""
    numbers = tuple(int(part) for part in re.findall(r"\d+", path.parent.name))
    return numbers or (0,)


def _looks_like_inno(name: str) -> bool:
    """True for "Inno Setup 6", "InnoSetup", an uninstaller DisplayName, ..."""
    return name.lower().replace(" ", "").startswith("innosetup")


def _standard_inno_directories() -> list[Path]:
    """Inno Setup folders under the install roots Windows reports.

    Every root is read from the environment instead of being spelled out, so
    the search follows Program Files to another drive or another Windows user.
    """
    roots = []

    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value))

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        # A per-user install lands in ...\Programs, an older one directly in ...
        roots.append(Path(local_appdata) / "Programs")
        roots.append(Path(local_appdata))

    directories = []
    for root in roots:
        try:
            entries = sorted(root.iterdir())
        except OSError:  # missing or unreadable root, e.g. no ProgramW6432 on 32-bit
            continue
        directories.extend(
            entry
            for entry in entries
            if entry.is_dir() and _looks_like_inno(entry.name)
        )
    return directories


def _registered_inno_directories() -> list[Path]:
    """Inno Setup folders taken from the uninstall registry entries.

    A normal install registers itself wherever it was installed to, which is
    how a non-default location such as D:\\Apps\\Inno Setup 6 is found without
    hardcoding the drive.
    """
    try:
        import winreg
    except ImportError:  # not Windows
        return []

    def read_string(key, name: str) -> str | None:
        try:
            value, _ = winreg.QueryValueEx(key, name)
        except OSError:  # value absent
            return None
        return value if isinstance(value, str) else None

    def containing_folder(value: str) -> Path | None:
        """The folder an UninstallString/DisplayIcon value points into.

        Those read D:\\Apps\\Inno Setup 6\\unins000.exe, optionally quoted and
        followed by an icon index.
        """
        cleaned = value.strip().strip('"').split(",", 1)[0].strip().strip('"')
        return Path(cleaned).parent if cleaned else None

    subkey = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    # A 32-bit Python is redirected to Wow6432Node, so ask for both views.
    hives = (
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    )

    directories = []
    for hive, access in hives:
        try:
            key = winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | access)
        except OSError:  # hive or subkey absent
            continue
        with key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                with winreg.OpenKey(key, winreg.EnumKey(key, index)) as entry:
                    display_name = read_string(entry, "DisplayName")
                    if not display_name or not _looks_like_inno(display_name):
                        continue

                    install_location = read_string(entry, "InstallLocation")
                    if install_location:
                        folders = [Path(install_location.strip().strip('"'))]
                    else:
                        folders = [
                            folder
                            for folder in (
                                containing_folder(read_string(entry, "DisplayIcon") or ""),
                                containing_folder(read_string(entry, "UninstallString") or ""),
                            )
                            if folder
                        ]
                    directories.extend(folders)
    return directories


def find_iscc() -> str | None:
    """Locate ISCC.exe without hardcoding drives or Inno Setup versions.

    An explicit override wins, then every install the registry and the standard
    roots reveal -- newest version first -- and finally PATH.
    """
    for variable in ISCC_ENV_VARS:
        override = os.environ.get(variable)
        if not override:
            continue
        candidate = Path(override)
        if candidate.is_dir():
            candidate = candidate / ISCC_NAME
        if candidate.is_file():
            return str(candidate)

    candidates = set()
    for directory in _registered_inno_directories() + _standard_inno_directories():
        candidates.add(directory / ISCC_NAME)

    found = sorted(
        (candidate for candidate in candidates if candidate.is_file()),
        key=_version_key,
        reverse=True,
    )
    if found:
        return str(found[0])

    return shutil.which("ISCC")


def create_installer():
    """Create Windows installer using Inno Setup"""
    
    print("=" * 60)
    print("Creating Rose Windows Installer")
    print("=" * 60)
    
    iscc_path = find_iscc()
    
    if not iscc_path:
        print("Inno Setup not found!")
        print("\nPlease install Inno Setup from: https://jrsoftware.org/isdl.php")
        print("Then run this script again.")
        print(f"Or point {' or '.join(ISCC_ENV_VARS)} at the ISCC.exe to use.")
        return False
    
    print(f"Found Inno Setup: {iscc_path}")
    
    # Check if dist directory exists
    if not (ROOT / "dist/Rose").exists():
        print("\nError: dist/Rose directory not found!")
        print("Please run 'python scripts/build_pyinstaller.py' first to create the executable.")
        return False
    
    # Create installer directory
    installer_dir = ROOT / "installer"
    installer_dir.mkdir(exist_ok=True)
    
    # Check if installer script exists
    if not (ROOT / "installer.iss").exists():
        print("Error: installer.iss not found!")
        return False
    
    print("\n[1/3] Preparing installer files...")
    
    # Convert tray_ready.png to ICO format for installer
    # Inno Setup requires ICO format for SetupIconFile
    png_icon = ROOT / "assets/tray_ready.png"
    ico_icon = ROOT / "assets/icon.ico"
    
    if png_icon.exists() and PIL_AVAILABLE:
        try:
            # Convert PNG to ICO with multiple sizes for best compatibility
            with Image.open(png_icon) as img:
                ico_icon.parent.mkdir(exist_ok=True)
                img.save(
                    ico_icon,
                    format="ICO",
                    sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
                )
            print(f"Converted {png_icon} to {ico_icon}")
        except Exception as e:
            print(f"Warning: Could not convert {png_icon} to ICO: {e}")
            if not ico_icon.exists():
                print("Error: No valid icon file available!")
                return False
    elif not ico_icon.exists():
        print(f"Error: Icon file not found at {ico_icon}")
        if not png_icon.exists():
            print(f"  Source PNG also not found at {png_icon}")
        return False
    
    # Copy icon file to dist directory if it doesn't exist
    icon_dst = ROOT / "dist/Rose/icon.ico"
    if ico_icon.exists() and not icon_dst.exists():
        shutil.copy2(ico_icon, icon_dst)
        print(f"Copied {ico_icon} to {icon_dst}")
    
    print("\n[2/3] Compiling installer...")
    
    # Compile the installer
    cmd = [iscc_path, str(ROOT / "installer.iss")]
    print(f"Running: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    
    if result.returncode != 0:
        print("Installer compilation failed!")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        return False
    
    print("\n[3/3] Installer created successfully!")
    
    # Check if installer was created
    # Named Rose_Setup_<version>.exe: the one just compiled is the newest
    installer_files = sorted(installer_dir.glob("Rose_Setup*.exe"), key=lambda p: p.stat().st_mtime)
    if installer_files:
        installer_file = installer_files[-1]
        size_mb = installer_file.stat().st_size / (1024 * 1024)
        print(f"\nInstaller: {installer_file}")
        print(f"Size: {size_mb:.1f} MB")
        
        print("\n" + "=" * 60)
        print("Installer Ready!")
        print("=" * 60)
        print(f"File: {installer_file}")
        print("\nFeatures:")
        print("- Windows Apps list integration")
        print("- Start Menu shortcuts")
        print("- Desktop shortcut (optional)")
        print("- Uninstaller included")
        print("- Admin privileges for proper installation")
        print("- Registry entries for Windows recognition")
        print("\nTo install:")
        print("1. Run the installer as Administrator")
        print("2. Follow the installation wizard")
        print("3. App will appear in 'Installed Apps' list")
        
        return True
    else:
        print("Installer compilation failed - no output file found!")
        return False

if __name__ == "__main__":
    success = create_installer()
    if not success:
        sys.exit(1)
