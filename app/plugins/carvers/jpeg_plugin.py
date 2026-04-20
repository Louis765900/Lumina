"""
Lumina v2.0 — JPEG carver plugin.

Detects all JFIF / Exif / raw DCT variants and validates candidates via
standard JPEG marker inspection (SOI + 0xFF marker byte + known app/frame
segments within the first 256 B).

Fragmentation handling: when the naive FF D9 lookup fails or returns a
suspiciously small file (< 2 KB), `estimate_size()` falls back to a full
syntactic marker walk inspired by FileScraper / JPEG-Restorer. The parser
follows the ISO/IEC 10918-1 segment structure byte-by-byte on the buffer
already in RAM — no disk I/O, no thread blocking. Bad-sector recovery
(1 MB skip on OSError/WinError 483) remains the FileCarver's
responsibility upstream.
"""

from __future__ import annotations

from .base_plugin import BaseCarverPlugin

# Integrity scoring for fragmented reassembly (see estimate_size)
_FRAGMENT_MIN_SIZE = 2048  # bytes — below this, naive footer is suspect


class JpegPlugin(BaseCarverPlugin):
    extension          = ".jpg"
    category           = "image"
    min_size           = 128
    default_size_kb    = 2048
    handled_extensions = (".jpg", ".jpeg")

    @property
    def signatures(self) -> list[tuple[bytes, bytes | None]]:
        return [
            (b"\xFF\xD8\xFF\xE0", b"\xFF\xD9"),   # JFIF
            (b"\xFF\xD8\xFF\xE1", b"\xFF\xD9"),   # Exif
            (b"\xFF\xD8\xFF\xDB", b"\xFF\xD9"),   # DQT / raw
            (b"\xFF\xD8\xFF\xC0", b"\xFF\xD9"),   # Baseline DCT
            (b"\xFF\xD8\xFF\xC2", b"\xFF\xD9"),   # Progressive DCT
            (b"\xFF\xD8\xFF\xC4", b"\xFF\xD9"),   # Huffman table
            (b"\xFF\xD8\xFF\xE2", b"\xFF\xD9"),   # ICC profile
            (b"\xFF\xD8\xFF\xE8", b"\xFF\xD9"),   # SPIFF
            (b"\xFF\xD8\xFF\xEE", b"\xFF\xD9"),   # Adobe
            (b"\xFF\xD8\xFF\xFE", b"\xFF\xD9"),   # Comment
        ]

    def validate_mime(self, file_bytes: bytes) -> bool:
        if len(file_bytes) < 4:
            return False

        # Must begin with SOI (FF D8) followed by a marker (FF XX)
        if file_bytes[0] != 0xFF or file_bytes[1] != 0xD8 or file_bytes[2] != 0xFF:
            return False

        marker = file_bytes[3]
        # Valid JPEG markers span 0xC0-0xFE (excluding 0xFF repeat and 0x00 stuffing)
        if not (0xC0 <= marker <= 0xFE):
            return False

        head = file_bytes[:64]
        # Fast path: well-known ASCII magic for JFIF / Exif / Adobe variants
        if b"JFIF" in head or b"Exif" in head or b"Adobe" in head:
            return True

        # Fallback: scan first 256 B for at least one structural marker
        # (DQT 0xDB, SOF0-SOF15 0xC0-0xCF, SOS 0xDA, DRI 0xDD)
        scan = file_bytes[:256]
        limit = len(scan) - 1
        for i in range(limit):
            if scan[i] != 0xFF:
                continue
            b = scan[i + 1]
            if b == 0xDB or (0xC0 <= b <= 0xCF) or b in (0xDA, 0xDD):
                return True
        return False

    def estimate_size(
        self,
        data: bytes,
        start: int,
        footer: bytes | None,
    ) -> tuple[int, int]:
        """
        Locate the end of a JPEG starting at `start`.

        Strategy:
          1. Fast path — naive search for FF D9. If found AND the resulting
             file is ≥ 2 KB, trust it (integrity 100).
          2. Slow path — syntactic marker walk (`_parse_structure`) that
             follows the JPEG segment structure. Used when the naive footer
             is missing or suspiciously close to the header (possible
             fragment with a premature 0xFF 0xD9 sequence inside entropy
             data that wasn't properly byte-stuffed in a corrupt source).
        """
        # ── 1. Fast path ──────────────────────────────────────────────────
        end = data.find(b"\xFF\xD9", start + 4)
        if end != -1:
            size = end - start + 2
            if size >= _FRAGMENT_MIN_SIZE:
                return max(1, size // 1024), 100

        # ── 2. Syntactic fallback ─────────────────────────────────────────
        return self._parse_structure(data, start)

    # ── Internal: JPEG structural parser ──────────────────────────────────
    def _parse_structure(self, data: bytes, start: int) -> tuple[int, int]:
        """
        Walk the JPEG segment structure starting at `start` and return
        (size_kb, integrity_score).

        - Returns (size, 100) when a real EOI (FF D9) is found via parsing.
        - Returns (size, 70) when the parser finishes cleanly without EOI
          (fragment reassembly — last valid scan boundary used).
        - Returns (default_size_kb, 75) when an invalid marker is hit
          (MIME already validated upstream, so we keep a reasonable guess).

        No I/O is performed — only operates on `data` already in RAM.
        """
        n = len(data)
        # SOI (FF D8) is at [start, start+1]; payload begins after.
        p = start + 2
        last_valid_end: int | None = None

        while p < n - 1:
            # Expect a marker prefix 0xFF
            if data[p] != 0xFF:
                break

            # Collapse fill bytes (FF FF FF ... FF XX)
            while p + 1 < n and data[p + 1] == 0xFF:
                p += 1
            if p + 1 >= n:
                break
            marker = data[p + 1]

            # Byte stuffing (FF 00) — shouldn't appear outside entropy, treat as benign
            if marker == 0x00:
                p += 2
                continue

            # RSTn markers (FF D0..D7) — standalone, no payload
            if 0xD0 <= marker <= 0xD7:
                p += 2
                continue

            # EOI (FF D9) — clean end of image
            if marker == 0xD9:
                size_bytes = (p + 2) - start
                return max(1, size_bytes // 1024), 100

            # SOS (FF DA) — Start of Scan: header segment then entropy data
            if marker == 0xDA:
                if p + 4 > n:
                    break
                seg_len = (data[p + 2] << 8) | data[p + 3]
                if seg_len < 2:
                    break
                p += 2 + seg_len  # skip SOS segment header
                # Now scan entropy-coded data byte-by-byte until we hit a
                # real marker (FF XX where XX != 0x00 and XX != 0xFF).
                # RSTn markers (FF D0..D7) are legal inside the scan stream.
                while p < n - 1:
                    if data[p] == 0xFF:
                        nxt = data[p + 1]
                        if nxt == 0x00:
                            p += 2           # stuffed literal 0xFF
                            continue
                        if nxt == 0xFF:
                            p += 1           # fill byte, keep looking
                            continue
                        if 0xD0 <= nxt <= 0xD7:
                            p += 2           # restart marker, still in scan
                            continue
                        # genuine marker — end of this scan
                        last_valid_end = p
                        break
                    p += 1
                else:
                    break
                continue

            # Standard length-prefixed segments: APPn, DQT, DHT, SOFn, DRI,
            # COM, etc. Layout: FF XX LEN_HI LEN_LO <payload (LEN-2 bytes)>
            if 0xC0 <= marker <= 0xFE:
                if p + 4 > n:
                    break
                seg_len = (data[p + 2] << 8) | data[p + 3]
                if seg_len < 2:
                    break
                p += 2 + seg_len
                continue

            # Unknown marker — corruption, give up structural walk
            break

        # Clean walk but no EOI → treat as reassembled fragment
        if last_valid_end is not None:
            size_bytes = last_valid_end - start
            if size_bytes > 0:
                return max(1, size_bytes // 1024), 70

        # Fallback: parser blocked on garbage — MIME already passed upstream
        return self.default_size_kb, 75
