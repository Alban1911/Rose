#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create Windows installer for Rose using Inno Setup
"""

import sys
import subprocess
import shutil
from pathlib import Path

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


def create_installer():
    """Create Windows installer using Inno Setup"""
    
    print("=" * 60)
    print("Creating Rose Windows Installer")
    print("=" * 60)
    
    # Check if Inno Setup is installed
    inno_setup_paths = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        r"C:\Program Files\Inno Setup 5\ISCC.exe"
    ]
    
    iscc_path = None
    for path in inno_setup_paths:
        if Path(path).exists():
            iscc_path = path
            break
    
    if not iscc_path:
        print("Inno Setup not found!")
        print("\nPlease install Inno Setup from: https://jrsoftware.org/isdl.php")
        print("Then run this script again.")
        return False
    
    print(f"Found Inno Setup: {iscc_path}")
    
    # Check if dist directory exists
    if not Path("dist/Rose").exists():
        print("\nError: dist/Rose directory not found!")
        print("Please run 'python build_pyinstaller.py' first to create the executable.")
        return False
    
    # Create installer directory
    installer_dir = Path("installer")
    installer_dir.mkdir(exist_ok=True)
    
    # Check if installer script exists
    if not Path("installer.iss").exists():
        print("Error: installer.iss not found!")
        return False
    
    print("\n[1/3] Preparing installer files...")
    
    # Convert tray_ready.png to ICO format for installer
    # Inno Setup requires ICO format for SetupIconFile
    png_icon = Path("assets/tray_ready.png")
    ico_icon = Path("assets/icon.ico")
    
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
    icon_dst = Path("dist/Rose/icon.ico")
    if ico_icon.exists() and not icon_dst.exists():
        shutil.copy2(ico_icon, icon_dst)
        print(f"Copied {ico_icon} to {icon_dst}")
    
    print("\n[2/3] Compiling installer...")
    
    # Compile the installer
    cmd = [iscc_path, "installer.iss"]
    print(f"Running: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print("Installer compilation failed!")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        return False
    
    print("\n[3/3] Installer created successfully!")
    
    # Check if installer was created
    installer_files = list(installer_dir.glob("Rose_Setup*.exe"))
    if installer_files:
        installer_file = installer_files[0]
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
