#!/usr/bin/env python3
"""
Build Lumina for the host platform.

Usage::

    python scripts/build.py                 # release build, includes Rust
    python scripts/build.py --skip-rust     # skip cargo build (use existing binary)
    python scripts/build.py --debug         # cargo build without --release
    python scripts/build.py --no-upx        # disable upx (passed through to PyInstaller)

Selects the correct PyInstaller spec based on ``platform.system()``.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], **kw) -> None:
    print(f"[build] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=_ROOT, **kw)


def _build_rust(release: bool) -> Path:
    """Build the Rust helper. Returns the binary path."""
    rust_dir = _ROOT / "native" / "lumina_scan"
    if not rust_dir.exists():
        raise SystemExit(f"[build] native helper not found at {rust_dir}")

    if shutil.which("cargo") is None:
        raise SystemExit(
            "[build] cargo not on PATH — install Rust toolchain "
            "(https://rustup.rs) before building."
        )

    cmd = ["cargo", "build"]
    if release:
        cmd.append("--release")
    subprocess.run(cmd, check=True, cwd=rust_dir)

    profile = "release" if release else "debug"
    bin_name = "lumina_scan.exe" if platform.system() == "Windows" else "lumina_scan"
    binary = rust_dir / "target" / profile / bin_name
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Lumina for the host OS.")
    parser.add_argument(
        "--skip-rust", action="store_true", help="skip cargo build; reuse existing binary if any"
    )
    parser.add_argument("--debug", action="store_true", help="build Rust helper without --release")
    parser.add_argument("--no-upx", action="store_true", help="disable upx during PyInstaller pass")
    args = parser.parse_args()

    os_name = platform.system()
    print(f"[build] target: {os_name} ({platform.machine()})")

    if not args.skip_rust:
        binary = _build_rust(release=not args.debug)
        print(f"[build] Rust helper: {binary}")
    else:
        print("[build] --skip-rust set, leaving native binary as-is")

    spec = _spec_for(os_name)
    spec_path = _ROOT / spec
    if not spec_path.exists():
        raise SystemExit(f"[build] spec missing: {spec_path}")

    if shutil.which("pyinstaller") is None:
        raise SystemExit(
            "[build] pyinstaller not on PATH — install with `pip install pyinstaller`."
        )

    pi_cmd = ["pyinstaller", str(spec_path), "--noconfirm", "--distpath", str(_ROOT / "dist")]
    if args.no_upx:
        pi_cmd.append("--noupx")
    _run(pi_cmd)

    dist = _ROOT / "dist"
    print()
    if os_name == "Windows":
        print(f"[done] dist/Lumina.exe ({(dist / 'Lumina.exe').exists()})")
    elif os_name == "Darwin":
        print(f"[done] dist/Lumina.app ({(dist / 'Lumina.app').exists()})")
        print("[hint] Optional ad-hoc codesign: codesign --deep -s - dist/Lumina.app")
    elif os_name == "Linux":
        print(f"[done] dist/lumina/ ({(dist / 'lumina').exists()})")
        print("[hint] Install system-wide: sudo bash scripts/install_linux.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
