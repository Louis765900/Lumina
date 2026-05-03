"""Tests for diagnose_jpeg / diagnose_mp4 read-only analysis."""

from __future__ import annotations

import os
import struct
import tempfile
from pathlib import Path

from app.core.repair.jpeg_repair import diagnose_jpeg, repair_jpeg
from app.core.repair.mp4_repair import diagnose_mp4


def _write_tmp(data: bytes, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


# ─── JPEG ──────────────────────────────────────────────────────────────────


def _minimal_jpeg() -> bytes:
    soi = b"\xff\xd8"
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    eoi = b"\xff\xd9"
    return soi + app0 + eoi


def test_diagnose_jpeg_clean_file_reports_no_issues():
    path = _write_tmp(_minimal_jpeg(), ".jpg")
    try:
        report = diagnose_jpeg(path)
        assert report.issues_found == []
        assert report.repaired is False
        assert report.original_size == report.repaired_size
    finally:
        os.unlink(path)


def test_diagnose_jpeg_missing_eoi_is_reported():
    path = _write_tmp(_minimal_jpeg()[:-2], ".jpg")  # strip EOI
    try:
        report = diagnose_jpeg(path)
        assert any("EOI" in issue for issue in report.issues_found)
        assert report.repaired is False
    finally:
        os.unlink(path)


def test_diagnose_jpeg_missing_soi_is_reported():
    body = _minimal_jpeg()[2:]  # strip SOI
    path = _write_tmp(body, ".jpg")
    try:
        report = diagnose_jpeg(path)
        # Either "Missing SOI" or garbage-bytes-stripped wording.
        assert any("SOI" in issue for issue in report.issues_found)
    finally:
        os.unlink(path)


def test_diagnose_jpeg_does_not_create_repaired_file():
    """diagnose_jpeg must be read-only; repair_jpeg writes a sibling output."""
    path = _write_tmp(_minimal_jpeg(), ".jpg")
    sibling = path + ".repaired.jpg"
    try:
        diagnose_jpeg(path)
        assert not Path(sibling).exists()
    finally:
        os.unlink(path)
        if Path(sibling).exists():
            os.unlink(sibling)


def test_diagnose_jpeg_empty_file_reported():
    path = _write_tmp(b"", ".jpg")
    try:
        report = diagnose_jpeg(path)
        assert report.issues_found
        assert any("Empty" in issue for issue in report.issues_found)
    finally:
        os.unlink(path)


# ─── MP4 ───────────────────────────────────────────────────────────────────


def _minimal_mp4(*, moov_first: bool = True) -> bytes:
    """Build a minimal MP4 with ftyp + moov + mdat in chosen order."""
    ftyp = struct.pack(">I", 16) + b"ftyp" + b"isom\x00\x00\x00\x00"
    moov = struct.pack(">I", 8) + b"moov"
    mdat = struct.pack(">I", 8) + b"mdat"
    if moov_first:
        return ftyp + moov + mdat
    return ftyp + mdat + moov


def test_diagnose_mp4_clean_file_reports_no_issues():
    path = _write_tmp(_minimal_mp4(moov_first=True), ".mp4")
    try:
        report = diagnose_mp4(path)
        assert report.issues_found == []
        assert report.repaired is False
    finally:
        os.unlink(path)


def test_diagnose_mp4_moov_after_mdat_is_reported():
    path = _write_tmp(_minimal_mp4(moov_first=False), ".mp4")
    try:
        report = diagnose_mp4(path)
        assert any("moov" in issue and "mdat" in issue for issue in report.issues_found)
        assert report.repaired is False
    finally:
        os.unlink(path)


def test_diagnose_mp4_no_moov_is_reported():
    only_ftyp_mdat = (
        struct.pack(">I", 16) + b"ftyp" + b"isom\x00\x00\x00\x00" + struct.pack(">I", 8) + b"mdat"
    )
    path = _write_tmp(only_ftyp_mdat, ".mp4")
    try:
        report = diagnose_mp4(path)
        assert any("moov" in issue for issue in report.issues_found)
    finally:
        os.unlink(path)


def test_diagnose_mp4_does_not_create_output():
    path = _write_tmp(_minimal_mp4(), ".mp4")
    sibling = path + ".repaired.mp4"
    try:
        diagnose_mp4(path)
        assert not Path(sibling).exists()
    finally:
        os.unlink(path)
        if Path(sibling).exists():
            os.unlink(sibling)


def test_diagnose_mp4_too_small_is_reported():
    path = _write_tmp(b"abc", ".mp4")
    try:
        report = diagnose_mp4(path)
        assert any("too small" in issue.lower() for issue in report.issues_found)
    finally:
        os.unlink(path)


# ─── repair_dialog dispatch helper (no PyQt6 widgets exercised) ─────────────


def test_repair_dialog_detect_kind_classifies_correctly():
    from app.ui.repair_dialog import _detect_kind

    assert _detect_kind("photo.jpg") == "jpeg"
    assert _detect_kind("PHOTO.JPEG") == "jpeg"
    assert _detect_kind("clip.mp4") == "mp4"
    assert _detect_kind("clip.MOV") == "mp4"
    assert _detect_kind("doc.pdf") is None
    assert _detect_kind("noext") is None


def test_repair_module_exposes_diagnose_and_repair_pairs():
    """Sanity check that the symbols RepairDialog imports remain present."""
    import app.core.repair.jpeg_repair as jpeg
    import app.core.repair.mp4_repair as mp4

    assert callable(jpeg.diagnose_jpeg)
    assert callable(jpeg.repair_jpeg)
    assert callable(mp4.diagnose_mp4)
    assert callable(mp4.repair_mp4)


def test_diagnose_then_repair_round_trip_on_jpeg():
    """diagnose() must report the same issues that repair() ends up fixing."""
    path = _write_tmp(_minimal_jpeg()[:-2], ".jpg")  # missing EOI
    try:
        before = diagnose_jpeg(path)
        out = path + ".out.jpg"
        result = repair_jpeg(path, out)
        try:
            assert before.issues_found
            assert result.repaired is True
            assert any("EOI" in i for i in result.issues_found)
        finally:
            if Path(out).exists():
                os.unlink(out)
    finally:
        os.unlink(path)
