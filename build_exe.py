#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script for creating LoL Skin Changer executable using PyInstaller
"""

import os
import sys
import subprocess
import shutil
import fnmatch
from pathlib import Path

def read_gitignore():
    """Read .gitignore file and return list of patterns"""
    gitignore_path = Path(".gitignore")
    if not gitignore_path.exists():
        return []
    
    patterns = []
    with open(gitignore_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                patterns.append(line)
    return patterns

def should_exclude_path(path, gitignore_patterns):
    """Check if a path should be excluded based on .gitignore patterns"""
    path_str = str(path).replace('\\', '/')
    
    for pattern in gitignore_patterns:
        # Handle directory patterns (ending with /)
        if pattern.endswith('/'):
            if path_str.startswith(pattern[:-1]) or fnmatch.fnmatch(path_str, pattern[:-1]):
                return True
        # Handle regular patterns
        elif fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(os.path.basename(path_str), pattern):
            return True
    
    return False

def build_executable():
    """Build the LoL Skin Changer executable using PyInstaller"""
    
    print("=" * 50)
    print("Building LoL Skin Changer Executable")
    print("=" * 50)
    
    # Read .gitignore patterns
    gitignore_patterns = read_gitignore()
    print(f"Found {len(gitignore_patterns)} .gitignore patterns")
    
    # Check if PyInstaller is installed
    try:
        import PyInstaller
        print(f"PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        print("PyInstaller installed successfully!")
    
    # Clean previous builds
    print("\n[1/4] Cleaning previous builds...")
    for dir_name in ["build", "dist", "__pycache__"]:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"Removed {dir_name}/")
    
    # Remove spec files
    for spec_file in Path(".").glob("*.spec"):
        spec_file.unlink()
        print(f"Removed {spec_file}")
    
    # Build PyInstaller command with smart exclusions
    print("\n[2/4] Building executable...")
    cmd = [
        "pyinstaller",
        "--onedir",  # Directory distribution (faster startup)
        "--console",  # Show console window for debugging
        "--name=LoLSkinChanger",
        "--icon=icon.ico",
        "--add-data=icon.ico;.",
        "--add-data=icon.webp;.",
        "--add-data=requirements.txt;.",
    ]
    
    # Add directories while respecting .gitignore
    directories_to_add = [
        "dependencies", "database", "injection", "lcu", 
        "ocr", "state", "threads", "utils"
    ]
    
    for dir_name in directories_to_add:
        if os.path.exists(dir_name):
            # Check if the directory itself should be excluded
            if not should_exclude_path(dir_name, gitignore_patterns):
                # Use --add-data with exclusions for directories that might contain gitignored files
                if dir_name in ["injection", "state"]:  # These directories have gitignored subdirectories
                    cmd.append(f"--add-data={dir_name};{dir_name}")
                    cmd.append(f"--exclude-module={dir_name}.overlay")
                    cmd.append(f"--exclude-module={dir_name}.mods")
                    cmd.append(f"--exclude-module={dir_name}.incoming_zips")
                    if dir_name == "state":
                        cmd.append("--exclude-module=state.last_hovered_skin")
                else:
                    cmd.append(f"--add-data={dir_name};{dir_name}")
                print(f"Including directory: {dir_name}")
            else:
                print(f"Excluding directory (gitignore): {dir_name}")
        else:
            print(f"Directory not found: {dir_name}")
    
    # Add hidden imports
    hidden_imports = [
        "numpy", "cv2", "psutil", "requests", "rapidfuzz",
        "websocket", "mss", "PIL", "PIL.Image", "PIL.ImageTk",
        "tesserocr", "Pillow"
    ]
    
    for imp in hidden_imports:
        cmd.append(f"--hidden-import={imp}")
    
    # Add main script
    cmd.append("main.py")
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print("Build failed!")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        return False
    
    print("\n[3/4] Build completed successfully!")
    
    # Check if executable was created
    exe_path = Path("dist/LoLSkinChanger/LoLSkinChanger.exe")
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n[4/4] Executable created: {exe_path}")
        print(f"Size: {size_mb:.1f} MB")
        
        # Create a simple launcher script with verbose logging
        launcher_content = '''@echo off
echo Starting LoL Skin Changer with verbose logging...
echo.
"%~dp0LoLSkinChanger\LoLSkinChanger.exe" --verbose
if errorlevel 1 (
    echo.
    echo Application encountered an error.
    echo Please check that League of Legends is running.
    pause
)
'''
        launcher_path = Path("dist/start.bat")
        launcher_path.write_text(launcher_content)
        print(f"Launcher created: {launcher_path}")
        
        print("\n" + "=" * 50)
        print("Build Complete!")
        print("=" * 50)
        print(f"Executable: {exe_path}")
        print(f"Launcher: {launcher_path}")
        print("\nTo distribute:")
        print("1. Copy the entire 'dist' folder")
        print("2. Users run 'start.bat' or 'LoLSkinChanger/LoLSkinChanger.exe'")
        print("3. Make sure League of Legends is running first")
        
        return True
    else:
        print("Build failed - executable not found!")
        return False

if __name__ == "__main__":
    success = build_executable()
    if not success:
        sys.exit(1)
