# 🔨 Building SkinCloner

This guide explains how to build SkinCloner into a distributable executable.

## 🎯 Build System: Nuitka

SkinCloner uses **Nuitka** - a Python to C compiler that creates native machine code executables.

### Why Nuitka?

✅ **Native Compilation**: Python → C → Machine code  
✅ **Best Protection**: Very difficult to reverse engineer  
✅ **Best Performance**: No Python interpreter overhead  
✅ **Fast Rebuilds**: ccache only recompiles changed files  
✅ **Professional**: Commercial-grade compilation

---

## 📦 Prerequisites

1. **Install Nuitka:**

   ```bash
   pip install -r build_requirements.txt
   ```

2. **C Compiler (Auto-installed):**
   - Nuitka will automatically download GCC on first build
   - Takes ~5-15 minutes on first build only
   - Cached in: `C:\Users\<YOU>\AppData\Local\Nuitka\`

---

## 🚀 Building the Executable

### Option 1: Quick Build (Executable Only)

```bash
python build_nuitka.py
```

**Output:**

- `dist/SkinCloner/SkinCloner.exe` - Standalone executable
- `dist/SkinCloner/start.bat` - Launcher with verbose logging

**Build Times:**

- First build: 5-15 minutes (compiles all C files)
- Subsequent builds: **1-3 minutes** (ccache magic! ⚡)
- No code changes: **< 1 minute** (just repackaging)

---

### Option 2: Full Build (Executable + Installer)

```bash
python build_all.py
```

**What it does:**

1. Runs `build_nuitka.py` (creates executable)
2. Runs `create_installer.py` (creates Windows installer)

**Output:**

- `dist/SkinCloner/SkinCloner.exe` - Standalone executable
- `installer/SkinCloner_Setup_vX.X.exe` - Windows installer

**Requirements:**

- [Inno Setup](https://jrsoftware.org/isdl.php) must be installed
- Build times same as Option 1, plus ~30 seconds for installer

---

## ⚡ Speed Improvements

We've **removed the `--disable-ccache` flag**, which means:

| Build Type   | Before   | After           |
| ------------ | -------- | --------------- |
| First build  | 5-15 min | 5-15 min (same) |
| Code changes | 5-15 min | **1-3 min** ⚡  |
| No changes   | 5-15 min | **< 1 min** 🚀  |

**Why?** Ccache (compiler cache) only recompiles changed files instead of all 537 C files every time!

---

## 📁 Build Output

```
dist/
└── SkinCloner/
    ├── SkinCloner.exe          # Main executable
    ├── start.bat               # Launcher with logging
    └── [bundled dependencies]  # All required files

installer/
└── SkinCloner_Setup_vX.X.exe  # Windows installer (after build_all.py)
```

---

## 🧹 Cleaning Build Artifacts

Build directories are automatically cleaned on each build:

- `dist/` - Output directory
- `main.build/` - Nuitka build cache
- `main.dist/` - Nuitka distribution folder

The **Nuitka compiler cache** is preserved for fast rebuilds:

- Location: `%LOCALAPPDATA%\Nuitka\`
- Contains: Downloaded GCC compiler + compiled objects
- **Do NOT delete** unless you want to re-download everything!

---

## 🐛 Troubleshooting

### Build is slow (5-15 min every time)

**Problem:** ccache might not be working  
**Solution:** Make sure you're using the updated `build_nuitka.py` without `--disable-ccache`

### "Permission denied" errors

**Problem:** Previous build is still running  
**Solution:**

1. Close SkinCloner.exe if running
2. Check Task Manager for lingering processes
3. Restart and try again

### GCC compiler download fails

**Problem:** Network issue during first build  
**Solution:**

1. Check internet connection
2. Disable antivirus temporarily
3. Run as Administrator

### "Module not found" errors

**Problem:** Missing dependencies  
**Solution:**

```bash
pip install -r requirements.txt
pip install -r build_requirements.txt
```

---

## 📊 What Changed?

### ❌ Removed (PyInstaller-based builds)

- `build_exe.py` - PyInstaller build script
- `build_cython.py` - Cython + PyInstaller
- `build_obfuscated.py` - PyArmor + PyInstaller
- `build_all_obfuscated.py` - PyArmor full build
- `pyarmor_config.py` - PyArmor configuration
- `license_validator.py` - PyArmor license system
- `license_manager.py` - License management
- All PyArmor/PyInstaller documentation

### ✅ Updated (Nuitka builds only)

- `build_nuitka.py` - **Removed `--disable-ccache`**, added `--show-progress`
- `build_all.py` - Now calls `build_nuitka.py` instead of `build_exe.py`
- `build_requirements.txt` - Removed PyInstaller/PyArmor, kept Nuitka
- `.gitignore` - Updated for Nuitka-specific files
- `README.md` - Updated project structure

---

## 🎓 For Developers

### Testing Builds

```bash
# Quick test after code changes
python build_nuitka.py
cd dist/SkinCloner
start.bat

# Full release build
python build_all.py
```

### Build Options

Edit `build_nuitka.py` to customize:

- `--low-memory` - Reduce memory usage (slower)
- `--show-progress` - Show compilation progress
- `--follow-imports` - Include all dependencies
- `--onefile` - Single executable (current default)

### Distribution

**For Users:**

- Share `installer/SkinCloner_Setup.exe` (recommended)
- Or zip the `dist/SkinCloner/` folder (portable)

**Requirements:**

- Windows 10/11
- Tesseract OCR installed
- League of Legends installed

---

**Happy Building!** 🚀
