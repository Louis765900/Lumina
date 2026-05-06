from __future__ import annotations

import json
import subprocess

import pytest

from app.modules.disk_health import collect_disk_health
from app.modules.integrity_score import enrich_file, score_file
from app.modules.registry import MODULE_IDS, ModuleRegistry
from app.modules.reporting_suite import build_html_report, emit_dfxml
from app.modules.search_filters import FilterCriteria, apply_filters
from app.modules.storage_index import StorageIndex


def test_registry_registers_full_premium_module_map():
    registry = ModuleRegistry(settings={"modules": {}}, env={})

    assert "storage-index" in MODULE_IDS
    assert "local-assistant" in MODULE_IDS
    assert len(registry.manifests()) == len(MODULE_IDS)
    assert registry.get("storage-index").priority == 1


def test_registry_keeps_planned_modules_disabled_by_default():
    registry = ModuleRegistry(settings={"modules": {}}, env={})

    assert registry.is_enabled("storage-index") is True
    assert registry.is_enabled("integrity-score") is True
    assert registry.is_enabled("local-assistant") is False


def test_registry_supports_settings_and_env_disables():
    settings = {"modules": {"storage-index": {"enabled": False}}}

    assert ModuleRegistry(settings=settings, env={}).is_enabled("storage-index") is False
    assert (
        ModuleRegistry(settings={"modules": {}}, env={"LUMINA_DISABLE_STORAGE_INDEX": "1"})
        .is_enabled("storage-index")
        is False
    )


def test_integrity_score_enriches_without_overwriting_base_integrity():
    info = {
        "name": "photo.jpg",
        "type": "JPG",
        "integrity": 80,
        "source": "mft",
        "data_runs": [(1024, 4096)],
        "size_kb": 4,
    }

    enriched = enrich_file(info)

    assert enriched["integrity"] == 80
    assert enriched["integrity_score"] > 80
    assert enriched["integrity_label"] in {"good", "excellent"}
    assert "filesystem-runs" in enriched["integrity_signals"]


def test_integrity_score_penalizes_partial_fragmented_results():
    result = score_file(
        {
            "name": "frag.bin",
            "integrity": 70,
            "source": "carver",
            "data_runs": [(0, 1), (10, 1), (20, 1)],
            "partial": True,
            "size_kb": 0,
        }
    )

    assert result.score < 60
    assert result.label == "fragile"


def test_search_filters_query_group_system_and_sort():
    files = [
        {"name": "photo-vacances.jpg", "type": "JPG", "size_kb": 300, "integrity_score": 92},
        {"name": "setup.exe", "type": "EXE", "size_kb": 100, "integrity_score": 99},
        {"name": "notes.pdf", "type": "PDF", "size_kb": 50, "integrity_score": 70},
    ]

    result = apply_filters(
        files,
        FilterCriteria(query="vacances", group="Images", hide_system=True, sort_key="integrity"),
    )

    assert [item["name"] for item in result] == ["photo-vacances.jpg"]


def test_storage_index_indexes_and_searches_with_fts5(tmp_path):
    index = StorageIndex(tmp_path / "lumina-index.sqlite3")
    try:
        index.initialize()
    except RuntimeError as exc:
        pytest.skip(str(exc))

    scan_id = index.index_files(
        [
            {
                "name": "photo-vacances.jpg",
                "type": "JPG",
                "device": "disk.img",
                "offset": 4096,
                "size_kb": 512,
                "integrity": 80,
                "integrity_score": 91,
                "source": "carver",
            },
            {
                "name": "notes.pdf",
                "type": "PDF",
                "device": "disk.img",
                "offset": 8192,
                "size_kb": 32,
                "integrity": 70,
                "source": "mft",
            },
        ],
        scan_id="scan-test",
        source="disk.img",
    )

    assert scan_id == "scan-test"
    results = index.search("vacances", file_types={"JPG"}, min_integrity=90)
    assert len(results) == 1
    assert results[0]["name"] == "photo-vacances.jpg"
    assert results[0]["scan_id"] == "scan-test"


def test_reporting_suite_escapes_html_and_writes_dfxml(tmp_path):
    files = [{"name": "<script>.jpg", "type": "JPG", "size_kb": 1, "offset": 10}]
    html = build_html_report(files, device="disk.img")
    dfxml_path = tmp_path / "report.xml"

    emit_dfxml(files, "disk.img", str(dfxml_path))

    assert "&lt;script&gt;.jpg" in html
    assert "fileobject" in dfxml_path.read_text(encoding="utf-8")


def test_disk_health_uses_smartctl_when_available(monkeypatch):
    def fake_run(cmd, **kwargs):
        if "--scan-open" in cmd:
            payload = {"devices": [{"name": "/dev/sda"}]}
        else:
            payload = {
                "model_name": "Test SSD",
                "serial_number": "ABC123",
                "smart_status": {"passed": True},
                "user_capacity": {"bytes": 1024},
                "protocol": "NVMe",
            }
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("app.modules.disk_health.shutil.which", lambda name: "smartctl")
    monkeypatch.setattr("app.modules.disk_health.subprocess.run", fake_run)

    disks = collect_disk_health(env={"LUMINA_MODULE_DISK_HEALTH": "1"})

    assert disks[0]["Caption"] == "Test SSD"
    assert disks[0]["Status"] == "OK"
    assert disks[0]["HealthSource"] == "smartctl"


def test_disk_health_can_be_disabled():
    with pytest.raises(RuntimeError, match="disabled"):
        collect_disk_health(env={"LUMINA_DISABLE_DISK_HEALTH": "1"})
