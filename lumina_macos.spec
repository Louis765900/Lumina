# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for macOS — produces dist/Lumina.app."""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None
APP_NAME = "Lumina"
APP_VERSION = "1.1.0"

# Native helper (Rust, no .exe suffix on POSIX). Optional: only embed when built.
_extra_binaries = []
_rust_bin = "native/lumina_scan/target/release/lumina_scan"
if os.path.exists(_rust_bin):
    _extra_binaries.append((_rust_bin, "native/lumina_scan"))

_extra_datas = [("app/ui/styles.qss", "app/ui")]

# Plugin carvers discovered via pkgutil.iter_modules at runtime.
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

# Two-step bundle: EXE (without binaries) → COLLECT → BUNDLE.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # upx routinely breaks codesign on macOS
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,     # default to host arch; pass --target-arch=universal2 to cover both
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/lumina.icns" if os.path.exists("assets/lumina.icns") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon="assets/lumina.icns" if os.path.exists("assets/lumina.icns") else None,
    bundle_identifier="com.lumina.recovery",
    version=APP_VERSION,
    info_plist={
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": "com.lumina.recovery",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,  # honour macOS dark mode
        "LSMinimumSystemVersion": "10.13",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHumanReadableCopyright": "Lumina Data Recovery",
    },
)
