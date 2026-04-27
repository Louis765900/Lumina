from __future__ import annotations

import sys
import textwrap

import pytest

from app.core.native.client import (
    NativeAnomalyError,
    NativeScanClient,
    NativeScanSummary,
    NativeUnavailableError,
)
from app.core.native.protocol import NativeCandidate, NativeSignature, NativeSource


def _summary(reason: str | None = None) -> NativeScanSummary:
    return NativeScanSummary(
        engine="python",
        bytes_scanned=1,
        duration_ms=1,
        mbps=1.0,
        candidate_count=0,
        stopped=False,
        fallback_reason=reason,
    )


def _source() -> NativeSource:
    return NativeSource(kind="image", path="sample.img", size_bytes=100)


def _sigs() -> list[NativeSignature]:
    return [NativeSignature("png", ".png", b"PNG")]


def _helper(tmp_path, body: str):
    path = tmp_path / "fake_helper.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, "-S", str(path)]


def test_auto_fallback_if_helper_missing(tmp_path):
    client = NativeScanClient(
        helper_path=tmp_path / "missing.exe",
        engine="auto",
    )

    summary = client.scan_candidates(
        _source(),
        _sigs(),
        on_candidates=lambda _batch: None,
        python_fallback=lambda: _summary(),
    )

    assert summary.engine == "python"
    assert summary.fallback_reason is not None


def test_native_forced_missing_helper_raises(tmp_path):
    client = NativeScanClient(
        helper_path=tmp_path / "missing.exe",
        engine="native",
    )

    with pytest.raises(NativeUnavailableError):
        client.scan_candidates(
            _source(),
            _sigs(),
            on_candidates=lambda _batch: None,
        )


def test_client_streams_candidate_batches(tmp_path):
    helper = _helper(
        tmp_path,
        """
        import json, sys
        cmd = json.loads(sys.stdin.readline())
        req = cmd["request_id"]
        print(json.dumps({
            "event": "candidates",
            "request_id": req,
            "batch_index": 0,
            "items": [{"offset": 2, "signature_id": "png", "ext": ".png"}],
        }), flush=True)
        print(json.dumps({
            "event": "finished",
            "request_id": req,
            "bytes_scanned": 100,
            "candidates": 1,
            "duration_ms": 1,
            "mbps": 100.0,
            "stopped": False,
        }), flush=True)
        """,
    )
    client = NativeScanClient(helper_command=helper, engine="native", timeout_s=60)
    batches: list[list[NativeCandidate]] = []

    summary = client.scan_candidates(
        _source(),
        _sigs(),
        on_candidates=lambda batch: batches.append(batch),
    )

    assert summary.engine == "native"
    assert summary.candidate_count == 1
    assert batches == [[NativeCandidate(2, "png", ".png")]]


def test_on_candidates_receives_new_list_copy(tmp_path):
    helper = _helper(
        tmp_path,
        """
        import json, sys
        cmd = json.loads(sys.stdin.readline())
        req = cmd["request_id"]
        for i in range(2):
            print(json.dumps({
                "event": "candidates",
                "request_id": req,
                "batch_index": i,
                "items": [{"offset": i, "signature_id": "png", "ext": ".png"}],
            }), flush=True)
        print(json.dumps({
            "event": "finished",
            "request_id": req,
            "bytes_scanned": 100,
            "candidates": 2,
            "duration_ms": 1,
            "mbps": 100.0,
            "stopped": False,
        }), flush=True)
        """,
    )
    client = NativeScanClient(helper_command=helper, engine="native", timeout_s=60)
    seen: list[list[NativeCandidate]] = []

    def _on_candidates(batch: list[NativeCandidate]) -> None:
        seen.append(batch)
        batch.clear()

    client.scan_candidates(_source(), _sigs(), on_candidates=_on_candidates)

    assert len(seen) == 2
    assert seen[0] is not seen[1]


def test_stop_flag_sends_stop_and_accepts_stopped_finished(tmp_path):
    helper = _helper(
        tmp_path,
        """
        import json, sys
        scan = json.loads(sys.stdin.readline())
        stop = json.loads(sys.stdin.readline())
        req = scan["request_id"]
        assert stop["cmd"] == "stop"
        print(json.dumps({
            "event": "finished",
            "request_id": req,
            "bytes_scanned": 0,
            "candidates": 0,
            "duration_ms": 1,
            "mbps": 0.0,
            "stopped": True,
        }), flush=True)
        """,
    )
    client = NativeScanClient(helper_command=helper, engine="native", timeout_s=60)

    summary = client.scan_candidates(
        _source(),
        _sigs(),
        on_candidates=lambda _batch: None,
        stop_flag=lambda: True,
    )

    assert summary.stopped is True


def test_auto_anomaly_after_candidates_does_not_fallback(tmp_path):
    helper = _helper(
        tmp_path,
        """
        import json, sys
        cmd = json.loads(sys.stdin.readline())
        req = cmd["request_id"]
        print(json.dumps({
            "event": "candidates",
            "request_id": req,
            "batch_index": 0,
            "items": [{"offset": 2, "signature_id": "png", "ext": ".png"}],
        }), flush=True)
        print(json.dumps({
            "event": "candidates",
            "request_id": req,
            "batch_index": 1,
            "items": [{"offset": 200, "signature_id": "png", "ext": ".png"}],
        }), flush=True)
        """,
    )
    client = NativeScanClient(helper_command=helper, engine="auto", timeout_s=60)
    fallback_called = False

    def _fallback() -> NativeScanSummary:
        nonlocal fallback_called
        fallback_called = True
        return _summary()

    with pytest.raises(NativeAnomalyError):
        client.scan_candidates(
            _source(),
            _sigs(),
            on_candidates=lambda _batch: None,
            python_fallback=_fallback,
        )

    assert fallback_called is False
