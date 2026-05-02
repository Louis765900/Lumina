"""
Tests for HFSPlusParser in app/core/fs_parser.py

Uses tempfile.mkstemp() to create real binary files — no PyQt6.
"""
from __future__ import annotations

import os
import struct
import tempfile
from unittest.mock import patch

import pytest

from app.core.fs_parser import HFSPlusParser, detect_fs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VH_OFFSET = 1024
_HFSPLUS_SIG = 0x482B
_HFSX_SIG = 0x4858


def make_hfsplus_volume_header(
    *,
    signature: int = _HFSPLUS_SIG,
    block_size: int = 4096,
    total_blocks: int = 500000,
) -> bytes:
    """
    Build a 162-byte HFS+ Volume Header (Big-Endian).
    Only the fields checked by probe() are set.
    """
    vh = bytearray(162)
    # Signature at offset 0 (BE u16)
    struct.pack_into(">H", vh, 0, signature)
    # blockSize at offset 40 (BE u32)
    struct.pack_into(">I", vh, 40, block_size)
    # totalBlocks at offset 44 (BE u32)
    struct.pack_into(">I", vh, 44, total_blocks)
    return bytes(vh)


def make_hfsplus_image(
    signature: int = _HFSPLUS_SIG,
    block_size: int = 4096,
    total_blocks: int = 500000,
    total_size: int = 4096,
) -> bytes:
    """Build a minimal HFS+ image: 1024 bytes padding + Volume Header."""
    vh = make_hfsplus_volume_header(
        signature=signature,
        block_size=block_size,
        total_blocks=total_blocks,
    )
    buf = bytearray(max(total_size, _VH_OFFSET + len(vh)))
    buf[_VH_OFFSET:_VH_OFFSET + len(vh)] = vh
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

class TestHFSPlusProbe:
    def test_probe_valid_hfsplus(self):
        data = make_hfsplus_image(signature=_HFSPLUS_SIG)
        fd, path = _write_tmp(data)
        try:
            parser = HFSPlusParser("test.img", fd)
            assert parser.probe() is True
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_valid_hfsx(self):
        data = make_hfsplus_image(signature=_HFSX_SIG)
        fd, path = _write_tmp(data)
        try:
            parser = HFSPlusParser("test.img", fd)
            assert parser.probe() is True
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_ntfs(self):
        data = bytearray(4096)
        data[3:11] = b"NTFS    "
        fd, path = _write_tmp(bytes(data))
        try:
            parser = HFSPlusParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_fat32(self):
        # FAT32 has its signature at a different location — no HFS+ magic
        data = bytearray(4096)
        data[0x52:0x5A] = b"FAT32   "
        data[0x0B:0x0D] = struct.pack("<H", 512)  # bytes_per_sector
        fd, path = _write_tmp(bytes(data))
        try:
            parser = HFSPlusParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_wrong_signature(self):
        data = make_hfsplus_image(signature=0xDEAD)
        fd, path = _write_tmp(data)
        try:
            parser = HFSPlusParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_too_short(self):
        # Less than 1024 + 162 bytes
        data = b"\x00" * 512
        fd, path = _write_tmp(data)
        try:
            parser = HFSPlusParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_zero_block_size(self):
        data = make_hfsplus_image(block_size=0)
        fd, path = _write_tmp(data)
        try:
            parser = HFSPlusParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_big_endian_parsing(self):
        """Verify that probe() correctly uses Big-Endian byte order."""
        # Build Volume Header manually in Big-Endian
        vh = bytearray(162)
        # Signature "H+" = 0x482B in BE → bytes 0x48, 0x2B
        vh[0] = 0x48
        vh[1] = 0x2B
        # blockSize = 8192 = 0x00002000 in BE at offset 40
        vh[40] = 0x00
        vh[41] = 0x00
        vh[42] = 0x20
        vh[43] = 0x00
        # totalBlocks = 1000 = 0x000003E8 in BE at offset 44
        vh[44] = 0x00
        vh[45] = 0x00
        vh[46] = 0x03
        vh[47] = 0xE8

        buf = bytearray(max(4096, _VH_OFFSET + 162))
        buf[_VH_OFFSET:_VH_OFFSET + 162] = vh
        fd, path = _write_tmp(bytes(buf))
        try:
            parser = HFSPlusParser("test.img", fd)
            assert parser.probe() is True
            assert parser._block_size == 8192
            assert parser._total_blocks == 1000
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_swallows_exceptions(self):
        """OSError from read → False, no exception propagates."""
        with patch("app.core.fs_parser.os.lseek", side_effect=OSError("I/O error")):
            parser = HFSPlusParser("test.img", 99)
            result = parser.probe()
        assert result is False

    def test_probe_rejects_non_power_of_two_block_size(self):
        """Block size must be a power of 2."""
        data = make_hfsplus_image(block_size=3000)
        fd, path = _write_tmp(data)
        try:
            parser = HFSPlusParser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: enumerate_files()
# ---------------------------------------------------------------------------

class TestHFSPlusEnumerateFiles:
    def test_enumerate_returns_zero_on_unprobed(self):
        """If the volume is not HFS+, enumerate returns 0."""
        data = b"\x00" * 4096
        fd, path = _write_tmp(data)
        try:
            parser = HFSPlusParser("test.img", fd)
            count = parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=lambda info: None,
            )
            assert count == 0
        finally:
            os.close(fd)
            os.unlink(path)

    def test_enumerate_calls_progress_cb(self):
        """progress_cb(100) must always be called."""
        data = make_hfsplus_image()
        fd, path = _write_tmp(data)
        try:
            progress_calls: list[int] = []
            parser = HFSPlusParser("test.img", fd)
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=lambda pct: progress_calls.append(pct),
                file_found_cb=lambda info: None,
            )
            assert 100 in progress_calls
        finally:
            os.close(fd)
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: detect_fs() integration
# ---------------------------------------------------------------------------

class TestHFSPlusDetectFS:
    def test_detect_fs_returns_hfsplus(self):
        """detect_fs() should return HFSPlusParser for an HFS+ image."""
        data = make_hfsplus_image()
        fd, path = _write_tmp(data)
        try:
            parser = detect_fs("test.img", fd)
            assert parser is not None
            assert isinstance(parser, HFSPlusParser)
        finally:
            os.close(fd)
            os.unlink(path)
