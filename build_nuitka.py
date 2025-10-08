#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script for SkinCloner using Nuitka (Python to C compiler)
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
    """Clean previous builds (NEVER touches Nuitka cache!)"""
    print_step(1, 3, "Cleaning Previous Builds & Nuitka Cache")
    print("-" * 70)
    
    # Only clean build output directories - NEVER the Nuitka cache!
    dirs_to_clean = ["dist", "main.build", "main.dist"]
    
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            try:
                shutil.rmtree(dir_name)
                print(f"[OK] Removed {dir_name}/")
            except Exception as e:
                print(f"[ERROR] Failed to remove {dir_name}/: {e}")
    
    # Remove old exe files
    old_exe_files = ["main.exe", "SkinCloner.exe"]
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
    
    print("\n[INFO] Nuitka cache is PRESERVED (no re-download needed!)")
    print("[INFO] GCC compiler location: C:\\Users\\Florent\\AppData\\Local\\Nuitka\\Nuitka\\Cache\\downloads\\gcc")
    
    return True

def build_with_nuitka():
    """Build executable using Nuitka"""
    print_step(2, 3, "Building with Nuitka (Python to C Compiler)")
    
    cmd = [
        "python", "-m", "nuitka",
        "--standalone",  # Create standalone distribution
        "--onefile",  # Single executable file
        "--windows-console-mode=disable",  # No console window (updated syntax)
        "--enable-plugin=tk-inter",  # Tkinter support (for PIL)
        "--enable-plugin=anti-bloat",  # Reduce size
        f"--windows-icon-from-ico=icon.ico",  # Application icon
        "--include-data-dir=dependencies=dependencies",  # Include dependencies
        "--include-data-dir=injection/tools=injection/tools",  # Include tools
        "--include-data-file=injection/mods_map.json=injection/mods_map.json",
        "--include-data-file=icon.ico=icon.ico",
        "--include-data-file=requirements.txt=requirements.txt",
        "--include-package=database",  # Include packages
        "--include-package=injection",
        "--include-package=lcu",
        "--include-package=ocr",
        "--include-package=state",
        "--include-package=threads",
        "--include-package=utils",
        "--follow-imports",  # Follow all imports
        "--assume-yes-for-downloads",  # Auto-download dependencies
        "--nofollow-import-to=tkinter",  # Don't follow tkinter (we don't use it)
        "--nofollow-import-to=test",  # Don't follow test modules
        "--show-progress",  # Show compilation progress
        "--low-memory",  # Reduce memory usage during compilation
        "main.py"
    ]
    
    print(f"Running: {' '.join(cmd)}\n")
    print("Note: First build may take 5-15 minutes (compiles all C files)")
    print("Subsequent builds: 1-3 minutes (ccache only recompiles changed files!)")
    print("Nuitka compiles Python to C code for maximum protection!\n")
    
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
    
    # Nuitka creates main.exe (onefile mode)
    exe_file = Path("main.exe")
    dist_folder = Path("main.dist")  # May exist but not needed for onefile
    onefile_build = Path("main.onefile-build")
    
    output_dir = Path("dist/SkinCloner")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if onefile exe was created (this is what we configured)
    if exe_file.exists():
        # Single file mode - copy the exe
        target = output_dir / "SkinCloner.exe"
        
        # Use copy instead of move to avoid file locking issues
        try:
            shutil.copy2(str(exe_file), str(target))
            print(f"[OK] Copied executable to {target}")
            
            # Verify copy succeeded before deleting
            if target.exists():
                try:
                    exe_file.unlink()
                    print(f"[OK] Cleaned up {exe_file}")
                except Exception as e:
                    print(f"[WARNING] Could not delete {exe_file}: {e}")
            
        except Exception as e:
            print(f"[ERROR] Failed to copy executable: {e}")
            return False
        
    elif dist_folder.exists() and (dist_folder / "main.exe").exists():
        # Distribution folder mode (shouldn't happen with --onefile, but handle it)
        print("[INFO] Found dist folder mode output")
        
        # Copy files from dist folder instead of moving
        src_exe = dist_folder / "main.exe"
        target = output_dir / "SkinCloner.exe"
        
        try:
            shutil.copy2(str(src_exe), str(target))
            print(f"[OK] Copied executable from dist folder to {target}")
        except Exception as e:
            print(f"[ERROR] Failed to copy from dist folder: {e}")
            return False
    else:
        print("[ERROR] Build output not found!")
        print(f"  Expected: {exe_file.absolute()}")
        print(f"  Or: {dist_folder.absolute()}/main.exe")
        return False
    
    # Create launcher
    launcher_content = '''@echo off
echo Starting SkinCloner...
echo.
"%~dp0SkinCloner.exe" --verbose
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
    
    # Clean up build artifacts (but keep main.dist if it exists for debugging)
    build_dir = Path("main.build")
    if build_dir.exists():
        try:
            shutil.rmtree(build_dir)
            print("[OK] Cleaned build artifacts (main.build)")
        except Exception as e:
            print(f"[WARNING] Could not clean build artifacts: {e}")
    
    # Clean up onefile build directory
    if onefile_build.exists():
        try:
            shutil.rmtree(onefile_build)
            print("[OK] Cleaned onefile build artifacts")
        except Exception as e:
            print(f"[WARNING] Could not clean onefile artifacts: {e}")
    
    # Clean up main.dist if it exists (not needed for onefile)
    if dist_folder.exists():
        try:
            shutil.rmtree(dist_folder)
            print("[OK] Cleaned dist folder (not needed for onefile)")
        except Exception as e:
            print(f"[WARNING] Could not clean dist folder: {e}")
    
    return True

def main():
    """Main build process"""
    print_header("SkinCloner - Nuitka Build (Python to C Compilation)")
    
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
    
    exe_path = Path("dist/SkinCloner/SkinCloner.exe")
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"Executable: {exe_path}")
        print(f"Size: {size_mb:.1f} MB")
        print(f"\nYour application is now compiled to native machine code!")
        print(f"\nProtection level:")
        print(f"  [OK] Python code compiled to C")
        print(f"  [OK] Native machine code (no Python interpreter needed)")
        print(f"  [OK] Very difficult to reverse engineer")
        print(f"  [OK] Better performance than interpreted Python")
        print(f"\nTo test:")
        print(f"  cd dist\\SkinCloner")
        print(f"  start.bat")
    else:
        print("[ERROR] Executable not found!")
        print("Check the build output above for errors.")
        sys.exit(1)

if __name__ == "__main__":
    main()

