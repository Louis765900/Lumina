"""
Tests for APFSParser in app/core/fs_parser.py

Uses tempfile.mkstemp() to create real binary files — no PyQt6.
"""

from __future__ import annotations

import os
import struct
import tempfile
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# v1 partial parser — NX Superblock + APSB scan + encryption detection
# ---------------------------------------------------------------------------


def _build_full_nx_superblock(
    *,
    nx_block_size: int = 4096,
    nx_block_count: int = 1024,
    nx_max_fs: int = 100,
    fs_oids: list[int] | None = None,
) -> bytes:
    """Build the first NX block (size = nx_block_size) with realistic fields."""
    blk = bytearray(nx_block_size)
    blk[32:36] = _NXSB_MAGIC
    struct.pack_into("<I", blk, 0x24, nx_block_size)
    struct.pack_into("<Q", blk, 0x28, nx_block_count)
    struct.pack_into("<I", blk, 0xB4, nx_max_fs)
    fs_oids = fs_oids or []
    for i, oid in enumerate(fs_oids[:nx_max_fs]):
        struct.pack_into("<Q", blk, 0xB8 + i * 8, oid)
    return bytes(blk)


def _build_apsb_block(
    *,
    block_size: int = 4096,
    encrypted: bool,
    volume_name: str | None = None,
) -> bytes:
    blk = bytearray(block_size)
    blk[32:36] = _APSB_MAGIC
    flags = 0x00 if encrypted else 0x01  # bit 0 = APFS_FS_UNENCRYPTED
    struct.pack_into("<Q", blk, 0x88, flags)
    if volume_name is not None:
        encoded = volume_name.encode("utf-8")[:255]
        blk[0x2D0 : 0x2D0 + len(encoded)] = encoded
        # Trailing NUL guaranteed by zero-init.
    return bytes(blk)


def _build_apfs_image_with_volumes(
    *,
    block_size: int = 4096,
    volumes: list[dict] | None = None,
    nx_max_fs: int = 100,
) -> bytes:
    """Build a multi-block image: NXSB at block 0, APSB blocks afterward."""
    volumes = volumes or []
    fs_oids = [1024 + i for i in range(len(volumes))]
    n_blocks = max(8, 2 + len(volumes))
    img = bytearray(n_blocks * block_size)
    img[0:block_size] = _build_full_nx_superblock(
        nx_block_size=block_size,
        nx_max_fs=nx_max_fs,
        fs_oids=fs_oids,
    )
    for i, v in enumerate(volumes):
        block_idx = 2 + i  # leave block 1 free
        apsb = _build_apsb_block(
            block_size=block_size,
            encrypted=v["encrypted"],
            volume_name=v.get("name"),
        )
        img[block_idx * block_size : (block_idx + 1) * block_size] = apsb
    return bytes(img)


class TestAPFSV1PartialParser:
    def test_nx_superblock_full_parse_caches_geometry(self):
        img = _build_apfs_image_with_volumes(volumes=[])
        fd, path = _write_tmp(img)
        try:
            parser = APFSParser("test.img", fd)
            assert parser.probe() is True
            count = parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=lambda _i: None,
            )
            # Always 0 in v1; success is "didn't crash".
            assert count == 0
            # Internal cache populated.
            assert parser._nx_ready is True
            assert parser._nx_block_size == 4096
            assert parser._nx_max_file_systems == 100
            assert parser._nx_fs_oids == []
        finally:
            os.close(fd)
            os.unlink(path)

    def test_invalid_max_fs_falls_back_silently(self):
        img = _build_apfs_image_with_volumes(volumes=[], nx_max_fs=200)  # > 100
        fd, path = _write_tmp(img)
        try:
            parser = APFSParser("test.img", fd)
            count = parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=lambda _i: None,
            )
            assert count == 0
            assert parser._nx_ready is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_single_volume_unencrypted_detected(self):
        img = _build_apfs_image_with_volumes(volumes=[{"encrypted": False, "name": "Macintosh HD"}])
        fd, path = _write_tmp(img)
        try:
            parser = APFSParser("test.img", fd)
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=lambda _i: None,
            )
            volumes = parser._discover_volumes()
            assert len(volumes) == 1
            assert volumes[0]["encrypted"] is False
            assert volumes[0]["volume_name"] == "Macintosh HD"
        finally:
            os.close(fd)
            os.unlink(path)

    def test_encrypted_volume_detected(self):
        img = _build_apfs_image_with_volumes(volumes=[{"encrypted": True, "name": "Data"}])
        fd, path = _write_tmp(img)
        try:
            parser = APFSParser("test.img", fd)
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=lambda _i: None,
            )
            volumes = parser._discover_volumes()
            assert len(volumes) == 1
            assert volumes[0]["encrypted"] is True
            assert volumes[0]["volume_name"] == "Data"
        finally:
            os.close(fd)
            os.unlink(path)

    def test_multi_volume_container(self):
        img = _build_apfs_image_with_volumes(
            volumes=[
                {"encrypted": False, "name": "Macintosh HD"},
                {"encrypted": True, "name": "Macintosh HD - Data"},
                {"encrypted": False, "name": "Recovery"},
            ]
        )
        fd, path = _write_tmp(img)
        try:
            parser = APFSParser("test.img", fd)
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=lambda _i: None,
            )
            volumes = parser._discover_volumes()
            assert len(volumes) == 3
            names = [v["volume_name"] for v in volumes]
            assert names == ["Macintosh HD", "Macintosh HD - Data", "Recovery"]
            assert [v["encrypted"] for v in volumes] == [False, True, False]
            # Each volume has a sequential index.
            assert [v["index"] for v in volumes] == [0, 1, 2]
        finally:
            os.close(fd)
            os.unlink(path)

    def test_no_apsb_in_container_returns_zero_with_no_crash(self):
        # Valid NXSB but no APSB blocks anywhere.
        img = _build_full_nx_superblock(nx_max_fs=100)
        img += b"\x00" * (4096 * 4)  # extra empty blocks
        fd, path = _write_tmp(img)
        try:
            parser = APFSParser("test.img", fd)
            count = parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=lambda _i: None,
            )
            assert count == 0
        finally:
            os.close(fd)
            os.unlink(path)

    def test_enumerate_progress_reaches_100_on_full_image(self):
        img = _build_apfs_image_with_volumes(volumes=[{"encrypted": False, "name": "Vol"}])
        fd, path = _write_tmp(img)
        try:
            parser = APFSParser("test.img", fd)
            progress: list[int] = []
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=progress.append,
                file_found_cb=lambda _i: None,
            )
            assert progress[-1] == 100
        finally:
            os.close(fd)
            os.unlink(path)

    def test_stop_flag_aborts_before_volume_scan(self):
        img = _build_apfs_image_with_volumes(volumes=[{"encrypted": False, "name": "Vol"}])
        fd, path = _write_tmp(img)
        try:
            parser = APFSParser("test.img", fd)
            count = parser.enumerate_files(
                stop_flag=lambda: True,
                progress_cb=_no_progress,
                file_found_cb=lambda _i: None,
            )
            assert count == 0
        finally:
            os.close(fd)
            os.unlink(path)

    def test_enumerate_does_not_call_file_found_cb_in_v1(self):
        """v1 emits no file_info dicts even when volumes are detected."""
        img = _build_apfs_image_with_volumes(volumes=[{"encrypted": False, "name": "Vol"}])
        fd, path = _write_tmp(img)
        try:
            parser = APFSParser("test.img", fd)
            collected: list[dict] = []
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=collected.append,
            )
            assert collected == []
        finally:
            os.close(fd)
            os.unlink(path)
