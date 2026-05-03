"""Tests for JPEG repair module."""
from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path

from app.core.repair.jpeg_repair import RepairReport, is_valid_jpeg, repair_jpeg


def _make_minimal_jpeg() -> bytes:
    """Build a minimal but structurally valid JPEG."""
    # SOI + APP0 (JFIF) + EOI
    soi = b"\xff\xd8"
    # APP0: marker 0xFFE0, length 16 (includes length field), JFIF\0 + version + density
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    eoi = b"\xff\xd9"
    return soi + app0 + eoi


class TestIsValidJpeg(unittest.TestCase):
    def test_valid_jpeg_returns_true(self):
        data = _make_minimal_jpeg()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            self.assertTrue(is_valid_jpeg(path))
        finally:
            os.unlink(path)

    def test_missing_eoi_returns_false(self):
        data = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 8
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            self.assertFalse(is_valid_jpeg(path))
        finally:
            os.unlink(path)

    def test_missing_soi_returns_false(self):
        # Starts with APP0, not SOI
        data = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            self.assertFalse(is_valid_jpeg(path))
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_false(self):
        self.assertFalse(is_valid_jpeg("/nonexistent/path/file.jpg"))

    def test_empty_file_returns_false(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            path = f.name
        try:
            self.assertFalse(is_valid_jpeg(path))
        finally:
            os.unlink(path)


class TestRepairJpeg(unittest.TestCase):
    def _write_temp(self, data: bytes) -> str:
        fd, path = tempfile.mkstemp(suffix=".jpg")
        os.write(fd, data)
        os.close(fd)
        return path

    def test_valid_jpeg_is_unchanged_in_structure(self):
        data = _make_minimal_jpeg()
        path = self._write_temp(data)
        out_path = path + ".repaired.jpg"
        try:
            report = repair_jpeg(path, out_path)
            self.assertTrue(report.repaired)
            # Still valid after repair
            self.assertTrue(is_valid_jpeg(out_path))
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_missing_soi_gets_added(self):
        # Start with APP0 (no SOI)
        data = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
        path = self._write_temp(data)
        out_path = path + ".repaired.jpg"
        try:
            report = repair_jpeg(path, out_path)
            repaired = Path(out_path).read_bytes()
            self.assertTrue(repaired.startswith(b"\xff\xd8"))
            self.assertTrue(any("SOI" in issue for issue in report.issues_found))
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_missing_eoi_gets_added(self):
        data = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        path = self._write_temp(data)
        out_path = path + ".repaired.jpg"
        try:
            report = repair_jpeg(path, out_path)
            repaired = Path(out_path).read_bytes()
            self.assertTrue(repaired.endswith(b"\xff\xd9"))
            self.assertTrue(any("EOI" in issue for issue in report.issues_found))
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_invalid_segment_length_handled(self):
        # SOI + marker with length that overflows
        data = b"\xff\xd8" + b"\xff\xe1" + b"\x7f\xff" + b"x" * 10 + b"\xff\xd9"
        path = self._write_temp(data)
        out_path = path + ".repaired.jpg"
        try:
            report = repair_jpeg(path, out_path)
            self.assertTrue(report.repaired)
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_empty_file_returns_report_not_repaired(self):
        path = self._write_temp(b"")
        out_path = path + ".repaired.jpg"
        try:
            report = repair_jpeg(path, out_path)
            self.assertFalse(report.repaired)
            self.assertTrue(any("Empty" in issue for issue in report.issues_found))
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_default_output_path(self):
        data = _make_minimal_jpeg()
        path = self._write_temp(data)
        default_out = path + ".repaired.jpg"
        try:
            repair_jpeg(path)
            self.assertTrue(os.path.exists(default_out))
        finally:
            os.unlink(path)
            if os.path.exists(default_out):
                os.unlink(default_out)

    def test_repair_report_has_sizes(self):
        data = _make_minimal_jpeg()
        path = self._write_temp(data)
        out_path = path + ".repaired.jpg"
        try:
            report = repair_jpeg(path, out_path)
            self.assertGreater(report.original_size, 0)
            self.assertGreater(report.repaired_size, 0)
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_garbage_before_soi_stripped(self):
        data = b"\x00" * 20 + _make_minimal_jpeg()
        path = self._write_temp(data)
        out_path = path + ".repaired.jpg"
        try:
            report = repair_jpeg(path, out_path)
            repaired = Path(out_path).read_bytes()
            self.assertTrue(repaired.startswith(b"\xff\xd8"))
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_repaired_file_ends_with_eoi(self):
        """A repaired file should always end with FF D9."""
        # No EOI in the original
        data = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        path = self._write_temp(data)
        out_path = path + ".repaired.jpg"
        try:
            repair_jpeg(path, out_path)
            repaired = Path(out_path).read_bytes()
            self.assertEqual(repaired[-2:], b"\xff\xd9")
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_repair_report_is_dataclass(self):
        """RepairReport should be a proper dataclass with expected fields."""
        r = RepairReport(original_size=100, repaired_size=102)
        self.assertEqual(r.original_size, 100)
        self.assertEqual(r.repaired_size, 102)
        self.assertFalse(r.repaired)
        self.assertEqual(r.issues_found, [])

    def test_rst_markers_preserved_in_entropy(self):
        """RST markers inside SOS entropy data should not be treated as segment ends."""
        # Minimal JPEG with SOS + RST marker in entropy data
        soi = b"\xff\xd8"
        # SOF0: minimal
        sof0 = b"\xff\xc0\x00\x0bSOF00000000"
        # DHT: minimal
        dht = b"\xff\xc4\x00\x04\x00\x00"
        # SOS: header length=8 (6 bytes payload + 2 for length field)
        sos_header = b"\xff\xda\x00\x08\x00\x00\x00\x00\x00\x00"
        # Entropy data with RST marker (FF D0) and byte stuffing (FF 00), then EOI
        entropy = b"\xab\xcd\xff\xd0\xef\xff\x00\x12"
        eoi = b"\xff\xd9"
        data = soi + sof0 + dht + sos_header + entropy + eoi
        path = self._write_temp(data)
        out_path = path + ".repaired.jpg"
        try:
            report = repair_jpeg(path, out_path)
            self.assertTrue(report.repaired)
            repaired = Path(out_path).read_bytes()
            self.assertTrue(repaired.startswith(b"\xff\xd8"))
            self.assertTrue(repaired.endswith(b"\xff\xd9"))
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)
