#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU Setup Verification Script for LeagueUnlocked
Tests PyTorch CUDA and EasyOCR GPU support
"""

import sys

def print_section(title):
    """Print section header"""
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)

def test_pytorch_cuda():
    """Test PyTorch CUDA availability"""
    print_section("PYTORCH CUDA TEST")
    
    try:
        import torch
        print(f"✓ PyTorch installed: {torch.__version__}")
        
        cuda_available = torch.cuda.is_available()
        print(f"  CUDA available: {'✓ YES' if cuda_available else '✗ NO'}")
        
        if cuda_available:
            print(f"  CUDA version: {torch.version.cuda}")
            print(f"  cuDNN version: {torch.backends.cudnn.version()}")
            print(f"  cuDNN enabled: {torch.backends.cudnn.enabled}")
            
            # GPU details
            gpu_count = torch.cuda.device_count()
            print(f"\n  GPU Count: {gpu_count}")
            
            for i in range(gpu_count):
                props = torch.cuda.get_device_properties(i)
                print(f"\n  GPU {i}: {torch.cuda.get_device_name(i)}")
                print(f"    Compute Capability: {props.major}.{props.minor}")
                print(f"    Total Memory: {props.total_memory / 1024**3:.2f} GB")
                print(f"    Multi-Processors: {props.multi_processor_count}")
            
            # Test GPU tensor operation
            try:
                x = torch.randn(100, 100).cuda()
                y = torch.randn(100, 100).cuda()
                z = torch.matmul(x, y)
                print(f"\n  ✓ GPU tensor operations: WORKING")
            except Exception as e:
                print(f"\n  ✗ GPU tensor operations: FAILED - {e}")
                return False
            
            return True
        else:
            print("\n  ℹ️  PyTorch is installed but CUDA is not available")
            print("  This could be because:")
            print("    1. No NVIDIA GPU detected")
            print("    2. NVIDIA drivers not installed")
            print("    3. CUDA Toolkit not installed")
            print("    4. PyTorch CPU-only version installed")
            print("\n  Install GPU version with:")
            print("    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
            return False
            
    except ImportError:
        print("✗ PyTorch not installed")
        print("\n  Install with:")
        print("    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
        return False
    except Exception as e:
        print(f"✗ PyTorch test failed: {e}")
        return False

def test_easyocr_gpu():
    """Test EasyOCR GPU support"""
    print_section("EASYOCR GPU TEST")
    
    try:
        import easyocr
        print(f"✓ EasyOCR installed: {easyocr.__version__}")
        
        # Check if GPU is available first
        import torch
        if not torch.cuda.is_available():
            print("  ℹ️  Skipping GPU test (CUDA not available)")
            print("  EasyOCR will use CPU mode")
            return False
        
        # Test GPU initialization
        print("\n  Testing EasyOCR GPU initialization...")
        try:
            reader = easyocr.Reader(['en'], gpu=True, verbose=False)
            print("  ✓ EasyOCR GPU initialization: SUCCESS")
            
            # Test a simple recognition (optional)
            import numpy as np
            test_image = np.ones((100, 300, 3), dtype=np.uint8) * 255
            try:
                results = reader.readtext(test_image, detail=0)
                print("  ✓ EasyOCR GPU recognition: WORKING")
            except Exception as e:
                print(f"  ⚠️  EasyOCR recognition test: {e}")
            
            return True
            
        except Exception as e:
            print(f"  ✗ EasyOCR GPU initialization: FAILED")
            print(f"     Error: {e}")
            print("\n  EasyOCR will fall back to CPU mode")
            return False
            
    except ImportError:
        print("✗ EasyOCR not installed")
        print("\n  Install with:")
        print("    pip install easyocr")
        return False
    except Exception as e:
        print(f"✗ EasyOCR test failed: {e}")
        return False

def test_dependencies():
    """Test other required dependencies"""
    print_section("DEPENDENCIES TEST")
    
    dependencies = [
        'numpy',
        'scipy',
        'cv2',
        'PIL',
    ]
    
    all_ok = True
    for dep in dependencies:
        try:
            if dep == 'cv2':
                import cv2
                print(f"✓ opencv-python: {cv2.__version__}")
            elif dep == 'PIL':
                from PIL import Image
                print(f"✓ Pillow: {Image.__version__}")
            else:
                module = __import__(dep)
                version = getattr(module, '__version__', 'unknown')
                print(f"✓ {dep}: {version}")
        except ImportError:
            print(f"✗ {dep}: NOT INSTALLED")
            all_ok = False
    
    return all_ok

def print_summary(pytorch_ok, easyocr_ok, deps_ok):
    """Print final summary"""
    print_section("SUMMARY")
    
    print("\nComponent Status:")
    print(f"  PyTorch CUDA: {'✓ READY' if pytorch_ok else '✗ NOT AVAILABLE'}")
    print(f"  EasyOCR GPU:  {'✓ READY' if easyocr_ok else '✗ NOT AVAILABLE'}")
    print(f"  Dependencies: {'✓ OK' if deps_ok else '✗ MISSING'}")
    
    if pytorch_ok and easyocr_ok and deps_ok:
        print("\n" + "🎉" * 35)
        print("  GPU ACCELERATION IS READY!")
        print("  LeagueUnlocked will use GPU for faster OCR")
        print("🎉" * 35)
    elif not pytorch_ok:
        print("\n" + "⚠️" * 35)
        print("  GPU NOT AVAILABLE - CPU MODE ONLY")
        print("  ")
        print("  To enable GPU acceleration:")
        print("  1. Install NVIDIA CUDA Toolkit 11.8+")
        print("  2. Install cuDNN 8.x")
        print("  3. Reinstall PyTorch with GPU support:")
        print("     pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
        print("  ")
        print("  See GPU_INSTALLATION_GUIDE.md for detailed instructions")
        print("⚠️" * 35)
    elif not easyocr_ok:
        print("\n" + "⚠️" * 35)
        print("  EASYOCR GPU INITIALIZATION FAILED")
        print("  ")
        print("  EasyOCR will fall back to CPU mode")
        print("  This may be due to:")
        print("  - CUDA/cuDNN version mismatch")
        print("  - Insufficient GPU memory")
        print("  - GPU driver issues")
        print("  ")
        print("  Check error messages above for details")
        print("⚠️" * 35)
    else:
        print("\n" + "⚠️" * 35)
        print("  MISSING DEPENDENCIES")
        print("  ")
        print("  Install all dependencies:")
        print("  pip install -r requirements.txt")
        print("⚠️" * 35)
    
    print("\n")

def main():
    """Main test function"""
    print("\n" + "=" * 70)
    print(" LeagueUnlocked - GPU Setup Verification")
    print(" Testing PyTorch CUDA and EasyOCR GPU support")
    print("=" * 70)
    
    # Run tests
    pytorch_ok = test_pytorch_cuda()
    easyocr_ok = test_easyocr_gpu() if pytorch_ok else False
    deps_ok = test_dependencies()
    
    # Print summary
    print_summary(pytorch_ok, easyocr_ok, deps_ok)
    
    # Exit code
    sys.exit(0 if (pytorch_ok and easyocr_ok and deps_ok) else 1)

if __name__ == "__main__":
    main()

