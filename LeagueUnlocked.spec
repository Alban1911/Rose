# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for LeagueUnlocked
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

# Verify and add icons directory
if Path('icons').exists() and Path('icons').is_dir():
    icon_dir_files = os.listdir('icons')
    if icon_dir_files:
        datas += [('icons', 'icons')]
        print(f"[OK] Icons directory found with {len(icon_dir_files)} files: {', '.join(icon_dir_files)}")
    else:
        print("[WARNING] Icons directory is empty")
else:
    print("[WARNING] Icons directory not found")

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

# uiautomation removed - using custom uia module instead

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
    'ui.chroma_base',
    'ui.chroma_button',
    'ui.chroma_click_catcher',
    'ui.click_blocker',
    'ui.click_catcher',
    'ui.click_catcher_hide',
    'ui.click_catcher_show',
    'ui.chroma_panel',
    'ui.chroma_panel_widget',
    'ui.chroma_preview_manager',
    'ui.chroma_scaling',
    'ui.chroma_selector',
    'ui.chroma_ui',
    'ui.dice_button',
    'ui.random_flag',
    'ui.unowned_frame',
    'ui.user_interface',
    'ui.z_order_manager',
    'uia',
    'uia.connection',
    'uia.debug',
    'uia.detector',
    'uia.ui_thread',
    'utils.license_client',
    'utils.logging',
    'utils.normalization',
    'utils.paths',
    'utils.repo_downloader',
    'utils.skin_downloader',
    'utils.smart_skin_downloader',
    'utils.thread_manager',
    'utils.tray_manager',
    'utils.utilities',
    'utils.validation',
    'utils.window_utils',
    
    # PyQt6
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    
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
    
    # License dialogs (PyQt6 only)
    'utils.license_dialog',
    
    # Other dependencies
    'psutil',
    'pywinauto',
]

# Exclusions - modules we don't need (reduces size and build time)
excludes = [
    # 'tkinter',  # REMOVED - needed for license dialog
    'matplotlib',
    'pytest',
    'setuptools',
    'pip',
    'wheel',
    'distutils',
    'PyQt5',  # Exclude PyQt5 to avoid conflict with PyQt6
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
    name='LeagueUnlocked',
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
    name='LeagueUnlocked',
)

