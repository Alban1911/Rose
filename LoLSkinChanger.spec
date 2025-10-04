# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.'), ('requirements.txt', '.'), ('dependencies', 'dependencies'), ('database', 'database'), ('injection', 'injection'), ('lcu', 'lcu'), ('ocr', 'ocr'), ('state', 'state'), ('threads', 'threads'), ('utils', 'utils')],
    hiddenimports=['numpy', 'cv2', 'psutil', 'requests', 'rapidfuzz', 'websocket', 'mss', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'tesserocr', 'Pillow'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['injection.overlay', 'injection.mods', 'injection.incoming_zips', 'state.overlay', 'state.mods', 'state.last_hovered_skin'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LoLSkinChanger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LoLSkinChanger',
)
