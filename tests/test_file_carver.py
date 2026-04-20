"""
Tests for the Lumina v2.0 recovery engine.

Covers the four refactoring objectives:
  • Obj 1 — NTFS MFT parser: silent fallback when MFT is unreachable.
  • Obj 2 — Plugin architecture + Apache Tika-style MIME validation.
  • Obj 3 — JPEG fragmentation heuristics (syntactic marker walker).
  • Obj 4 — FileCarver end-to-end detection against synthetic buffers.

All disk I/O is mocked — tests run entirely in RAM.
"""

from __future__ import annotations

import os
import struct
import tempfile
from unittest.mock import patch

import pytest

from app.core.file_carver import (
    MAX_FILE_CAP,
    SIGNATURES,
    SKIP_ON_ERR,
    FileCarver,
    _optimal_block_size,
)
from app.core.fs_parser import NTFSParser
from app.plugins.carvers.base_plugin import BaseCarverPlugin
from app.plugins.carvers.jpeg_plugin import JpegPlugin
from app.plugins.carvers.pdf_plugin import PdfPlugin
from app.plugins.carvers.zip_plugin import ZipPlugin


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _temp_file(content: bytes) -> str:
    fd, path = tempfile.mkstemp(prefix="lumina_test_")
    os.write(fd, content)
    os.close(fd)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Constants / adaptive block size
# ─────────────────────────────────────────────────────────────────────────────

class TestConstants:
    def test_skip_on_err_is_one_megabyte(self):
        assert SKIP_ON_ERR == 1024 * 1024

    def test_max_file_cap_is_500mb(self):
        assert MAX_FILE_CAP == 500 * 1024 * 1024

    def test_optimal_block_size_small_drive(self):
        # Under 100 GB → 512 KB block
        assert _optimal_block_size(50 * 1024**3) == 512 * 1024

    def test_optimal_block_size_mid_drive(self):
        # 100 GB to 1 TB → 4 MB block
        assert _optimal_block_size(500 * 1024**3) == 4 * 1024 * 1024

    def test_optimal_block_size_large_drive(self):
        # Over 1 TB → 16 MB block
        assert _optimal_block_size(2 * 1024**4) == 16 * 1024 * 1024


# ─────────────────────────────────────────────────────────────────────────────
# SIGNATURES legacy table — still used for non-plugin formats
# ─────────────────────────────────────────────────────────────────────────────

class TestLegacySignatures:
    def test_expected_legacy_extensions_present(self):
        """The legacy SIGNATURES dict still covers the formats without plugins."""
        # PNG, MP4, MOV, DOC... are still in the legacy table
        expected_legacy = {".png", ".mp4", ".mov", ".doc", ".rar", ".7z"}
        assert expected_legacy.issubset(set(SIGNATURES.keys()))

    def test_plugin_extensions_not_required_in_legacy(self):
        """Plugin-handled formats (.jpg, .pdf, zip family) may still
        appear in legacy for backwards-compat, but FileCarver will filter
        them out at init time (cf. _build_signature_tables)."""
        carver = FileCarver()
        plugin_handled = set()
        for p in carver._plugins:
            plugin_handled.update(p.handled_extensions)
        # A plugin must exist for each of these
        assert ".jpg" in plugin_handled
        assert ".pdf" in plugin_handled
        assert ".zip" in plugin_handled


# ─────────────────────────────────────────────────────────────────────────────
# FileCarver plugin loading
# ─────────────────────────────────────────────────────────────────────────────

class TestFileCarverInit:
    def test_plugins_loaded(self):
        carver = FileCarver()
        plugin_types = {type(p).__name__ for p in carver._plugins}
        assert "JpegPlugin" in plugin_types
        assert "PdfPlugin" in plugin_types
        assert "ZipPlugin" in plugin_types

    def test_header_map_populated(self):
        carver = FileCarver()
        assert len(carver._header_map) > 0
        # Plugin signatures override legacy — a JPEG header must map to JpegPlugin
        entry = carver._header_map.get(b"\xFF\xD8\xFF\xE0")
        assert entry is not None
        ext, _footer, plugin = entry
        assert ext == ".jpg"
        assert isinstance(plugin, JpegPlugin)

    def test_max_header_len_matches(self):
        carver = FileCarver()
        longest = max(len(h) for h in carver._header_map)
        assert carver._max_header_len == longest

    def test_regex_pattern_compiled(self):
        carver = FileCarver()
        # The pattern should match a known header
        m = carver._pattern.search(b"\x00\x00" + b"\xFF\xD8\xFF\xE0" + b"\x00")
        assert m is not None
        assert m.group(0) == b"\xFF\xD8\xFF\xE0"


