"""
B1 Phase 3 benchmark: Python regex hot path vs Rust JSONL helper.

The script builds a deterministic synthetic disk image with seeded signatures,
runs Python and/or native candidate scanning, writes a JSON report under
benchmarks/results/, and prints the same report to stdout.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.file_carver import FileCarver
from app.core.native.client import NativeScanClient
from app.core.native.protocol import NativeCandidate, NativeSignature, NativeSource

CORPUS_DIR = Path("benchmarks/corpus")
RESULTS_DIR = Path("benchmarks/results")
RNG_SEED = 0xB103
DEFAULT_SIZE_MB = 256
DEFAULT_SEEDS = 5000
RUST_MIN_MBPS = 100.0

CandidateKey = tuple[int, str, str]
Mode = Literal["python", "native", "both"]


@dataclass(frozen=True)
class SignatureRecord:
    signature_id: str
    ext: str
    header_hex: str
    family: str

    @property
    def header(self) -> bytes:
        return bytes.fromhex(self.header_hex)

    def native_signature(self) -> NativeSignature:
        return NativeSignature(self.signature_id, self.ext, self.header)


@dataclass(frozen=True)
class InjectionRecord:
    offset: int
    signature_id: str
    ext: str

    def key(self) -> CandidateKey:
        return (self.offset, self.signature_id, self.ext)


def _family_for_ext(ext: str) -> str | None:
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}:
        return "images"
    if ext in {".pdf"}:
        return "documents"
    if ext in {".zip", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".apk", ".jar", ".epub"}:
        return "archives"
    return None


def _signature_id(ext: str, header: bytes) -> str:
    return f"{ext.lstrip('.')}_{header.hex()}"


def selected_signatures(carver: FileCarver) -> list[SignatureRecord]:
    preferred_exts = {".jpg", ".png", ".gif", ".pdf", ".zip"}
    seen_exts: set[str] = set()
    selected: list[SignatureRecord] = []

    for header, (ext, _footer, _plugin) in sorted(
        carver._header_map.items(),
        key=lambda item: (item[1][0], item[0].hex()),
    ):
        family = _family_for_ext(ext)
        if family is None or ext not in preferred_exts or ext in seen_exts:
            continue
        selected.append(
            SignatureRecord(
                signature_id=_signature_id(ext, header),
                ext=ext,
                header_hex=header.hex(),
                family=family,
            )
        )
        seen_exts.add(ext)

    required = {".png", ".pdf", ".zip"}
    missing = required - seen_exts
    if missing:
        raise RuntimeError(f"required benchmark signatures missing: {sorted(missing)}")
    return selected


def build_image(
    image: Path,
    signatures: list[SignatureRecord],
    *,
    size_mb: int,
    seeds: int,
) -> list[InjectionRecord]:
    rng = random.Random(RNG_SEED)
    size = size_mb * 1024 * 1024
    data = bytearray(rng.randbytes(size))
    occupied: list[tuple[int, int]] = []
    injections: list[InjectionRecord] = []

    boundary_offsets = [
        1 * 1024 * 1024 + 123,
        16 * 1024 * 1024 - 2,
        16 * 1024 * 1024 + 7,
        32 * 1024 * 1024 - 3,
        64 * 1024 * 1024 + 11,
    ]

    for idx in range(seeds):
        sig = signatures[idx % len(signatures)]
        if idx < len(boundary_offsets):
            raw_offset = boundary_offsets[idx]
        else:
            raw_offset = rng.randrange(4096, size - len(sig.header) - 4096)
        offset = _next_free_offset(raw_offset, len(sig.header), size, occupied)
        data[offset : offset + len(sig.header)] = sig.header
        occupied.append((offset, offset + len(sig.header)))
        injections.append(InjectionRecord(offset, sig.signature_id, sig.ext))

    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(data)
    return injections


def _next_free_offset(
    offset: int,
    length: int,
    size: int,
    occupied: list[tuple[int, int]],
) -> int:
    end_limit = size - length
    candidate = max(0, min(offset, end_limit))
    while _overlaps(candidate, candidate + length, occupied):
        candidate += length + 17
        if candidate > end_limit:
            candidate = 4096
        if _overlaps(candidate, candidate + length, occupied):
            continue
    return candidate


def _overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start < other_end and end > other_start for other_start, other_end in ranges)


def load_or_create_image(
    image: Path,
    signatures: list[SignatureRecord],
    *,
    size_mb: int,
    seeds: int,
    force_rebuild: bool,
) -> list[InjectionRecord]:
    manifest = image.with_suffix(image.suffix + ".manifest.json")
    if image.exists() and manifest.exists() and not force_rebuild:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            data.get("size_mb") == size_mb
            and data.get("seeds") == seeds
            and data.get("rng_seed") == RNG_SEED
        ):
            return [InjectionRecord(**item) for item in data["injections"]]

    injections = build_image(image, signatures, size_mb=size_mb, seeds=seeds)
    manifest.write_text(
        json.dumps(
            {
                "size_mb": size_mb,
                "seeds": seeds,
                "rng_seed": RNG_SEED,
                "injections": [asdict(item) for item in injections],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return injections


def run_python(
    carver: FileCarver,
    image: Path,
    signature_by_header: dict[bytes, SignatureRecord],
) -> tuple[list[CandidateKey], dict[str, float | int | bool]]:
    data = image.read_bytes()
    started = time.perf_counter()
    candidates: list[CandidateKey] = []
    for match in carver._pattern.finditer(data):
        header = match.group(0)
        sig = signature_by_header.get(header)
        if sig is None:
            continue
        candidates.append((match.start(), sig.signature_id, sig.ext))
    duration_s = time.perf_counter() - started
    size_mb = image.stat().st_size / (1024 * 1024)
    return candidates, _metrics(True, duration_s, size_mb, len(candidates))


def run_native(
    image: Path,
    signatures: list[SignatureRecord],
) -> tuple[list[CandidateKey], dict[str, float | int | bool | str | None]]:
    client = NativeScanClient(engine="native")
    helper = client.helper_path()
    if not helper.exists():
        return [], {
            "enabled": False,
            "error": f"native helper not built: {helper}",
            "duration_ms": 0,
            "mbps": 0.0,
            "candidate_count": 0,
            "candidates_per_sec": 0.0,
        }

    found: list[NativeCandidate] = []
    started = time.perf_counter()
    summary = client.scan_candidates(
        NativeSource(kind="image", path=str(image), size_bytes=image.stat().st_size),
        [sig.native_signature() for sig in signatures],
        on_candidates=lambda batch: found.extend(batch),
    )
    duration_s = time.perf_counter() - started
    candidates = [(item.offset, item.signature_id, item.ext) for item in found]
    size_mb = image.stat().st_size / (1024 * 1024)
    helper_duration_s = summary.duration_ms / 1000 if summary.duration_ms > 0 else 0.0
    metrics = {
        "enabled": True,
        "duration_ms": summary.duration_ms,
        "mbps": summary.mbps,
        "candidate_count": summary.candidate_count,
        "candidates_per_sec": summary.candidate_count / helper_duration_s
        if helper_duration_s > 0
        else 0.0,
        "wall_duration_ms": int(duration_s * 1000),
        "wall_mbps": size_mb / duration_s if duration_s > 0 else 0.0,
    }
    metrics["error"] = None
    return candidates, metrics


def _metrics(
    enabled: bool,
    duration_s: float,
    size_mb: float,
    count: int,
) -> dict[str, float | int | bool]:
    duration_ms = int(duration_s * 1000)
    return {
        "enabled": enabled,
        "duration_ms": duration_ms,
        "mbps": size_mb / duration_s if duration_s > 0 else 0.0,
        "candidate_count": count,
        "candidates_per_sec": count / duration_s if duration_s > 0 else 0.0,
    }


def analyze_parity(
    expected: list[InjectionRecord],
    python_candidates: list[CandidateKey] | None,
    native_candidates: list[CandidateKey] | None,
) -> dict[str, object]:
    expected_set = {item.key() for item in expected}
    python_set = set(python_candidates or [])
    native_set = set(native_candidates or [])

    duplicate_python = _duplicates(python_candidates or [])
    duplicate_native = _duplicates(native_candidates or [])
    mismatched = _mismatched_ext(python_set, native_set)

    false_positive_common = (python_set & native_set) - expected_set
    false_positive_native_only = native_set - python_set - expected_set
    false_positive_python_only = python_set - native_set - expected_set

    seeded_missing_native = expected_set - native_set if native_candidates is not None else set()
    native_extra_vs_seeded = native_set - expected_set if native_candidates is not None else set()
    parity_missing_vs_python = python_set - native_set if None not in (python_candidates, native_candidates) else set()
    native_extra_vs_python = native_set - python_set if None not in (python_candidates, native_candidates) else set()

    return {
        "seeded_missing_native": len(seeded_missing_native),
        "parity_missing_vs_python": len(parity_missing_vs_python),
        "native_extra_vs_seeded": len(native_extra_vs_seeded),
        "native_extra_vs_python": len(native_extra_vs_python),
        "mismatched_ext": len(mismatched),
        "duplicates_python": len(duplicate_python),
        "duplicates_native": len(duplicate_native),
        "false_positive_common": len(false_positive_common),
        "false_positive_native_only": len(false_positive_native_only),
        "false_positive_python_only": len(false_positive_python_only),
        "seeded_missing_native_items": _items(seeded_missing_native, 50),
        "parity_missing_vs_python_items": _items(parity_missing_vs_python, 50),
        "native_extra_vs_seeded_items": _items(native_extra_vs_seeded, 50),
        "native_extra_vs_python_items": _items(native_extra_vs_python, 50),
        "mismatched_items": mismatched[:50],
        "duplicate_python_items": _items(duplicate_python, 50),
        "duplicate_native_items": _items(duplicate_native, 50),
        "false_positive_common_items_sample": _items(false_positive_common, 50),
        "false_positive_native_only_items": _items(false_positive_native_only, 50),
        "false_positive_python_only_items": _items(false_positive_python_only, 50),
        "analysis_notes": _analysis_notes(
            false_positive_common,
            false_positive_native_only,
            false_positive_python_only,
        ),
    }


def _duplicates(candidates: list[CandidateKey]) -> set[CandidateKey]:
    return {item for item, count in Counter(candidates).items() if count > 1}


def _mismatched_ext(python_set: set[CandidateKey], native_set: set[CandidateKey]) -> list[dict[str, object]]:
    py_by_offset: dict[int, set[tuple[str, str]]] = {}
    native_by_offset: dict[int, set[tuple[str, str]]] = {}
    for offset, sig_id, ext in python_set:
        py_by_offset.setdefault(offset, set()).add((sig_id, ext))
    for offset, sig_id, ext in native_set:
        native_by_offset.setdefault(offset, set()).add((sig_id, ext))

    mismatches: list[dict[str, object]] = []
    for offset in sorted(set(py_by_offset) & set(native_by_offset)):
        if py_by_offset[offset] != native_by_offset[offset]:
            mismatches.append(
                {
                    "offset": offset,
                    "python": sorted(py_by_offset[offset]),
                    "native": sorted(native_by_offset[offset]),
                }
            )
    return mismatches


def _items(items: set[CandidateKey], limit: int) -> list[dict[str, object]]:
    return [
        {"offset": offset, "signature_id": signature_id, "ext": ext}
        for offset, signature_id, ext in sorted(items)[:limit]
    ]


def _analysis_notes(
    false_positive_common: set[CandidateKey],
    false_positive_native_only: set[CandidateKey],
    false_positive_python_only: set[CandidateKey],
) -> list[str]:
    notes = []
    if false_positive_common:
        notes.append(
            "false_positive_common are signatures naturally present in deterministic random noise and detected by both engines."
        )
    if false_positive_native_only:
        notes.append(
            "false_positive_native_only are Rust-only matches; inspect listed offsets before enabling Phase 4."
        )
    if false_positive_python_only:
        notes.append(
            "false_positive_python_only are Python-only matches and imply parity_missing_vs_python when native was run."
        )
    if not notes:
        notes.append("No parity differences or non-seeded false positives detected.")
    return notes


def build_gate(
    mode: Mode,
    native_metrics: dict[str, object] | None,
    parity: dict[str, object],
) -> dict[str, object]:
    native_enabled = bool(native_metrics and native_metrics.get("enabled"))
    rust_mbps = float(native_metrics.get("mbps", 0.0)) if native_metrics else 0.0
    rust_mbps_ok = mode == "python" or (native_enabled and rust_mbps >= RUST_MIN_MBPS)
    seeded_ok = mode == "python" or parity["seeded_missing_native"] == 0
    parity_ok = mode != "both" or parity["parity_missing_vs_python"] == 0
    mismatch_ok = parity["mismatched_ext"] == 0
    duplicates_ok = mode == "python" or parity["duplicates_native"] == 0
    passed = all([rust_mbps_ok, seeded_ok, parity_ok, mismatch_ok, duplicates_ok])
    return {
        "rust_min_mbps": RUST_MIN_MBPS,
        "rust_mbps_ok": rust_mbps_ok,
        "seeded_missing_native_ok": seeded_ok,
        "parity_missing_vs_python_ok": parity_ok,
        "mismatched_ext_ok": mismatch_ok,
        "duplicates_native_ok": duplicates_ok,
        "passed": passed,
        "decision": "native helper eligible for Phase 4 image-only integration"
        if passed and mode == "both"
        else "Phase 3 gate not evaluated for full integration"
        if mode != "both"
        else "native helper is not eligible for Phase 4 yet",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["python", "native", "both"], default="both")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--size-mb", type=int, default=DEFAULT_SIZE_MB)
    parser.add_argument("--seeds", type=int, default=DEFAULT_SEEDS)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--keep-image", action="store_true")
    parser.add_argument("--force-rebuild", action="store_true")
    args = parser.parse_args()

    mode: Mode = args.mode
    carver = FileCarver()
    signatures = selected_signatures(carver)
    signature_by_header = {sig.header: sig for sig in signatures}
    image = args.image or CORPUS_DIR / f"native_phase3_{args.size_mb}mb.img"
    injections = load_or_create_image(
        image,
        signatures,
        size_mb=args.size_mb,
        seeds=args.seeds,
        force_rebuild=args.force_rebuild,
    )

    python_raw: list[CandidateKey] | None = None
    native_raw: list[CandidateKey] | None = None
    python_metrics: dict[str, object] | None = None
    native_metrics: dict[str, object] | None = None

    if mode in {"python", "both"}:
        python_raw, python_metrics = run_python(carver, image, signature_by_header)
    if mode in {"native", "both"}:
        native_raw, native_metrics = run_native(image, signatures)

    parity = analyze_parity(injections, python_raw, native_raw)
    gate = build_gate(mode, native_metrics, parity)

    result = {
        "schema_version": 1,
        "phase": "B1 Phase 3",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": mode,
        "image": {
            "path": str(image),
            "size_bytes": image.stat().st_size,
            "size_mb": args.size_mb,
            "rng_seed": RNG_SEED,
            "kept": bool(args.keep_image or args.image),
        },
        "signatures": {
            "count": len(signatures),
            "families": sorted({sig.family for sig in signatures}),
            "items": [asdict(sig) for sig in signatures],
        },
        "injections": {
            "count": len(injections),
            "items_sample": [asdict(item) for item in injections[:25]],
        },
        "python": python_metrics or {"enabled": False},
        "native": native_metrics or {"enabled": False},
        "parity": parity,
        "gate": gate,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = args.json or RESULTS_DIR / f"native_phase3_{int(time.time())}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))

    if not (args.keep_image or args.image):
        image.unlink(missing_ok=True)
        image.with_suffix(image.suffix + ".manifest.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
