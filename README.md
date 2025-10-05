# LoL Skin Changer - Fully Automated System

A complete League of Legends skin changer that automatically detects skins using OCR and injects them 2 seconds before the game starts. 

## Two Ways to Use This Project

### 🚀 **Option 1: Download Installer (Recommended for Most Users)**
For users who want a simple, ready-to-use application:
- **Download the latest installer** from our releases
- **Run the installer** and follow the setup wizard
- **Launch the app** from your desktop or start menu
- **No technical knowledge required!**

**[📥 Download Latest Installer](https://github.com/AlbanCliquet/LoLSkinChanger/releases/latest)**

### 💻 **Option 2: Run from Source Code (For Developers/Advanced Users)**
For developers or users who want to modify the code:
- **Clone this repository**
- **Install Python dependencies**
- **Run `main.py`** directly
- **Full control over the codebase**

---

## 🚀 Quick Start (Installer Version)

1. **Download** the latest installer from the releases page
2. **Run** `LoLSkinChanger_Setup.exe` as Administrator
3. **Launch** League of Legends and start a game
4. **Hover over skins** in champion select for 2+ seconds
5. **Enjoy** your custom skins automatically injected!

**That's it!** The system handles everything automatically - no manual intervention required!

## Project Structure

```
LoLSkinChanger/
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
- **Multi-Language Support**: Works with any League of Legends client language (17 languages supported)
- **⚠️ Limitation**: Languages with non-Latin alphabets (Chinese, Japanese, Korean, Arabic, etc.) are currently not supported due to OCR limitations
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

1. **Install Python 3.11 or higher**
2. **Clone this repository**:
   ```bash
   git clone https://github.com/AlbanCliquet/LoLSkinChanger.git
   cd LoLSkinChanger
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   This will automatically install the local tesserocr wheel from the `dependencies/` folder.
4. **Install Tesseract OCR** on your system
5. **Run the system**:
   ```bash
   # That's it! Just run this:
   python main.py
   
   # Optional: Enable verbose logging
   python main.py --verbose
   
   # Optional: Enable WebSocket mode for better performance
   python main.py --ws
   
   # Optional: Specify language (auto-detection by default)
   python main.py --language es_ES    # Spanish
   python main.py --language fr_FR    # French
   python main.py --language zh_CN    # Chinese Simplified
   python main.py --language auto     # Auto-detect (default)
   
   # Optional: Specify OCR language for non-Latin alphabets
   python main.py --lang kor          # Korean OCR
   python main.py --lang chi_sim      # Chinese Simplified OCR
   python main.py --lang ell          # Greek OCR
   python main.py --lang auto         # Auto-detect OCR language (default)
   
   # Optional: Disable multi-language support
   python main.py --no-multilang
   
   # Optional: Control automatic skin downloading
   python main.py --no-download-skins        # Disable automatic skin downloads
   python main.py --force-update-skins       # Force update all skins
   python main.py --max-champions 10         # Limit to first 10 champions (for testing)
   ```

## Usage

### How It Works (Both Versions)
1. **Launch League of Legends** and start a game
2. **Enter Champion Select** - the system detects this automatically
3. **Hover over skins** for 2+ seconds - the system detects the skin name
4. **The system automatically injects** the skin before the game starts
5. **Enjoy your custom skin** in the game!

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
- `--language <lang>`: Specify language or auto-detection
  - `auto`: Auto-detect language from LCU API (default)
  - `en_US`: English (United States)
  - `es_ES`: Spanish (Spain)
  - `fr_FR`: French
  - `de_DE`: German
  - `zh_CN`: Chinese (Simplified)
  - `ja_JP`: Japanese
  - `ko_KR`: Korean
  - `ru_RU`: Russian
  - `pt_BR`: Portuguese (Brazil)
  - `it_IT`: Italian
  - `tr_TR`: Turkish
  - `pl_PL`: Polish
  - `hu_HU`: Hungarian
  - `ro_RO`: Romanian
  - `el_GR`: Greek
  - `zh_TW`: Chinese (Traditional)
  - `es_MX`: Spanish (Mexico)

### OCR Language Options
- `--lang <ocr_lang>`: Specify OCR language for text recognition
  - `auto`: Auto-detect OCR language based on LCU language (default)
  - `eng`: English
  - `fra+eng`: French + English
  - `spa+eng`: Spanish + English
  - `deu+eng`: German + English
  - `kor+eng`: Korean + English
  - `chi_sim+eng`: Chinese Simplified + English
  - `chi_tra+eng`: Chinese Traditional + English
  - `jpn+eng`: Japanese + English
  - `ell+eng`: Greek + English
  - `rus+eng`: Russian + English
  - `pol+eng`: Polish + English
  - `tur+eng`: Turkish + English
  - `hun+eng`: Hungarian + English
  - `ron+eng`: Romanian + English
  - `por+eng`: Portuguese + English
  - `ita+eng`: Italian + English

### Supported Languages
The system supports 17 languages with automatic detection and optimized loading:
- **Auto-Detection**: Automatically detects language from LCU API and OCR text
- **Manual Selection**: Force specific language for better performance
- **Optimized Loading**: Only loads necessary language databases
- **OCR Language Mapping**: Automatically selects appropriate OCR language for non-Latin alphabets
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

## Troubleshooting

### Common Issues
- **No injection**: Check that CSLOL tools are present in `injection/tools/` directory
- **Wrong skin**: Verify skin names match the collection in `skins/`
- **Missing CSLOL tools**: Download from https://github.com/CommunityDragon/CDTB and place in `injection/tools/`
- **No match**: Check OCR detection accuracy with `--verbose` flag
- **Game not detected**: Ensure League of Legends is installed in default location
- **Language issues**: Use `--language auto` for automatic detection or specify your client's language
- **Performance issues**: Use manual language selection (`--language <lang>`) for better performance
- **Non-Latin alphabet issues**: Languages with non-Latin alphabets (Chinese, Japanese, Korean, Arabic, etc.) are currently not supported due to OCR limitations
- **OCR language not found**: Ensure Tesseract OCR has the required language packs installed
- **Permission errors**: The installer version automatically uses user data directories to avoid permission issues

### System Requirements

**For Installer Version:**
- Windows 10/11
- League of Legends installed
- Tesseract OCR installed (for OCR functionality)

**For Source Code Version:**
- Python 3.11+
- Tesseract OCR installed
- League of Legends installed
- Windows operating system (for CSLOL tools)
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
   - Run `start.bat` or `LoLSkinChanger.exe` directly

The build process creates a single executable file that includes:
- All Python dependencies
- Application code and resources
- No Python installation required on target systems

**Note**: Users still need to have:
- League of Legends installed and running
- Tesseract OCR installed (for OCR functionality)

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