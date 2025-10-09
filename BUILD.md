# Building SkinCloner

This guide explains how to build SkinCloner with **GPU acceleration support** bundled in the executable.

## 🎯 Quick Build

The easiest way to build is using the automated build script:

```bash
python build_all.py
```

This will:

1. **✅ Automatically verify/install CUDA-enabled PyTorch** (required for GPU support)
2. **✅ Build the executable** with Nuitka (Python to C compilation)
3. **✅ Create the installer** with Inno Setup

## 🎮 GPU Support in Built Executables

### Important: Build-Time GPU Bundling

The built executable will **bundle whatever PyTorch version is installed on the build machine**.

- ✅ **Build with CUDA PyTorch** → Executable supports GPU on all machines with NVIDIA GPUs
- ❌ **Build with CPU PyTorch** → Executable is CPU-only for everyone

### Automatic CUDA PyTorch Installation

`build_all.py` automatically ensures CUDA-enabled PyTorch is installed before building:

```python
# Automatically runs this check:
python ensure_cuda_pytorch.py
```

This script will:

1. **Check** if PyTorch is installed and if it has CUDA support
2. **Install** CUDA-enabled PyTorch if needed (uninstalls CPU version first)
3. **Verify** the installation before proceeding with the build

### Manual PyTorch Installation (Optional)

If you want to manually install CUDA PyTorch before building:

```bash
pip uninstall torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

## 🔧 Build Scripts

### 1. `build_all.py` (Recommended)

Complete build pipeline:

- Ensures CUDA PyTorch is installed
- Builds executable with Nuitka
- Creates installer with Inno Setup

**Usage:**

```bash
python build_all.py
```

### 2. `build_nuitka.py` (Executable Only)

Builds just the executable (no installer):

- Checks for CUDA PyTorch (warns if CPU-only)
- Compiles with Nuitka

**Usage:**

```bash
python build_nuitka.py
```

### 3. `ensure_cuda_pytorch.py` (Utility)

Utility script to ensure CUDA PyTorch is installed:

- Checks current PyTorch installation
- Installs CUDA version if needed
- Verifies installation

**Usage:**

```bash
python ensure_cuda_pytorch.py
```

## 📦 Build Requirements

Install build dependencies:

```bash
pip install -r build_requirements.txt
```

For the complete build (including installer):

- **Nuitka** (Python to C compiler) - auto-installed
- **Inno Setup** - Download from [jrsoftware.org](https://jrsoftware.org/isdl.php)

## 🚀 Build Process Details

### Step 0: CUDA PyTorch Verification

```bash
[Step 0/3] Verifying CUDA-enabled PyTorch Installation
----------------------------------------------------------------------
[OK] CUDA-enabled PyTorch already installed: 2.x.x+cu121
[OK] Built for CUDA: 12.1
[OK] Ready to build with GPU support!
```

### Step 1: Nuitka Build

```bash
[Step 1/3] Building Executable with Nuitka (Python to C Compiler)
----------------------------------------------------------------------
- Compiles Python to native C code
- Bundles all dependencies (including CUDA PyTorch)
- Includes injection tools
- Output: dist/SkinCloner/SkinCloner.exe
```

### Step 2: Installer Creation

```bash
[Step 2/3] Creating Windows Installer with Inno Setup
----------------------------------------------------------------------
- Packages executable + dependencies
- Creates installer with UAC prompt
- Output: installer/SkinCloner_Setup.exe
```

## ✅ Verifying GPU Support in Built Executable

After building, you can verify GPU support is included:

1. **Run the executable** on a machine with an NVIDIA GPU
2. **Check the logs** - it should show:

   ```
   🚀 Initializing EasyOCR: en (tesseract lang: eng)
      🎮 GPU: NVIDIA GeForce RTX 2060 (CUDA 12.1)
   ✅ EasyOCR initialized successfully
   ```

3. **On machines without NVIDIA GPU** (or with AMD/Intel GPU):
   ```
   🚀 Initializing EasyOCR: en (tesseract lang: eng)
      🔍 Detected: AMD Radeon RX 6800
      ℹ️  GPU Type: AMD
      💡 Note: EasyOCR GPU acceleration only supports NVIDIA GPUs (CUDA)
      ✅ CPU mode works perfectly - GPU not required!
   ```

## 🔍 Troubleshooting

### Build Shows "CPU-only PyTorch"

If you see this warning during build:

```
[WARNING] CPU-only PyTorch detected!
The executable will NOT support GPU acceleration!
```

**Solution:**

```bash
# Run the automatic fix
python ensure_cuda_pytorch.py

# Or install manually
pip uninstall torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

### Built Executable Doesn't Support GPU

If your built executable shows "GPU requested but not available" on NVIDIA machines:

**Cause:** The build machine had CPU-only PyTorch when you built it.

**Solution:** Rebuild with CUDA PyTorch:

```bash
python ensure_cuda_pytorch.py
python build_all.py
```

### "No NVIDIA GPU" During Build (But Want GPU Support in Executable)

**This is OK!** The build machine doesn't need an NVIDIA GPU. As long as you have CUDA-enabled PyTorch **installed**, the executable will support GPU on machines that have NVIDIA GPUs.

You'll see this message:

```
[OK] CUDA-enabled PyTorch installed: 2.x.x+cu121
[INFO] CUDA not available on this machine (no NVIDIA GPU)
[OK] But the built executable will support CUDA on machines with NVIDIA GPUs!
Ready to build!
```

## 📊 Build Output

After a successful build:

```
[SUCCESS] BUILD COMPLETED SUCCESSFULLY!

Build Summary:
  Time elapsed: 15m 30s

Generated Files:
  [OK] Executable:  dist/SkinCloner/SkinCloner.exe
    Size: 650.0 MB
  [OK] Installer:   installer/SkinCloner_Setup_v1.0.0.exe
    Size: 680.0 MB

Next Steps:
  • For development/testing:
    Run: dist\SkinCloner\start.bat

  • For distribution:
    Share: installer/SkinCloner_Setup_v1.0.0.exe

  • For portable version:
    Zip: dist\SkinCloner\ folder
```

## 🌐 Distribution

### End User Experience

When users install your built executable:

1. **With NVIDIA GPU + CUDA drivers**: Automatic GPU acceleration (3-5x faster OCR)
2. **Without NVIDIA GPU**: Automatic CPU fallback (still works great)
3. **With AMD/Intel GPU**: Automatic CPU mode with clear explanation

**No manual PyTorch installation required by end users!** Everything is bundled in the executable.

## 📝 Notes

- **Executable size**: ~650-800 MB (PyTorch + dependencies)
- **First run**: Downloads EasyOCR models (~50-100 MB) - requires internet
- **Build time**: 10-20 minutes first build, 1-3 minutes subsequent builds (ccache)
- **Protection**: Python code compiled to native C (very difficult to reverse engineer)

---

**Summary:** Run `python build_all.py` and the system automatically ensures GPU support is included! 🚀
