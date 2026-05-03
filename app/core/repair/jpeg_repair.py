"""
Lumina — JPEG file repair module.

Repairs common JPEG corruption patterns:
  1. Missing SOI marker (FF D8)
  2. Missing EOI marker (FF D9)
  3. Truncated marker segments (invalid length fields)
  4. Completely invalid files

stdlib-only: no Pillow dependency.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("lumina.recovery")

# JPEG marker constants
_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"
_MARKERS_NO_LENGTH = {
    0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7,  # RST0-RST7
    0xD8,  # SOI
    0xD9,  # EOI
    0x01,  # TEM
}
_MARKER_SOS = 0xDA  # Start of Scan


@dataclass
class RepairReport:
    original_size: int
    repaired_size: int
    issues_found: list[str] = field(default_factory=list)
    repaired: bool = False


def repair_jpeg(input_path: str, output_path: str | None = None) -> RepairReport:
    """
    Attempt to repair a JPEG file.

    Args:
        input_path:  Path to the (possibly corrupt) JPEG file.
        output_path: Where to write the repaired file. Defaults to
                     input_path + ".repaired.jpg".

    Returns:
        RepairReport with details of what was found and fixed.
    """
    data = Path(input_path).read_bytes()
    report = RepairReport(original_size=len(data), repaired_size=len(data))

    if not data:
        report.issues_found.append("Empty file — cannot repair")
        return report

    # --- Step 1: Ensure SOI marker ---
    if not data.startswith(_SOI):
        # Look for SOI anywhere in the first 512 bytes
        idx = data.find(_SOI, 0, 512)
        if idx > 0:
            data = data[idx:]
            report.issues_found.append(f"Stripped {idx} garbage bytes before SOI")
        else:
            # Prepend SOI
            data = _SOI + data
            report.issues_found.append("Added missing SOI marker")

    # --- Step 2: Walk markers and fix lengths ---
    data = _fix_marker_structure(data, report)

    # --- Step 3: Ensure EOI marker ---
    if not data.endswith(_EOI):
        data = data + _EOI
        report.issues_found.append("Added missing EOI marker")

    # --- Write output ---
    if output_path is None:
        output_path = str(input_path) + ".repaired.jpg"

    Path(output_path).write_bytes(data)
    report.repaired_size = len(data)
    report.repaired = True
    _log.info(
        "[jpeg_repair] Repaired %s → %s (%d issues).",
        input_path, output_path, len(report.issues_found),
    )
    return report


def _fix_marker_structure(data: bytes, report: RepairReport) -> bytes:
    """
    Walk JPEG marker segments. Fix segments where the declared length
    would overflow the buffer. Returns (possibly modified) data bytes.
    """
    output = bytearray()
    i = 0
    n = len(data)

    if n < 2:
        return data

    # Copy SOI
    output.extend(data[0:2])
    i = 2

    while i < n - 1:
        if data[i] != 0xFF:
            # Lost sync — search for next marker
            next_ff = data.find(b"\xff", i + 1)
            if next_ff == -1:
                # Rest of data — append as-is (might be entropy data)
                output.extend(data[i:])
                break
            # Skip to next potential marker
            i = next_ff
            continue

        marker_byte = data[i + 1]

        # Skip fill bytes (0xFF 0xFF)
        if marker_byte == 0xFF:
            output.append(data[i])
            i += 1
            continue

        if marker_byte in _MARKERS_NO_LENGTH:
            # Single marker, no length field
            output.extend(data[i:i + 2])
            i += 2
            if marker_byte == 0xD9:  # EOI
                break
            continue

        if marker_byte == _MARKER_SOS:
            # SOS: copy the header, then scan entropy stream until EOI or next RST/SOF
            if i + 3 >= n:
                output.extend(data[i:])
                break
            sos_len = (data[i + 2] << 8) | data[i + 3]
            # SOS segment header
            sos_end = i + 2 + sos_len
            if sos_end > n:
                sos_end = n
            output.extend(data[i:sos_end])
            # Now scan entropy coded data until FF D9 or another significant marker
            j = sos_end
            while j < n - 1:
                if data[j] == 0xFF:
                    next_b = data[j + 1]
                    if next_b == 0x00 or next_b == 0xFF:
                        # Stuffed byte or fill byte — part of entropy data
                        output.extend(data[j:j + 2])
                        j += 2
                        continue
                    if 0xD0 <= next_b <= 0xD7:
                        # RST marker — part of entropy data
                        output.extend(data[j:j + 2])
                        j += 2
                        continue
                    # Real marker — end of entropy data
                    break
                output.append(data[j])
                j += 1
            i = j
            continue

        # Normal marker with length
        if i + 3 >= n:
            output.extend(data[i:])
            break
        seg_len = (data[i + 2] << 8) | data[i + 3]
        seg_end = i + 2 + seg_len

        if seg_len < 2:
            # Invalid length — skip marker pair, search for next
            report.issues_found.append(
                f"Invalid segment length {seg_len} at offset {i} for marker 0xFF{marker_byte:02X}"
            )
            next_marker = data.find(b"\xff", i + 2)
            if next_marker == -1:
                output.extend(data[i:])
                break
            i = next_marker
            continue

        if seg_end > n:
            # Segment overflows — truncate to available data
            report.issues_found.append(
                f"Segment 0xFF{marker_byte:02X} at {i} declares length {seg_len} "
                f"but only {n - i - 2} bytes remain — truncating"
            )
            output.extend(data[i:n])
            break

        output.extend(data[i:seg_end])
        i = seg_end

    return bytes(output)


def is_valid_jpeg(path: str) -> bool:
    """Quick validity check: SOI + EOI present and non-empty."""
    try:
        data = Path(path).read_bytes()
        return len(data) >= 4 and data[:2] == _SOI and data[-2:] == _EOI
    except OSError:
        return False
