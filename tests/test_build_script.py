from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_build_module():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("lumina_build", root / "scripts" / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_script_selects_windows_spec_and_artifact():
    build = _load_build_module()

    assert build._spec_for("Windows") == "lumina.spec"
    assert build._artifact_for("Windows").name == "Lumina.exe"


def test_build_script_expected_windows_rust_helper():
    build = _load_build_module()

    helper = build._rust_binary_path("Windows", release=True)

    assert helper.name == "lumina_scan.exe"
    assert helper.parts[-3:] == ("target", "release", "lumina_scan.exe")


def test_windows_spec_requires_rust_helper_and_excludes_env():
    root = Path(__file__).resolve().parents[1]
    spec_text = (root / "lumina.spec").read_text(encoding="utf-8")
    build_text = (root / "scripts" / "build.py").read_text(encoding="utf-8")

    assert "Rust helper missing" in spec_text
    assert "'/.env'" not in spec_text
    assert "'.env'" not in spec_text
    assert "\".env\"" not in spec_text
    assert "LUMINA_NO_UPX" in spec_text
    assert "LUMINA_NO_UPX" in build_text
    assert "--noupx" not in build_text
