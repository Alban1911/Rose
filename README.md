# SkinCloner

**League of Legends Skin Changer with Advanced OCR Detection**

SkinCloner is a fully automated system that detects skin selections in League of Legends champion select using advanced OCR technology and automatically injects custom skins 3 seconds before the game starts. Built with a modular architecture and multi-language support, it provides a seamless experience for League of Legends players.

## 🔧 Prerequisites

### ⚠️ MANDATORY: Tesseract OCR Installation

**SkinCloner requires Tesseract OCR to function properly. This is a mandatory dependency that must be installed before using the application.**

#### Download and Installation

1. **Download Tesseract OCR for Windows:**
   - Visit: **[https://github.com/UB-Mannheim/tesseract/releases](https://github.com/UB-Mannheim/tesseract/releases)**
   - Download the latest Windows installer (e.g., `tesseract-ocr-w64-setup-5.x.x.exe`)

2. **Install Tesseract OCR:**
   - Run the installer **as Administrator**
   - **IMPORTANT**: During installation, select "Additional language data" to install language packs
   - Use the default installation path: `C:\Program Files\Tesseract-OCR\`

3. **Optional - Add to System PATH** (Recommended):
     ```powershell
   # Add Tesseract to PATH (run as Administrator)
     $env:PATH += ";C:\Program Files\Tesseract-OCR"
     [Environment]::SetEnvironmentVariable("PATH", $env:PATH, [EnvironmentVariableTarget]::Machine)
     ```

4. **Verify Installation:**
   ```bash
   # Check if Tesseract is accessible
   tesseract --version
   
   # Check available languages
   tesseract --list-langs
   ```

---

## 📦 Installation

### Option 1: Installer Version (Recommended for Users)

**For users who want a simple, ready-to-use application:**

1. **Download the latest installer** from [releases](https://github.com/AlbanCliquet/SkinCloner/releases/latest)
2. **Run** `SkinCloner_Setup.exe` **as Administrator**
3. **Follow the setup wizard** - the installer will create shortcuts and configure the application
4. **Launch the app** from your desktop or start menu

**System Requirements:**
- Windows 10/11
- League of Legends installed
- Tesseract OCR installed (see Prerequisites)

### Option 2: Source Code Version (For Developers)

**For developers and advanced users who want to modify the code:**

1. **Install Python 3.11**
2. **Clone this repository:**
   ```bash
   git clone https://github.com/AlbanCliquet/SkinCloner.git
   cd SkinCloner
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   This automatically installs the local tesserocr wheel from the `dependencies/` folder.

4. **Verify installation** (optional but recommended):
   ```bash
   python utils/check_tesseract.py
   ```

**System Requirements:**
- Windows 10/11
- Python 3.11
- Tesseract OCR installed (see Prerequisites)
- League of Legends installed
- CSLOL tools present in `injection/tools/` directory

---

## 🌍 Supported Languages

SkinCloner supports all languages that use the Latin alphabet, including:

- **English** (eng) - **Spanish** (spa) - **French** (fra) - **German** (deu)
- **Italian** (ita) - **Portuguese** (por) - **Polish** (pol) - **Turkish** (tur)
- **Hungarian** (hun) - **Romanian** (ron) - And other Latin-based languages

The system automatically detects your League of Legends client language.

---

## 🚀 Usage

### Quick Start

**SkinCloner is designed to be completely transparent - just launch it and forget about it!**

1. **Launch SkinCloner** (from desktop shortcut or start menu)
2. **Let it run in the background** - you don't need to interact with it
3. **Play League of Legends normally** - the app works silently in the background
4. **That's it!** SkinCloner handles everything automatically

The application runs in the system tray and requires no user interaction. Simply play League of Legends as usual, and when you hover over skins in champion select, the app will automatically detect and inject them.

### How It Works Behind the Scenes

While you play, SkinCloner operates through a sophisticated multi-threaded system:

1. **Phase Detection**: Monitors League Client for game phases (lobby, champion select, in-game)
2. **OCR Activation**: Automatically activates OCR when entering champion select
3. **Skin Detection**: Uses advanced computer vision to detect skin names as you hover over them
4. **Smart Matching**: Applies fuzzy matching algorithms to accurately identify skins
5. **Automatic Injection**: Injects the last detected skin 3 seconds before the game starts

**No manual intervention required - just launch the app and play!**


## ✨ Features

### Core Capabilities

- **🎯 Fully Automated**: Works completely automatically - no manual intervention required
- **🔍 Advanced OCR Detection**: Uses Tesseract OCR with optimized image processing for accurate skin name recognition
- **⚡ Instant Injection**: Automatically injects skins 3 seconds before game starts
- **🌍 Multi-Language Support**: Supports many languages with automatic detection
- **📊 Massive Skin Collection**: 8,277+ skins for 171 champions included
- **🧠 Smart Matching**: Advanced fuzzy matching algorithms for accurate skin detection

### Technical Features

- **🏗️ Modular Architecture**: Clean, maintainable codebase with separated concerns
- **🧵 Multi-threaded Design**: Optimal performance with concurrent processing
- **🔄 LCU Integration**: Real-time communication with League Client API
- **🛠️ CSLOL Tools**: Reliable injection using proven CSLOL modification tools
- **📈 Optimized Loading**: Only loads necessary language databases for better performance
- **🔒 Permission-Safe**: Uses user data directories to avoid permission issues

### Advanced Features

- **📥 Smart Downloads**: Efficient repository ZIP download with automatic updates
- **🎛️ Configurable OCR**: Adjustable confidence thresholds and processing modes
- **📊 Real-time Monitoring**: WebSocket-based event handling for optimal performance
- **🔧 Diagnostic Tools**: Built-in Tesseract validation and troubleshooting utilities
- **📱 System Tray Integration**: Clean background operation with system tray management
- **📝 Comprehensive Logging**: Detailed logging system with configurable retention

### Performance Optimizations

- **⚡ Burst OCR**: High-frequency OCR during motion/hover detection
- **💤 Idle Optimization**: Reduced OCR frequency when inactive
- **🎯 ROI Locking**: Intelligent region-of-interest detection and locking
- **🔄 Adaptive Timing**: Dynamic timing adjustments based on system performance
- **📊 Rate Limiting**: Intelligent GitHub API rate limiting for skin downloads

---

## 📁 Project Structure

```
SkinCloner/
├── main.py                       # Main application entry point
├── requirements.txt              # Python dependencies
├── constants.py                  # Centralized configuration constants
├── README.md                     # This documentation file
│
├── injection/                    # Skin injection system
│   ├── injector.py               # CSLOL injection logic
│   ├── manager.py                # Injection management and coordination
│   ├── mods_map.json             # Mod configuration mapping
│   └── tools/                    # CSLOL modification tools
│       ├── mod-tools.exe         # Main modification tool
│       ├── cslol-diag.exe        # Diagnostics tool
│       ├── cslol-dll.dll         # Core injection DLL
│       └── [WAD utilities]       # WAD extraction/creation tools
│
├── ocr/                          # OCR functionality
│   ├── backend.py                # Tesseract OCR backend implementation
│   └── image_processing.py       # Advanced image processing for OCR
│
├── database/                     # Champion and skin databases
│   ├── name_db.py                # Champion and skin name database
│   └── multilang_db.py           # Multi-language database with auto-detection
│
├── lcu/                          # League Client API integration
│   ├── client.py                 # LCU API client implementation
│   └── utils.py                  # LCU utility functions
│
├── threads/                      # Multi-threaded components
│   ├── phase_thread.py           # Game phase monitoring
│   ├── champ_thread.py           # Champion hover/lock monitoring
│   ├── ocr_thread.py             # OCR skin detection thread
│   ├── websocket_thread.py       # WebSocket event handling
│   ├── lcu_monitor_thread.py     # LCU connection monitoring
│   └── loadout_ticker.py         # Loadout countdown timer
│
├── utils/                        # Utility functions and helpers
│   ├── logging.py                # Comprehensive logging system
│   ├── normalization.py          # Text normalization utilities
│   ├── paths.py                  # Cross-platform path management
│   ├── skin_downloader.py        # Skin download system
│   ├── smart_skin_downloader.py  # Smart downloader with rate limiting
│   ├── repo_downloader.py        # Repository ZIP downloader
│   ├── window_utils.py           # Windows window capture utilities
│   ├── tesseract_path.py         # Tesseract path detection
│   ├── check_tesseract.py        # Tesseract diagnostic tool
│   └── tray_manager.py           # System tray management
│
├── state/                        # Shared state management
│   ├── shared_state.py           # Thread-safe shared state
│   └── [runtime files]           # Temporary state files
│
├── dependencies/                 # Local dependencies
│   └── tesserocr-*.whl          # Pre-compiled Tesseract OCR wheel
│
└── [build system]/               # Build and distribution
    ├── build_all.py              # Complete build script
    ├── build_exe.py              # PyInstaller executable builder
    ├── create_installer.py       # Inno Setup installer creator
    ├── build_requirements.txt    # Build-time dependencies
    └── installer.iss             # Inno Setup configuration
```

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## ⚠️ Disclaimer

This tool is for educational purposes only. Use at your own risk. The developers are not responsible for any issues that may arise from using this software.

---

**SkinCloner** -  League of Legends Skin Changer