"""
Tests for ExFATParser in app/core/fs_parser.py

Uses tempfile.mkstemp() to create real binary files — no PyQt6.
"""
from __future__ import annotations

import os
import struct
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from app.core.fs_parser import ExFATParser, FAT32Parser, detect_fs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_exfat_boot_sector() -> bytes:
    """Build a minimal 16-byte exFAT-like header with 'EXFAT   ' OEM at bytes 3-10."""
    data = bytearray(512)
    data[3:11] = b"EXFAT   "
    return bytes(data)


def _write_tmp(data: bytes) -> tuple[int, str]:
    fd, path = tempfile.mkstemp(suffix=".img")
    try:
        os.write(fd, data)
        os.lseek(fd, 0, os.SEEK_SET)
    except Exception:
        os.close(fd)
        os.unlink(path)
        raise
    return fd, path


def _no_stop() -> bool:
    return False


def _no_progress(pct: int) -> None:
    pass


# ---------------------------------------------------------------------------
# Test: probe()
# ---------------------------------------------------------------------------

class TestExFATProbe:
    def test_probe_valid_exfat(self):
        data = make_exfat_boot_sector()
        fd, path = _write_tmp(data)
        try:
            parser = ExFATParser("test.img", fd)
            assert parser.probe() is True
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_fat32(self):
        # FAT32 OEM string at bytes 3-10 should be "MSDOS5.0" or similar, not "EXFAT   "
        data = bytearray(512)
        data[3:11] = b"MSDOS5.0"
        data[0x52:0x5A] = b"FAT32   "
        fd, path = _write_tmp(bytes(data))
        try:
            parser = ExFATParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_ntfs(self):
        data = bytearray(512)
        data[3:11] = b"NTFS    "
        fd, path = _write_tmp(bytes(data))
        try:
            parser = ExFATParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_short_buffer(self):
        # Only 5 bytes — less than 11 required
        data = b"\x00" * 5
        fd, path = _write_tmp(data)
        try:
            parser = ExFATParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_wrong_oem(self):
        data = bytearray(512)
        data[3:11] = b"exfat   "  # wrong case
        fd, path = _write_tmp(bytes(data))
        try:
            parser = ExFATParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_swallows_os_error(self):
        """OSError from read → False, no exception propagates."""
        with patch("app.core.fs_parser.os.lseek", side_effect=OSError("disk error")):
            parser = ExFATParser("\\.\PhysicalDrive0", 99)
            result = parser.probe()
        assert result is False


# ---------------------------------------------------------------------------
# Test: enumerate_files()
# ---------------------------------------------------------------------------

class TestExFATEnumerateFiles:
    def _make_exfat_parser(self) -> tuple[ExFATParser, int, str]:
        data = make_exfat_boot_sector()
        fd, path = _write_tmp(data)
        parser = ExFATParser("test.img", fd)
        return parser, fd, path

    def test_enumerate_files_returns_zero(self):
        parser, fd, path = self._make_exfat_parser()
        try:
            count = parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=lambda info: None,
            )
            assert count == 0
        finally:
            os.close(fd)
            os.unlink(path)

    def test_enumerate_files_calls_progress_cb(self):
        parser, fd, path = self._make_exfat_parser()
        try:
            progress_calls: list[int] = []
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=lambda pct: progress_calls.append(pct),
                file_found_cb=lambda info: None,
            )
            assert 100 in progress_calls
        finally:
            os.close(fd)
            os.unlink(path)

    def test_enumerate_files_respects_stop_flag(self):
        """Returns 0 even with stop_flag=True (stub implementation)."""
        parser, fd, path = self._make_exfat_parser()
        try:
            count = parser.enumerate_files(
                stop_flag=lambda: True,
                progress_cb=_no_progress,
                file_found_cb=lambda info: None,
            )
            assert count == 0
        finally:
            os.close(fd)
            os.unlink(path)

    def test_enumerate_files_never_calls_file_found_cb(self):
        """file_found_cb should never be called (exFAT delegated to carver)."""
        parser, fd, path = self._make_exfat_parser()
        try:
            found: list[dict] = []
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=lambda info: found.append(info),
            )
            assert len(found) == 0
        finally:
            os.close(fd)
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: detect_fs() integration
# ---------------------------------------------------------------------------

class TestExFATDetectFS:
    def test_detect_fs_returns_exfat_parser(self):
        data = make_exfat_boot_sector()
        fd, path = _write_tmp(data)
        try:
            parser = detect_fs("test.img", fd)
            assert parser is not None
            assert isinstance(parser, ExFATParser)
        finally:
            os.close(fd)
            os.unlink(path)

    def test_detect_fs_prefers_fat32_over_exfat(self):
        """A valid FAT32 volume should be detected as FAT32, not exFAT."""
        from tests.test_fat32_parser import make_fat32_boot_sector
        boot = make_fat32_boot_sector()
        total = 16 * 1024 * 1024
        fd, path = _write_tmp(boot + b"\x00" * (total - len(boot)))
        try:
            parser = detect_fs("test.img", fd)
            assert parser is not None
            # Should be FAT32, not exFAT
            assert isinstance(parser, FAT32Parser)
        finally:
            os.close(fd)
            os.unlink(path)