# ─────────────────────────────────────────────────────────────────────────────
# Legacy _estimate_size — now takes (data, start, footer, ext)
# ─────────────────────────────────────────────────────────────────────────────

class TestLegacyEstimateSize:
    def test_with_footer_found(self):
        carver = FileCarver()
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2048 + b"IEND\xaeB`\x82"
        size_kb, integrity = carver._estimate_size(data, 0, b"IEND\xaeB`\x82", ".png")
        assert integrity == 100
        assert size_kb >= 2

    def test_without_footer_returns_default(self):
        carver = FileCarver()
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000
        size_kb, integrity = carver._estimate_size(data, 0, None, ".png")
        assert integrity == 60
        assert size_kb == 1024  # default for .png

    def test_footer_not_found_falls_back_to_default(self):
        carver = FileCarver()
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500
        size_kb, integrity = carver._estimate_size(data, 0, b"IEND\xaeB`\x82", ".png")
        # Footer not present → heuristic default
        assert integrity == 60
        assert size_kb == 1024


# ─────────────────────────────────────────────────────────────────────────────
# Objective 2 — MIME validation rejects false positives
# ─────────────────────────────────────────────────────────────────────────────

class TestMimeValidation:
    """A valid magic-number prefix alone must not trick plugin.validate_mime()
    — the content itself must match the format specification."""

    # ── JPEG ──────────────────────────────────────────────────────────────
    def test_jpeg_valid_jfif_passes(self):
        plugin = JpegPlugin()
        # Genuine JFIF: SOI + APP0 + "JFIF" in ASCII + filler
        buf = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        buf += b"\x00" * 256
        assert plugin.validate_mime(buf) is True

    def test_jpeg_valid_exif_passes(self):
        plugin = JpegPlugin()
        buf = b"\xFF\xD8\xFF\xE1\x00\x10Exif\x00\x00" + b"\x00" * 256
        assert plugin.validate_mime(buf) is True

    def test_jpeg_valid_without_ascii_magic_via_dqt(self):
        """A JPEG header followed by a DQT marker (0xFF 0xDB) must pass
        even without the JFIF/Exif ASCII signature."""
        plugin = JpegPlugin()
        # SOI + marker byte + DQT somewhere in the first 256 B
        buf = b"\xFF\xD8\xFF\xDB\x00\x43" + b"\x10" * 64 + b"\x00" * 200
        assert plugin.validate_mime(buf) is True

    def test_jpeg_rejects_too_short(self):
        plugin = JpegPlugin()
        assert plugin.validate_mime(b"\xFF\xD8") is False

    def test_jpeg_rejects_bad_magic(self):
        plugin = JpegPlugin()
        # Starts with \xFF\xD8 but third byte is 0x00 (not 0xFF)
        buf = b"\xFF\xD8\x00\xE0" + b"\x00" * 256
        assert plugin.validate_mime(buf) is False

    def test_jpeg_rejects_false_positive(self):
        """The magic bytes \\xFF\\xD8\\xFF\\xE0 can appear inside arbitrary
        binary data. If the 4 KB window has no structural marker at all,
        validate_mime must return False."""
        plugin = JpegPlugin()
        # First 4 B look like a JPEG header, but rest is garbage with
        # deliberately no 0xFF bytes. Marker byte E0 is in valid range but
        # no JFIF/Exif/Adobe/DQT/SOF/SOS follows.
        buf = b"\xFF\xD8\xFF\xE0" + bytes(range(32)) * 10  # no 0xFF inside
        # Make sure no 0xFF byte appears in the scanned window after the head
        filtered = bytes(b for b in buf[4:256] if b != 0xFF)
        buf = buf[:4] + filtered[:252]
        assert plugin.validate_mime(buf) is False

    def test_jpeg_rejects_invalid_marker_byte(self):
        plugin = JpegPlugin()
        # 4th byte is 0xBF — below valid marker range (0xC0..0xFE)
        buf = b"\xFF\xD8\xFF\xBF" + b"\x00" * 256
        assert plugin.validate_mime(buf) is False

    # ── PDF ───────────────────────────────────────────────────────────────
    def test_pdf_valid_versions_pass(self):
        plugin = PdfPlugin()
        for ver in (b"1.0", b"1.4", b"1.7", b"2.0", b"2.9"):
            buf = b"%PDF-" + ver + b"\n" + b"\x00" * 256
            assert plugin.validate_mime(buf) is True, f"failed on {ver!r}"

    def test_pdf_rejects_invalid_version(self):
        plugin = PdfPlugin()
        # PDF 1.8 does not exist — per ISO 32000 only 1.0-1.7 / 2.0-2.9
        buf = b"%PDF-1.8\n" + b"\x00" * 256
        assert plugin.validate_mime(buf) is False

    def test_pdf_rejects_bogus_magic(self):
        plugin = PdfPlugin()
        # Matches magic start but no valid version tuple
        buf = b"%PDF-XX\n" + b"\x00" * 256
        assert plugin.validate_mime(buf) is False

    def test_pdf_rejects_too_short(self):
        plugin = PdfPlugin()
        assert plugin.validate_mime(b"%PDF-1") is False

    # ── ZIP ───────────────────────────────────────────────────────────────
    def test_zip_valid_local_file_header_passes(self):
        plugin = ZipPlugin()
        # PK\x03\x04 + LFH: version=20, flags=0, method=8 (deflate),
        # time/date, crc, compsize, uncompsize, name_len=8, extra_len=0
        lfh = (
            b"PK\x03\x04"
            + struct.pack("<H", 20)   # version needed
            + struct.pack("<H", 0)    # flags
            + struct.pack("<H", 8)    # method = deflate
            + b"\x00" * 8             # time/date/crc
            + struct.pack("<I", 100)  # comp size
            + struct.pack("<I", 200)  # uncomp size
            + struct.pack("<H", 8)    # name len
            + struct.pack("<H", 0)    # extra len
            + b"file.txt"
        )
        assert plugin.validate_mime(lfh) is True

    def test_zip_rejects_invalid_method(self):
        plugin = ZipPlugin()
        # method = 77 (not in valid set)
        lfh = (
            b"PK\x03\x04"
            + struct.pack("<H", 20)
            + struct.pack("<H", 0)
            + struct.pack("<H", 77)   # invalid compression method
            + b"\x00" * 8
            + struct.pack("<I", 100)
            + struct.pack("<I", 200)
            + struct.pack("<H", 8)
            + struct.pack("<H", 0)
            + b"file.txt"
        )
        assert plugin.validate_mime(lfh) is False

    def test_zip_rejects_zero_name_length(self):
        plugin = ZipPlugin()
        lfh = (
            b"PK\x03\x04"
            + struct.pack("<H", 20)
            + struct.pack("<H", 0)
            + struct.pack("<H", 8)
            + b"\x00" * 8
            + struct.pack("<I", 100)
            + struct.pack("<I", 200)
            + struct.pack("<H", 0)    # name_len = 0 → rejected
            + struct.pack("<H", 0)
        )
        assert plugin.validate_mime(lfh) is False

    # ── ZIP refine_extension (family discrimination) ──────────────────────
    def test_zip_refine_docx(self):
        plugin = ZipPlugin()
        data = b"PK\x03\x04...word/document.xml..."
        assert plugin.refine_extension(data, 0) == ".docx"

    def test_zip_refine_xlsx(self):
        plugin = ZipPlugin()
        data = b"PK\x03\x04...xl/workbook.xml..."
        assert plugin.refine_extension(data, 0) == ".xlsx"

    def test_zip_refine_epub(self):
        plugin = ZipPlugin()
        data = b"PK\x03\x04...application/epub+zip..."
        assert plugin.refine_extension(data, 0) == ".epub"

    def test_zip_refine_apk(self):
        plugin = ZipPlugin()
        data = b"PK\x03\x04...AndroidManifest.xml..."
        assert plugin.refine_extension(data, 0) == ".apk"

    def test_zip_refine_fallback_to_zip(self):
        plugin = ZipPlugin()
        data = b"PK\x03\x04...some/plain/file.txt..."
        assert plugin.refine_extension(data, 0) == ".zip"


