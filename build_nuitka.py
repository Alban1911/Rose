#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script for LeagueUnlocked using Nuitka (Python to C compiler)
Better protection than obfuscation + produces native executables
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

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
    """Clean previous builds (preserves main.build for faster incremental compilation)"""
    print_step(1, 3, "Cleaning Previous Build Outputs")
    print("-" * 70)
    
    # Only clean output directories - PRESERVE main.build for incremental builds!
    dirs_to_clean = ["dist", "main.dist"]
    
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            try:
                shutil.rmtree(dir_name)
                print(f"[OK] Removed {dir_name}/")
            except Exception as e:
                print(f"[ERROR] Failed to remove {dir_name}/: {e}")
    
    # Remove old exe files
    old_exe_files = ["main.exe", "LeagueUnlocked.exe"]
    for exe_name in old_exe_files:
        if os.path.exists(exe_name):
            try:
                os.remove(exe_name)
                print(f"[OK] Removed {exe_name}")
            except Exception as e:
                print(f"[WARNING] Could not remove {exe_name}: {e}")
    
    # Clean injection directories
    injection_dirs = ["injection/mods", "injection/overlay", "injection/incoming_zips"]
    for dir_path in injection_dirs:
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
            print(f"[OK] Removed {dir_path}/")
    
    # Check if main.build exists (incremental build cache)
    if os.path.exists("main.build"):
        print("\n[INFO] ✓ Preserved main.build/ for FAST incremental compilation")
        print("[INFO]   This will make your build 10-20x faster!")
    else:
        print("\n[INFO] No main.build/ found - this will be a full build (slower)")
    
    print("[INFO] Nuitka cache is PRESERVED (no re-download needed!)")
    print("[INFO] GCC compiler location: C:\\Users\\Florent\\AppData\\Local\\Nuitka\\Nuitka\\Cache\\downloads\\gcc")
    
    return True

