from __future__ import annotations

import json
from pathlib import Path

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
from app.core.recovery import (
    default_recovery_dir,
    ensure_lumina_log,
    persist_recovery_dir,
    validate_recovery_destination,
)
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


def test_first_launch_false_triggers_setup_wizard_and_saves_settings(tmp_path):
    from PyQt6.QtWidgets import QDialog

    from app.ui.setup_wizard import ensure_setup_complete

    path = tmp_path / "settings.json"
    save_settings({"first_launch_done": False, "accepted_disclaimer": False}, path)
    calls = {"shown": 0}

    class _FakeWizard:
        def __init__(self, settings, parent=None):
            calls["shown"] += 1
            assert settings["first_launch_done"] is False

        def exec(self):
            return QDialog.DialogCode.Accepted

        def settings(self):
            return {
                "language": "en",
                "default_recovery_dir": r"D:\Recovered",
                "scan_engine": "python",
                "prefer_image_first": False,
                "accepted_disclaimer": True,
                "first_launch_done": True,
            }

    assert ensure_setup_complete(settings_file=path, dialog_factory=_FakeWizard) is True
    saved = load_settings(path)
    assert calls["shown"] == 1
    assert saved["language"] == "en"
    assert saved["scan_engine"] == "python"
    assert saved["accepted_disclaimer"] is True
    assert saved["first_launch_done"] is True


def test_completed_setup_does_not_show_wizard(tmp_path):
    from app.ui.setup_wizard import ensure_setup_complete

    path = tmp_path / "settings.json"
    save_settings({"first_launch_done": True, "accepted_disclaimer": True}, path)

    def _should_not_be_called(_settings, _parent=None):
        raise AssertionError("wizard should not be shown")

    assert ensure_setup_complete(settings_file=path, dialog_factory=_should_not_be_called) is True


def test_setup_wizard_requires_disclaimer(qtbot, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    from app.ui.setup_wizard import SetupWizard

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    wizard = SetupWizard({"accepted_disclaimer": False})
    qtbot.addWidget(wizard)

    assert not wizard.start_btn.isEnabled()
    wizard.accept()
    assert wizard.result() == 0
    assert warnings

    wizard.disclaimer_check.setChecked(True)
    assert wizard.start_btn.isEnabled()
    settings = wizard.settings()
    assert settings["accepted_disclaimer"] is True
    assert settings["first_launch_done"] is True


def test_recovery_destination_is_created_and_valid(tmp_path):
    dest = tmp_path / "new-recovery-folder"

    check = validate_recovery_destination(
        [{"device": r"\\.\PhysicalDrive9", "name": "a.bin"}],
        dest,
    )

    assert check.blocked is False
    assert dest.is_dir()


def test_recovery_blocks_same_logical_source_drive(tmp_path):
    drive = Path.cwd().drive
    if not drive:
        pytest.skip("drive-letter check is Windows-specific")
    dest = tmp_path / "recovered"

    check = validate_recovery_destination([{"device": drive}], dest)

    assert check.blocked is True
    assert check.message == "Vous ne pouvez pas récupérer sur le disque source"


def test_recovery_warns_for_image_on_same_drive(tmp_path):
    image = tmp_path / "source.img"
    image.write_bytes(b"image")
    dest = tmp_path / "recovered"

    check = validate_recovery_destination([{"device": str(image)}], dest)

    assert check.blocked is False
    assert check.warning is True
    assert "même lettre de lecteur" in check.message


def test_recovery_dir_persistence_uses_last_folder(tmp_path):
    settings_file = tmp_path / "settings.json"
    dest = tmp_path / "last"

    persist_recovery_dir(dest, settings_file)

    assert default_recovery_dir(settings_file) == str(dest)


def test_lumina_log_is_created(tmp_path):
    log_path = ensure_lumina_log(tmp_path)

    assert log_path.exists() or log_path.parent.exists()
    assert log_path.name == "lumina.log"


def test_empty_extraction_worker_does_not_crash(qtbot, tmp_path):
    from app.ui.screen_results import _ExtractionWorker

    finished: list[tuple[int, int]] = []
    worker = _ExtractionWorker([], str(tmp_path))
    worker.finished.connect(lambda ok, fail: finished.append((ok, fail)))

    worker.run()

    assert finished == [(0, 0)]
