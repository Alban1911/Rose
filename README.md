# LeagueUnlocked

**League of Legends Skin Changer with Advanced OCR Detection**

LeagueUnlocked is a fully automated system that detects skin selections in League of Legends champion select using advanced OCR technology and automatically injects custom skins 300 milliseconds before the game starts. Built with a modular architecture, unified game process monitoring, multi-language support, and an interactive chroma selection UI, it provides a seamless experience for League of Legends players.

## 🔧 Prerequisites

### System Requirements

**Minimum Requirements:**

- Windows 10/11 (64-bit)
- 4 GB RAM
- League of Legends installed
- Internet connection (for first-time EasyOCR model download)

**Recommended for Optimal Performance:**

- 8+ GB RAM
- SSD storage

### 🔍 OCR Technology

**LeagueUnlocked uses EasyOCR with GPU acceleration for accurate skin detection across all languages.**

- **GPU Accelerated**: Automatically uses GPU if available (CUDA) for faster OCR
- **CPU Fallback**: Seamlessly falls back to CPU mode if GPU is not available
- **Universal compatibility**: Works on all systems with or without GPU
- **Advanced preprocessing**: Research-based image processing for optimal accuracy

**No additional installation required** - EasyOCR models download automatically on first run!

---

## 📦 Installation

### Option 1: Installer Version (Recommended for Users)

**For users who want a simple, ready-to-use application:**

