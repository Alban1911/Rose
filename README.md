# 🌹 Rose - Effortless Skin Changer for LoL

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
3. **Game Opening Delay**: To make sure the injection has time to occur we suspend League of Legend's game process as long as the overlay is not ran
4. **Game Injection**: Using CSLOL tools, Rose injects the selected skin when the game starts
5. **Seamless Experience**: The skin loads as if you owned it, with full chroma support and no gameplay impact (Rose will never provide any feature that gives a competitive advantage to its users)

## Features

- **Automatic Skin Detection**: Detects skin selections through hover events in champion select
- **All Skins Accessible**: Access to every skin for every champion
- **Chroma Support**: Select any chroma variant through the enhanced UI
- **Random Skin Mode**: Automatically select random skins
- **Historic Mode**: Access last used skin on every champion
- **Smart Injection**: Never injects skins you already own
- **Safe & Compatible**: Uses CSLOL injection tools compatible with Riot Vanguard
- **Multi-Language Support**: Works with any client language
- **Open Source**: Fully open source and extensible
- **Free**: If you bought this software, you got scammed 💀

## Requirements

- **Windows 10/11**
- **League of Legends** installed

## Installation

1. Download the latest installer from [Releases](https://github.com/Alban1911/Rose/releases/latest)
2. Run the installer as Administrator
3. Launch Rose from the Start Menu or desktop shortcut

## Setting up dev environment

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

# Initialize and update submodules (Pengu Loader plugins)
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
├── requirements.txt        # Python dependencies
├── assets/                 # Application assets (icons, fonts, images)
│
├── main/                   # Main application package
│   ├── core/              # Core initialization and lifecycle
│   │   ├── initialization.py
│   │   ├── threads.py
│   │   ├── state.py
│   │   ├── signals.py
│   │   ├── lockfile.py
│   │   ├── lcu_handler.py
│   │   └── cleanup.py
│   ├── setup/             # Application setup and configuration
│   │   ├── console.py
│   │   ├── arguments.py
│   │   └── initialization.py
│   └── runtime/           # Main runtime loop
│       └── loop.py
│
├── injection/             # CSLOL injection system
│   ├── core/              # Core injection logic
│   │   ├── manager.py    # Injection manager & coordination
│   │   └── injector.py   # CSLOL skin injector
│   ├── game/              # Game detection and monitoring
│   │   ├── game_detector.py
│   │   └── game_monitor.py
│   ├── config/            # Configuration management
│   │   ├── config_manager.py
│   │   └── threshold_manager.py
│   ├── mods/              # Mod management
│   │   ├── mod_manager.py
│   │   └── zip_resolver.py
│   ├── overlay/           # Overlay process management
│   │   ├── overlay_manager.py
│   │   └── process_manager.py
│   └── tools/             # CSLOL tools (cslol-dll.dll, mod-tools.exe, etc.)
│       └── tools_manager.py
│
├── lcu/                   # League Client API integration
│   ├── core/              # Core LCU client components
│   │   ├── client.py      # Main LCU client orchestrator
│   │   ├── lcu_api.py     # LCU API wrapper
│   │   ├── lcu_connection.py
│   │   └── lockfile.py
│   ├── data/              # Data management
│   │   ├── skin_scraper.py
│   │   ├── skin_cache.py
│   │   ├── types.py
│   │   └── utils.py
│   └── features/          # LCU feature implementations
│       ├── lcu_properties.py
│       ├── lcu_skin_selection.py
│       ├── lcu_game_mode.py
│       └── lcu_swiftplay.py
│
├── threads/               # Background threads
│   ├── core/              # Core thread implementations
│   │   ├── websocket_thread.py
│   │   ├── phase_thread.py
│   │   └── lcu_monitor_thread.py
│   ├── handlers/         # Event handlers
│   │   ├── champ_thread.py
│   │   ├── champion_lock_handler.py
│   │   ├── game_mode_detector.py
│   │   ├── injection_trigger.py
│   │   ├── lobby_processor.py
│   │   ├── phase_handler.py
│   │   └── swiftplay_handler.py
│   ├── utilities/         # Thread utilities
│   │   ├── timer_manager.py
│   │   ├── loadout_ticker.py
│   │   └── skin_name_resolver.py
│   └── websocket/         # WebSocket components
│       ├── websocket_connection.py
│       └── websocket_event_handler.py
│
├── utils/                 # Utility modules
│   ├── core/              # Core utilities
│   │   ├── logging.py
│   │   ├── paths.py
│   │   ├── utilities.py
│   │   ├── validation.py
│   │   ├── normalization.py
│   │   └── historic.py
│   ├── download/          # Download utilities
│   │   ├── skin_downloader.py
│   │   ├── smart_skin_downloader.py
│   │   ├── repo_downloader.py
│   │   ├── hashes_downloader.py
│   │   └── hash_updater.py
│   ├── integration/       # External integrations
│   │   ├── pengu_loader.py
│   │   ├── tray_manager.py
│   │   └── tray_settings.py
│   ├── system/            # System utilities
│   │   ├── admin_utils.py
│   │   ├── win32_base.py
│   │   ├── window_utils.py
│   │   └── resolution_utils.py
│   └── threading/         # Threading utilities
│       └── thread_manager.py
│
├── ui/                    # UI components
│   ├── core/              # Core UI management
│   │   ├── user_interface.py
│   │   └── lifecycle_manager.py
│   ├── chroma/            # Chroma selection UI
│   │   ├── selector.py
│   │   ├── ui.py
│   │   ├── panel.py
│   │   ├── preview_manager.py
│   │   ├── selection_handler.py
│   │   └── special_cases.py
│   └── handlers/          # UI feature handlers
│       ├── historic_mode_handler.py
│       ├── randomization_handler.py
│       └── skin_display_handler.py
│
├── pengu/                 # Pengu Loader integration
│   ├── core/              # Core Pengu functionality
│   │   ├── websocket_server.py
│   │   ├── http_handler.py
│   │   └── skin_monitor.py
│   ├── communication/     # Communication layer
│   │   ├── message_handler.py
│   │   └── broadcaster.py
│   └── processing/        # Data processing
│       ├── skin_processor.py
│       ├── skin_mapping.py
│       └── flow_controller.py
│
├── state/                 # Shared application state
│   └── core/
│       ├── shared_state.py
│       └── app_status.py
│
├── launcher/              # Application launcher and updater
│   ├── core/
│   │   └── launcher.py
│   ├── sequences/         # Launch sequences
│   │   ├── hash_check_sequence.py
│   │   └── skin_sync_sequence.py
│   ├── update/            # Update system
│   │   ├── update_sequence.py
│   │   ├── update_downloader.py
│   │   ├── update_installer.py
│   │   └── github_client.py
│   ├── ui/
│   │   └── update_dialog.py
│   └── updater.py
│
└── Pengu Loader/          # Pengu Loader and plugins
    ├── Pengu Loader.exe   # Pengu Loader executable
    └── plugins/           # JavaScript plugins
        ├── ROSE-UI/
        ├── ROSE-SkinMonitor/
        ├── ROSE-ChromaWheel/
        ├── ROSE-SettingsPanel/
        ├── ROSE-RandomSkin/
        └── ROSE-HistoricMode/
```

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
