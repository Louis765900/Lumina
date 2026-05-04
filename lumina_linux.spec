# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Linux — produces dist/lumina/ (one-folder bundle)."""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None
APP_NAME = "lumina"

_extra_binaries = []
_rust_bin = "native/lumina_scan/target/release/lumina_scan"
if os.path.exists(_rust_bin):
    _extra_binaries.append((_rust_bin, "native/lumina_scan"))

_extra_datas = [("app/ui/styles.qss", "app/ui")]
_plugin_hiddenimports = collect_submodules("app.plugins")
_plugin_datas = collect_data_files("app.plugins.carvers", include_py_files=True)
_extra_datas.extend(_plugin_datas)

a = Analysis(
    ["main.py"],
    pathex=[os.path.abspath(".")],
    binaries=_extra_binaries,
    datas=_extra_datas,
    hiddenimports=[
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.QtNetwork",
        "PyQt6.sip",
        "psutil",
        "app.core.dedup",
        "app.core.fs_parser",
        "app.core.platform",
        "app.core.native.client",
        "app.core.repair.jpeg_repair",
        "app.core.repair.mp4_repair",
        "app.cli.main",
    ] + _plugin_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy", "scipy",
        "pandas", "IPython", "jupyter", "notebook",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# One-folder bundle: faster startup than --onefile, simpler to package as
# tarball or AppImage downstream. Console=False keeps the GUI launchable
# from a desktop entry without a stray terminal window; the CLI is shipped
# separately via the `lumina` console script entry point.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
