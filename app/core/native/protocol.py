from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class NativeSource:
    kind: Literal["image"]
    path: str
    size_bytes: int


@dataclass(frozen=True)
class NativeSignature:
    signature_id: str
    ext: str
    header: bytes


@dataclass(frozen=True)
class NativeCandidate:
    offset: int
    signature_id: str
    ext: str


@dataclass(frozen=True)
class NativeCandidateBatch:
    batch_index: int
    items: list[NativeCandidate]


@dataclass(frozen=True)
class NativeProgress:
    bytes_scanned: int
    total_bytes: int
    percent: int
    mbps: float


@dataclass(frozen=True)
class NativeFinished:
    bytes_scanned: int
    candidates: int
    duration_ms: int
    mbps: float
    stopped: bool


@dataclass(frozen=True)
class NativeError:
    code: str
    message: str


NativeEvent: TypeAlias = (
    NativeProgress | NativeCandidateBatch | NativeFinished | NativeError
)


def build_scan_command(
    request_id: str,
    source: NativeSource,
    signatures: Sequence[NativeSignature],
    *,
    chunk_size: int = 16 * 1024 * 1024,
    candidate_batch_size: int = 512,
    progress_interval_ms: int = 250,
) -> str:
    if source.kind != "image":
        raise ProtocolError("native phase 2 only supports image sources")
    if source.size_bytes < 0:
        raise ProtocolError("source.size_bytes must be >= 0")
    if not signatures:
        raise ProtocolError("at least one signature is required")

    payload = {
        "cmd": "scan",
        "request_id": request_id,
        "source": {
            "kind": source.kind,
            "path": source.path,
            "size_bytes": source.size_bytes,
        },
        "signatures": [
            {
                "signature_id": sig.signature_id,
                "ext": sig.ext,
                "header_hex": sig.header.hex(),
            }
            for sig in signatures
        ],
        "chunk_size": _positive_int("chunk_size", chunk_size),
        "candidate_batch_size": _positive_int(
            "candidate_batch_size", candidate_batch_size
        ),
        "progress_interval_ms": _positive_int(
            "progress_interval_ms", progress_interval_ms
        ),
    }
    return json.dumps(payload, separators=(",", ":"))


def build_stop_command(request_id: str) -> str:
    return json.dumps(
        {"cmd": "stop", "request_id": request_id}, separators=(",", ":")
    )


def parse_event_line(line: str, request_id: str) -> NativeEvent:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSONL event: {exc}") from exc

    obj = _object(raw, "event")
    event = _required_str(obj, "event")
    actual_request_id = _required_str(obj, "request_id")
    if actual_request_id != request_id:
        raise ProtocolError(
            f"event request_id mismatch: expected {request_id!r}, got {actual_request_id!r}"
        )

    if event == "progress":
        _require_keys(
            obj,
            {
                "event",
                "request_id",
                "bytes_scanned",
                "total_bytes",
                "percent",
                "mbps",
            },
        )
        return NativeProgress(
            bytes_scanned=_required_int(obj, "bytes_scanned"),
            total_bytes=_required_int(obj, "total_bytes"),
            percent=_required_int(obj, "percent"),
            mbps=_required_number(obj, "mbps"),
        )

    if event == "candidates":
        _require_keys(obj, {"event", "request_id", "batch_index", "items"})
        items_raw = _required_list(obj, "items")
        items = [_parse_candidate(item) for item in items_raw]
        return NativeCandidateBatch(
            batch_index=_required_int(obj, "batch_index"),
            items=items,
        )

    if event == "finished":
        _require_keys(
            obj,
            {
                "event",
                "request_id",
                "bytes_scanned",
                "candidates",
                "duration_ms",
                "mbps",
                "stopped",
            },
        )
        return NativeFinished(
            bytes_scanned=_required_int(obj, "bytes_scanned"),
            candidates=_required_int(obj, "candidates"),
            duration_ms=_required_int(obj, "duration_ms"),
            mbps=_required_number(obj, "mbps"),
            stopped=_required_bool(obj, "stopped"),
        )

    if event == "error":
        _require_keys(obj, {"event", "request_id", "code", "message"})
        return NativeError(
            code=_required_str(obj, "code"),
            message=_required_str(obj, "message"),
        )

    raise ProtocolError(f"unknown native event: {event!r}")


def _parse_candidate(raw: Any) -> NativeCandidate:
    obj = _object(raw, "candidate")
    _require_keys(obj, {"offset", "signature_id", "ext"})
    return NativeCandidate(
        offset=_required_int(obj, "offset"),
        signature_id=_required_str(obj, "signature_id"),
        ext=_required_str(obj, "ext"),
    )


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProtocolError(f"{name} must be a positive int")
    return value


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{name} must be a JSON object")
    return value


def _require_keys(obj: dict[str, Any], expected: set[str]) -> None:
    actual = set(obj)
    if actual != expected:
        extra = sorted(actual - expected)
        missing = sorted(expected - actual)
        raise ProtocolError(f"invalid event schema: missing={missing}, extra={extra}")


def _required_str(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise ProtocolError(f"{key} must be a string")
    return value


def _required_int(obj: dict[str, Any], key: str) -> int:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{key} must be an int")
    return value


def _required_bool(obj: dict[str, Any], key: str) -> bool:
    value = obj.get(key)
    if not isinstance(value, bool):
        raise ProtocolError(f"{key} must be a bool")
    return value


def _required_number(obj: dict[str, Any], key: str) -> float:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ProtocolError(f"{key} must be a number")
    return float(value)


def _required_list(obj: dict[str, Any], key: str) -> list[Any]:
    value = obj.get(key)
    if not isinstance(value, list):
        raise ProtocolError(f"{key} must be a list")
    return value
