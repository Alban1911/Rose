# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for LeagueUnlocked
Builds a standalone executable with EasyOCR support
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from pathlib import Path

block_cipher = None

# Collect all data files for packages that need them
datas = []

# Icons and assets - verify they exist
import os
icon_files = [
    ('icon.ico', '.'),
    ('icon.png', '.'),
    ('champ-select-flyout-background.jpg', '.'),
]

# Verify individual icon files
for src, dst in icon_files:
    if os.path.exists(src):
        datas += [(src, dst)]
    else:
        print(f"[WARNING] Missing: {src}")

# Verify and add icons directory
if os.path.exists('icons') and os.path.isdir('icons'):
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
    if os.path.exists(tool):
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
    if os.path.exists(tool):
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
if os.path.exists('injection/mods_map.json'):
    datas += [('injection/mods_map.json', 'injection')]
else:
    print("[WARNING] injection/mods_map.json not found")

# Collect EasyOCR data files (character files, configs, etc.)
try:
    easyocr_datas = collect_data_files('easyocr')
    datas += easyocr_datas
    print(f"[OK] Collected {len(easyocr_datas)} EasyOCR data files")
except Exception as e:
    print(f"Warning: Could not collect EasyOCR data files: {e}")

# Collect PyTorch data files
try:
    torch_datas = collect_data_files('torch')
    datas += torch_datas
    print(f"[OK] Collected {len(torch_datas)} PyTorch data files")
except Exception as e:
    print(f"Warning: Could not collect PyTorch data files: {e}")

# Hidden imports - modules PyInstaller might not detect
hiddenimports = [
    # Core app modules
    'database',
    'database.name_db',
    'injection',
    'injection.injector',
    'injection.manager',
    'lcu',
    'lcu.client',
    'lcu.skin_scraper',
    'lcu.types',
    'lcu.utils',
    'ocr',
    'ocr.backend',
    'ocr.image_processing',
    'state',
    'state.app_status',
    'state.shared_state',
    'threads',
    'threads.champ_thread',
    'threads.lcu_monitor_thread',
    'threads.loadout_ticker',
    'threads.ocr_thread',
    'threads.phase_thread',
    'threads.websocket_thread',
    'utils',
    'utils.admin_utils',
    'utils.chroma_base',
    'utils.chroma_button',
    'utils.chroma_click_catcher',
    'utils.chroma_panel',
    'utils.chroma_panel_widget',
    'utils.chroma_preview_manager',
    'utils.chroma_scaling',
    'utils.chroma_selector',
    'utils.config_hot_reload',
    'utils.logging',
    'utils.normalization',
    'utils.paths',
    'utils.preview_repo_downloader',
    'utils.repo_downloader',
    'utils.skin_downloader',
    'utils.smart_skin_downloader',
    'utils.thread_manager',
    'utils.tray_manager',
    'utils.validation',
    'utils.window_utils',
    
    # EasyOCR and all its submodules
    'easyocr',
    'easyocr.config',
    'easyocr.craft',
    'easyocr.craft_utils',
    'easyocr.detection',
    'easyocr.detection_db',
    'easyocr.easyocr',
    'easyocr.recognition',
    'easyocr.utils',
    'easyocr.imgproc',
    'easyocr.model',
    'easyocr.model.model',
    'easyocr.model.modules',
    'easyocr.model.vgg_model',
    
    # PyTorch
    'torch',
    'torch._C',
    'torch.nn',
    'torch.nn.functional',
    'torchvision',
    'torchvision.models',
    
    # PyQt6
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    
    # Computer vision
    'cv2',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    
    # Scientific computing
    'numpy',
    'scipy',
    'scipy.ndimage',
    'scipy.stats',
    
    # Networking
    'requests',
    'urllib3',
    'websocket',
    'websocket_client',
    
    # System tray
    'pystray',
    'pystray._win32',
    
    # Other dependencies
    'psutil',
    'yaml',
    'packaging',
]

# Collect all submodules for complex packages
try:
    hiddenimports += collect_submodules('easyocr')
    print("[OK] Collected EasyOCR submodules")
except Exception as e:
    print(f"Warning: Could not collect EasyOCR submodules: {e}")

try:
    hiddenimports += collect_submodules('torch')
    print("[OK] Collected PyTorch submodules")
except Exception as e:
    print(f"Warning: Could not collect PyTorch submodules: {e}")

# Exclusions - modules we don't need (reduces size and build time)
excludes = [
    'tkinter',
    'matplotlib',
    'pytest',
    'setuptools',
    'pip',
    'wheel',
    'distutils',
    'PyQt5',  # Exclude PyQt5 to avoid conflict with PyQt6
    'PySide2',
    'PySide6',
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
    icon='icon.ico',
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

