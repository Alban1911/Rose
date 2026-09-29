#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script for Rose using PyInstaller
Fast builds with Windows UI API support
"""

import sys
import subprocess
import shutil
import stat
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


MIN_PYTHON = (3, 11)
if sys.version_info < MIN_PYTHON:
    sys.stderr.write(
        f"Rose build scripts require Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.\n"
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
    """Clean only the active output, preserving archived releases and build/ cache."""
    print_step(1, 4, "Cleaning Previous Build Output")

    try:
        workspace = ROOT.resolve()
        output = workspace / "dist" / "Rose"
        # Validate both paths even when Rose is absent: PyInstaller must not
        # create its output through a redirected dist directory.
        for directory in (output.parent, output):
            resolved = directory.resolve()
            if not resolved.is_relative_to(workspace) or resolved != directory:
                raise ValueError(f"Refusing redirected build output: {directory}")
            try:
                metadata = directory.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode) or (
                getattr(metadata, "st_file_attributes", 0)
                & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ValueError(f"Refusing linked build output: {directory}")
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(f"Build output path is not a directory: {directory}")

        if output.exists():
            shutil.rmtree(output)
            print("[OK] Removed dist/Rose/ (preserved other dist/ contents)")
    except (OSError, RuntimeError, ValueError) as e:
        print(f"[ERROR] Failed to clean dist/Rose/: {e}")
        return False
    
    # Check if build cache exists
    if (ROOT / "build").exists():
        print("[INFO] Preserved build/ folder for faster incremental builds")
    else:
        print("[INFO] No build/ cache found - this will be a full build")
    
    # Note: injection/ directories are no longer cleaned as they contain real scripts
    # that need to be preserved (tools, config, etc.)
    
    return True


def build_pengu_loader():
    """Build the vendored Pengu Loader source before packaging Rose."""
    print_step(2, 4, "Building Pengu Loader From Source")

    script = ROOT / "scripts" / "build_pengu_loader.py"
    result = subprocess.run([sys.executable, str(script)], check=False, cwd=ROOT)
    if result.returncode != 0:
        print(f"[ERROR] Pengu Loader source build failed with exit code {result.returncode}")
        return False

    return True


def build_cslol_stub():
    """Build the stand-in cslol-dll.dll that mod-tools.exe needs to start."""
    script = ROOT / "scripts" / "build_cslol_stub.py"
    result = subprocess.run([sys.executable, str(script)], check=False, cwd=ROOT)
    if result.returncode != 0:
        print(f"[ERROR] cslol-dll stub build failed with exit code {result.returncode}")
        return False

    return True


def check_relay_config():
    """Refuse to build without the gitignored party relay config (party mode would ship broken)."""
    config = ROOT / "party" / "network" / "relay_config.py"
    if not config.exists() or "RELAY_URL" not in config.read_text(encoding="utf-8"):
        print(f"[ERROR] Missing {config.relative_to(ROOT)} - party mode cannot reach its relay without it")
        print('        Create it with: RELAY_URL = "wss://<relay-worker-host>"')
        return False

    return True


def build_with_pyinstaller():
    """Build executable using PyInstaller with multi-threading"""
    print_step(3, 4, "Building with PyInstaller (Multi-threaded)")

    # Use spec file which has all the configuration
    cmd = [
        "pyinstaller",
        "--clean",
        "--noconfirm",
        "Rose.spec",
    ]
    
    print(f"Running: {' '.join(cmd)}\n")
    
    try:
        result = subprocess.run(cmd, check=True, cwd=ROOT)
        print("\n[OK] PyInstaller build completed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Build failed: {e}")
        return False


def organize_output():
    """Organize output files and verify"""
    print_step(4, 4, "Organizing Output & Verification")
    
    dist_folder = ROOT / "dist/Rose"
    
    if not dist_folder.exists():
        print("[ERROR] Build output not found!")
        return False
    
    return True


def main():
    """Main build process"""
    print_header("Rose - PyInstaller Build")
    
    start_time = time.time()
    
    # Execute build steps
    if not check_relay_config():
        sys.exit(1)

    if not clean_previous_builds():
        sys.exit(1)

    # --skip-pengu-loader packages the existing Pengu Loader build as-is
    if "--skip-pengu-loader" not in sys.argv[1:] and not build_pengu_loader():
        sys.exit(1)

    if not build_cslol_stub():
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
    
    exe_path = ROOT / "dist/Rose/Rose.exe"
    
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"Executable: {exe_path}")
        print(f"Size: {size_mb:.1f} MB")
        print(f"Build time: {minutes}m {seconds}s")
        
        print(f"\nYour application is ready!")
        print(f"\nMode: STANDALONE (folder with all dependencies)")
        print(f"  - All DLLs and dependencies included")
        print(f"  - CSLOL tools included")
        
        print(f"\nProtection:")
        print(f"  - Python bytecode (not raw source)")
        print(f"  - Requires decompiler tools to reverse")
        print(f"  - Good enough against casual theft")
        
        print(f"\nTo test:")
        print(f"  cd dist\\Rose")
        print(f"  Rose.exe")
    else:
        print("[ERROR] Executable not found!")
        sys.exit(1)


if __name__ == "__main__":
    main()

