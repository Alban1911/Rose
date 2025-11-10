#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script for LeagueUnlocked using PyInstaller
Fast builds with Windows UI API support
"""

import sys
import subprocess
import shutil
import time
from pathlib import Path


MIN_PYTHON = (3, 11)
if sys.version_info < MIN_PYTHON:
    sys.stderr.write(
        f"LeagueUnlocked build scripts require Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.\n"
        "Please re-run using an updated interpreter.\n"
    )
    sys.exit(1)


def print_header(title):
    """Print a formatted header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def print_step(step_num, total_steps, description):
    """Print a step description"""
    print(f"\n[Step {step_num}/{total_steps}] {description}")
    print("-" * 70)


def clean_previous_builds():
    """Clean previous build output (preserves build/ cache for faster rebuilds)"""
    print_step(1, 3, "Cleaning Previous Build Output")
    
    # Only clean dist/ - preserve build/ folder for PyInstaller cache
    dirs_to_clean = ["dist"]
    
    for dir_name in dirs_to_clean:
        if Path(dir_name).exists():
            try:
                shutil.rmtree(dir_name)
                print(f"[OK] Removed {dir_name}/")
            except Exception as e:
                print(f"[ERROR] Failed to remove {dir_name}/: {e}")
    
    # Check if build cache exists
    if Path("build").exists():
        print("[INFO] Preserved build/ folder for faster incremental builds")
    else:
        print("[INFO] No build/ cache found - this will be a full build")
    
    # Clean injection directories
    injection_dirs = ["injection/mods", "injection/overlay", "injection/incoming_zips"]
    for dir_path in injection_dirs:
        if Path(dir_path).exists():
            shutil.rmtree(dir_path)
            print(f"[OK] Removed {dir_path}/")
    
    return True


def build_with_pyinstaller():
    """Build executable using PyInstaller with multi-threading"""
    print_step(2, 3, "Building with PyInstaller (Multi-threaded)")
    
    # Use spec file which has all the configuration
    cmd = [
        "pyinstaller",
        "--clean",
        "--noconfirm",
        "LeagueUnlocked.spec",
    ]
    
    print(f"Running: {' '.join(cmd)}\n")
    
    try:
        result = subprocess.run(cmd, check=True)
        print("\n[OK] PyInstaller build completed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Build failed: {e}")
        return False


def organize_output():
    """Organize output files and verify"""
    print_step(3, 3, "Organizing Output & Verification")
    
    dist_folder = Path("dist/LeagueUnlocked")
    
    if not dist_folder.exists():
        print("[ERROR] Build output not found!")
        return False
    
    return True


def main():
    """Main build process"""
    print_header("LeagueUnlocked - PyInstaller Build")
    
    start_time = time.time()
    
    # Execute build steps
    if not clean_previous_builds():
        sys.exit(1)
    
    if not build_with_pyinstaller():
        sys.exit(1)
    
    if not organize_output():
        print("[WARNING] Verification incomplete, but build may have succeeded")
    
    # Print summary
    elapsed_time = time.time() - start_time
    minutes = int(elapsed_time // 60)
    seconds = int(elapsed_time % 60)
    
    print_header("[OK] BUILD COMPLETED SUCCESSFULLY!")
    
    exe_path = Path("dist/LeagueUnlocked/LeagueUnlocked.exe")
    
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"Executable: {exe_path}")
        print(f"Size: {size_mb:.1f} MB")
        print(f"Build time: {minutes}m {seconds}s")
        
        print(f"\nYour application is ready!")
        print(f"\nMode: STANDALONE (folder with all dependencies)")
        print(f"  - All DLLs and dependencies included")
        print(f"  - Windows UI API should be fully functional!")
        print(f"  - CSLOL tools included")
        
        print(f"\nProtection:")
        print(f"  - Python bytecode (not raw source)")
        print(f"  - Requires decompiler tools to reverse")
        print(f"  - Good enough against casual theft")
        
        print(f"\nTo test:")
        print(f"  cd dist\\LeagueUnlocked")
        print(f"  LeagueUnlocked.exe")
        
        print(f"\nIMPORTANT: Check the log file after running!")
        print(f"  Look for: 'UIA Detection: Thread ready' message")
        print(f"  If you see that, Windows UI API is working!")
    else:
        print("[ERROR] Executable not found!")
        sys.exit(1)


if __name__ == "__main__":
    main()