def build_with_nuitka():
    """Build executable using Nuitka"""
    print_step(2, 3, "Building with Nuitka (Python to C Compiler)")
    
    cmd = [
        "python", "-m", "nuitka",
        "--standalone",  # Create standalone distribution (folder with all files)
        "--windows-console-mode=disable",  # No console window (updated syntax)
        "--enable-plugin=tk-inter",  # Tkinter support (for PIL)
        "--enable-plugin=pyqt6",  # PyQt6 support (includes platform plugins)
        "--enable-plugin=anti-bloat",  # Reduce size
        # f"--windows-icon-from-ico=icon.ico",  # Application icon (disabled - antivirus blocks it)
        # Include CSLOL tools - must explicitly include .exe and .dll files
        "--include-data-file=injection/tools/mod-tools.exe=injection/tools/mod-tools.exe",
        "--include-data-file=injection/tools/cslol-diag.exe=injection/tools/cslol-diag.exe",
        "--include-data-file=injection/tools/cslol-dll.dll=injection/tools/cslol-dll.dll",
        "--include-data-file=injection/tools/wad-extract.exe=injection/tools/wad-extract.exe",
        "--include-data-file=injection/tools/wad-make.exe=injection/tools/wad-make.exe",
        "--include-data-file=injection/tools/wad-extract-multi.bat=injection/tools/wad-extract-multi.bat",
        "--include-data-file=injection/tools/wad-make-multi.bat=injection/tools/wad-make-multi.bat",
        "--include-data-file=injection/tools/wxy-extract-multi.bat=injection/tools/wxy-extract-multi.bat",
        "--include-data-dir=icons=icons",  # Include tray icons
        "--include-data-file=injection/mods_map.json=injection/mods_map.json",
        "--include-data-file=icon.ico=icon.ico",
        "--include-data-file=icon.png=icon.png",
        "--include-package=database",  # Include packages
        "--include-package=injection",
        "--include-package=lcu",
        "--include-package=ocr",
        "--include-package=state",
        "--include-package=threads",
        "--include-package=utils",
        "--include-package=easyocr",  # EasyOCR for OCR
        "--include-package-data=easyocr",  # Include EasyOCR model files and data
        "--include-package=torch",  # PyTorch deep learning framework
        "--include-package=torchvision",  # Computer vision for PyTorch
        "--include-package-data=torch",  # Include PyTorch data files
        "--follow-imports",  # Follow all imports
        "--assume-yes-for-downloads",  # Auto-download dependencies
        "--nofollow-import-to=tkinter",  # Don't follow tkinter (we don't use it)
        "--nofollow-import-to=test",  # Don't follow test modules
        "--nofollow-import-to=torch.test",  # Don't include torch tests
        "--nofollow-import-to=torch.testing",  # Don't include torch testing
        "--nofollow-import-to=torchvision.datasets",  # Don't include large datasets
        "--nofollow-import-to=matplotlib",  # Don't include matplotlib (optional dependency)
        "--nofollow-import-to=torch.utils.tensorboard",  # Don't include tensorboard utils
        "--nofollow-import-to=IPython",  # Don't include IPython (optional)
        "--nofollow-import-to=pytest",  # Don't include pytest
        "--nofollow-import-to=scipy.io",  # Don't include scipy.io (optional, but keep ndimage for EasyOCR)
        "--nofollow-import-to=skimage",  # Don't include scikit-image (using cv2 instead)
        "--nofollow-import-to=pandas",  # Don't include pandas (optional)
        "--nofollow-import-to=dask",  # Don't include dask (heavy data processing library)
        "--nofollow-import-to=numba",  # Don't include numba (JIT compiler, optional)
        "--nofollow-import-to=sympy",  # Don't include sympy (symbolic math)
        "--nofollow-import-to=networkx",  # Don't include networkx (graph algorithms)
        "--nofollow-import-to=h5py",  # Don't include h5py (HDF5 files)
        "--nofollow-import-to=setuptools",  # Don't include setuptools (build tools)
        "--nofollow-import-to=wheel",  # Don't include wheel (build tools)
        "--nofollow-import-to=pip",  # Don't include pip (package manager)
        "--nofollow-import-to=docutils",  # Don't include docutils (documentation)
        "--nofollow-import-to=jinja2",  # Don't include jinja2 (templating)
        "--nofollow-import-to=torch.distributed",  # Don't include distributed training
        "--nofollow-import-to=torchvision.models",  # Don't include large pre-trained models
        "--nofollow-import-to=torchvision.transforms",  # Don't include transforms (using cv2)
        "--show-progress",  # Show compilation progress
        "--jobs=12",  # Use 12 parallel jobs for faster compilation
        "--lto=no",  # Disable Link Time Optimization (much faster, minimal impact)
        "--mingw64",  # Use MinGW64 compiler (faster than MSVC on Windows)
        "main.py"
    ]
    
    print(f"Running: {' '.join(cmd)}\n")
    print("Note: First build may take 10-20 minutes (compiles all C files + PyTorch)")
    print("Subsequent builds: 1-3 minutes (ccache only recompiles changed files!)")
    print("Nuitka compiles Python to C code for maximum protection!")
    print("Building STANDALONE mode: All files in one folder (includes injection/tools)")
    print("\n[INFO] Includes: EasyOCR + PyTorch + torchvision (CPU mode)")
    print("   - Executable size: ~500-800 MB")
    print("   - First run requires internet to download EasyOCR models\n")
    
    try:
        result = subprocess.run(cmd, check=True)
        print("\n[OK] Nuitka build completed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Build failed: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Build failed: {e}")
        return False

