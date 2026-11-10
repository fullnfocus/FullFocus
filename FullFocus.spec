# -*- mode: python ; coding: utf-8 -*-
# build: pyinstaller FullFocus.spec
import os

ICON = os.path.join(SPECPATH, 'icon.ico')


a = Analysis(
    ['full_focus.py'],
    pathex=[],
    binaries=[],
    datas=[(ICON, '.')],  # so the tray icon works from the single .exe
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FullFocus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[ICON],
)
