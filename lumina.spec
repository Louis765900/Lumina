# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

# Only include DLL/env if they exist
_extra_binaries = []
if os.path.exists('app/core/lumina_engine.dll'):
    _extra_binaries.append(('app/core/lumina_engine.dll', 'app/core'))

_extra_datas = [('app/ui/styles.qss', 'app/ui')]
if os.path.exists('.env'):
    _extra_datas.append(('.env', '.'))

a = Analysis(
    ['main.py'],
    pathex=[os.path.abspath('.')],
    binaries=_extra_binaries,
    datas=_extra_datas,
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtNetwork',
        'PyQt6.sip',
        'psutil',
        'wmi',
        'win32api',
        'win32con',
        'win32file',
        'pywintypes',
        'PIL',
        'PIL.Image',
        'PIL.ImageQt',
        'dotenv',
        'google.generativeai',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'scipy',
        'pandas', 'IPython', 'jupyter', 'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Lumina',
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
    icon='lumina.ico',
    uac_admin=True,
)
