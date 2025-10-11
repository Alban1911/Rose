#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Complete build script for LeagueUnlocked
Builds executable with Nuitka and creates Windows installer in one step
"""

import sys
import subprocess
import time
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


def run_build_exe():
    """Run the build_nuitka.py script"""
    print_step(1, 3, "Building Executable with Nuitka (Python to C Compiler)")
    
    # Run build_nuitka.py as a subprocess
    result = subprocess.run(
        [sys.executable, "build_nuitka.py"],
        capture_output=False,  # Show output in real-time
        text=True
    )
    
    if result.returncode != 0:
        print("\n[ERROR] Executable build failed!")
        return False
    
    # Verify the executable was created
    exe_path = Path("dist/LeagueUnlocked/LeagueUnlocked.exe")
    if not exe_path.exists():
        print("\n[ERROR] Executable not found at expected location!")
        return False
    
    print("\n[OK] Executable build completed successfully!")
    return True


def run_create_installer():
    """Run the create_installer.py script"""
    print_step(2, 3, "Creating Windows Installer with Inno Setup")
    
    # Run create_installer.py as a subprocess
    result = subprocess.run(
        [sys.executable, "create_installer.py"],
        capture_output=False,  # Show output in real-time
        text=True
    )
    
    if result.returncode != 0:
        print("\n[ERROR] Installer creation failed!")
        return False
    
    # Verify the installer was created
    installer_dir = Path("installer")
    installer_files = list(installer_dir.glob("LeagueUnlocked_Setup*.exe"))
    if not installer_files:
        print("\n[ERROR] Installer not found at expected location!")
        return False
    
    print("\n[OK] Installer creation completed successfully!")
    return True


def ensure_cuda_pytorch():
    """Ensure CUDA-enabled PyTorch is installed"""
    print_step(0, 3, "Verifying CUDA-enabled PyTorch Installation")
    
    # Run ensure_cuda_pytorch.py as a subprocess
    result = subprocess.run(
        [sys.executable, "ensure_cuda_pytorch.py"],
        capture_output=False,  # Show output in real-time
        text=True
    )
    
    if result.returncode != 0:
        print("\n[ERROR] Failed to ensure CUDA PyTorch is installed!")
        print("\nThe build requires CUDA-enabled PyTorch to support GPU acceleration.")
        print("Please install it manually:")
        print("  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
        return False
    
    print("\n[OK] CUDA PyTorch verification completed!")
    return True


def build_all():
    """Complete build process: executable + installer"""
    
    print_header("LeagueUnlocked - Complete Build Process")
    
    start_time = time.time()
    
    # Step 0: Ensure CUDA PyTorch is installed
    if not ensure_cuda_pytorch():
        print_header("[FAILED] BUILD FAILED AT STEP 0/3")
        print("CUDA-enabled PyTorch is required for the build.")
        print("\nTroubleshooting:")
        print("1. Install CUDA PyTorch manually:")
        print("   pip uninstall torch torchvision")
        print("   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
        print("2. Run the build again")
        return False
    
    # Step 1: Build executable
    if not run_build_exe():
        print_header("[FAILED] BUILD FAILED AT STEP 1/3")
        print("The executable build failed. Please check the errors above.")
        print("\nTroubleshooting:")
        print("1. Make sure all dependencies are installed:")
        print("   pip install -r build_requirements.txt")
        print("2. Close any running instances of LeagueUnlocked.exe")
        print("3. Try removing build/dist directories manually")
        return False
    
    # Step 2: Create installer
    if not run_create_installer():
        print_header("[WARNING] BUILD PARTIALLY COMPLETED (2/3)")
        print("Executable was built successfully, but installer creation failed.")
        print("\nYou can still use the executable directly from:")
        print("  dist/LeagueUnlocked/LeagueUnlocked.exe")
        print("\nTo create the installer:")
        print("1. Install Inno Setup from: https://jrsoftware.org/isdl.php")
        print("2. Run: python create_installer.py")
        return False
    
    # Success!
    elapsed_time = time.time() - start_time
    minutes = int(elapsed_time // 60)
    seconds = int(elapsed_time % 60)
    
    print_header("[SUCCESS] BUILD COMPLETED SUCCESSFULLY!")
    
    # Get file information
    exe_path = Path("dist/LeagueUnlocked/LeagueUnlocked.exe")
    installer_files = list(Path("installer").glob("LeagueUnlocked_Setup*.exe"))
    installer_path = installer_files[0] if installer_files else None
    
    exe_size_mb = exe_path.stat().st_size / (1024 * 1024)
    
    print("Build Summary:")
    print(f"  Time elapsed: {minutes}m {seconds}s")
    print()
    print("Generated Files:")
    print(f"  [OK] Executable:  {exe_path}")
    print(f"    Size: {exe_size_mb:.1f} MB")
    
    if installer_path:
        installer_size_mb = installer_path.stat().st_size / (1024 * 1024)
        print(f"  [OK] Installer:   {installer_path}")
        print(f"    Size: {installer_size_mb:.1f} MB")
    
    print("\nNext Steps:")
    print("  • For development/testing:")
    print("    Run: dist\\LeagueUnlocked\\start.bat")
    print()
    print("  • For distribution:")
    print(f"    Share: {installer_path if installer_path else 'installer/LeagueUnlocked_Setup.exe'}")
    print()
    print("  • For portable version:")
    print("    Zip: dist\\LeagueUnlocked\\ folder")
    
    print("\n" + "=" * 70)
    
    return True


def main():
    """Main entry point"""
    
    # Check if we're in the right directory
    if not Path("main.py").exists():
        print("ERROR: main.py not found!")
        print("Please run this script from the LeagueUnlocked root directory.")
        sys.exit(1)
    
    # Check if build_nuitka.py exists
    if not Path("build_nuitka.py").exists():
        print("ERROR: build_nuitka.py not found!")
        sys.exit(1)
    
    # Check if create_installer.py exists
    if not Path("create_installer.py").exists():
        print("ERROR: create_installer.py not found!")
        sys.exit(1)
    
    # Run the complete build
    success = build_all()
    
    if not success:
        sys.exit(1)
    


if __name__ == "__main__":
    main()

