#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ensure CUDA-enabled PyTorch is installed for building
This script checks if PyTorch has CUDA support and installs it if needed
"""

import subprocess
import sys


def check_pytorch_cuda():
    """Check if PyTorch has CUDA support"""
    try:
        import torch
        has_cuda = torch.cuda.is_available()
        version = torch.__version__
        
        # Check if it's a CPU-only build
        is_cpu_only = '+cpu' in version or not hasattr(torch.version, 'cuda') or torch.version.cuda is None
        
        return has_cuda, is_cpu_only, version
    except ImportError:
        return None, None, None


def install_cuda_pytorch():
    """Install CUDA-enabled PyTorch"""
    print("\n" + "=" * 70)
    print("  Installing CUDA-enabled PyTorch for build")
    print("=" * 70 + "\n")
    
    print("[1/2] Uninstalling existing PyTorch packages...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "-y", "torch", "torchvision"],
            check=False  # Don't fail if not installed
        )
        print("[OK] Uninstalled existing PyTorch\n")
    except Exception as e:
        print(f"[INFO] No existing PyTorch to uninstall: {e}\n")
    
    print("[2/2] Installing CUDA-enabled PyTorch (CUDA 12.1)...")
    print("Note: This may take a few minutes...")
    try:
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install",
                "torch", "torchvision",
                "--index-url", "https://download.pytorch.org/whl/cu121"
            ],
            check=True
        )
        print("\n[OK] CUDA-enabled PyTorch installed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Failed to install CUDA PyTorch: {e}")
        return False


def main():
    """Main entry point"""
    print("\n" + "=" * 70)
    print("  Checking PyTorch CUDA Support for Build")
    print("=" * 70 + "\n")
    
    has_cuda, is_cpu_only, version = check_pytorch_cuda()
    
    if version is None:
        print("[INFO] PyTorch not installed")
        print("[ACTION] Installing CUDA-enabled PyTorch...\n")
        if not install_cuda_pytorch():
            print("\n[ERROR] Failed to install CUDA PyTorch!")
            print("\nPlease install manually:")
            print("  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
            sys.exit(1)
    elif is_cpu_only:
        print(f"[WARNING] CPU-only PyTorch detected: {version}")
        print("[ACTION] Switching to CUDA-enabled PyTorch...\n")
        if not install_cuda_pytorch():
            print("\n[ERROR] Failed to install CUDA PyTorch!")
            print("\nPlease install manually:")
            print("  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
            sys.exit(1)
    elif has_cuda:
        print(f"[OK] CUDA-enabled PyTorch already installed: {version}")
        print(f"[OK] CUDA support available: Yes")
        print("\nNo action needed - ready to build with GPU support!")
    else:
        # Has CUDA PyTorch but CUDA not available on this machine
        print(f"[OK] CUDA-enabled PyTorch installed: {version}")
        print(f"[INFO] CUDA not available on this machine (no NVIDIA GPU)")
        print(f"[OK] But the built executable will support CUDA on machines with NVIDIA GPUs!")
        print("\nReady to build!")
    
    # Verify installation
    print("\n" + "-" * 70)
    print("Final verification:")
    print("-" * 70)
    
    has_cuda, is_cpu_only, version = check_pytorch_cuda()
    
    if is_cpu_only:
        print(f"[ERROR] Still have CPU-only PyTorch: {version}")
        print("\nSomething went wrong. Please install manually:")
        print("  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
        sys.exit(1)
    else:
        import torch
        print(f"[OK] PyTorch version: {version}")
        if hasattr(torch.version, 'cuda') and torch.version.cuda:
            print(f"[OK] Built for CUDA: {torch.version.cuda}")
        print(f"[OK] CUDA available on this machine: {torch.cuda.is_available()}")
        print("\n✅ Ready to build with GPU support!")
        print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()

