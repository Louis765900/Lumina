#!/usr/bin/env python3
"""
Build Lumina for the host platform.

Usage::

    python scripts/build.py                 # install deps, build Rust, test, package
    python scripts/build.py --skip-rust     # reuse an existing Rust helper
    python scripts/build.py --skip-install  # assume Python deps are already installed
    python scripts/build.py --skip-tests    # package without running pytest
    python scripts/build.py --debug         # cargo build without --release
    python scripts/build.py --no-upx        # disable upx for PyInstaller

Selects the correct PyInstaller spec based on ``platform.system()``.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LUMINA_RUNNING_MESSAGE = (
    "Lumina.exe est en cours d'exécution. Fermez Lumina avant de reconstruire."
)


def _run(cmd: list[str], **kw) -> None:
    print(f"[build] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=_ROOT, **kw)


def _install_python_deps() -> None:
    _run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    _run([sys.executable, "-m", "pip", "install", "-r", str(_ROOT / "requirements.txt")])
    _run([sys.executable, "-m", "pip", "install", "pyinstaller", "pytest", "pytest-qt"])


def _run_tests() -> None:
    _run([sys.executable, "-m", "pytest"])


def _rust_binary_path(os_name: str, release: bool) -> Path:
    profile = "release" if release else "debug"
    bin_name = "lumina_scan.exe" if os_name == "Windows" else "lumina_scan"
    return _ROOT / "native" / "lumina_scan" / "target" / profile / bin_name


def _build_rust(release: bool) -> Path:
    """Build the Rust helper and return the expected binary path."""
    rust_dir = _ROOT / "native" / "lumina_scan"
    if not rust_dir.exists():
        raise SystemExit(f"[build] native helper not found at {rust_dir}")

    if shutil.which("cargo") is None:
        raise SystemExit(
            "[build] cargo not on PATH - install Rust toolchain "
            "(https://rustup.rs) before building."
        )

    cmd = ["cargo", "build"]
    if release:
        cmd.append("--release")
    subprocess.run(cmd, check=True, cwd=rust_dir)

    binary = _rust_binary_path(platform.system(), release)
    if not binary.exists():
        raise SystemExit(f"[build] expected {binary} after cargo build, got nothing")
    return binary


def _spec_for(os_name: str) -> str:
    if os_name == "Windows":
        return "lumina.spec"
    if os_name == "Darwin":
        return "lumina_macos.spec"
    if os_name == "Linux":
        return "lumina_linux.spec"
    raise SystemExit(f"[build] unsupported OS: {os_name}")


def _artifact_for(os_name: str) -> Path:
    if os_name == "Windows":
        return _ROOT / "dist" / "Lumina.exe"
    if os_name == "Darwin":
        return _ROOT / "dist" / "Lumina.app"
    if os_name == "Linux":
        return _ROOT / "dist" / "lumina" / "lumina"
    raise SystemExit(f"[build] unsupported OS: {os_name}")


def _lumina_process_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Lumina.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            encoding="utf-8",
            errors="replace",
            text=True,
        )
    except OSError:
        return False
    return "Lumina.exe" in result.stdout


def _windows_file_locked(path: Path) -> bool:
    if not path.exists():
        return False

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE

    handle = create_file(
        str(path),
        0x80000000,  # GENERIC_READ
        0,  # exclusive access: fail if the existing exe is mapped/running
        None,
        3,  # OPEN_EXISTING
        0x80,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        return True

    kernel32.CloseHandle(handle)
    return False


def _assert_artifact_rebuildable(os_name: str) -> None:
    if os_name != "Windows":
        return

    artifact = _artifact_for(os_name)
    if _lumina_process_running() or _windows_file_locked(artifact):
        raise SystemExit(f"[build] {_LUMINA_RUNNING_MESSAGE}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Lumina for the host OS.")
    parser.add_argument(
        "--skip-rust", action="store_true", help="skip cargo build; reuse existing binary"
    )
    parser.add_argument("--skip-install", action="store_true", help="do not install Python deps")
    parser.add_argument("--skip-tests", action="store_true", help="do not run pytest before build")
    parser.add_argument("--debug", action="store_true", help="build Rust helper without --release")
    parser.add_argument("--no-upx", action="store_true", help="disable upx during PyInstaller pass")
    args = parser.parse_args()

    os_name = platform.system()
    release = not args.debug
    print(f"[build] target: {os_name} ({platform.machine()})")

    if args.skip_install:
        print("[build] --skip-install set, assuming Python deps are ready")
    else:
        _install_python_deps()

    if args.skip_rust:
        binary = _rust_binary_path(os_name, release)
        if not binary.exists():
            raise SystemExit(f"[build] --skip-rust set but required helper is missing: {binary}")
        print(f"[build] --skip-rust set, using existing helper: {binary}")
    else:
        binary = _build_rust(release=release)
        print(f"[build] Rust helper: {binary}")

    if args.skip_tests:
        print("[build] --skip-tests set, packaging without running pytest")
    else:
        _run_tests()

    _assert_artifact_rebuildable(os_name)

    spec_path = _ROOT / _spec_for(os_name)
    if not spec_path.exists():
        raise SystemExit(f"[build] spec missing: {spec_path}")

    pi_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(spec_path),
        "--noconfirm",
        "--distpath",
        str(_ROOT / "dist"),
    ]
    pyinstaller_env = None
    if args.no_upx:
        pyinstaller_env = os.environ.copy()
        pyinstaller_env["LUMINA_NO_UPX"] = "1"
    _run(pi_cmd, env=pyinstaller_env)

    artifact = _artifact_for(os_name)
    if not artifact.exists():
        raise SystemExit(f"[build] expected artifact missing after PyInstaller: {artifact}")

    print()
    if os_name == "Windows":
        print(f"[done] dist/Lumina.exe ({artifact.stat().st_size} bytes)")
    elif os_name == "Darwin":
        print("[done] dist/Lumina.app")
        print("[hint] Optional ad-hoc codesign: codesign --deep -s - dist/Lumina.app")
    elif os_name == "Linux":
        print("[done] dist/lumina/")
        print("[hint] Install system-wide: sudo bash scripts/install_linux.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
