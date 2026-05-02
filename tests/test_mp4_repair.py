"""Tests for MP4 repair module."""
from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path

from app.core.repair.mp4_repair import (
    Mp4RepairReport,
    _parse_atoms,
    is_valid_mp4,
    repair_mp4,
)


def _make_atom(type_str: str, payload: bytes = b"") -> bytes:
    """Build a minimal ISO BMFF atom."""
    size = 8 + len(payload)
    return struct.pack(">I", size) + type_str.encode("latin-1")[:4] + payload


def _make_minimal_mp4() -> bytes:
    ftyp = _make_atom("ftyp", b"isom\x00\x00\x00\x00isom")
    moov = _make_atom("moov", b"\x00" * 8)
    mdat = _make_atom("mdat", b"\x00" * 16)
    return ftyp + moov + mdat


class TestParseAtoms(unittest.TestCase):
    def test_parses_ftyp(self):
        data = _make_minimal_mp4()
        atoms = _parse_atoms(data)
        types = [a.type_ for a in atoms]
        self.assertIn("ftyp", types)
        self.assertIn("moov", types)
        self.assertIn("mdat", types)

    def test_handles_truncated_atom(self):
        # Declare size larger than available data
        bad_atom = struct.pack(">I", 10000) + b"mdat" + b"\x00" * 8
        atoms = _parse_atoms(bad_atom)
        self.assertEqual(len(atoms), 1)
        self.assertEqual(atoms[0].type_, "mdat")

    def test_empty_data(self):
        atoms = _parse_atoms(b"")
        self.assertEqual(atoms, [])

    def test_too_short_for_header(self):
        atoms = _parse_atoms(b"\x00\x00\x00")
        self.assertEqual(atoms, [])

    def test_zero_size_extends_to_eof(self):
        # size=0 means extend to EOF
        atom = struct.pack(">I", 0) + b"mdat" + b"\xAB" * 8
        atoms = _parse_atoms(atom)
        self.assertEqual(len(atoms), 1)
        self.assertEqual(atoms[0].type_, "mdat")
        self.assertEqual(atoms[0].size, len(atom))

    def test_multiple_atoms(self):
        ftyp = _make_atom("ftyp", b"isom")
        free = _make_atom("free", b"\x00" * 4)
        mdat = _make_atom("mdat", b"\xff" * 8)
        data = ftyp + free + mdat
        atoms = _parse_atoms(data)
        types = [a.type_ for a in atoms]
        self.assertEqual(types, ["ftyp", "free", "mdat"])

    def test_atom_offset_is_correct(self):
        ftyp = _make_atom("ftyp", b"x" * 4)
        moov = _make_atom("moov", b"y" * 4)
        data = ftyp + moov
        atoms = _parse_atoms(data)
        self.assertEqual(atoms[0].offset, 0)
        self.assertEqual(atoms[1].offset, len(ftyp))


class TestIsValidMp4(unittest.TestCase):
    def test_valid_mp4(self):
        data = _make_minimal_mp4()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            self.assertTrue(is_valid_mp4(path))
        finally:
            os.unlink(path)

    def test_invalid_too_small(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"\x00" * 4)
            path = f.name
        try:
            self.assertFalse(is_valid_mp4(path))
        finally:
            os.unlink(path)

    def test_only_mdat_not_valid(self):
        data = _make_atom("mdat", b"\x00" * 8)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            # Only mdat, no ftyp or moov
            self.assertFalse(is_valid_mp4(path))
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_false(self):
        self.assertFalse(is_valid_mp4("/no/such/file.mp4"))


