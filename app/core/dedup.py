"""
Lumina - DedupIndex

Interval index for silent dedup between the filesystem enumeration phase and the
carving phase. Used by ScanWorker to suppress carver candidates that overlap
with already-found MFT (or equivalent) file data ranges.
"""

from __future__ import annotations

import bisect


class _DedupIndex:
    """
    Interval index for silent dedup between the filesystem phase and the
    carving phase. Phase 1 calls add() for every data run harvested from
    the MFT (or equivalent); freeze() then merges overlaps so Phase 2 can
    query overlaps() in O(log n).

    Any overlap (tout chevauchement) between a carved candidate and a
    recorded MFT run is treated as the same file — the carved candidate
    is silently dropped. This matches the user-validated semantics:
    results should be clean, no partial-fragment duplicates of named files.
    """

    def __init__(self) -> None:
        self._raw: list[tuple[int, int]] = []
        self._starts: list[int] = []
        self._ends:   list[int] = []

    def add(self, start: int, length: int) -> None:
        if length > 0 and start >= 0:
            self._raw.append((start, start + length))

    def freeze(self) -> None:
        """Sort + merge overlapping ranges; enables O(log n) overlaps() queries."""
        if not self._raw:
            return
        self._raw.sort()
        merged: list[tuple[int, int]] = []
        for s, e in self._raw:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        self._starts = [r[0] for r in merged]
        self._ends   = [r[1] for r in merged]

    def overlaps(self, start: int, length: int) -> bool:
        if length <= 0 or start < 0 or not self._starts:
            return False
        end = start + length
        pos = bisect.bisect_right(self._starts, start)
        if pos > 0 and self._ends[pos - 1] > start:
            return True
        return pos < len(self._starts) and self._starts[pos] < end

    def __len__(self) -> int:
        return len(self._starts)
