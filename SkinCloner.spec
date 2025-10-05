# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.'), ('requirements.txt', '.'), ('dependencies', 'dependencies'), ('database', 'database'), ('injection', 'injection'), ('lcu', 'lcu'), ('ocr', 'ocr'), ('state', 'state'), ('threads', 'threads'), ('utils', 'utils')],
    hiddenimports=['numpy', 'cv2', 'psutil', 'requests', 'rapidfuzz', 'websocket', 'mss', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'PIL.ImageDraw', 'PIL.ImageFont', 'PIL.ImageOps', 'PIL.ImageFilter', 'PIL.ImageEnhance', 'PIL.ImageColor', 'PIL.ImageFile', 'PIL.ImageSequence', 'PIL.ImageStat', 'PIL.ImageTransform', 'PIL.ImageWin', 'PIL.ImageGrab', 'PIL.ImageMorph', 'PIL.ImagePalette', 'PIL.ImagePath', 'PIL.ImageQt', 'PIL.ImageShow', 'PIL.ImageMath', 'PIL.ImageMode', 'PIL.ImageChops', 'PIL.ImageCms', 'tesserocr', 'Pillow', 'pystray', 'pystray._base', 'pystray._win32', 'pystray._darwin', 'pystray._gtk', 'pystray._xorg', 'pystray._util', 'logging.handlers'],
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
    name='SkinCloner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    name='SkinCloner',
)
