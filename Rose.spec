# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Rose
Builds a standalone executable with Windows UI API support
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from pathlib import Path

block_cipher = None

# Collect all data files for packages that need them
datas = []

# Assets folder - verify and add entire directory
import os
if Path('assets').exists() and Path('assets').is_dir():
    asset_files = os.listdir('assets')
    if asset_files:
        # Add entire assets folder (preserves directory structure)
        datas += [('assets', 'assets')]
        print(f"[OK] Assets directory found with {len(asset_files)} files: {', '.join(asset_files)}")
    else:
        print("[WARNING] Assets directory is empty")
else:
    print("[WARNING] Assets directory not found")

# Icons have been moved to assets folder, no separate icons directory needed

# Injection tools - separate binaries (.exe, .dll) from data files (.bat)
import os

# Binary files (executables and DLLs) - these go in binaries, not datas
injection_binaries = [
    'injection/tools/mod-tools.exe',
    'injection/tools/cslol-diag.exe',
    'injection/tools/cslol-dll.dll',
    'injection/tools/wad-extract.exe',
    'injection/tools/wad-make.exe',
]

# Data files (batch scripts, text files, etc.)
injection_data_files = [
    'injection/tools/wad-extract-multi.bat',
    'injection/tools/wad-make-multi.bat',
    'injection/tools/wxy-extract-multi.bat',
    'injection/tools/hashes.game.txt',
]

# Verify and add injection binaries
binaries = []
missing_binaries = []
for tool in injection_binaries:
    if Path(tool).exists():
        binaries.append((tool, 'injection/tools'))
    else:
        missing_binaries.append(tool)

if missing_binaries:
    print(f"[WARNING] Missing injection binaries:")
    for tool in missing_binaries:
        print(f"  - {tool}")
else:
    print(f"[OK] All {len(injection_binaries)} injection binaries found")

# Verify and add injection data files
missing_data = []
for tool in injection_data_files:
    if Path(tool).exists():
        datas += [(tool, 'injection/tools')]
    else:
        missing_data.append(tool)

if missing_data:
    print(f"[WARNING] Missing injection data files:")
    for tool in missing_data:
        print(f"  - {tool}")
else:
    print(f"[OK] All {len(injection_data_files)} injection data files found")

# Add mods_map.json
if Path('injection/mods_map.json').exists():
    datas += [('injection/mods_map.json', 'injection')]
else:
    print("[WARNING] injection/mods_map.json not found")

# Include Pengu Loader directory (for Pengu activation/deactivation CLI)
pengu_loader_dir = Path('Pengu Loader')
if pengu_loader_dir.exists() and pengu_loader_dir.is_dir():
    datas += [(str(pengu_loader_dir), 'Pengu Loader')]
    contained = ", ".join(os.listdir(pengu_loader_dir)) or "<empty>"
    print(f"[OK] Pengu Loader directory bundled ({contained})")
else:
    print("[WARNING] Pengu Loader directory not found – Pengu features will be disabled")

