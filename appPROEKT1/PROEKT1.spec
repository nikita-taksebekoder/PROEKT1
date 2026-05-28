# -*- mode: python ; coding: utf-8 -*-
import glob

_app_dlls   = [(f, '.') for f in glob.glob('*.dll')]
_pawnio     = [('PawnIO.sys', '.'), ('PawnIO.cat', '.'), ('pawnio.inf', '.'), ('PawnIO_setup.exe', '.')]

a = Analysis(
    ['PROEKT1.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('../appDESIGN/design-preview.html', 'appDESIGN'),
        ('theme.qss', '.'),
        ('config.json', '.'),
        ('curves.json', '.'),
    ] + _app_dlls + _pawnio,
    hiddenimports=[
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebChannel',
        'clr',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter', 'turtle', 'turtledemo',
        'matplotlib', 'notebook', 'IPython',
        'PIL', 'Pillow',
        'PyQt5', 'PyQt6', 'PySide2',
        'pdb', 'doctest', 'lib2to3',
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='PROEKT1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    uac_admin=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['rocket.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PROEKT1',
)
