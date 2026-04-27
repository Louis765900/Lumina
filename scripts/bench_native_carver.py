"""
Preliminary benchmark for B1 Phase 2.

This script compares Python's current signature regex hot path with the Rust
JSONL helper candidate stream on a synthetic image. Full parity gates are owned
by Phase 3; this script establishes the versioned harness.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.file_carver import FileCarver
from app.core.native.client import NativeScanClient
from app.core.native.protocol import NativeCandidate, NativeSignature, NativeSource

RESULTS_DIR = Path("benchmarks/results")
RNG_SEED = 0xB100


def build_image(path: Path, headers: list[bytes], size_mb: int, seeds: int) -> None:
    rng = random.Random(RNG_SEED)
    size = size_mb * 1024 * 1024
    data = bytearray(rng.randbytes(size))
    for _ in range(seeds):
        header = rng.choice(headers)
        off = rng.randrange(0, size - len(header))
        data[off : off + len(header)] = header
    path.write_bytes(data)


def python_candidates(carver: FileCarver, data: bytes) -> set[tuple[int, bytes]]:
    return {(m.start(), m.group(0)) for m in carver._pattern.finditer(data)}


def native_candidates(
    image: Path,
    signatures: list[NativeSignature],
) -> tuple[set[tuple[int, str]], dict[str, float | int | str]]:
    client = NativeScanClient(engine="native")
    found: list[NativeCandidate] = []
    started = time.perf_counter()
    summary = client.scan_candidates(
        NativeSource(kind="image", path=str(image), size_bytes=image.stat().st_size),
        signatures,
        on_candidates=lambda batch: found.extend(batch),
    )
    elapsed = time.perf_counter() - started
    return (
        {(item.offset, item.signature_id) for item in found},
        {
            "engine": summary.engine,
            "duration_s": elapsed,
            "mbps": summary.mbps,
            "candidate_count": summary.candidate_count,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path)
    parser.add_argument("--size-mb", type=int, default=64)
    parser.add_argument("--seeds", type=int, default=2500)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    carver = FileCarver()
    header_items = list(carver._header_map.items())
    headers = [header for header, _entry in header_items]

    image = args.image or Path("benchmarks") / f"native_synth_{args.size_mb}mb.img"
    image.parent.mkdir(parents=True, exist_ok=True)
    if args.image is None:
        build_image(image, headers, args.size_mb, args.seeds)

    data = image.read_bytes()
    started = time.perf_counter()
    py_found = python_candidates(carver, data)
    py_elapsed = time.perf_counter() - started

    sig_by_header: dict[bytes, NativeSignature] = {}
    for header, (ext, _footer, _plugin) in header_items:
        sig_id = f"{ext.lstrip('.')}_{header.hex()}"
        sig_by_header[header] = NativeSignature(sig_id, ext, header)

    native_found: set[tuple[int, str]] = set()
    native_result: dict[str, float | int | str] | None = None
    native_error: str | None = None
    helper = NativeScanClient(engine="native").helper_path()
    if helper.exists():
        try:
            native_found, native_result = native_candidates(
                image, list(sig_by_header.values())
            )
        except Exception as exc:
            native_error = str(exc)
    else:
        native_error = f"native helper not built: {helper}"

    py_as_native_ids = {
        (offset, sig_by_header[header].signature_id) for offset, header in py_found
    }
    result = {
        "image": str(image),
        "size_bytes": image.stat().st_size,
        "python": {
            "duration_s": py_elapsed,
            "mbps": (image.stat().st_size / (1024 * 1024)) / py_elapsed,
            "candidate_count": len(py_found),
        },
        "native": native_result,
        "native_error": native_error,
        "parity": {
            "missing_candidates": len(py_as_native_ids - native_found),
            "extra_candidates": len(native_found - py_as_native_ids),
        }
        if native_result is not None
        else None,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = args.json or RESULTS_DIR / f"native_phase2_{int(time.time())}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
