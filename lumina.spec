# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

_no_upx = os.environ.get('LUMINA_NO_UPX') == '1'
_rust_helper = 'native/lumina_scan/target/release/lumina_scan.exe'
if not os.path.exists(_rust_helper):
    raise SystemExit(
        'Rust helper missing. Run `python scripts/build.py` so cargo builds lumina_scan.exe first.'
    )
_extra_binaries = [(_rust_helper, 'native/lumina_scan')]

_extra_datas = [('app/ui/styles.qss', 'app/ui')]

# Plugin carvers are discovered via pkgutil.iter_modules at runtime.
# PyInstaller needs both explicit hiddenimports AND the .py source files on disk
# so iter_modules() can still enumerate them inside the frozen bundle.
_plugin_hiddenimports = collect_submodules('app.plugins')
_module_hiddenimports = collect_submodules('app.modules')
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
    ] + _plugin_hiddenimports + _module_hiddenimports,
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
    upx=not _no_upx,
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
