from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from app.core.native.protocol import (
    NativeCandidateBatch,
    NativeError,
    NativeEvent,
    NativeFinished,
    NativeProgress,
    NativeSignature,
)


class AnomalySeverity(Enum):
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class NativeAnomaly:
    severity: AnomalySeverity
    code: str
    message: str


@dataclass(frozen=True)
class NativeScanContext:
    request_id: str
    source_size: int
    signatures: Mapping[str, NativeSignature]
    max_batch_size: int
    stop_requested: bool = False


class NativeAnomalyDetector:
    def __init__(self, context: NativeScanContext) -> None:
        self._context = context
        self._last_progress_bytes = 0
        self._finished: NativeFinished | None = None
        self._observed_candidates = 0
        self._stop_requested = context.stop_requested

    def mark_stop_requested(self) -> None:
        self._stop_requested = True

    def observe(self, event: NativeEvent) -> list[NativeAnomaly]:
        if isinstance(event, NativeProgress):
            return self._observe_progress(event)
        if isinstance(event, NativeCandidateBatch):
            return self._observe_candidates(event)
        if isinstance(event, NativeFinished):
            return self._observe_finished(event)
        if isinstance(event, NativeError):
            return [
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "native_error",
                    f"native helper reported {event.code}: {event.message}",
                )
            ]
        return [
            NativeAnomaly(
                AnomalySeverity.CRITICAL,
                "unknown_event",
                f"unexpected native event type: {type(event).__name__}",
            )
        ]

    def finalize(self) -> list[NativeAnomaly]:
        if self._finished is None:
            return [
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "finished_missing",
                    "native helper closed without a finished event",
                )
            ]
        return []

    def _observe_progress(self, event: NativeProgress) -> list[NativeAnomaly]:
        anomalies: list[NativeAnomaly] = []
        if event.bytes_scanned < self._last_progress_bytes:
            anomalies.append(
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "progress_regression",
                    "progress bytes_scanned moved backwards",
                )
            )
        if event.bytes_scanned > self._context.source_size:
            anomalies.append(
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "progress_beyond_source",
                    "progress bytes_scanned exceeds source size",
                )
            )
        if event.total_bytes != self._context.source_size:
            anomalies.append(
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "progress_total_mismatch",
                    "progress total_bytes differs from source size",
                )
            )
        if event.percent < 0 or event.percent > 100:
            anomalies.append(
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "progress_percent_out_of_range",
                    "progress percent must be between 0 and 100",
                )
            )
        if event.mbps < 0:
            anomalies.append(
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "progress_negative_mbps",
                    "progress mbps must be non-negative",
                )
            )

        self._last_progress_bytes = max(self._last_progress_bytes, event.bytes_scanned)
        return anomalies

    def _observe_candidates(self, event: NativeCandidateBatch) -> list[NativeAnomaly]:
        anomalies: list[NativeAnomaly] = []
        if len(event.items) > self._context.max_batch_size:
            anomalies.append(
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "batch_too_large",
                    "native candidate batch exceeds configured max_batch_size",
                )
            )

        for item in event.items:
            if item.offset < 0 or item.offset >= self._context.source_size:
                anomalies.append(
                    NativeAnomaly(
                        AnomalySeverity.CRITICAL,
                        "candidate_offset_out_of_bounds",
                        f"candidate offset {item.offset} is outside source bounds",
                    )
                )
            signature = self._context.signatures.get(item.signature_id)
            if signature is None:
                anomalies.append(
                    NativeAnomaly(
                        AnomalySeverity.CRITICAL,
                        "unknown_signature_id",
                        f"candidate references unknown signature_id {item.signature_id!r}",
                    )
                )
            elif item.ext != signature.ext:
                anomalies.append(
                    NativeAnomaly(
                        AnomalySeverity.CRITICAL,
                        "candidate_ext_mismatch",
                        f"candidate ext {item.ext!r} does not match signature ext {signature.ext!r}",
                    )
                )

        self._observed_candidates += len(event.items)
        return anomalies

    def _observe_finished(self, event: NativeFinished) -> list[NativeAnomaly]:
        anomalies: list[NativeAnomaly] = []
        self._finished = event

        if event.bytes_scanned > self._context.source_size:
            anomalies.append(
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "finished_beyond_source",
                    "finished bytes_scanned exceeds source size",
                )
            )
        if event.duration_ms < 0:
            anomalies.append(
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "finished_negative_duration",
                    "finished duration_ms must be non-negative",
                )
            )
        if event.mbps < 0:
            anomalies.append(
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "finished_negative_mbps",
                    "finished mbps must be non-negative",
                )
            )
        if self._stop_requested and not event.stopped:
            anomalies.append(
                NativeAnomaly(
                    AnomalySeverity.CRITICAL,
                    "stopped_incoherent",
                    "stop was requested but finished.stopped is false",
                )
            )
        if event.candidates != self._observed_candidates:
            anomalies.append(
                NativeAnomaly(
                    AnomalySeverity.WARNING,
                    "candidate_count_mismatch",
                    "finished candidate count differs from observed streamed candidates",
                )
            )
        return anomalies


def critical_anomalies(anomalies: list[NativeAnomaly]) -> list[NativeAnomaly]:
    return [a for a in anomalies if a.severity is AnomalySeverity.CRITICAL]
