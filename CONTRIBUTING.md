# Contributing to Rose

Contributions are welcome! Report bugs or suggest features via GitHub Issues, submit pull requests, or join our [Discord](https://discord.com/invite/roseapp) for discussions.

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

# Install all dependencies
pip install -r requirements.txt

# Ready to develop! Run main.py as administrator when testing
```

## Project Structure

```
Rose/
├── main.py                 # Application entry point
├── config.py               # Configuration constants
├── requirements.txt        # Python dependencies
├── assets/                 # Application assets (icons, fonts, images)
│
├── main/                   # Main application package
│   ├── core/               # Core initialization and lifecycle
│   │   ├── initialization.py
│   │   ├── threads.py
│   │   ├── state.py
│   │   ├── signals.py
│   │   ├── lockfile.py
│   │   ├── lcu_handler.py
│   │   └── cleanup.py
│   ├── setup/              # Application setup and configuration
│   │   ├── console.py
│   │   ├── arguments.py
│   │   └── initialization.py
│   └── runtime/            # Main runtime loop
│       └── loop.py
│
├── injection/              # Skin injection system
│   ├── core/               # Core injection logic
│   │   ├── manager.py      # Injection manager & coordination
│   │   └── injector.py     # Skin injector
│   ├── game/               # Game detection and monitoring
│   │   ├── game_detector.py
│   │   └── game_monitor.py
│   ├── config/             # Configuration management
│   │   ├── config_manager.py
│   │   └── threshold_manager.py
│   ├── mods/               # Mod management
│   │   ├── mod_manager.py
│   │   └── zip_resolver.py
│   ├── overlay/            # Overlay process management
│   │   ├── overlay_manager.py
│   │   └── process_manager.py
│   └── tools/              # Injection tools (mod-tools.exe, etc.)
│       └── tools_manager.py
│
├── lcu/                    # League Client API integration
│   ├── core/               # Core LCU client components
│   │   ├── client.py       # Main LCU client orchestrator
│   │   ├── lcu_api.py      # LCU API wrapper
│   │   ├── lcu_connection.py
│   │   └── lockfile.py
│   ├── data/               # Data management
│   │   ├── skin_scraper.py
│   │   ├── skin_cache.py
│   │   ├── types.py
│   │   └── utils.py
│   └── features/           # LCU feature implementations
│       ├── lcu_properties.py
│       ├── lcu_skin_selection.py
│       ├── lcu_game_mode.py
│       └── lcu_swiftplay.py
│
├── threads/                # Background threads
│   ├── core/               # Core thread implementations
│   │   ├── websocket_thread.py
│   │   ├── phase_thread.py
│   │   └── lcu_monitor_thread.py
│   ├── handlers/            # Event handlers
│   │   ├── champ_thread.py
│   │   ├── champion_lock_handler.py
│   │   ├── game_mode_detector.py
│   │   ├── injection_trigger.py
│   │   ├── lobby_processor.py
│   │   ├── phase_handler.py
│   │   └── swiftplay_handler.py
│   ├── utilities/           # Thread utilities
│   │   ├── timer_manager.py
│   │   ├── loadout_ticker.py
│   │   └── skin_name_resolver.py
│   └── websocket/           # WebSocket components
│       ├── websocket_connection.py
│       └── websocket_event_handler.py
│
├── utils/                  # Utility modules
│   ├── core/               # Core utilities
│   │   ├── logging.py
│   │   ├── paths.py
│   │   ├── utilities.py
│   │   ├── validation.py
│   │   ├── normalization.py
│   │   ├── historic.py
│   │   ├── mod_historic.py
│   │   ├── issue_reporter.py
│   │   ├── junction.py
│   │   └── safe_extract.py
│   ├── crypto/             # Skin encryption
│   │   ├── skin_crypto.py
│   │   └── key_provider.py
│   ├── download/           # Download utilities
│   │   ├── skin_downloader.py
│   │   ├── smart_skin_downloader.py
│   │   ├── repo_downloader.py
│   │   ├── hashes_downloader.py
│   │   └── hash_updater.py
│   ├── integration/        # External integrations
│   │   ├── pengu_loader.py
│   │   ├── tray_manager.py
│   │   └── tray_settings.py
│   ├── system/             # System utilities
│   │   ├── admin_utils.py
│   │   ├── win32_base.py
│   │   ├── window_utils.py
│   │   └── resolution_utils.py
│   └── threading/          # Threading utilities
│       └── thread_manager.py
│
├── ui/                     # UI components
│   ├── core/               # Core UI management
│   │   ├── user_interface.py
│   │   └── lifecycle_manager.py
│   ├── chroma/             # Chroma selection UI
│   │   ├── selector.py
│   │   ├── ui.py
│   │   ├── panel.py
│   │   ├── preview_manager.py
│   │   ├── selection_handler.py
│   │   └── special_cases.py
│   └── handlers/           # UI feature handlers
│       ├── historic_mode_handler.py
│       ├── randomization_handler.py
│       └── skin_display_handler.py
│
├── pengu/                  # Pengu Loader integration
│   ├── core/               # Core Pengu functionality
│   │   ├── websocket_server.py
│   │   ├── http_handler.py
│   │   └── skin_monitor.py
│   ├── communication/      # Communication layer
│   │   ├── message_handler.py
│   │   └── broadcaster.py
│   └── processing/         # Data processing
│       ├── skin_processor.py
│       ├── skin_mapping.py
│       └── flow_controller.py
│
├── state/                  # Shared application state
│   └── core/
│       ├── shared_state.py
│       └── app_status.py
│
├── launcher/               # Application launcher and updater
│   ├── core/
│   │   └── launcher.py
│   ├── sequences/          # Launch sequences
│   │   ├── hash_check_sequence.py
│   │   └── skin_sync_sequence.py
│   ├── update/             # Update system
│   │   ├── update_sequence.py
│   │   ├── update_downloader.py
│   │   ├── update_installer.py
│   │   └── github_client.py
│   ├── ui/
│   │   └── update_dialog.py
│   └── updater.py
│
├── party/                  # Party mode (skin sharing)
│   ├── core/               # Party orchestration
│   │   ├── party_manager.py  # Main party mode orchestrator
│   │   └── party_state.py
│   ├── network/            # Networking layer
│   │   ├── ws_relay.py     # WebSocket relay client
│   │   ├── peer_connection.py
│   │   ├── stun_client.py
│   │   └── udp_transport.py
│   ├── protocol/           # Wire protocol
│   │   ├── crypto.py       # XOR cipher with dynamic keys
│   │   ├── message_types.py
│   │   └── token_codec.py
│   ├── discovery/          # Lobby and skin discovery
│   │   ├── lobby_matcher.py
│   │   └── skin_collector.py
│   └── integration/        # UI and injection hooks
│       ├── injection_hook.py
│       └── ui_bridge.py
│
├── relay-worker/           # Cloudflare Worker — party relay
│   ├── src/
│   │   ├── index.ts        # Worker entry point
│   │   └── room.ts         # Durable Object party room
│   └── wrangler.toml
│
├── skin-key-worker/        # Cloudflare Worker — skin key server
│   ├── src/
│   │   └── index.ts
│   └── wrangler.toml
│
├── analytics/              # Analytics and user tracking
│   └── core/
│       ├── machine_id.py   # Machine ID retrieval (Windows Machine GUID)
│       ├── analytics_client.py  # HTTP client for analytics pings
│       └── analytics_thread.py  # Background thread for periodic pings
│
└── Pengu Loader/           # Pengu Loader and plugins
    ├── Pengu Loader.exe    # Pengu Loader executable
    └── plugins/            # JavaScript plugins
        ├── ROSE-UI/
        ├── ROSE-SkinMonitor/
        ├── ROSE-ChromaWheel/
        ├── ROSE-FormsWheel/
        ├── ROSE-CustomWheel/
        ├── ROSE-SettingsPanel/
        ├── ROSE-RandomSkin/
        ├── ROSE-HistoricMode/
        ├── ROSE-PartyMode/
        └── ROSE-Jade/
```
