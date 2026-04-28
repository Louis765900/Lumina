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

    class _Signal:
        def connect(self, _callback):
            return None

    class _FakeWorker:
        created: list[tuple[dict, bool]] = []

        def __init__(self, disk, simulate=False):
            self.progress = _Signal()
            self.status_text = _Signal()
            self.files_batch_found = _Signal()
            self.finished = _Signal()
            self.error = _Signal()
            self.started = False
            type(self).created.append((disk, simulate))

        def start(self):
            self.started = True

    monkeypatch.delenv("LUMINA_ENABLE_DEMO", raising=False)
    monkeypatch.setattr("app.ui.screen_scan.ScanWorker", _FakeWorker)
    screen = ScanScreen()
    qtbot.addWidget(screen)

    screen.start_scan({"device": "sample.img", "size_gb": 1, "scan_mode": "quick"})

    assert _FakeWorker.created
    assert _FakeWorker.created[0][1] is False


def test_quick_scan_ntfs_uses_metadata_parser_only(monkeypatch, qtbot, tmp_path):
    calls = {"enumerate": 0}

    class _FakeParser:
        name = "NTFS"

        def enumerate_files(self, stop_flag, progress_cb, file_found_cb):
            calls["enumerate"] += 1
            progress_cb(50)
            file_found_cb(
                {
                    "name": "deleted.docx",
                    "type": "DOCX",
                    "offset": 4096,
                    "size_kb": 12,
                    "device": "disk.img",
                    "integrity": 85,
                    "source": "mft",
                    "fs": "NTFS",
                    "data_runs": [(4096, 4096)],
                }
            )
            progress_cb(100)
            return 1

    image = tmp_path / "ntfs.img"
    image.write_bytes(b"NTFS test image")
    monkeypatch.setattr("app.core.fs_parser.detect_fs", lambda _raw, _fd: _FakeParser())

    def _file_carver_should_not_run():
        raise AssertionError("quick scan must not instantiate FileCarver")

    monkeypatch.setattr("app.core.file_carver.FileCarver", _file_carver_should_not_run)

    worker = ScanWorker({"device": str(image), "scan_mode": "quick"})
    batches: list[list[dict]] = []
    worker.files_batch_found.connect(batches.append)

    worker._run_real()

    assert batches
    assert calls["enumerate"] == 1
    assert batches[0][0]["source"] == "mft"
    assert "simulated" not in batches[0][0]


def test_quick_scan_unsupported_emits_no_results_and_no_fake(monkeypatch, qtbot, tmp_path):
    image = tmp_path / "fat.img"
    image.write_bytes(b"not ntfs")
    monkeypatch.setattr("app.core.fs_parser.detect_fs", lambda _raw, _fd: None)

    def _file_carver_should_not_run():
        raise AssertionError("quick scan must not instantiate FileCarver")

    monkeypatch.setattr("app.core.file_carver.FileCarver", _file_carver_should_not_run)

    worker = ScanWorker({"device": str(image), "scan_mode": "quick"})
    batches: list[list[dict]] = []
    statuses: list[str] = []
    errors: list[str] = []
    worker.files_batch_found.connect(batches.append)
    worker.status_text.connect(statuses.append)
    worker.error.connect(errors.append)

    worker._run_real()

    assert batches == []
    assert any("Scan rapide non disponible pour cette source" in msg for msg in statuses)
    assert errors == ["Scan rapide non disponible pour cette source. Lancez un scan profond."]