class TestRepairMp4(unittest.TestCase):
    def _write_temp(self, data: bytes) -> str:
        fd, path = tempfile.mkstemp(suffix=".mp4")
        os.write(fd, data)
        os.close(fd)
        return path

    def test_valid_mp4_is_repaired_successfully(self):
        data = _make_minimal_mp4()
        path = self._write_temp(data)
        out_path = path + ".repaired.mp4"
        try:
            report = repair_mp4(path, out_path)
            self.assertTrue(report.repaired)
            self.assertGreater(report.repaired_size, 0)
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_moov_after_mdat_gets_reordered(self):
        # Build file with mdat before moov
        ftyp = _make_atom("ftyp", b"isom\x00\x00\x00\x00isom")
        mdat = _make_atom("mdat", b"\x00" * 16)
        moov = _make_atom("moov", b"\x00" * 8)
        data = ftyp + mdat + moov  # mdat before moov
        path = self._write_temp(data)
        out_path = path + ".repaired.mp4"
        try:
            report = repair_mp4(path, out_path)
            self.assertTrue(report.repaired)
            # Verify moov is before mdat in output
            out_data = Path(out_path).read_bytes()
            out_atoms = _parse_atoms(out_data)
            out_types = [a.type_ for a in out_atoms]
            moov_i = out_types.index("moov")
            mdat_i = out_types.index("mdat")
            self.assertLess(moov_i, mdat_i, "moov should come before mdat after repair")
            self.assertTrue(any("reorder" in issue.lower() for issue in report.issues_found))
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_file_too_small_not_repaired(self):
        path = self._write_temp(b"\x00\x00\x00")
        out_path = path + ".repaired.mp4"
        try:
            report = repair_mp4(path, out_path)
            self.assertFalse(report.repaired)
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_no_moov_noted_in_report(self):
        # Only mdat, no moov
        mdat = _make_atom("mdat", b"\x00" * 32)
        path = self._write_temp(mdat)
        out_path = path + ".repaired.mp4"
        try:
            report = repair_mp4(path, out_path)
            self.assertTrue(any("moov" in issue.lower() for issue in report.issues_found))
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_default_output_path(self):
        data = _make_minimal_mp4()
        path = self._write_temp(data)
        default_out = path + ".repaired.mp4"
        try:
            repair_mp4(path)
            self.assertTrue(os.path.exists(default_out))
        finally:
            os.unlink(path)
            if os.path.exists(default_out):
                os.unlink(default_out)

    def test_repair_report_fields(self):
        """Mp4RepairReport should be a proper dataclass."""
        r = Mp4RepairReport(original_size=1000, repaired_size=1000)
        self.assertEqual(r.original_size, 1000)
        self.assertFalse(r.repaired)
        self.assertEqual(r.issues_found, [])

    def test_truncated_atom_reported(self):
        """Atoms that overflow the file boundary should be reported."""
        # Declare size much larger than available
        big_atom = struct.pack(">I", 50000) + b"mdat" + b"\x00" * 20
        path = self._write_temp(big_atom)
        out_path = path + ".repaired.mp4"
        try:
            report = repair_mp4(path, out_path)
            self.assertTrue(report.repaired)
            # Should note the truncation
            self.assertTrue(
                any("truncated" in issue.lower() for issue in report.issues_found),
                f"Expected truncation issue, got: {report.issues_found}"
            )
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_ftyp_stays_first_after_reorder(self):
        """ftyp must remain the first atom after moov reordering."""
        ftyp = _make_atom("ftyp", b"isom" * 3)
        free = _make_atom("free", b"\x00" * 4)
        mdat = _make_atom("mdat", b"\x00" * 16)
        moov = _make_atom("moov", b"\x00" * 8)
        # ftyp + free + mdat + moov (moov after mdat)
        data = ftyp + free + mdat + moov
        path = self._write_temp(data)
        out_path = path + ".repaired.mp4"
        try:
            report = repair_mp4(path, out_path)
            out_data = Path(out_path).read_bytes()
            out_atoms = _parse_atoms(out_data)
            self.assertEqual(out_atoms[0].type_, "ftyp")
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_no_mdat_noted_in_report(self):
        """Missing mdat should be reported."""
        moov = _make_atom("moov", b"\x00" * 8)
        path = self._write_temp(moov)
        out_path = path + ".repaired.mp4"
        try:
            report = repair_mp4(path, out_path)
            self.assertTrue(any("mdat" in issue.lower() for issue in report.issues_found))
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)