# ─────────────────────────────────────────────────────────────────────────────
# Objective 3 — JPEG fragmentation heuristics (_parse_structure)
# ─────────────────────────────────────────────────────────────────────────────

class TestJpegFragmentation:
    """The syntactic marker walker must:
      • trust a naive FF D9 footer when the resulting file is ≥ 2 KB (score 100)
      • fall back to _parse_structure() for tiny buffers
      • return score 70 when parser finishes without EOI but with a valid scan
      • return score 75 when parser hits bogus data (MIME already validated)
    """

    def test_naive_footer_trusted_when_large(self):
        plugin = JpegPlugin()
        # SOI + 2 KB payload + EOI → size >= 2 KB → score 100
        data = b"\xFF\xD8\xFF\xE0" + b"\x00" * 2100 + b"\xFF\xD9"
        size_kb, integrity = plugin.estimate_size(data, 0, b"\xFF\xD9")
        assert integrity == 100
        assert size_kb >= 2

    def test_clean_eoi_via_structural_walk(self):
        """Build a minimal-but-valid JPEG where the syntactic walker
        reaches EOI cleanly → score 100."""
        plugin = JpegPlugin()
        # SOI + APP0 (len=16) segment + DQT segment + SOS + small entropy + EOI
        soi  = b"\xFF\xD8"
        app0 = b"\xFF\xE0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
        dqt  = b"\xFF\xDB" + struct.pack(">H", 67) + b"\x00" * 65
        sos  = b"\xFF\xDA" + struct.pack(">H", 12) + b"\x00" * 10
        # entropy data (no 0xFF inside to keep it simple) + EOI
        entropy = b"\x00" * 32
        eoi  = b"\xFF\xD9"
        data = soi + app0 + dqt + sos + entropy + eoi
        # Call _parse_structure directly to bypass the fast-path (< 2 KB)
        size_kb, integrity = plugin._parse_structure(data, 0)
        assert integrity == 100
        assert size_kb >= 1

    def test_fragment_without_eoi_returns_score_70(self):
        """If the parser finishes a scan cleanly but never sees EOI,
        it must flag the candidate as a reassembled fragment (score 70)."""
        plugin = JpegPlugin()
        soi  = b"\xFF\xD8"
        app0 = b"\xFF\xE0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
        dqt  = b"\xFF\xDB" + struct.pack(">H", 67) + b"\x00" * 65
        sos  = b"\xFF\xDA" + struct.pack(">H", 12) + b"\x00" * 10
        # Entropy stream terminated by a "genuine" marker (0xFF 0xC4 — DHT).
        # But then we DO NOT provide the DHT segment payload — buffer just ends.
        entropy = b"\x00" * 64 + b"\xFF\xC4"
        data = soi + app0 + dqt + sos + entropy
        # Ensure below fast-path threshold so _parse_structure runs
        assert len(data) < 2048
        size_kb, integrity = plugin.estimate_size(data, 0, b"\xFF\xD9")
        assert integrity == 70, f"expected fragment score 70, got {integrity}"
        assert size_kb >= 1

    def test_bogus_data_falls_back_to_default_75(self):
        """Parser blocked on garbage immediately → returns default_size_kb, 75."""
        plugin = JpegPlugin()
        # SOI followed by garbage that doesn't start with 0xFF
        data = b"\xFF\xD8" + b"\x42\x42\x42\x42" * 20
        size_kb, integrity = plugin.estimate_size(data, 0, b"\xFF\xD9")
        assert integrity == 75
        assert size_kb == plugin.default_size_kb

    def test_rstn_markers_handled_in_entropy(self):
        """RSTn markers (FF D0..FF D7) inside the scan stream must not end
        the scan prematurely."""
        plugin = JpegPlugin()
        soi  = b"\xFF\xD8"
        app0 = b"\xFF\xE0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
        sos  = b"\xFF\xDA" + struct.pack(">H", 12) + b"\x00" * 10
        # Entropy: some data, RST0, more data, RST1, then EOI
        entropy = b"\x11" * 20 + b"\xFF\xD0" + b"\x22" * 20 + b"\xFF\xD1" + b"\x33" * 20
        eoi  = b"\xFF\xD9"
        data = soi + app0 + sos + entropy + eoi
        _size_kb, integrity = plugin._parse_structure(data, 0)
        assert integrity == 100

    def test_byte_stuffing_ff00_handled(self):
        """FF 00 byte-stuffing inside entropy must be consumed as a literal
        0xFF, not trigger marker processing."""
        plugin = JpegPlugin()
        soi  = b"\xFF\xD8"
        sos  = b"\xFF\xDA" + struct.pack(">H", 12) + b"\x00" * 10
        # Entropy contains FF 00 (escaped 0xFF) — must be passed through
        entropy = b"\x00" * 16 + b"\xFF\x00" + b"\x00" * 16 + b"\xFF\x00" + b"\x00" * 16
        eoi  = b"\xFF\xD9"
        data = soi + sos + entropy + eoi
        _size_kb, integrity = plugin._parse_structure(data, 0)
        assert integrity == 100