# Hidden imports - modules PyInstaller might not detect
hiddenimports = [
    # Main package modules
    'main',
    'main.setup',
    'main.setup.console',
    'main.setup.arguments',
    'main.setup.initialization',
    'main.core',
    'main.core.state',
    'main.core.lockfile',
    'main.core.signals',
    'main.core.initialization',
    'main.core.threads',
    'main.core.lcu_handler',
    'main.core.cleanup',
    'main.runtime',
    'main.runtime.loop',
    # Core app modules
    'injection',
    'injection.core',
    'injection.core.injector',
    'injection.core.manager',
    'injection.game',
    'injection.game.game_monitor',
    'injection.game.game_detector',
    'injection.config',
    'injection.config.config_manager',
    'injection.config.threshold_manager',
    'injection.mods',
    'injection.mods.mod_manager',
    'injection.mods.zip_resolver',
    'injection.overlay',
    'injection.overlay.overlay_manager',
    'injection.overlay.process_manager',
    'injection.tools',
    'injection.tools.tools_manager',
    'lcu',
    'lcu.core',
    'lcu.core.client',
    'lcu.core.lcu_api',
    'lcu.core.lcu_connection',
    'lcu.core.lockfile',
    'lcu.data',
    'lcu.data.skin_scraper',
    'lcu.data.skin_cache',
    'lcu.data.types',
    'lcu.data.utils',
    'lcu.features',
    'lcu.features.lcu_properties',
    'lcu.features.lcu_skin_selection',
    'lcu.features.lcu_game_mode',
    'lcu.features.lcu_swiftplay',
    'pengu',
    'pengu.core',
    'pengu.core.skin_monitor',
    'pengu.core.websocket_server',
    'pengu.core.http_handler',
    'pengu.communication',
    'pengu.communication.message_handler',
    'pengu.communication.broadcaster',
    'pengu.processing',
    'pengu.processing.skin_processor',
    'pengu.processing.skin_mapping',
    'pengu.processing.flow_controller',
    'state',
    'state.core',
    'state.core.app_status',
    'state.core.shared_state',
    'threads',
    'threads.core',
    'threads.core.phase_thread',
    'threads.core.websocket_thread',
    'threads.core.lcu_monitor_thread',
    'threads.handlers',
    'threads.handlers.champ_thread',
    'threads.handlers.champion_lock_handler',
    'threads.handlers.game_mode_detector',
    'threads.handlers.injection_trigger',
    'threads.handlers.lobby_processor',
    'threads.handlers.phase_handler',
    'threads.handlers.swiftplay_handler',
    'threads.utilities',
    'threads.utilities.loadout_ticker',
    'threads.utilities.timer_manager',
    'threads.utilities.skin_name_resolver',
    'threads.websocket',
    'threads.websocket.websocket_connection',
    'threads.websocket.websocket_event_handler',
    'utils',
    'utils.core',
    'utils.core.logging',
    'utils.core.paths',
    'utils.core.utilities',
    'utils.core.validation',
    'utils.core.normalization',
    'utils.core.historic',
    'utils.system',
    'utils.system.admin_utils',
    'utils.system.win32_base',
    'utils.system.window_utils',
    'utils.system.resolution_utils',
    'utils.download',
    'utils.download.repo_downloader',
    'utils.download.skin_downloader',
    'utils.download.smart_skin_downloader',
    'utils.download.hashes_downloader',
    'utils.download.hash_updater',
    'utils.integration',
    'utils.integration.tray_manager',
    'utils.integration.tray_settings',
    'utils.integration.pengu_loader',
    'utils.threading',
    'utils.threading.thread_manager',
    'ui',
    'ui.core',
    'ui.core.user_interface',
    'ui.core.lifecycle_manager',
    'ui.chroma',
    'ui.chroma.panel',
    'ui.chroma.preview_manager',
    'ui.chroma.selector',
    'ui.chroma.ui',
    'ui.chroma.selection_handler',
    'ui.chroma.special_cases',
    'ui.handlers',
    'ui.handlers.historic_mode_handler',
    'ui.handlers.randomization_handler',
    'ui.handlers.skin_display_handler',
    
    # Launcher module
    'launcher',
    'launcher.core',
    'launcher.core.launcher',
    'launcher.sequences',
    'launcher.sequences.hash_check_sequence',
    'launcher.sequences.skin_sync_sequence',
    'launcher.ui',
    'launcher.ui.update_dialog',
    'launcher.update',
    'launcher.update.github_client',
    'launcher.update.update_downloader',
    'launcher.update.update_installer',
    'launcher.update.update_sequence',
    'launcher.updater',
    
    # Image processing (PIL only)
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    
    # Networking
    'requests',
    'urllib3',
    'websocket',
    'websocket_client',
    
    # System tray
    'pystray',
    'pystray._win32',
    
    # Native dialogs and settings (already covered by utils.integration and utils.system above)
    
    # Other dependencies
    'psutil',
    
    # Top-level modules
    'config',
]

# Exclusions - modules we don't need (reduces size and build time)
excludes = [
    'matplotlib',
    'pytest',
    'setuptools',
    'pip',
    'wheel',
    'distutils',
    'PySide2',
    'PySide6',
    # Exclude removed packages
    'easyocr',
    'torch',
    'torchvision',
    'cv2',
    'numpy',
    'scipy',
    'mss',
    # Exclude heavy data science packages we don't use
    'pandas',
    'pyarrow',
    'statsmodels',
    'patsy',
    'tables',
    'openpyxl',
    'xlrd',
    'xlwt',
    'sqlalchemy',
    # Exclude Jupyter/notebook packages
    'IPython',
    'jupyter',
    'notebook',
    'nbformat',
    'nbconvert',
    # Exclude documentation/development tools
    'sphinx',
    'docutils',
    'jinja2',
    'pygments',
    'black',
    'mypy',
    # Exclude distributed computing packages
    'dask',
    'distributed',
    'numba',
    'llvmlite',
    # Exclude plotting packages
    'plotly',
    'bokeh',
    'panel',
    'holoviews',
    'pyviz_comms',
    'markdown',
    # Exclude cloud/AWS packages
    'botocore',
    'boto3',
    's3transfer',
]

a = Analysis(
    ['main.py'],
    pathex=[str(Path.cwd())],  # Add current directory to Python path
    binaries=binaries,  # Include injection tool executables
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Rose',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Don't use UPX (can cause issues)
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
    uac_admin=True,  # Request admin rights (required for injection)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Rose',
)
