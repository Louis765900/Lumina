"""
Lumina — MP4/MOV file repair module.

Repairs common MP4/MOV corruption patterns:
  1. Invalid atom sizes (recalculate from data)
  2. moov atom after mdat (reorder for fast-start)
  3. Truncated moov (log as unrecoverable)

stdlib-only: no external dependencies.

Reference: ISO/IEC 14496-12 (ISOBMFF) and Apple QuickTime File Format spec.
"""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("lumina.recovery")


@dataclass
class Mp4Atom:
    offset: int
    size: int
    type_: str
    data: bytes


@dataclass
class Mp4RepairReport:
    original_size: int
    repaired_size: int
    issues_found: list[str] = field(default_factory=list)
    repaired: bool = False


def _parse_atoms(data: bytes) -> list[Mp4Atom]:
    """Parse top-level atoms from *data*. Returns list of Mp4Atom."""
    atoms: list[Mp4Atom] = []
    i = 0
    n = len(data)
    while i < n:
        if i + 8 > n:
            break
        size = struct.unpack_from(">I", data, i)[0]
        atom_type = data[i + 4:i + 8]
        try:
            type_str = atom_type.decode("latin-1")
        except Exception:
            type_str = "????"

        if size == 1:
            # Extended 64-bit size
            if i + 16 > n:
                break
            size = struct.unpack_from(">Q", data, i + 8)[0]
            header_size = 16
        elif size == 0:
            # Atom extends to end of file
            size = n - i
            header_size = 8
        else:
            header_size = 8

        if size < header_size or i + size > n:
            # Clamp to available data
            size = n - i

        atoms.append(Mp4Atom(
            offset=i,
            size=size,
            type_=type_str,
            data=data[i:i + size],
        ))
        i += size
        if i == 0 or size == 0:
            break

    return atoms


def repair_mp4(input_path: str, output_path: str | None = None) -> Mp4RepairReport:
    """
    Attempt to repair a MP4/MOV file.

    Strategies applied (in order):
      1. Parse atom structure; skip/fix atoms with invalid sizes.
      2. If moov appears after mdat, reorder: ftyp → moov → mdat (fast-start).
      3. Ensure file ends after the last valid atom.

    Args:
        input_path:  Path to the (possibly corrupt) MP4/MOV file.
        output_path: Output path. Defaults to input_path + ".repaired.mp4".

    Returns:
        Mp4RepairReport with repair details.
    """
    data = Path(input_path).read_bytes()
    report = Mp4RepairReport(original_size=len(data), repaired_size=len(data))

    if len(data) < 8:
        report.issues_found.append("File too small to be a valid MP4")
        return report

    atoms = _parse_atoms(data)
    if not atoms:
        report.issues_found.append("No valid atoms found")
        return report

    atom_types = [a.type_ for a in atoms]

    # Check for moov
    has_moov = "moov" in atom_types
    has_mdat = "mdat" in atom_types

    if not has_mdat:
        report.issues_found.append("No mdat atom found — file may be empty or completely corrupt")

    if not has_moov:
        report.issues_found.append(
            "No moov atom found — recording may have been interrupted. "
            "Full moov reconstruction requires codec-specific analysis (not implemented in v1)."
        )

    # Strategy: reorder if moov is after mdat
    reordered = False
    if has_moov and has_mdat:
        moov_idx = atom_types.index("moov")
        mdat_idx = atom_types.index("mdat")
        if moov_idx > mdat_idx:
            report.issues_found.append("moov atom is after mdat — reordering for fast-start")
            reordered = True
            # Reorder: ftyp (if present) → moov → all others
            ordered: list[Mp4Atom] = []
            for a in atoms:
                if a.type_ == "ftyp":
                    ordered.append(a)
            for a in atoms:
                if a.type_ == "moov":
                    ordered.append(a)
            for a in atoms:
                if a.type_ not in ("ftyp", "moov"):
                    ordered.append(a)
            atoms = ordered

    # Strategy: fix atoms with declared size > available data (already clamped in _parse_atoms)
    # Check for any atoms that were clamped
    for atom in _parse_atoms(data):  # re-parse original to detect clamping
        raw_size = struct.unpack_from(">I", data, atom.offset)[0]
        if raw_size not in (0, 1):
            expected_end = atom.offset + raw_size
            if expected_end > len(data):
                report.issues_found.append(
                    f"Atom '{atom.type_}' at offset {atom.offset} declares size "
                    f"{raw_size} but file is smaller — truncated"
                )

    if output_path is None:
        output_path = str(input_path) + ".repaired.mp4"

    output_data = b"".join(a.data for a in atoms)
    Path(output_path).write_bytes(output_data)
    report.repaired_size = len(output_data)
    report.repaired = True

    _log.info(
        "[mp4_repair] Repaired %s → %s (%d issues, reordered=%s).",
        input_path, output_path, len(report.issues_found), reordered,
    )
    return report


def is_valid_mp4(path: str) -> bool:
    """Quick check: file has at least ftyp or moov at a reasonable position."""
    try:
        data = Path(path).read_bytes()
        if len(data) < 8:
            return False
        atoms = _parse_atoms(data)
        types = {a.type_ for a in atoms}
        return bool({"ftyp", "moov"} & types)
    except OSError:
        return False