1. **Download the latest installer** from [releases](https://github.com/AlbanCliquet/LeagueUnlocked/releases/latest)
2. **Run** `LeagueUnlocked_Setup.exe` **as Administrator**
3. **Follow the setup wizard** - the installer will create shortcuts and configure the application
4. **Launch the app** from your desktop or start menu

### Option 2: Source Code Version (For Developers)

**For developers and advanced users who want to modify the code:**

1. **Install Python 3.11**
2. **Clone this repository:**

   ```bash
   git clone https://github.com/AlbanCliquet/LeagueUnlocked.git
   cd LeagueUnlocked
   ```

3. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

   This automatically installs:

   - EasyOCR with PyTorch (GPU-accelerated with CPU fallback)
   - OpenCV, NumPy, SciPy (image processing)
   - All other required packages

   **Note**: First run will download EasyOCR models (~50-100 MB) - requires internet connection.

4. **GPU Acceleration (Optional - For Developers Only):**

   **⚠️ NOTE FOR END USERS**: If you're using the pre-built executable (.exe), you can skip this section! The executable already includes GPU support and will automatically use your GPU if available.

   **For developers** running from source who want GPU acceleration:

   **Requirements:**

   - NVIDIA GPU with CUDA support
   - CUDA Toolkit 11.8+ (12.x recommended)
   - cuDNN 8.x+

   **Installation:**

   ```bash
   # Uninstall CPU-only PyTorch (if installed)
   pip uninstall torch torchvision -y

   # Install PyTorch with GPU support (CUDA 12.1)
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
   ```

   **Verify GPU Setup:**

   ```bash
   python test_gpu_setup.py
   ```

   **Performance:** GPU acceleration provides much faster OCR (0-5ms vs 200-800ms on CPU)!

5. **Building from Source:**

   To build the executable and installer:

   ```bash
   python build_all.py
   ```

   This will:

   - Build the executable with PyInstaller
   - Create a Windows installer with Inno Setup
   - Output to `dist/LeagueUnlocked/` and `installer/` directories

**System Requirements:**

- Windows 10/11 (64-bit)
- Python 3.11
- CSLOL tools present in `injection/tools/` directory

---

## 🌍 Supported Languages

**LeagueUnlocked uses EasyOCR with support for 80+ languages**, including Latin and non-Latin alphabets:

**Latin Alphabet:**

- **English** (eng) - **Spanish** (spa) - **French** (fra) - **German** (deu)
- **Italian** (ita) - **Portuguese** (por) - **Polish** (pol) - **Turkish** (tur)
- **Hungarian** (hun) - **Romanian** (ron) - And more

**Non-Latin Alphabets:**

- **Korean** (kor) - **Chinese Simplified** (chi_sim) - **Chinese Traditional** (chi_tra)
- **Japanese** (jpn) - **Russian** (rus) - **Arabic** (ara) - **Vietnamese** (vie)
- **Thai** (tha) - And more

**The system automatically detects your League of Legends client language.**

---

## 🚀 Usage

### Quick Start

**LeagueUnlocked is designed to be completely transparent - just launch it and forget about it!**

1. **Launch LeagueUnlocked** (from desktop shortcut or start menu)
2. **Accept the UAC prompt** (Administrator privileges required for injection)
3. **Let it run in the background** - you don't need to interact with it
4. **Play League of Legends normally** - the app works silently in the background
5. **That's it!** LeagueUnlocked handles everything automatically

### 🔐 Administrator Rights & Auto-Start

**LeagueUnlocked requires Administrator privileges** to inject skins into League of Legends.

#### First Launch

- **UAC Prompt**: On first launch, Windows will ask for administrator permission
- **One-Time**: Click "Yes" to allow the app to run with admin rights
- **Automatic**: The app will then restart with proper privileges

#### Auto-Start (Recommended)

**Enable seamless auto-start to avoid UAC prompts on every launch:**

1. Launch LeagueUnlocked (accept the initial UAC prompt)
2. Right-click the LeagueUnlocked icon in the system tray
3. Click **"Enable Auto-Start"**
4. Done! The app will now:
   - Start automatically when you log into Windows
   - Run with administrator privileges
   - **No UAC prompts** on startup

**Benefits:**

- ✅ No more UAC prompts on every launch
- ✅ Starts automatically with Windows
- ✅ Runs silently in the background
- ✅ Works across computer restarts

**To disable auto-start:**

- Right-click the tray icon → "Remove Auto-Start"

The application runs in the system tray and requires no user interaction. Simply play League of Legends as usual, and when you hover over skins in champion select, the app will automatically detect and inject them.

### How It Works Behind the Scenes

While you play, LeagueUnlocked operates through a sophisticated multi-threaded system:

1. **Phase Detection**: Monitors League Client for game phases (lobby, champion select, in-game)
2. **OCR Activation**: Automatically activates OCR when entering champion select
3. **Champion Lock Detection**: Detects when you lock a champion and fetches your owned skins from LCU
4. **Real-Time Skin Detection**: Uses advanced OCR to detect skin names as you hover over them during champion select
5. **Chroma Selection**: Shows interactive chroma wheel when skin with chromas is detected
6. **Ownership Verification**: Automatically skips injection if you already own the detected skin
7. **Base Skin Forcing**: Forces base skin selection before injection (required for proper skin overlay)
8. **Automatic Injection**: Injects the last hovered unowned skin 300 milliseconds before game starts with CPU priority boost for reliability

**Performance & Reliability**:

- **Process Suspension**: Game process is suspended during injection to ensure reliable overlay installation
- **High-Priority Processing**: Uses CPU priority boost for mkoverlay and runoverlay processes
- **Safety Mechanisms**: 20-second auto-resume timeout prevents game from being stuck frozen
- **Smart Injection**: Only injects skins you don't own, verified against LCU inventory
- **Robust Fallbacks**: Multiple LCU endpoints ensure base skin forcing works reliably

**No manual intervention required - just launch the app and play!**

### Chroma Selection

When you hover over a skin that has chroma variants, LeagueUnlocked automatically displays an interactive chroma wheel:

- **Visual Preview**: See preview images of each chroma variant
- **One-Click Selection**: Click any chroma to select it for injection
- **Ownership Indicators**: Lock icons show which chromas you don't own
- **Resolution Adaptive**: UI automatically scales to match your League window resolution
- **Instant Updates**: Selected chroma is immediately queued for injection

The chroma wheel appears automatically when OCR detects a skin with chromas, and disappears when you move to a different skin or exit champion select.

## ✨ Features

### Core Capabilities

- **🎯 Fully Automated**: Works completely automatically - no manual intervention required
- **🔍 Advanced OCR Detection**: Uses EasyOCR with research-based preprocessing and optimized image processing for accurate skin name recognition
- **🎨 Chroma Selection UI**: Interactive chroma wheel with preview images for easy chroma variant selection
- **⚡ Optimized Injection**: Uses high-priority processes and game suspension for reliable injection 300ms before game starts
- **✅ Ownership Detection**: Automatically detects owned skins via LCU inventory and skips injection to avoid conflicts
- **🔄 Base Skin Forcing**: Intelligently forces base skin selection before injection with multiple fallback endpoints
- **🎮 Unified Game Monitor**: Single, efficient monitor handles game process suspension and resume
- **🌍 Multi-Language Support**: Supports 80+ languages including Latin and non-Latin alphabets (Korean, Chinese, Russian, etc.)
- **📊 Massive Skin Collection**: 8,277+ skins for 171 champions included
- **🧠 Smart Matching**: Advanced fuzzy matching algorithms for accurate skin detection

### Technical Features

- **🏗️ Modular Architecture**: Clean, maintainable codebase with separated concerns
- **🧵 Multi-threaded Design**: Optimal performance with concurrent processing (6 specialized threads)
- **🔄 LCU Integration**: Real-time communication with League Client API (with fallback endpoints for robustness)
- **🛠️ CSLOL Tools**: Reliable injection using proven CSLOL modification tools
- **📈 Optimized Loading**: Only loads necessary language databases for better performance
- **🔒 Permission-Safe**: Uses user data directories to avoid permission issues
- **🎮 Inventory-Aware**: Fetches owned skins from LCU to prevent unnecessary injections
- **⚡ Process Management**: Unified monitor with game suspension, priority boost, and safety timeouts
- **💾 OCR Caching**: Intelligent caching system reduces redundant OCR operations for better performance

### Advanced Features

- **📥 Smart Downloads**: Efficient repository ZIP download with automatic updates
- **🎛️ Configurable OCR**: Adjustable confidence thresholds and processing modes
- **📊 Real-time Monitoring**: WebSocket-based event handling for optimal performance
- **🔧 Diagnostic Tools**: Built-in EasyOCR validation and diagnostic utilities
- **📱 System Tray Integration**: Clean background operation with system tray management
- **🔐 Auto-Start with Admin Rights**: Task Scheduler integration for seamless auto-start (no UAC prompts)
- **📝 Comprehensive Logging**: Detailed logging system with configurable retention
- **🖼️ Chroma Previews**: Automatic download of chroma preview images from CommunityDragon
- **🎯 Resolution-Adaptive UI**: Chroma UI automatically scales to match League window resolution

### Performance Optimizations

- **⚡ Burst OCR**: High-frequency OCR (40 Hz) during motion/hover detection
- **💤 Idle Optimization**: Reduced OCR frequency when inactive to save CPU
- **🎯 ROI Locking**: Intelligent region-of-interest detection and locking
- **🔄 Adaptive Timing**: Dynamic timing adjustments based on system performance
- **📊 Rate Limiting**: Intelligent GitHub API rate limiting for skin downloads
- **🎭 Smart Filtering**: Only injects unowned skins by filtering against LCU inventory
- **🔧 Robust Fallbacks**: Multiple LCU endpoints for reliable base skin forcing
- **🧹 Automatic Cleanup**: Cleans up injection processes when entering lobby
- **⚙️ Unified Monitor**: Single monitor eliminates race conditions and reduces complexity
- **💨 Fast Injection**: Optimized injection timing at 300ms before game starts

---

## 🏗️ Architecture Highlights

### Unified Game Monitor System

LeagueUnlocked uses a **single, unified monitor** for game process management, eliminating race conditions and complexity:

**Monitor Lifecycle:**

1. **Start**: Monitor activates when injection begins
2. **Watch**: Continuously scans for `League of Legends.exe` process
3. **Suspend**: Immediately suspends game when found to freeze loading
4. **Hold**: Keeps game suspended during mkoverlay (skin preparation)
5. **Resume**: Releases game when runoverlay starts (allows game to load while overlay hooks in)
6. **Safety**: Auto-resumes after 20s if injection stalls (prevents permanent freeze)

**Benefits:**

- ✅ **No Race Conditions**: Single source of truth for game state
- ✅ **Reliable Timing**: Ensures injection completes before game finishes loading
- ✅ **Fail-Safe**: Multiple safety mechanisms prevent game from being stuck

### In-Memory State Management

All application state is stored in memory using a thread-safe `SharedState` dataclass:

- **Zero File I/O**: No reading/writing state files during operation
- **Faster Performance**: Eliminates disk access overhead
- **Thread-Safe**: Lock-protected shared state across 6 concurrent threads
- **Clean Architecture**: Centralized state management in `state/shared_state.py`

### Multi-Threaded Architecture

LeagueUnlocked uses 6 specialized threads for optimal performance:

1. **Phase Thread**: Monitors LCU for game phase changes (lobby → champ select → in-game)
2. **Champion Thread**: Detects champion hover/lock and fetches owned skins from LCU
3. **OCR Thread**: High-frequency skin name detection using EasyOCR with optimized preprocessing
4. **WebSocket Thread**: Real-time event handling via LCU WebSocket connection
5. **LCU Monitor Thread**: Maintains connection to League Client
6. **Loadout Ticker Thread**: Countdown timer for injection timing

All threads coordinate through the shared state system for seamless operation.

---

## 📁 Project Structure

```
LeagueUnlocked/
├── main.py                       # Main application entry point
├── requirements.txt              # Python dependencies
├── config.py                     # Centralized configuration constants
├── README.md                     # This documentation file
│
├── injection/                    # Skin injection system
│   ├── injector.py               # CSLOL injection logic with overlay management
│   ├── manager.py                # Injection manager with unified game monitor
│   ├── mods_map.json             # Mod configuration mapping
│   └── tools/                    # CSLOL modification tools
│       ├── mod-tools.exe         # Main modification tool
│       ├── cslol-diag.exe        # Diagnostics tool
│       ├── cslol-dll.dll         # Core injection DLL
│       └── [WAD utilities]       # WAD extraction/creation tools
│
├── ocr/                          # OCR functionality
│   ├── backend.py                # EasyOCR backend (GPU/CPU mode with caching)
│   └── image_processing.py       # Research-based image preprocessing for OCR
│
├── database/                     # Champion and skin databases
│   └── name_db.py                # Champion and skin name database
│
├── lcu/                          # League Client API integration
│   ├── client.py                 # LCU API client implementation
│   ├── skin_scraper.py           # Scrapes skin/chroma data from LCU
│   ├── types.py                  # Type definitions for LCU data
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
│   ├── preview_repo_downloader.py # Chroma preview images downloader
│   ├── window_utils.py           # Windows window capture utilities
│   ├── admin_utils.py            # Admin rights and auto-start management
│   ├── tray_manager.py           # System tray management
│   ├── thread_manager.py         # Centralized thread lifecycle management
│   ├── validation.py             # Input validation utilities
│   ├── chroma_selector.py        # Chroma selection coordinator
│   ├── chroma_panel.py           # Chroma panel widget manager
│   ├── chroma_panel_widget.py    # Main chroma panel UI widget
│   ├── chroma_button.py          # Chroma selection button UI
│   ├── chroma_click_catcher.py   # Click detection overlay for chroma UI
│   ├── chroma_preview_manager.py # Manages chroma preview images
│   ├── chroma_scaling.py         # Resolution-adaptive UI scaling
│   └── chroma_base.py            # Base classes for chroma UI
│
├── state/                        # Shared state management
│   ├── shared_state.py           # Thread-safe in-memory shared state (no file I/O)
│   └── app_status.py             # Application status tracking for tray icon
│
└── [build system]/               # Build and distribution
    ├── build_all.py              # Complete build script (PyInstaller + Installer)
    ├── build_pyinstaller.py      # PyInstaller build script
    ├── LeagueUnlocked.spec       # PyInstaller configuration
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

**LeagueUnlocked** - League of Legends Skin Changer