# ─────────────────────────────────────────────────────────────────────────────
# Objective 1 — NTFSParser silent fallback on bad source
# ─────────────────────────────────────────────────────────────────────────────

class TestNtfsParserFallback:
    """When the MFT cannot be located (non-NTFS disk, corrupted MBR,
    unreachable BPB…) read_boot_sector() must return None quietly.
    ScanWorker then degrades to raw FileCarver. No exception must bubble up."""

    def test_read_boot_sector_returns_none_on_logical_nonntfs(self):
        """Logical volume with a valid-looking buffer that is NOT NTFS.
        The BPB OEM field (offset 3..11) is not "NTFS    "."""
        # Fake BPB: 512 bytes, OEM = "FAT32   "
        fake_bpb = (
            b"\xEB\x3C\x90"
            + b"FAT32   "          # OEM — not "NTFS    "
            + b"\x00" * (512 - 11)
        )

        # Mock os.lseek + os.read so NTFSParser reads our buffer
        with patch("app.core.fs_parser.os.lseek", return_value=0), \
             patch("app.core.fs_parser.os.read", return_value=fake_bpb):
            parser = NTFSParser(r"\\.\C:", fd=999)  # fd is never actually used
            boot = parser.read_boot_sector()
        assert boot is None

    def test_read_boot_sector_returns_none_on_truncated_read(self):
        """If os.read returns less than 512 bytes, no BPB parsing is possible."""
        with patch("app.core.fs_parser.os.lseek", return_value=0), \
             patch("app.core.fs_parser.os.read", return_value=b"\x00" * 16):
            parser = NTFSParser(r"\\.\C:", fd=999)
            assert parser.read_boot_sector() is None

    def test_read_boot_sector_returns_none_on_ioerror(self):
        """A raw-device OSError during read must be caught silently."""
        def _boom(*_a, **_kw):
            raise OSError("device not ready")

        with patch("app.core.fs_parser.os.lseek", return_value=0), \
             patch("app.core.fs_parser.os.read", side_effect=_boom):
            parser = NTFSParser(r"\\.\C:", fd=999)
            assert parser.read_boot_sector() is None

    def test_find_ntfs_partition_returns_minus1_without_mbr_signature(self):
        """Physical drive with no 0x55 0xAA MBR boot signature → -1."""
        fake_sector0 = b"\x00" * 512  # no boot signature
        with patch("app.core.fs_parser.os.lseek", return_value=0), \
             patch("app.core.fs_parser.os.read", return_value=fake_sector0):
            parser = NTFSParser(r"\\.\PhysicalDrive0", fd=999)
            assert parser._find_ntfs_partition() == -1

    def test_read_boot_sector_returns_none_on_physical_no_ntfs_partition(self):
        """Physical drive: valid MBR signature but no type=0x07 partition."""
        # 512-byte MBR with boot signature but no NTFS entry
        mbr = bytearray(b"\x00" * 512)
        mbr[510] = 0x55
        mbr[511] = 0xAA
        # All four partition entries' type byte (offset 0x1BE + i*16 + 4)
        # stays 0 — no NTFS, no GPT (0xEE) either
        with patch("app.core.fs_parser.os.lseek", return_value=0), \
             patch("app.core.fs_parser.os.read", return_value=bytes(mbr)):
            parser = NTFSParser(r"\\.\PhysicalDrive0", fd=999)
            assert parser.read_boot_sector() is None


