# Contributing to Rose

Contributions are welcome! Report bugs or suggest features through the [issue forms](https://github.com/Alban1911/Rose/issues/new/choose), submit pull requests, or join our [Discord](https://discord.com/invite/roseskins) for discussions and installation help.

## Reporting bugs

Use the **Bug report** form. Besides your Rose version, League patch, client,
region and game mode, it asks for the message shown in Rose's Troubleshooting
panel and the latest log file from **Open Logs Folder**. Remove party tokens,
account identifiers and personal paths before posting. For ideas, use the
**Feature request** form.

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

# Create a feature branch (e.g. feat/skin-preview, fix/chroma-crash, docs/readme)
git checkout -b feat/your-feature-name

# Install all dependencies
pip install -r requirements.txt

# Ready to develop! Run main.py as administrator when testing
```

## Building locally

Rose builds the Pengu Loader executable from the vendored source in
`vendor/PenguLoader-1.1.6/` during packaging. A prebuilt `Pengu Loader.exe`
is intentionally not committed to the repository.

In addition to Python 3.11+ and the Python dependencies above, install Visual
Studio Build Tools with the .NET desktop build tools, WPF support, and the
.NET Framework 4.7.2 targeting pack (for Pengu Loader), and the MSVC C++ build
tools (for Rose's stand-in `cslol-dll.dll`, built from `native/cslol_stub/`).
Install Inno Setup 6 only if you also want to build the Windows installer.

```powershell
# Build Pengu Loader only
python scripts/build_pengu_loader.py

# Build Rose (rebuilds Pengu Loader and the cslol-dll.dll stand-in)
python scripts/build_pyinstaller.py

# Build Rose and the Windows installer (installer/Rose_Setup_<version>.exe)
python scripts/build_all.py

# Zip dist/Rose into the auto-updater's package (installer/update_package_<version>.zip)
python scripts/create_update_package.py
```

To test Rose itself, you also need the LTK patcher (`ltk_patcher_host.exe`
and `ltk_patcher_dll.dll` from an LTK Manager install) in `injection/tools/`.

`scripts/build_pyinstaller.py` is the canonical Rose package build entry point; it
compiles the loader before invoking PyInstaller. Use it or `scripts/build_all.py`
instead of invoking `pyinstaller Rose.spec` directly.

## Tests and checks

CI runs these on every push to `main` and every pull request; run them before
opening one. The Python tests need Windows, since several modules call
`ctypes.windll` when imported.

```powershell
# Unit tests: test/ and every package's tests/ folder
$suites = @('test') + (Get-ChildItem -Directory | ForEach-Object { Join-Path $_.Name 'tests' } | Where-Object { Test-Path $_ })
foreach ($suite in $suites) { python -m unittest discover -s $suite -t . }

# Lint limited to syntax errors and undefined names
pip install ruff
python -m ruff check . --select E9,F63,F7,F82

# Plugin syntax (needs Node.js): a broken plugin otherwise just fails to load in the client
git ls-files 'Pengu Loader/plugins/*.js' | ForEach-Object { node --check $_ }
```

Add tests to the `tests/` folder of the package they cover (with an
`__init__.py`); CI picks up a new package's `tests/` folder by itself. CI also
lints the workflows in `.github/` (actionlint, zizmor) and reviews dependency
changes on pull requests.

## Pull requests

- Branch off `main`, with a name like the ones in the setup above
- Write commit messages as `type(scope): summary`, like the history
  (`fix(party): ...`, `feat(mods): ...`)
- Keep a pull request to one change, and make sure CI passes

## Writing plugins

`ROSE-SkinMonitor` hosts the WebSocket bridge to Rose and exposes it as
`window.__roseBridge` once the bridge port is known; other plugins wait for
that object to appear. It offers `send(payload)`, `subscribe(type, cb)` /
`unsubscribe(type, cb)` for messages from Rose, `onReady(cb)`, and
`onDisconnect(cb)`, which runs when an open connection to Rose closes (not on
each failed reconnect), so a plugin waiting on an answer can give up.

## Translations

Rose's menus are translated in `Pengu Loader/plugins/ROSE-I18n/locales/`, one
`<language>.json` per language, keyed by the English text. English is the
fallback, so a missing text shows in English. Both the plugins and the Python
side (`utils/core/i18n.py`) read these files.

## Project Structure

```
Rose/
├── main.py                 # Application entry point
├── config.py               # Configuration constants
├── requirements.txt        # Python dependencies
├── assets/                 # Application assets (icons, fonts, images)
├── test/                   # Cross-package tests (each package also has its own tests/)
├── .github/                # CI workflow and issue forms
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
│   ├── classic.py          # Rift Classic skins
│   ├── core/               # Core injection logic
│   │   ├── manager.py      # Injection manager & coordination
│   │   └── injector.py     # Skin injector
│   ├── game/               # Game detection and monitoring
│   │   ├── game_detector.py
│   │   └── game_monitor.py
│   ├── config/             # Configuration management
│   │   ├── config_manager.py
│   │   ├── threshold_manager.py
│   │   └── base_skin_tracker.py
│   ├── mods/               # Mod management
│   │   ├── mod_manager.py
│   │   ├── storage.py      # Custom mods storage
│   │   └── zip_resolver.py
│   ├── overlay/            # Overlay process management
│   │   ├── overlay_manager.py
│   │   └── process_manager.py
│   ├── loadingname/        # Skin name on the loading screen
│   │   └── loading_name.py
│   └── tools/              # Injection tools (mod-tools.exe, the user's LTK patcher)
│       ├── tools_manager.py
│       └── patcher.py      # LTK patcher checks (missing files, end of life)
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
│   │   ├── champ_select_reset.py
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
│   │   ├── safe_extract.py
│   │   ├── atomic_file.py
│   │   ├── i18n.py         # Interface language
│   │   ├── modpkg.py       # .modpkg custom mods
│   │   └── security.py
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
│   │   ├── party_state.py
│   │   └── party_storage.py
│   ├── network/            # Networking layer
│   │   ├── ws_relay.py     # WebSocket relay client
│   │   ├── peer_connection.py
│   │   ├── stun_client.py
│   │   └── udp_transport.py
│   ├── protocol/           # Wire protocol
│   │   ├── message_types.py
│   │   └── token_codec.py
│   ├── discovery/          # Lobby and skin discovery
│   │   ├── lobby_matcher.py
│   │   ├── skin_collector.py
│   │   └── custom_mods.py  # Custom mod hashes shared with friends
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
├── analytics/              # Analytics and user tracking
│   └── core/
│       ├── install_id.py   # Pseudonymous persistent installation UUID
│       ├── machine_id.py   # Old name of install_id, kept for compatibility
│       ├── analytics_client.py  # HTTP client for analytics and presence pings
│       └── analytics_thread.py  # Background thread for startup/heartbeat/close pings
│
├── scripts/                # Build scripts (loader, stand-in DLL, PyInstaller, installer, update package)
├── native/cslol_stub/      # Source of Rose's stand-in cslol-dll.dll
├── vendor/PenguLoader-1.1.6/  # Pengu Loader source, built with Rose
│
└── Pengu Loader/           # Runtime loader files and plugins
    ├── Pengu Loader.exe    # Generated during builds from vendor/PenguLoader-1.1.6
    ├── core.dll            # Pengu Loader's hook, loaded into the League client
    └── plugins/            # JavaScript plugins
        ├── ROSE-UI/
        ├── ROSE-SkinMonitor/
        ├── ROSE-ChromaWheel/
        ├── ROSE-FormsWheel/
        ├── ROSE-CustomSkinSelector/
        ├── ROSE-CustomWheel/
        ├── ROSE-SettingsPanel/
        ├── ROSE-RandomSkin/
        ├── ROSE-HistoricMode/
        ├── ROSE-PartyMode/
        ├── ROSE-I18n/      # Translations (locales/<language>.json)
        └── ROSE-Jade/      # Shipped disabled (index.js_)
```

## Credits

Rose uses the [official Pengu Loader](https://github.com/PenguLoader/PenguLoader)
project. Its source is vendored and built as part of Rose, with Rose-specific
lifecycle integration added around the loader. See the
[official Pengu Loader license](https://github.com/PenguLoader/PenguLoader/blob/main/LICENSE).
