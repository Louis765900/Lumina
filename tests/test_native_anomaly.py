from __future__ import annotations

from app.core.native.anomaly import (
    AnomalySeverity,
    NativeAnomalyDetector,
    NativeScanContext,
)
from app.core.native.protocol import (
    NativeCandidate,
    NativeCandidateBatch,
    NativeFinished,
    NativeProgress,
    NativeSignature,
)


def _detector(stop_requested: bool = False) -> NativeAnomalyDetector:
    return NativeAnomalyDetector(
        NativeScanContext(
            request_id="req",
            source_size=10,
            signatures={"png": NativeSignature("png", ".png", b"PNG")},
            max_batch_size=2,
            stop_requested=stop_requested,
        )
    )


def _codes(detector: NativeAnomalyDetector, event) -> set[str]:
    return {a.code for a in detector.observe(event)}


def test_offset_equal_to_source_size_is_critical():
    detector = _detector()
    codes = _codes(
        detector,
        NativeCandidateBatch(0, [NativeCandidate(10, "png", ".png")]),
    )

    assert "candidate_offset_out_of_bounds" in codes


def test_unknown_signature_is_critical():
    detector = _detector()
    codes = _codes(
        detector,
        NativeCandidateBatch(0, [NativeCandidate(1, "jpg", ".jpg")]),
    )

    assert "unknown_signature_id" in codes


def test_ext_mismatch_is_critical():
    detector = _detector()
    codes = _codes(
        detector,
        NativeCandidateBatch(0, [NativeCandidate(1, "png", ".jpg")]),
    )

    assert "candidate_ext_mismatch" in codes


def test_batch_too_large_is_critical():
    detector = _detector()
    codes = _codes(
        detector,
        NativeCandidateBatch(
            0,
            [
                NativeCandidate(1, "png", ".png"),
                NativeCandidate(2, "png", ".png"),
                NativeCandidate(3, "png", ".png"),
            ],
        ),
    )

    assert "batch_too_large" in codes


def test_progress_regression_is_critical():
    detector = _detector()
    detector.observe(NativeProgress(8, 10, 80, 1.0))
    codes = _codes(detector, NativeProgress(7, 10, 70, 1.0))

    assert "progress_regression" in codes


def test_missing_finished_is_critical():
    detector = _detector()
    anomalies = detector.finalize()

    assert anomalies[0].severity is AnomalySeverity.CRITICAL
    assert anomalies[0].code == "finished_missing"


def test_stopped_mismatch_is_critical():
    detector = _detector(stop_requested=True)
    codes = _codes(detector, NativeFinished(10, 0, 1, 10.0, False))

    assert "stopped_incoherent" in codes


def test_candidate_count_mismatch_is_warning():
    detector = _detector()
    detector.observe(NativeCandidateBatch(0, [NativeCandidate(1, "png", ".png")]))
    anomalies = detector.observe(NativeFinished(10, 2, 1, 10.0, False))

    assert anomalies[0].severity is AnomalySeverity.WARNING
    assert anomalies[0].code == "candidate_count_mismatch"
