"""
Tests for APFSParser in app/core/fs_parser.py

Uses tempfile.mkstemp() to create real binary files — no PyQt6.
"""
from __future__ import annotations

import os
import struct
import tempfile
from unittest.mock import patch

import pytest

from app.core.fs_parser import APFSParser, detect_fs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NXSB_MAGIC = b"NXSB"
_APSB_MAGIC = b"APSB"


def make_apfs_nx_superblock(
    *,
    magic: bytes = _NXSB_MAGIC,
    nx_block_size: int = 4096,
    total_size: int = 512,
) -> bytes:
    """
    Build a minimal 40-byte APFS NX Superblock header (Little-Endian).
    The magic 'NXSB' is at offset 32, nx_block_size at offset 36.
    """
    buf = bytearray(max(total_size, 40))
    buf[32:36] = magic
    struct.pack_into("<I", buf, 36, nx_block_size)
    return bytes(buf)


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

class TestAPFSProbe:
    def test_probe_valid_apfs(self):
        data = make_apfs_nx_superblock(nx_block_size=4096)
        fd, path = _write_tmp(data)
        try:
            parser = APFSParser("test.img", fd)
            assert parser.probe() is True
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_ntfs(self):
        data = bytearray(512)
        data[3:11] = b"NTFS    "
        fd, path = _write_tmp(bytes(data))
        try:
            parser = APFSParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_fat32(self):
        data = bytearray(512)
        data[0x52:0x5A] = b"FAT32   "
        data[0x0B:0x0D] = struct.pack("<H", 512)
        fd, path = _write_tmp(bytes(data))
        try:
            parser = APFSParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_hfsplus(self):
        # HFS+ signature at 1024, not 32
        data = bytearray(4096)
        struct.pack_into(">H", data, 1024, 0x482B)  # HFS+ sig
        fd, path = _write_tmp(bytes(data))
        try:
            parser = APFSParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_wrong_magic(self):
        data = make_apfs_nx_superblock(magic=b"NXXX")
        fd, path = _write_tmp(data)
        try:
            parser = APFSParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_too_short(self):
        # Less than 40 bytes
        data = b"\x00" * 20
        fd, path = _write_tmp(data)
        try:
            parser = APFSParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_small_block_size(self):
        """nx_block_size < 4096 → False."""
        data = make_apfs_nx_superblock(nx_block_size=512)
        fd, path = _write_tmp(data)
        try:
            parser = APFSParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_zero_block_size(self):
        data = make_apfs_nx_superblock(nx_block_size=0)
        fd, path = _write_tmp(data)
        try:
            parser = APFSParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_swallows_exceptions(self):
        """OSError from read → False, no exception propagates."""
        with patch("app.core.fs_parser.os.lseek", side_effect=OSError("I/O error")):
            parser = APFSParser("test.img", 99)
            result = parser.probe()
        assert result is False

    def test_probe_large_block_size(self):
        """Large block sizes (16384, 65536) should be accepted."""
        for block_size in (4096, 8192, 16384, 65536):
            data = make_apfs_nx_superblock(nx_block_size=block_size)
            fd, path = _write_tmp(data)
            try:
                parser = APFSParser("test.img", fd)
                assert parser.probe() is True, f"block_size={block_size} should be accepted"
            finally:
                os.close(fd)
                os.unlink(path)


# ---------------------------------------------------------------------------
# Test: enumerate_files()
# ---------------------------------------------------------------------------

class TestAPFSEnumerateFiles:
    def _make_probed_parser(self) -> tuple[APFSParser, int, str]:
        data = make_apfs_nx_superblock()
        fd, path = _write_tmp(data)
        parser = APFSParser("test.img", fd)
        assert parser.probe() is True
        return parser, fd, path

    def test_enumerate_returns_zero(self):
        parser, fd, path = self._make_probed_parser()
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

    def test_enumerate_calls_progress_100(self):
        parser, fd, path = self._make_probed_parser()
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

    def test_enumerate_never_calls_file_found_cb(self):
        """enumerate_files must never call file_found_cb (stub implementation)."""
        parser, fd, path = self._make_probed_parser()
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

    def test_enumerate_returns_zero_even_without_probe(self):
        """enumerate_files when volume is not APFS should also return 0."""
        data = b"\x00" * 512
        fd, path = _write_tmp(data)
        try:
            parser = APFSParser("test.img", fd)
            count = parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=lambda info: None,
            )
            assert count == 0
        finally:
            os.close(fd)
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: detect_fs() integration
# ---------------------------------------------------------------------------

class TestAPFSDetectFS:
    def test_detect_fs_returns_apfs(self):
        """detect_fs() should return APFSParser for an APFS image."""
        data = make_apfs_nx_superblock()
        fd, path = _write_tmp(data)
        try:
            parser = detect_fs("test.img", fd)
            assert parser is not None
            assert isinstance(parser, APFSParser)
        finally:
            os.close(fd)
            os.unlink(path)
