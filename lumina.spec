# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Only include native helper if it exists (built via `cargo build --release`)
_extra_binaries = []
if os.path.exists('native/lumina_scan/target/release/lumina_scan.exe'):
    _extra_binaries.append((
        'native/lumina_scan/target/release/lumina_scan.exe',
        'native/lumina_scan',
    ))

_extra_datas = [('app/ui/styles.qss', 'app/ui')]
if os.path.exists('.env'):
    _extra_datas.append(('.env', '.'))

# Plugin carvers are discovered via pkgutil.iter_modules at runtime.
# PyInstaller needs both explicit hiddenimports AND the .py source files on disk
# so iter_modules() can still enumerate them inside the frozen bundle.
_plugin_hiddenimports = collect_submodules('app.plugins')
_plugin_datas = collect_data_files(
    'app.plugins.carvers',
    include_py_files=True,
)
_extra_datas.extend(_plugin_datas)

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
    ] + _plugin_hiddenimports,
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
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='lumina.ico',
    uac_admin=True,
)