def organize_output():
    """Organize output files"""
    print_step(3, 3, "Organizing Output")
    
    import time
    
    # Nuitka creates main.dist folder in standalone mode
    dist_folder = Path("main.dist")
    build_dir = Path("main.build")
    
    output_dir = Path("dist/LeagueUnlocked")
    
    # Wait a moment for Nuitka to finish writing files
    time.sleep(1)
    
    # Check if standalone distribution was created
    print(f"[INFO] Checking for standalone distribution...")
    if dist_folder.exists() and (dist_folder / "main.exe").exists():
        print("[OK] Found standalone distribution in main.dist/")
        
        # Remove old output directory if it exists
        if output_dir.exists():
            try:
                shutil.rmtree(output_dir)
                print(f"[OK] Cleaned old output directory")
            except Exception as e:
                print(f"[WARNING] Could not clean old output: {e}")
        
        # Copy entire distribution folder
        try:
            shutil.copytree(dist_folder, output_dir)
            print(f"[OK] Copied distribution to {output_dir}/")
            
            # Rename main.exe to LeagueUnlocked.exe
            old_exe = output_dir / "main.exe"
            new_exe = output_dir / "LeagueUnlocked.exe"
            if old_exe.exists():
                old_exe.rename(new_exe)
                print(f"[OK] Renamed main.exe to LeagueUnlocked.exe")
                
        except Exception as e:
            print(f"[ERROR] Failed to copy distribution: {e}")
            return False
        
    else:
        print("[ERROR] Build output not found!")
        print(f"  Expected: {dist_folder.absolute()}/main.exe")
        return False
    
    # Create launcher
    launcher_content = '''@echo off
echo Starting LeagueUnlocked...
echo.
"%~dp0LeagueUnlocked.exe" --verbose
if errorlevel 1 (
    echo.
    echo Application encountered an error.
    pause
)
'''
    launcher_path = output_dir / "start.bat"
    try:
        launcher_path.write_text(launcher_content)
        print(f"[OK] Created launcher: {launcher_path}")
    except Exception as e:
        print(f"[WARNING] Could not create launcher: {e}")
    
    # Keep main.build for faster incremental builds (contains ccache artifacts)
    # Only clean main.dist (already copied to dist/LeagueUnlocked)
    if dist_folder.exists():
        try:
            shutil.rmtree(dist_folder)
            print("[OK] Cleaned main.dist folder (already copied)")
        except Exception as e:
            print(f"[WARNING] Could not clean main.dist folder: {e}")
    
    # Note: main.build directory is preserved for faster incremental compilation
    if build_dir.exists():
        print("[INFO] Kept main.build/ for faster incremental builds (ccache artifacts)")
        print("       To force a clean build, manually delete main.build/")
    
    return True

def check_pytorch():
    """Check if PyTorch is installed"""
    try:
        import torch
        version = torch.__version__
        print(f"\n[OK] PyTorch {version} detected")
        print("[INFO] Application configured for CPU-only mode\n")
    except ImportError:
        print("\n[ERROR] PyTorch not installed!")
        print("\nPlease install PyTorch:")
        print("  pip install -r requirements.txt")
        sys.exit(1)


def main():
    """Main build process"""
    print_header("LeagueUnlocked - Nuitka Build (Python to C Compilation)")
    
    # Check PyTorch is installed
    check_pytorch()
    
    # Check if Nuitka is installed
    try:
        result = subprocess.run(
            ["python", "-m", "nuitka", "--version"],
            capture_output=True,
            text=True
        )
        print(f"Nuitka: {result.stdout.strip()}")
    except Exception:
        print("[ERROR] Nuitka not installed!")
        print("\nInstalling Nuitka...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "nuitka"],
                check=True
            )
            print("[OK] Nuitka installed successfully!")
        except Exception as e:
            print(f"[ERROR] Failed to install Nuitka: {e}")
            print("\nManual installation:")
            print("  pip install nuitka")
            sys.exit(1)
    
    # Execute build steps
    if not clean_previous_builds():
        sys.exit(1)
    
    if not build_with_nuitka():
        sys.exit(1)
    
    if not organize_output():
        print("[WARNING] Failed to organize output, but build may have succeeded")
    
    # Print summary
    print_header("[OK] BUILD COMPLETED SUCCESSFULLY!")
    
    exe_path = Path("dist/LeagueUnlocked/LeagueUnlocked.exe")
    tools_path = Path("dist/LeagueUnlocked/injection/tools")
    
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"Executable: {exe_path}")
        print(f"Size: {size_mb:.1f} MB")
        
        # Check if CSLOL tools are included
        if tools_path.exists():
            tool_files = list(tools_path.glob("*.exe")) + list(tools_path.glob("*.dll"))
            print(f"CSLOL Tools: {len(tool_files)} files included in injection/tools/")
        
        print(f"\nYour application is now compiled to native machine code!")
        print(f"\nProtection level:")
        print(f"  [OK] Python code compiled to C")
        print(f"  [OK] Native machine code (no Python interpreter needed)")
        print(f"  [OK] Very difficult to reverse engineer")
        print(f"  [OK] Better performance than interpreted Python")
        print(f"\nMode: STANDALONE (folder with all dependencies)")
        print(f"  - All DLLs and dependencies included")
        print(f"  - CSLOL tools included in injection/tools/")
        print(f"  - Can be run from any location")
        print(f"\nTo test:")
        print(f"  cd dist\\LeagueUnlocked")
        print(f"  start.bat")
    else:
        print("[ERROR] Executable not found!")
        print("Check the build output above for errors.")
        sys.exit(1)

if __name__ == "__main__":
    main()

