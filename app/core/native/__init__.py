"""Native scan helper integration.

Phase 4 wires the strict JSONL client into ScanWorker for local image files
only. Physical drives, VSS, and UI-visible native streaming are still out of
scope.
"""

from app.core.native.client import (
    NativeAnomalyError,
    NativeProtocolError,
    NativeScanClient,
    NativeScanError,
    NativeUnavailableError,
)
from app.core.native.protocol import (
    NativeCandidate,
    NativeCandidateBatch,
    NativeFinished,
    NativeProgress,
    NativeSignature,
    NativeSource,
)

__all__ = [
    "NativeAnomalyError",
    "NativeCandidate",
    "NativeCandidateBatch",
    "NativeFinished",
    "NativeProgress",
    "NativeProtocolError",
    "NativeScanClient",
    "NativeScanError",
    "NativeSignature",
    "NativeSource",
    "NativeUnavailableError",
]
