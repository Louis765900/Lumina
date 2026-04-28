from __future__ import annotations

from pathlib import Path

import pytest

from app.core.native.client import NativeScanSummary
from app.core.native.protocol import NativeCandidate
from app.workers.scan_worker import ScanWorker


class FakeCarver:
    def __init__(self) -> None:
        self.scan_called = False
        self.build_calls = 0

    def native_signature_records(self) -> list[tuple[str, str, bytes]]:
        return [("abc_414243", ".abc", b"ABC")]

    def build_file_info_from_candidate(
        self,
        *,
        signature_id: str,
        candidate_offset: int,
        data: bytes,
        data_base_offset: int,
        device: str,
        counter: dict[str, int],
        dedup_check=None,
        source: str = "carver",
    ) -> tuple[dict | None, str | None]:
        self.build_calls += 1
        if signature_id != "abc_414243" or b"ABC" not in data:
            return None, "mismatch"
        counter[".abc"] = counter.get(".abc", 0) + 1
        return {
            "name": f"recovered_abc_{counter['.abc']:04d}.abc",
            "type": "ABC",
            "offset": candidate_offset,
            "size_kb": 1,
            "device": device,
            "integrity": 75,
            "source": source,
        }, None

    def scan(self, device, progress_cb=None, file_found_cb=None, stop_flag=None, dedup_check=None):
        self.scan_called = True
        info = {
            "name": "python.abc",
            "type": "ABC",
            "offset": 0,
            "size_kb": 1,
            "device": device,
            "integrity": 60,
            "source": "carver",
        }
        if file_found_cb:
            file_found_cb(info)
        if progress_cb:
            progress_cb(100)
        return [info]


class FakeNativeClient:
    available_value = True
    scan_impl = None
    constructed = 0

    def __init__(self, *args, **kwargs) -> None:
        type(self).constructed += 1

    def available(self) -> bool:
        return self.available_value

    def helper_path(self) -> Path:
        return Path("missing-lumina-scan.exe")

    def scan_candidates(self, source, signatures, **kwargs):
        scan_impl = type(self).scan_impl
        if scan_impl is None:
            kwargs["on_candidates"]([NativeCandidate(0, "abc_414243", ".abc")])
            return NativeScanSummary(
                engine="native",
                bytes_scanned=source.size_bytes,
                duration_ms=1,
                mbps=1.0,
                candidate_count=1,
                stopped=False,
            )
        return scan_impl(source, signatures, **kwargs)


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch):
    FakeNativeClient.available_value = True
    FakeNativeClient.scan_impl = None
    FakeNativeClient.constructed = 0
    monkeypatch.setattr("app.core.native.client.NativeScanClient", FakeNativeClient)
    monkeypatch.setattr("app.core.fs_parser.detect_fs", lambda _raw, _fd: None)


@pytest.fixture
def image(tmp_path: Path) -> Path:
    path = tmp_path / "disk.img"
    path.write_bytes(b"ABCxxxx")
    return path


def _patch_carver(monkeypatch, carver: FakeCarver) -> None:
    monkeypatch.setattr("app.core.file_carver.FileCarver", lambda: carver)


def _worker(image: Path) -> ScanWorker:
    return ScanWorker({"device": str(image)}, simulate=False)


def test_image_native_engine_uses_native_client(monkeypatch, qtbot, image):
    monkeypatch.setenv("LUMINA_SCAN_ENGINE", "native")
    carver = FakeCarver()
    _patch_carver(monkeypatch, carver)
    batches = []
    worker = _worker(image)
    worker.files_batch_found.connect(batches.append)

    worker._run_real()

    assert FakeNativeClient.constructed == 1
    assert not carver.scan_called
    assert batches and batches[0][0]["source"] == "native_carver"


def test_python_engine_never_uses_native(monkeypatch, qtbot, image):
    monkeypatch.setenv("LUMINA_SCAN_ENGINE", "python")
    carver = FakeCarver()
    _patch_carver(monkeypatch, carver)
    worker = _worker(image)

    worker._run_real()

    assert FakeNativeClient.constructed == 0
    assert carver.scan_called


