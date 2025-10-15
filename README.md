# LeagueUnlocked

**League of Legends Skin Changer with Advanced OCR Detection**

LeagueUnlocked is a fully automated system that detects skin selections in League of Legends champion select using advanced OCR technology and automatically injects custom skins 300 milliseconds before the game starts. Built with a modular architecture, unified game process monitoring, multi-language support, and an interactive chroma selection UI, it provides a seamless experience for League of Legends players.

## 🔧 Prerequisites

### System Requirements

**Minimum Requirements:**

- Windows 10/11 (64-bit)
- 4 GB RAM
- League of Legends installed
- Internet connection (for license activation and EasyOCR models)
- **Valid license key** (required for activation)

**Recommended for Optimal Performance:**

- 8+ GB RAM
- SSD storage
- NVIDIA GPU (optional - enables faster OCR via CUDA)

### 🔍 OCR Technology

**LeagueUnlocked uses EasyOCR with automatic GPU acceleration for accurate skin detection across all languages.**

- **GPU Accelerated**: Automatically detects and uses NVIDIA GPU (CUDA) if available
- **CPU Fallback**: Seamlessly falls back to CPU mode on systems without GPU
- **Advanced preprocessing**: Research-based image processing for optimal accuracy
- **No setup required**: EasyOCR models download automatically on first run

---

## 📦 Installation

### Option 1: Installer Version (Recommended for Users)

**For users who want a simple, ready-to-use application:**

1. **Download the latest installer** from [releases](https://github.com/AlbanCliquet/LeagueUnlocked/releases/latest)
2. **Run** `LeagueUnlocked_Setup.exe` **as Administrator**
3. **Follow the setup wizard** - the installer will create shortcuts and configure the application
4. **Launch the app** from your desktop or start menu
5. **Activate your license** when prompted (see License Activation below)

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

   **Note**: First run will download EasyOCR models (~50-100 MB). GPU support is automatic if CUDA is available.

4. **Building from Source:**

   To build the executable and installer:

   ```bash
   python build_all.py
   ```

   This will:

   - Build the executable with PyInstaller
   - Create a Windows installer with Inno Setup
   - Output to `dist/LeagueUnlocked/` and `installer/` directories

---

## 🔐 License Activation

**LeagueUnlocked requires a valid license key to operate.**

### First-Time Setup

1. **Launch the application** - it will check for an existing license
2. **If no license is found**, an activation dialog will appear
3. **Enter your license key** when prompted
4. **Activation is automatic** - the app validates with the license server
5. **License is saved locally** and bound to your machine

### License Features

- **Online validation** on first activation (requires internet)
- **Offline verification** for subsequent launches (works without internet)
- **Machine binding** - each license is tied to your specific computer
- **Expiration tracking** - displays days remaining on startup

### For Developers

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

### How It Works

LeagueUnlocked operates automatically through a multi-threaded system:

1. **Monitors** League Client for game phases (lobby, champion select, in-game)
2. **Activates OCR** when you enter champion select and lock a champion
3. **Detects skin names** in real-time as you hover over them using advanced OCR
4. **Shows chroma wheel** when hovering over skins with chroma variants
5. **Verifies ownership** and skips injection for skins you already own
6. **Injects selected skin** 300ms before game starts with process suspension for reliability

**No manual intervention required - just launch the app and play!**

### Chroma Selection

When you hover over a skin that has chroma variants, LeagueUnlocked automatically displays an interactive chroma wheel:

- **Visual Preview**: See preview images of each chroma variant
- **One-Click Selection**: Click any chroma to select it for injection
- **Resolution Adaptive**: UI automatically scales to match your League window resolution
- **Instant Updates**: Selected chroma is immediately queued for injection

The chroma wheel appears automatically when OCR detects a skin with chromas, and disappears when you move to a different skin or exit champion select.

## ✨ Features

- **🎯 Fully Automated**: Zero manual intervention - works silently in the background
- **🔍 Advanced OCR**: EasyOCR with GPU acceleration and multi-language support (80+ languages)
- **🎨 Interactive Chroma UI**: Resolution-adaptive chroma wheel with preview images
- **⚡ Fast Injection**: 300ms before game starts with process suspension for reliability
- **✅ Smart Ownership**: Auto-detects owned skins via LCU and skips injection
- **🎮 Game Monitor**: Unified process monitor with safety timeouts and auto-resume
- **🌍 Multi-Language**: Supports Latin and non-Latin alphabets (Korean, Chinese, Russian, Arabic, etc.)
- **📊 Massive Collection**: 8,277+ skins for 171 champions with automatic updates
- **🔐 Auto-Start**: Task Scheduler integration for seamless Windows startup (no UAC prompts)
- **📱 System Tray**: Background operation with status indicators
- **🧵 Multi-threaded**: 6 specialized threads for optimal performance
- **💾 OCR Caching**: Intelligent caching reduces redundant operations
- **🔧 Robust**: Multiple LCU fallback endpoints and error handling

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
