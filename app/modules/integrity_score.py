"""Optional recoverability scoring for scan results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IntegrityScore:
    score: int
    label: str
    signals: tuple[str, ...]


def _clamp_score(value: int) -> int:
    return max(0, min(100, value))


def _label(score: int) -> str:
    if score >= 90:
        return "excellent"
    if score >= 75:
        return "good"
    if score >= 60:
        return "partial"
    return "fragile"


def score_file(info: dict[str, Any]) -> IntegrityScore:
    """Compute a conservative score without needing to read disk bytes again."""

    try:
        score = int(info.get("integrity", 60))
    except (TypeError, ValueError):
        score = 60

    signals: list[str] = [f"base:{score}"]
    source = str(info.get("source") or "").lower()
    fs_name = str(info.get("fs") or "").lower()
    data_runs = info.get("data_runs") or []

    if source in {"mft", "fat32", "exfat", "ext4", "hfs+"} or fs_name:
        if data_runs:
            score += 6
            signals.append("filesystem-runs")
        else:
            score -= 8
            signals.append("filesystem-no-runs")

    if source == "native_carver":
        score += 2
        signals.append("native-validation")
    elif source == "carver":
        signals.append("signature-carving")

    if info.get("deleted"):
        score -= 6
        signals.append("deleted-entry")

    if isinstance(data_runs, list) and len(data_runs) > 1:
        score -= min(12, (len(data_runs) - 1) * 3)
        signals.append("fragmented-runs")

    if info.get("partial") or info.get("truncated"):
        score -= 20
        signals.append("partial-output")

    try:
        if int(info.get("size_kb", 0)) <= 0:
            score -= 12
            signals.append("unknown-size")
    except (TypeError, ValueError):
        score -= 12
        signals.append("unknown-size")

    try:
        if int(info.get("offset", 0)) < 0:
            score -= 20
            signals.append("invalid-offset")
    except (TypeError, ValueError):
        score -= 20
        signals.append("invalid-offset")

    score = _clamp_score(score)
    return IntegrityScore(score=score, label=_label(score), signals=tuple(signals))


def enrich_file(info: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *info* with optional integrity-score fields."""

    enriched = dict(info)
    result = score_file(enriched)
    enriched["integrity_score"] = result.score
    enriched["integrity_label"] = result.label
    enriched["integrity_signals"] = list(result.signals)
    enriched.setdefault("integrity", result.score)
    return enriched


def enrich_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [enrich_file(info) for info in files]