def test_auto_missing_helper_falls_back_python(monkeypatch, qtbot, image):
    monkeypatch.setenv("LUMINA_SCAN_ENGINE", "auto")
    FakeNativeClient.available_value = False
    carver = FakeCarver()
    _patch_carver(monkeypatch, carver)
    batches = []
    worker = _worker(image)
    worker.files_batch_found.connect(batches.append)

    worker._run_real()

    assert carver.scan_called
    assert batches and batches[0][0]["source"] == "carver"


def test_native_missing_helper_emits_error(monkeypatch, qtbot, image):
    monkeypatch.setenv("LUMINA_SCAN_ENGINE", "native")
    FakeNativeClient.available_value = False
    carver = FakeCarver()
    _patch_carver(monkeypatch, carver)
    errors = []
    worker = _worker(image)
    worker.error.connect(errors.append)

    worker._run_real()

    assert not carver.scan_called
    assert errors and "native helper not found" in errors[0]


def test_native_forced_non_image_errors(monkeypatch, qtbot):
    monkeypatch.setenv("LUMINA_SCAN_ENGINE", "native")
    errors = []
    worker = ScanWorker({"device": r"\\.\PhysicalDrive0"}, simulate=False)
    worker.error.connect(errors.append)

    worker._run_real()

    assert errors == ["Native engine Phase 4 supports image files only."]


def test_auto_native_error_discards_buffer_then_falls_back(monkeypatch, qtbot, image):
    monkeypatch.setenv("LUMINA_SCAN_ENGINE", "auto")
    carver = FakeCarver()
    _patch_carver(monkeypatch, carver)
    batches = []

    def _scan(_source, _signatures, **kwargs):
        kwargs["on_candidates"]([NativeCandidate(0, "abc_414243", ".abc")])
        raise RuntimeError("native anomaly")

    FakeNativeClient.scan_impl = _scan
    worker = _worker(image)
    worker.files_batch_found.connect(batches.append)

    worker._run_real()

    assert carver.scan_called
    assert len(batches) == 1
    assert batches[0][0]["source"] == "carver"


def test_native_candidates_not_emitted_before_finished(monkeypatch, qtbot, image):
    monkeypatch.setenv("LUMINA_SCAN_ENGINE", "native")
    carver = FakeCarver()
    _patch_carver(monkeypatch, carver)
    batches = []

    def _scan(source, _signatures, **kwargs):
        kwargs["on_candidates"]([NativeCandidate(0, "abc_414243", ".abc")])
        assert batches == []
        return NativeScanSummary("native", source.size_bytes, 1, 1.0, 1, False)

    FakeNativeClient.scan_impl = _scan
    worker = _worker(image)
    worker.files_batch_found.connect(batches.append)

    worker._run_real()

    assert len(batches) == 1
    assert batches[0][0]["source"] == "native_carver"


def test_native_stop_commits_validated_buffer_without_fallback(monkeypatch, qtbot, image):
    monkeypatch.setenv("LUMINA_SCAN_ENGINE", "native")
    carver = FakeCarver()
    _patch_carver(monkeypatch, carver)
    batches = []

    def _scan(source, _signatures, **kwargs):
        kwargs["on_candidates"]([NativeCandidate(0, "abc_414243", ".abc")])
        return NativeScanSummary("native", source.size_bytes, 1, 1.0, 1, True)

    FakeNativeClient.scan_impl = _scan
    worker = _worker(image)
    worker.files_batch_found.connect(batches.append)

    worker._run_real()

    assert not carver.scan_called
    assert len(batches) == 1
    assert batches[0][0]["source"] == "native_carver"


def test_native_duplicate_candidates_are_deduped(monkeypatch, qtbot, image):
    monkeypatch.setenv("LUMINA_SCAN_ENGINE", "native")
    carver = FakeCarver()
    _patch_carver(monkeypatch, carver)
    batches = []

    def _scan(source, _signatures, **kwargs):
        kwargs["on_candidates"](
            [
                NativeCandidate(0, "abc_414243", ".abc"),
                NativeCandidate(0, "abc_414243", ".abc"),
            ]
        )
        return NativeScanSummary("native", source.size_bytes, 1, 1.0, 2, False)

    FakeNativeClient.scan_impl = _scan
    worker = _worker(image)
    worker.files_batch_found.connect(batches.append)

    worker._run_real()

    assert carver.build_calls == 1
    assert len(batches[0]) == 1
