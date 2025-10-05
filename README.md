# SkinCloner - Fully Automated System

A complete League of Legends skin changer that automatically detects skins using OCR and injects them 2 seconds before the game starts. 

## Two Ways to Use This Project

### 🚀 **Option 1: Download Installer (Recommended for Most Users)**
For users who want a simple, ready-to-use application:
- **⚠️ MANDATORY**: Install Tesseract OCR first from [https://github.com/UB-Mannheim/tesseract/releases](https://github.com/UB-Mannheim/tesseract/releases)
- **Download the latest installer** from our releases
- **Run the installer** and follow the setup wizard
- **Launch the app** from your desktop or start menu
- **No technical knowledge required!**

**[📥 Download Latest Installer](https://github.com/AlbanCliquet/SkinCloner/releases/latest)**

### 💻 **Option 2: Run from Source Code (For Developers/Advanced Users)**
For developers or users who want to modify the code:
- **⚠️ MANDATORY**: Install Tesseract OCR first from [https://github.com/UB-Mannheim/tesseract/releases](https://github.com/UB-Mannheim/tesseract/releases)
- **Clone this repository**
- **Install Python dependencies**
- **Run `main.py`** directly
- **Full control over the codebase**

---

## 🚀 Quick Start (Installer Version)

1. **⚠️ MANDATORY**: Install Tesseract OCR first from [https://github.com/UB-Mannheim/tesseract/releases](https://github.com/UB-Mannheim/tesseract/releases)
   - Download the latest Windows installer (e.g., `tesseract-ocr-w64-setup-5.x.x.exe`)
   - Run as Administrator and install with default settings
   - **This is required** - the app cannot function without Tesseract OCR
2. **Download** the latest SkinCloner installer from the releases page
3. **Run** `SkinCloner_Setup.exe` as Administrator
4. **Launch** League of Legends and start a game
5. **Hover over skins** in champion select for 2+ seconds
6. **Enjoy** your custom skins automatically injected!

**That's it!** The system handles everything automatically - no manual intervention required!

## Project Structure

```
SkinCloner/
├── main.py                     # Single automated launcher - RUN THIS!
├── requirements.txt            # Python dependencies
├── README.md                  # This file
├── injection/                 # Complete injection system
│   ├── __init__.py
│   ├── injector.py            # CSLOL injection logic
│   ├── manager.py             # Injection management
│   ├── mods_map.json          # Mod configuration
│   ├── tools/                 # CSLOL tools
│   │   ├── mod-tools.exe      # Main modification tool
│   │   ├── cslol-diag.exe     # Diagnostics tool
│   │   ├── cslol-dll.dll      # Core DLL
│   │   └── [other tools]      # WAD utilities
│   ├── mods/                  # Extracted skin mods (created at runtime)
│   └── overlay/               # Temporary overlay files (created at runtime)
├── skins/                     # Skin collection (downloaded to user data directory at runtime)
│   ├── Aatrox/
│   ├── Ahri/
│   └── [171 champions]/
├── utils/                     # Utility functions
│   ├── __init__.py
│   ├── normalization.py       # Text normalization utilities
│   ├── logging.py             # Logging configuration
│   ├── window_capture.py      # Windows window capture utilities
│   ├── skin_downloader.py     # Skin download system
│   ├── smart_skin_downloader.py # Smart downloader with rate limiting
│   └── repo_downloader.py     # Repository ZIP downloader
├── ocr/                       # OCR functionality
│   ├── __init__.py
│   ├── backend.py             # OCR backend implementation
│   └── image_processing.py    # Image processing for OCR
├── database/                  # Champion/skin database
│   ├── __init__.py
│   ├── name_db.py             # Champion and skin name database
│   └── multilang_db.py        # Multi-language database with auto-detection
├── lcu/                       # League Client API
│   ├── __init__.py
│   ├── client.py              # LCU API client
│   └── utils.py               # LCU utility functions
├── state/                     # Shared state (stored in user data directory at runtime)
│   ├── __init__.py
│   ├── shared_state.py        # Shared state between threads
│   └── last_hovered_skin.txt  # Last hovered skin file (user data directory)
├── threads/                   # Threading components
│   ├── __init__.py
│   ├── phase_thread.py        # Game phase monitoring
│   ├── champ_thread.py        # Champion hover/lock monitoring
│   ├── ocr_thread.py          # OCR skin detection
│   ├── websocket_thread.py    # WebSocket event handling
│   └── loadout_ticker.py      # Loadout countdown timer
├── dependencies/              # Local dependencies
│   └── tesserocr-2.8.0-cp311-cp311-win_amd64.whl
└── [build files]              # Build system components
    ├── build_exe.py           # PyInstaller build script
    └── build_requirements.txt # Build dependencies
```

## Features

- **🚀 Two Usage Options**: Simple installer for users, source code for developers
- **Fully Automated**: Works automatically - no manual intervention required!
- **Multi-Language Support**: Works with League of Legends client languages that use Latin alphabets
- **Smart Detection**: OCR automatically detects skin names during champion select
- **Instant Injection**: Skins are injected 2 seconds before game starts
- **Massive Collection**: 8,277+ skins for 171 champions included
- **Smart Downloads**: Efficient repository ZIP download with automatic updates
- **Fuzzy Matching**: Smart matching system for accurate skin detection
- **LCU Integration**: Real-time communication with League Client
- **CSLOL Tools**: Reliable injection using CSLOL modification tools
- **Modular Architecture**: Clean, maintainable codebase
- **Multi-threaded**: Optimal performance with concurrent processing
- **Optimized Loading**: Only loads necessary language databases for better performance
- **Permission-Safe**: Uses user data directories to avoid permission issues when installed

## 💻 Installation (Source Code Version)

**For developers and advanced users who want to run from source:**

1. **⚠️ MANDATORY**: Install Tesseract OCR first from [https://github.com/UB-Mannheim/tesseract/releases](https://github.com/UB-Mannheim/tesseract/releases)
2. **Install Python 3.11**
3. **Clone this repository**:
   ```bash
   git clone https://github.com/AlbanCliquet/SkinCloner.git
   cd SkinCloner
   ```
4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   This will automatically install the local tesserocr wheel from the `dependencies/` folder.
5. **Verify installation** (optional but recommended):
   ```bash
   python utils/check_tesseract.py
   ```
6. **Run the system**:
   ```bash
   # That's it! Just run this:
   python main.py
   
   # Optional: Enable verbose logging
   python main.py --verbose
   
   # Optional: Enable WebSocket mode for better performance
   python main.py --ws
   
   # Optional: Specify language (auto-detection by default)
   python main.py                     # Auto-detect (default)
   python main.py --language es_ES    # Spanish
   python main.py --language fr_FR    # French   
   
   # Optional: Disable multi-language support
   python main.py --no-multilang
   
   # Optional: Control automatic skin downloading
   python main.py --no-download-skins        # Disable automatic skin downloads
   python main.py --force-update-skins       # Force update all skins
   python main.py --max-champions 10         # Limit to first 10 champions (for testing)
   ```

## Usage

### How It Works 
1. **Launch League of Legends** and start a game
2. **Enter Champion Select** - the system detects this automatically
3. **Hover over skins** - the system detects the skin name
4. **The system automatically injects** the skin 2 seconds before the game starts
5. **Enjoy your custom skin** in the game!

**Important**: The hovered skin will only be injected if the last owned skin hovered was the base one. Base skins are automatically skipped.

### Fully Automated Mode (Default)
The system will:
- Connect to League Client automatically
- Monitor game phases (lobby, champion select, in-game)
- Activate OCR when you enter champion select
- Detect skin names as you hover over them
- Inject the last hovered skin 2 seconds before the game starts
- Work completely automatically - no manual intervention!

### System Status
The system provides real-time status updates:
- **CHAMPION SELECT DETECTED** - OCR is active
- **GAME STARTING** - Last injected skin displayed
- **Detailed logs** with `--verbose` flag

## Command Line Arguments

### Core Options
- `--verbose`: Enable verbose logging
- `--ws`: Enable WebSocket mode for real-time events
- `--tessdata`: Specify Tesseract tessdata directory
- `--game-dir`: Specify League of Legends Game directory

### Skin Download Options
- `--download-skins`: Enable automatic skin downloading (default)
- `--no-download-skins`: Disable automatic skin downloading
- `--force-update-skins`: Force update all skins (re-download existing ones)
- `--max-champions <num>`: Limit number of champions to download skins for (for testing)

### Multi-Language Options
- `--multilang`: Enable multi-language support (default)
- `--no-multilang`: Disable multi-language support
- `--language <lang>`: Specify language
  - `auto`: Auto-detect language from LCU API (default)
  - `en_US`: English (United States)
  - `es_ES`: Spanish (Spain)
  - `fr_FR`: French
  - `de_DE`: German
  - `pt_BR`: Portuguese (Brazil)
  - `it_IT`: Italian
  - `tr_TR`: Turkish
  - `pl_PL`: Polish
  - `hu_HU`: Hungarian
  - `ro_RO`: Romanian
  - `el_GR`: Greek
  - `es_MX`: Spanish (Mexico)

### OCR Language Options
- `--lang <ocr_lang>`: Specify OCR language for text recognition
  - `auto`: Auto-detect OCR language based on LCU language (default)
  - `eng`: English
  - `fra+eng`: French + English
  - `spa+eng`: Spanish + English
  - `deu+eng`: German + English
  - `ell+eng`: Greek + English
  - `pol+eng`: Polish + English
  - `tur+eng`: Turkish + English
  - `hun+eng`: Hungarian + English
  - `ron+eng`: Romanian + English
  - `por+eng`: Portuguese + English
  - `ita+eng`: Italian + English

### Supported Languages
The system supports Latin alphabet languages with automatic detection and optimized loading:
- **Auto-Detection**: Automatically detects language from LCU API and OCR text
- **Manual Selection**: Force specific language for better performance
- **Optimized Loading**: Only loads necessary language databases
- **English Mapping**: All results logged in English for consistency

## Dependencies

- numpy: Numerical operations
- opencv-python: Computer vision
- psutil: Process utilities
- requests: HTTP requests
- rapidfuzz: String matching
- tesserocr: OCR functionality
- websocket-client: WebSocket support
- mss: Screen capture
- Pillow: Image processing

## 📚 Tesseract OCR Installation Guide

**🎯 Important**: The application automatically detects Tesseract OCR installations and configures all necessary paths. You only need to install Tesseract - no manual configuration required!

### Windows Installation

1. **Download Tesseract for Windows**:
   - Go to: https://github.com/UB-Mannheim/tesseract/wiki
   - Download the latest Windows installer (e.g., `tesseract-ocr-w64-setup-5.x.x.exe`)

2. **Install Tesseract**:
   - Run the installer as Administrator
   - **IMPORTANT**: During installation, select "Additional language data" to install language packs
   - Choose the default installation path: `C:\Program Files\Tesseract-OCR\`

3. **Optional: Add to System PATH** (Recommended but not required):
   - The application will automatically detect Tesseract even without PATH configuration
   - For faster detection, you can add: `C:\Program Files\Tesseract-OCR` to your system PATH
   - Open System Properties → Advanced → Environment Variables
   - Edit the "Path" variable and add: `C:\Program Files\Tesseract-OCR`
   - Or use PowerShell (as Administrator):
     ```powershell
     $env:PATH += ";C:\Program Files\Tesseract-OCR"
     [Environment]::SetEnvironmentVariable("PATH", $env:PATH, [EnvironmentVariableTarget]::Machine)
     ```

4. **Optional: Set TESSDATA_PREFIX Environment Variable** (Not required):
   - The application automatically configures this variable when it detects Tesseract
   - You can optionally set it manually: `TESSDATA_PREFIX=C:\Program Files\Tesseract-OCR\tessdata`
   - Or use PowerShell (as Administrator):
     ```powershell
     [Environment]::SetEnvironmentVariable("TESSDATA_PREFIX", "C:\Program Files\Tesseract-OCR\tessdata", [EnvironmentVariableTarget]::Machine)
     ```

5. **Verify Installation** (Optional but recommended):
   ```bash
   # Check if Tesseract is accessible
   tesseract --version
   
   # Check available languages
   tesseract --list-langs
   
   # Run our diagnostic tool
   python check_tesseract.py
   ```


### Common Language Codes

| Language | Code | Language | Code |
|----------|------|----------|------|
| English  | eng  | Spanish  | spa  |
| French   | fra  | German   | deu  |
| Italian  | ita  | Portuguese | por |
| Polish   | pol  | Greek    | ell  |
| Turkish  | tur  | Hungarian | hun |
| Romanian | ron  |          |      |

### Troubleshooting Tesseract Issues

If you encounter Tesseract-related errors:

1. **Run the diagnostic tool**:
   ```bash
   python utils/check_tesseract.py
   ```

2. **Common error messages and solutions**:

   - **"Tesseract executable not found"**:
     - Ensure Tesseract is installed and added to PATH
     - Restart your command prompt/IDE after installation

   - **"Tessdata directory not found"**:
     - The application should automatically detect this - try running the diagnostic tool
     - If manual configuration is needed, set TESSDATA_PREFIX environment variable
     - Ensure tessdata folder contains `.traineddata` files

   - **"Language not found"**:
     - Install additional language packs
     - Use `tesseract --list-langs` to see available languages

   - **"tesserocr import error"**:
     - Reinstall tesserocr: `pip install -r requirements.txt`
     - Ensure you're using the correct Python version (3.11+)

3. **Manual path specification** (Last resort):
   If automatic detection fails, you can specify paths manually:
   ```bash
   python main.py --tessdata "C:\Program Files\Tesseract-OCR\tessdata" --tesseract-exe "C:\Program Files\Tesseract-OCR\tesseract.exe"
   ```
   
   **Note**: This should rarely be necessary as the application automatically detects Tesseract installations.

## Troubleshooting

### Common Issues
- **No injection**: Check that CSLOL tools are present in `injection/tools/` directory
- **Wrong skin**: Verify skin names match the collection in `skins/`
- **Missing CSLOL tools**: Download from https://github.com/CommunityDragon/CDTB and place in `injection/tools/`
- **No match**: Check OCR detection accuracy with `--verbose` flag
- **Game not detected**: Ensure League of Legends is installed in default location
- **Language issues**: Use `--language auto` for automatic detection or specify your client's language
- **Performance issues**: Use manual language selection (`--language <lang>`) for better performance
- **OCR language not found**: Ensure Tesseract OCR has the required language packs installed
- **Tesseract OCR errors**: Run `python utils/check_tesseract.py` to diagnose installation issues
- **Permission errors**: The installer version automatically uses user data directories to avoid permission issues

### System Requirements

**For Installer Version:**
- Windows 10/11
- League of Legends installed
- **⚠️ MANDATORY**: Tesseract OCR installed from [https://github.com/UB-Mannheim/tesseract/releases](https://github.com/UB-Mannheim/tesseract/releases)

**For Source Code Version:**
- Windows 10/11
- Python 3.11+
- **⚠️ MANDATORY**: Tesseract OCR installed from [https://github.com/UB-Mannheim/tesseract/releases](https://github.com/UB-Mannheim/tesseract/releases)
- League of Legends installed
- CSLOL tools present in `injection/tools/` directory

## 🔧 Building from Source (For Developers)

To create a standalone executable for distribution:

1. **Install build dependencies**
   ```bash
   pip install -r build_requirements.txt
   ```

2. **Build the executable**
   ```bash
   python build_exe.py
   ```

3. **Find the executable**
   - The executable will be created in the `dist/` folder
   - Run `start.bat` or `SkinCloner.exe` directly

The build process creates a single executable file that includes:
- All Python dependencies
- Application code and resources
- No Python installation required on target systems

**Note**: Users still need to have:
- League of Legends installed and running
- **⚠️ MANDATORY**: Tesseract OCR installed from [https://github.com/UB-Mannheim/tesseract/releases](https://github.com/UB-Mannheim/tesseract/releases)

## 📦 Creating Windows Installer (For Developers)

To create a proper Windows installer that registers the app in Windows Apps list:

1. **Install Inno Setup**
   - Download from: https://jrsoftware.org/isdl.php
   - Install with default settings

2. **Create the installer**
   ```bash
   python create_installer.py
   ```

3. **Find the installer**
   - The installer will be created in the `installer/` folder
   - Upload to GitHub releases for distribution

The installer provides:
- Windows Apps list integration
- Start Menu shortcuts
- Desktop shortcut (optional)
- Proper uninstaller
- Registry entries for Windows recognition