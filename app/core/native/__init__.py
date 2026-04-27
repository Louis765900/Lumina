"""Native scan helper integration.

Phase 2 exposes a strict JSONL client for the Rust helper, without wiring it
into ScanWorker or the UI yet.
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