# ─────────────────────────────────────────────────────────────────────────────
# Objective 4 / integration — FileCarver.scan() end-to-end on synthetic data
# ─────────────────────────────────────────────────────────────────────────────

class TestFileCarverScan:
    def test_detect_jpeg_via_plugin(self):
        """A JFIF image embedded in a blob must be detected and the plugin
        must MIME-validate it."""
        jfif = (
            b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + b"\xFF\xDB\x00\x43" + b"\x10" * 64       # DQT
            + b"\xFF\xDA\x00\x0C" + b"\x00" * 10       # SOS
            + b"\x00" * 2500                            # entropy
            + b"\xFF\xD9"                               # EOI
        )
        content = b"\x00" * 256 + jfif + b"\x00" * 256
        path = _temp_file(content)
        try:
            carver = FileCarver()
            found = carver.scan(path, max_bytes=len(content))
            jpgs = [f for f in found if f["type"] == "JPG"]
            assert len(jpgs) >= 1
            assert jpgs[0]["offset"] == 256
            # EOI found cleanly → integrity 100
            assert jpgs[0]["integrity"] == 100
        finally:
            os.unlink(path)

    def test_detect_png_via_legacy(self):
        content = b"\x00" * 100 + b"\x89PNG\r\n\x1a\n" + b"\x00" * 500
        path = _temp_file(content)
        try:
            carver = FileCarver()
            found = carver.scan(path, max_bytes=len(content))
            pngs = [f for f in found if f["type"] == "PNG"]
            assert len(pngs) >= 1
            assert pngs[0]["offset"] == 100
        finally:
            os.unlink(path)

    def test_detect_pdf_via_plugin(self):
        content = b"\x00" * 50 + b"%PDF-1.4\n" + b"\x00" * 300 + b"%%EOF" + b"\x00" * 50
        path = _temp_file(content)
        try:
            carver = FileCarver()
            found = carver.scan(path, max_bytes=len(content))
            pdfs = [f for f in found if f["type"] == "PDF"]
            assert len(pdfs) >= 1
            assert pdfs[0]["integrity"] == 100  # header + footer found
        finally:
            os.unlink(path)

    def test_mime_rejection_silent(self):
        """A buffer starting with a PDF magic but with an invalid version
        must be silently rejected — no PDF in the results."""
        content = b"\x00" * 50 + b"%PDF-9.9\n" + b"\x00" * 300
        path = _temp_file(content)
        try:
            carver = FileCarver()
            found = carver.scan(path, max_bytes=len(content))
            pdfs = [f for f in found if f["type"] == "PDF"]
            assert len(pdfs) == 0
        finally:
            os.unlink(path)

    def test_progress_callback_called(self):
        content = b"\x00" * 2048
        path = _temp_file(content)
        pct_values: list[int] = []
        try:
            carver = FileCarver()
            carver.scan(
                path,
                progress_cb=lambda p: pct_values.append(p),
                max_bytes=len(content),
            )
            assert pct_values, "progress_cb should have been called"
            assert pct_values[-1] == 100
        finally:
            os.unlink(path)

    def test_stop_flag_halts_scan(self):
        content = b"\x00" * (4 * 1024 * 1024)  # 4 MB
        path = _temp_file(content)
        try:
            carver = FileCarver()
            calls = {"n": 0}

            def stop() -> bool:
                calls["n"] += 1
                return calls["n"] > 1

            carver.scan(path, stop_flag=stop, max_bytes=len(content))
            # Should have been queried a small number of times, not for
            # every byte of a 4 MB buffer.
            assert calls["n"] <= 50
        finally:
            os.unlink(path)

    def test_empty_file_returns_empty(self):
        path = _temp_file(b"")
        try:
            carver = FileCarver()
            assert carver.scan(path, max_bytes=0) == []
        finally:
            os.unlink(path)

    def test_zip_refined_to_docx_in_results(self):
        """A ZIP-family blob containing word/ must be reported as .docx
        thanks to ZipPlugin.refine_extension()."""
        # Minimal LFH + word/ directory marker
        lfh = (
            b"PK\x03\x04"
            + struct.pack("<H", 20) + struct.pack("<H", 0) + struct.pack("<H", 8)
            + b"\x00" * 8
            + struct.pack("<I", 100) + struct.pack("<I", 200)
            + struct.pack("<H", 19) + struct.pack("<H", 0)
            + b"word/document.xml"
        )
        content = b"\x00" * 64 + lfh + b"\x00" * 256
        path = _temp_file(content)
        try:
            carver = FileCarver()
            found = carver.scan(path, max_bytes=len(content))
            docx = [f for f in found if f["type"] == "DOCX"]
            assert len(docx) >= 1
        finally:
            os.unlink(path)


# ─────────────────────────────────────────────────────────────────────────────
# Base plugin contract
# ─────────────────────────────────────────────────────────────────────────────

class TestBasePlugin:
    def test_cannot_instantiate_abstract_base(self):
        with pytest.raises(TypeError):
            BaseCarverPlugin()   # type: ignore[abstract]

    def test_plugins_expose_handled_extensions(self):
        for p in (JpegPlugin(), PdfPlugin(), ZipPlugin()):
            assert isinstance(p.handled_extensions, tuple)
            assert p.extension in p.handled_extensions
