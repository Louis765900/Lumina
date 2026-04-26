"""
Micro-benchmark: re.Pattern.finditer vs pyahocorasick.Automaton.iter
over a synthetic 256 MB buffer seeded with random header signatures.

Run:  python scripts/bench_carver.py

Optional environment variables:
  BENCH_CARVER_MB=32
  BENCH_CARVER_SEEDS=1250
"""
from __future__ import annotations

import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.file_carver import FileCarver

BUF_SIZE = int(os.environ.get("BENCH_CARVER_MB", "256")) * 1024 * 1024
SEED_COUNT = int(os.environ.get("BENCH_CARVER_SEEDS", "10000"))
RNG_SEED = 0xC0DE


def build_buffer(headers: list[bytes]) -> bytes:
    rng = random.Random(RNG_SEED)
    buf = bytearray(rng.randbytes(BUF_SIZE))
    for _ in range(SEED_COUNT):
        h = rng.choice(headers)
        off = rng.randrange(0, BUF_SIZE - len(h))
        buf[off:off + len(h)] = h
    return bytes(buf)


def bench_regex(pattern: re.Pattern[bytes], data: bytes) -> tuple[float, int]:
    t0 = time.perf_counter()
    hits = sum(1 for _ in pattern.finditer(data))
    return time.perf_counter() - t0, hits


def bench_ahocorasick(automaton, data: bytes) -> tuple[float, int]:
    t0 = time.perf_counter()
    # pyahocorasick's wheel is built for str keys on Windows. latin-1 is a
    # bijection for bytes 0..255, so this keeps the benchmark byte-exact while
    # including the conversion cost paid by the production fallback path.
    text = data.decode("latin-1")
    hits = sum(1 for _ in automaton.iter(text))
    return time.perf_counter() - t0, hits


def main() -> None:
    carver = FileCarver()
    headers = list(carver._header_map.keys())
    print(f"Signatures: {len(headers)}")
    print(f"Buffer: {BUF_SIZE / (1024 * 1024):.0f} MB  seeds: {SEED_COUNT}")

    print("Building buffer...")
    data = build_buffer(headers)

    # --- re ---
    print("\n[re] warmup + run x3")
    re_times = []
    for i in range(3):
        t, n = bench_regex(carver._pattern, data)
        mbps = (BUF_SIZE / (1024 * 1024)) / t
        re_times.append(t)
        print(f"  run {i+1}: {t:.3f}s  hits={n}  {mbps:.1f} MB/s")
    re_best = min(re_times)

    # --- ahocorasick ---
    try:
        import ahocorasick
    except ImportError:
        print("\n[ahocorasick] NOT INSTALLED - install via `pip install pyahocorasick` to benchmark")
        return

    print("\n[ahocorasick] building automaton...")
    a = ahocorasick.Automaton()
    for h in headers:
        a.add_word(h.decode("latin-1"), h)
    a.make_automaton()

    print("[ahocorasick] warmup + run x3")
    ac_times = []
    for i in range(3):
        t, n = bench_ahocorasick(a, data)
        mbps = (BUF_SIZE / (1024 * 1024)) / t
        ac_times.append(t)
        print(f"  run {i+1}: {t:.3f}s  hits={n}  {mbps:.1f} MB/s")
    ac_best = min(ac_times)

    speedup = re_best / ac_best if ac_best > 0 else 0
    print("\n-- Result -------------------------------")
    print(f"  re          best: {re_best:.3f}s  ({(BUF_SIZE / (1024 * 1024)) / re_best:.1f} MB/s)")
    print(f"  aho-corasick best: {ac_best:.3f}s  ({(BUF_SIZE / (1024 * 1024)) / ac_best:.1f} MB/s)")
    print(f"  speedup: {speedup:.2f}x")
    print(f"  decision: {'SWAP to aho-corasick' if speedup >= 2.0 else 'KEEP re (below 2x threshold)'}")


if __name__ == "__main__":
    main()
