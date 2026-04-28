from __future__ import annotations

import json

import pytest

from app.core.i18n import t
from app.core.settings import (
    default_settings,
    is_demo_enabled,
    load_settings,
    save_settings,
    validate_settings,
)
from app.core.native.settings import get_scan_engine
from app.workers.scan_worker import ScanWorker


def test_settings_load_missing_file_uses_safe_defaults(tmp_path):
    settings = load_settings(tmp_path / "missing.json")

    assert settings["language"] == "fr"
    assert settings["scan_engine"] == "auto"
    assert settings["prefer_image_first"] is True
    assert settings["accepted_disclaimer"] is False
    assert settings["first_launch_done"] is False


def test_settings_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "settings.json"

    saved = save_settings(
        {
            "language": "en",
            "default_recovery_dir": r"D:\Recovered",
            "scan_engine": "native",
            "prefer_image_first": False,
            "accepted_disclaimer": True,
            "first_launch_done": True,
        },
        path,
    )

    assert saved == load_settings(path)
    assert json.loads(path.read_text(encoding="utf-8"))["scan_engine"] == "native"


def test_settings_corrupt_json_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not-json", encoding="utf-8")

    assert load_settings(path) == default_settings()


def test_settings_invalid_values_fall_back_safely():
    settings = validate_settings(
        {
            "language": "de",
            "default_recovery_dir": "",
            "scan_engine": "turbo",
            "prefer_image_first": "yes",
            "accepted_disclaimer": 1,
            "first_launch_done": None,
        }
    )

    assert settings["language"] == "fr"
    assert settings["scan_engine"] == "auto"
    assert settings["prefer_image_first"] is True
    assert settings["accepted_disclaimer"] is False
    assert settings["first_launch_done"] is False


def test_persisted_scan_engine_is_used_when_env_override_absent(tmp_path):
    path = tmp_path / "settings.json"
    save_settings({"scan_engine": "python"}, path)

    assert get_scan_engine({}, settings_file=path) == "python"


def test_i18n_falls_back_to_french():
    assert t("settings.language", "de") == "Langue"
    assert t("missing.key", "en") == "missing.key"


def test_demo_disabled_by_default():
    assert is_demo_enabled({}) is False
    assert is_demo_enabled({"LUMINA_ENABLE_DEMO": "0"}) is False
    assert is_demo_enabled({"LUMINA_ENABLE_DEMO": "1"}) is True


def test_simulate_true_is_impossible_without_demo_env(monkeypatch):
    monkeypatch.delenv("LUMINA_ENABLE_DEMO", raising=False)

    with pytest.raises(ValueError, match="mode demo"):
        ScanWorker({"device": "demo.img"}, simulate=True)


def test_simulation_guard_emits_no_fake_results_in_production(monkeypatch, qtbot):
    monkeypatch.delenv("LUMINA_ENABLE_DEMO", raising=False)
    worker = ScanWorker({"device": "demo.img"}, simulate=False)
    batches: list[list[dict]] = []
    worker.files_batch_found.connect(batches.append)

    with pytest.raises(RuntimeError, match="mode demo"):
        worker._run_simulation()

    assert batches == []


def test_quick_scan_user_path_does_not_start_demo_worker(monkeypatch, qtbot):
    from app.ui.screen_scan import ScanScreen

    monkeypatch.delenv("LUMINA_ENABLE_DEMO", raising=False)
    screen = ScanScreen()
    qtbot.addWidget(screen)

    screen.start_scan({"device": "sample.img", "size_gb": 1, "scan_mode": "quick"})

    assert screen._worker is None
    assert "Scan rapide reel non disponible" in screen._status_lbl.text()
