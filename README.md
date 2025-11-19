# 🌹 Rose - Seamless Skin Changer for LoL

<div align="center">

  <img src="./assets/icon.ico" alt="Rose Icon" width="128" height="128">

[![Installer](https://img.shields.io/badge/Installer-Windows-blue)](https://github.com/Alban1911/Rose/releases/latest) [![Discord](https://img.shields.io/discord/1426680928759189545?color=5865F2&logo=discord&logoColor=white&label=Discord)](https://discord.com/invite/cDepnwVS8Z) [![License](https://img.shields.io/badge/License-Open%20Source-green)](LICENSE)

### **✅ FULLY COMPATIBLE WITH LATEST VANGUARD UPDATE ✅**

</div>

---

## Overview

Rose is an open-source automatic skin changer for League of Legends that enables seamless access to all skins in the game. The application runs silently in the system tray and automatically detects skin selections during champion select, injecting the chosen skin when the game loads.

**Rose is built on two core technologies:**

- **🎮 [Pengu Loader](https://github.com/FlorentTariolle/ROSE-Pengu)**: Plugin system that injects JavaScript plugins into the League Client, enabling enhanced UI interactions and quick skin detection
- **🔧 [CSLOL](https://github.com/LeagueToolkit/cslol-manager)**: Safe skin injection framework that handles the actual skin injection process, fully compatible with Riot Vanguard

These technologies work together to provide a seamless and effortless automatic skin-changing experience without any manual intervention.

## Architecture

Rose consists of two main components:

### Python Backend

- **LCU API Integration**: Communicates with the League Client via the League Client Update (LCU) API
- **CSLOL Injection**: Uses CSLOL tools for safe skin injection
- **WebSocket Bridge**: Operates a WebSocket server for real-time communication with frontend plugins
- **Skin Management**: Downloads and manages skins from the [LeagueSkins repository](https://github.com/darkseal-org/lol-skins)
- **Game Monitoring**: Tracks game state, champion select phases, and loadout countdowns

### Pengu Loader Plugins

Rose includes a suite of JavaScript plugins that extend the League Client UI:

- **[ROSE-UI](https://github.com/Alban1911/ROSE-UI)**: Unlocks locked skin previews in champion select, enabling hover interactions on all skins
- **[ROSE-SkinMonitor](https://github.com/Alban1911/ROSE-SkinMonitor)**: Monitors currently selected skin's name and sends it to the Python backend via WebSocket
- **[ROSE-ChromaWheel](https://github.com/Alban1911/ROSE-ChromaWheel)**: Enhanced chroma selection interface for choosing any chroma variant
- **[ROSE-SettingsPanel](https://github.com/FlorentTariolle/ROSE-SettingsPanel)**: In-client settings panel accessible from the League Client UI
- **[ROSE-RandomSkin](https://github.com/FlorentTariolle/ROSE-RandomSkin)**: Random skin selection feature
- **[ROSE-HistoricMode](https://github.com/FlorentTariolle/ROSE-HistoricMode)**: Access to the last used skin for every champion

## How It Works

1. **League Client Integration**: Rose activates **[Pengu Loader](https://github.com/FlorentTariolle/ROSE-Pengu)** on startup, which injects the JavaScript plugins into the League Client
2. **Skin Detection**: When you hover over a skin in champion select, [`ROSE-SkinMonitor`](https://github.com/Alban1911/ROSE-SkinMonitor) detects the selection and sends it to the Python backend
3. **Skin Preparation**: The backend downloads the skin (if needed) from the LeagueSkins repository and prepares it for injection
4. **Game Injection**: Using CSLOL tools, Rose injects the selected skin when the game loads, suspending the game process temporarily during injection
5. **Seamless Experience**: The skin loads as if you owned it, with full chroma support and no gameplay impact

## Features

- **Automatic Skin Detection**: Detects skin selections through hover events in champion select
- **All Skins Accessible**: Access to every skin for every champion
- **Chroma Support**: Select any chroma variant through the enhanced UI
- **Random Skin Mode**: Automatically select random skins
- **Historic Mode**: Access legacy and historic skin variants
- **Smart Injection**: Never injects skins you already own
- **Safe & Compatible**: Uses CSLOL injection tools compatible with Riot Vanguard
- **Multi-Language Support**: Works with any client language
- **Open Source**: Fully open source and extensible

## Requirements

- **Windows 10/11**
- **Python 3.11+** (for development)
- **League of Legends** installed
- **Administrator privileges** (required for skin injection)

## Installation

### Using the Installer

1. Download the latest installer from [Releases](https://github.com/Alban1911/Rose/releases/latest)
2. Run the installer as Administrator
3. Launch Rose from the Start Menu or desktop shortcut

### Setting up dev environment

```powershell
# Create conda environment with Python 3.11 
conda create -n rose python=3.11 -y

# Activate the environment
conda activate rose

# Clone the repository
git clone https://github.com/Alban1911/Rose.git

# Navigate to project directory
cd Rose

# Switch to dev branch
git checkout dev

# Initialize and update submodules ([Pengu Loader](https://github.com/FlorentTariolle/ROSE-Pengu) plugins)
git submodule update --init --recursive

# Install all dependencies
pip install -r requirements.txt

# Ready to develop! Run main.py as administrator when testing
```

## Project Structure

```
Rose/
├── main.py                 # Application entry point
├── config.py              # Configuration constants
├── requirements.txt       # Python dependencies
│
├── injection/             # [CSLOL](https://github.com/LeagueToolkit/cslol-manager) injection system
│   ├── injector.py       # [CSLOL](https://github.com/LeagueToolkit/cslol-manager) skin injector
│   ├── manager.py        # Injection manager & coordination
│   └── tools/            # [CSLOL](https://github.com/LeagueToolkit/cslol-manager) tools (cslol-dll.dll, mod-tools.exe, etc.)
│
├── lcu/                   # League Client API integration
│   ├── client.py         # LCU API client
│   ├── skin_scraper.py   # Skin data scraper
│   └── utils.py          # LCU utilities
│
├── threads/               # Background threads
│   ├── websocket_thread.py    # WebSocket bridge server
│   ├── phase_thread.py        # Game phase monitoring
│   ├── champ_thread.py        # Champion select monitoring
│   └── lcu_monitor_thread.py  # LCU connection monitoring
│
├── utils/                 # Utility modules
│   ├── pengu_loader.py   # [Pengu Loader](https://github.com/FlorentTariolle/ROSE-Pengu) integration
│   ├── skin_downloader.py     # Skin repository downloader
│   └── tray_manager.py        # System tray interface
│
├── state/                 # Shared application state
│   └── shared_state.py   # Thread-safe state management
│
└── Pengu Loader/          # [Pengu Loader](https://github.com/FlorentTariolle/ROSE-Pengu) and plugins
    ├── Pengu Loader.exe   # [Pengu Loader](https://github.com/FlorentTariolle/ROSE-Pengu) executable
    └── plugins/           # JavaScript plugins
        ├── [ROSE-UI](https://github.com/Alban1911/ROSE-UI)/
        ├── [ROSE-SkinMonitor](https://github.com/Alban1911/ROSE-SkinMonitor)/
        ├── [ROSE-ChromaWheel](https://github.com/Alban1911/ROSE-ChromaWheel)/
        ├── [ROSE-SettingsPanel](https://github.com/FlorentTariolle/ROSE-SettingsPanel)/
        ├── [ROSE-RandomSkin](https://github.com/FlorentTariolle/ROSE-RandomSkin)/
        └── [ROSE-HistoricMode](https://github.com/FlorentTariolle/ROSE-HistoricMode)/
```

## Usage

1. **Launch Rose** - The application runs in the system tray
2. **Start League of Legends** - Rose automatically detects and integrates
3. **Enter Champion Select** - Select your champion normally
4. **Hover Over Skins** - Simply hover over any skin (even locked ones)
5. **Game Loads** - Your selected skin is automatically injected

## Development

### Key Technologies

- **Python 3.11+**: Backend application
- **[Pengu Loader](https://github.com/FlorentTariolle/ROSE-Pengu)**: Plugin system for League Client
- **[CSLOL](https://github.com/LeagueToolkit/cslol-manager)**: Safe skin injection tools
- **LCU API**: League Client communication
- **WebSocket**: Real-time frontend-backend communication
- **JavaScript/HTML/CSS**: Client UI plugins

### Contributing

Rose is open source! Contributions are welcome:

- Report bugs or suggest features via GitHub Issues
- Submit pull requests for improvements
- Join our [Discord](https://discord.com/invite/cDepnwVS8Z) for discussions

## Legal Disclaimer

**Important**: This project is not endorsed by Riot Games and does not represent the views or opinions of Riot Games or any of its affiliates. Riot Games and all related properties are trademarks or registered trademarks of Riot Games, Inc.

The use of custom skin tools may violate Riot Games' Terms of Service. Users proceed at their own risk.

Custom skins are allowed under Riot's terms of service and do not trigger detection as long as you are not discussing or advertising the use of the skins within the game.

---

**Rose** - _League, unlocked._
