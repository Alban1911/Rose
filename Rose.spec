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

# Data files (batch scripts, etc.)
injection_data_files = [
    'injection/tools/wad-extract-multi.bat',
    'injection/tools/wad-make-multi.bat',
    'injection/tools/wxy-extract-multi.bat',
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
    # Core app modules
    'injection',
    'injection.injector',
    'injection.manager',
    'lcu',
    'lcu.client',
    'lcu.skin_scraper',
    'lcu.types',
    'lcu.utils',
    'pengu',
    'pengu.skin_monitor',
    'state',
    'state.app_status',
    'state.shared_state',
    'threads',
    'threads.champ_thread',
    'threads.lcu_monitor_thread',
    'threads.loadout_ticker',
    'threads.phase_thread',
    'threads.websocket_thread',
    'utils',
    'utils.admin_utils',
    'utils.pengu_loader',
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
    'utils.logging',
    'utils.normalization',
    'utils.paths',
    'utils.repo_downloader',
    'utils.skin_downloader',
    'utils.smart_skin_downloader',
    'utils.thread_manager',
    'utils.tray_manager',
    'utils.utilities',
    'utils.historic',
    'utils.validation',
    'utils.window_utils',
    
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
    
    # Native dialogs and settings
    'utils.tray_settings',
    'utils.win32_base',
    
    # Other dependencies
    'psutil',
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
