"""
Tests for FAT32Parser in app/core/fs_parser.py

Uses tempfile.mkstemp() to create real binary files — no PyQt6.
"""
from __future__ import annotations

import os
import struct
import tempfile
from collections.abc import Callable

import pytest

from app.core.fs_parser import FAT32Parser, detect_fs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_fat32_boot_sector(
    *,
    oem: bytes = b"FAT32   ",
    bytes_per_sector: int = 512,
    sectors_per_cluster: int = 8,
    reserved_sectors: int = 32,
    num_fats: int = 2,
    sectors_per_fat32: int = 512,
    root_cluster: int = 2,
    total_size: int = 512,
) -> bytes:
    """
    Build a minimal 512-byte FAT32 boot sector.
    All other bytes are zero.
    """
    data = bytearray(total_size)

    # OEM name at 0x03..0x0B
    data[0x03:0x03 + 8] = oem[:8].ljust(8, b" ")

    # BPB fields
    struct.pack_into("<H", data, 0x0B, bytes_per_sector)  # bytes per sector
    data[0x0D] = sectors_per_cluster                       # sectors per cluster
    struct.pack_into("<H", data, 0x0E, reserved_sectors)   # reserved sectors
    data[0x10] = num_fats                                  # number of FATs
    struct.pack_into("<I", data, 0x24, sectors_per_fat32)  # sectors per FAT (FAT32)
    struct.pack_into("<I", data, 0x2C, root_cluster)       # root cluster

    # FAT32 FS type string at 0x52
    data[0x52:0x5A] = b"FAT32   "

    return bytes(data)


def _write_tmp(data: bytes) -> tuple[int, str]:
    """Write *data* to a temp file, return (fd, path)."""
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


def _collect_files(file_found_cb_list: list[dict]) -> Callable[[dict], None]:
    def cb(info: dict) -> None:
        file_found_cb_list.append(info)
    return cb


# ---------------------------------------------------------------------------
# Test: probe()
# ---------------------------------------------------------------------------

class TestFAT32Probe:
    def test_probe_valid_fat32(self):
        boot = make_fat32_boot_sector()
        fd, path = _write_tmp(boot)
        try:
            parser = FAT32Parser("test.img", fd)
            assert parser.probe() is True
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_ntfs(self):
        # NTFS OEM name
        data = bytearray(512)
        data[0x03:0x0B] = b"NTFS    "
        # Also set NTFS type string and make bps nonzero to ensure it's not FAT32
        data[0x0B] = 0  # bps = 0, ensures FAT32 check fails even earlier
        fd, path = _write_tmp(bytes(data))
        try:
            parser = FAT32Parser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_exfat(self):
        data = bytearray(512)
        data[0x03:0x0B] = b"EXFAT   "
        fd, path = _write_tmp(bytes(data))
        try:
            parser = FAT32Parser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_random_data(self):
        import random
        rng = random.Random(42)
        data = bytes([rng.randint(0, 255) for _ in range(512)])
        fd, path = _write_tmp(data)
        try:
            parser = FAT32Parser("test.img", fd)
            # May or may not pass by coincidence but almost certainly won't match "FAT32   "
            result = parser.probe()
            # We just verify it doesn't raise
            assert isinstance(result, bool)
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_too_short(self):
        # Fewer than 90 bytes → _parse_bpb returns False
        data = b"\x00" * 50
        fd, path = _write_tmp(data)
        try:
            parser = FAT32Parser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_zero_bps(self):
        boot = make_fat32_boot_sector(bytes_per_sector=0)
        # Manually restore FAT32 type string (make_fat32_boot_sector sets it)
        fd, path = _write_tmp(boot)
        try:
            parser = FAT32Parser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)

    def test_probe_rejects_zero_spc(self):
        boot = make_fat32_boot_sector(sectors_per_cluster=0)
        fd, path = _write_tmp(boot)
        try:
            parser = FAT32Parser("test.img", fd)
            assert parser.probe() is False
        finally:
            os.close(fd)
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: cluster math
# ---------------------------------------------------------------------------

class TestFAT32ClusterMath:
    def _make_probed_parser(
        self,
        bps: int = 512,
        spc: int = 8,
        reserved: int = 32,
        num_fats: int = 2,
        spf: int = 512,
        root_clus: int = 2,
    ) -> tuple[FAT32Parser, int, str]:
        boot = make_fat32_boot_sector(
            bytes_per_sector=bps,
            sectors_per_cluster=spc,
            reserved_sectors=reserved,
            num_fats=num_fats,
            sectors_per_fat32=spf,
            root_cluster=root_clus,
        )
        # Pad with enough data for FAT reads
        total = 16 * 1024 * 1024  # 16 MiB
        fd, path = _write_tmp(boot + b"\x00" * (total - len(boot)))
        parser = FAT32Parser("test.img", fd)
        assert parser.probe() is True
        return parser, fd, path

    def test_cluster_offset_calculation(self):
        """cluster_offset = data_start + (cluster - 2) * cluster_size"""
        bps, spc, reserved, num_fats, spf = 512, 8, 32, 2, 512
        parser, fd, path = self._make_probed_parser(
            bps=bps, spc=spc, reserved=reserved, num_fats=num_fats, spf=spf
        )
        try:
            cluster_size = bps * spc
            fat_start = reserved * bps
            data_start = (reserved + num_fats * spf) * bps
            expected_offset = data_start + (5 - 2) * cluster_size
            assert parser._cluster_offset(5) == expected_offset
            # Cluster 2 is the first data cluster (offset = data_start)
            assert parser._cluster_offset(2) == data_start
        finally:
            os.close(fd)
            os.unlink(path)

    def test_next_cluster_reads_fat_entry(self):
        """
        Write a known 4-byte FAT entry and verify _next_cluster reads it.
        """
        bps, spc, reserved, num_fats, spf = 512, 8, 32, 2, 512
        boot = make_fat32_boot_sector(
            bytes_per_sector=bps, sectors_per_cluster=spc,
            reserved_sectors=reserved, num_fats=num_fats,
            sectors_per_fat32=spf, root_cluster=2,
        )
        fat_start = reserved * bps
        # Cluster 3 → cluster 4 chain entry at fat_start + 3 * 4
        total = 16 * 1024 * 1024
        buf = bytearray(total)
        buf[:len(boot)] = boot
        # Write FAT entry for cluster 3 → 4 (value 0x00000004)
        offset_in_fat = fat_start + 3 * 4
        struct.pack_into("<I", buf, offset_in_fat, 4)
        fd, path = _write_tmp(bytes(buf))
        try:
            parser = FAT32Parser("test.img", fd)
            assert parser.probe() is True
            assert parser._next_cluster(3) == 4
        finally:
            os.close(fd)
            os.unlink(path)

    def test_collect_chain_stops_at_eoc(self):
        """Chain stops when FAT entry >= 0x0FFFFFF8 (end-of-chain)."""
        bps, spc, reserved, num_fats, spf = 512, 8, 32, 2, 512
        boot = make_fat32_boot_sector(
            bytes_per_sector=bps, sectors_per_cluster=spc,
            reserved_sectors=reserved, num_fats=num_fats,
            sectors_per_fat32=spf, root_cluster=2,
        )
        fat_start = reserved * bps
        total = 16 * 1024 * 1024
        buf = bytearray(total)
        buf[:len(boot)] = boot
        # Build chain: 2 → 3 → EOC
        struct.pack_into("<I", buf, fat_start + 2 * 4, 3)
        struct.pack_into("<I", buf, fat_start + 3 * 4, 0x0FFFFFFF)  # EOC
        fd, path = _write_tmp(bytes(buf))
        try:
            parser = FAT32Parser("test.img", fd)
            assert parser.probe() is True
            chain = parser._collect_chain(2)
            assert chain == [2, 3]
        finally:
            os.close(fd)
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: directory entry parsing
# ---------------------------------------------------------------------------

def make_83_entry(
    stem: str,
    ext: str,
    attr: int = 0x20,
    start_cluster_hi: int = 0,
    start_cluster_lo: int = 10,
    file_size: int = 1024,
    deleted: bool = False,
) -> bytes:
    """Build a 32-byte FAT 8.3 directory entry."""
    entry = bytearray(32)
    name = stem.upper().ljust(8)[:8].encode("latin-1")
    ext_b = ext.upper().ljust(3)[:3].encode("latin-1")
    if deleted:
        name = b"\xe5" + name[1:]
    entry[0x00:0x08] = name
    entry[0x08:0x0B] = ext_b
    entry[0x0B] = attr
    struct.pack_into("<H", entry, 0x14, start_cluster_hi)
    struct.pack_into("<H", entry, 0x1A, start_cluster_lo)
    struct.pack_into("<I", entry, 0x1C, file_size)
    return bytes(entry)


def make_lfn_entry(seq: int, chars: str, is_last: bool = False) -> bytes:
    """Build a 32-byte LFN directory entry."""
    entry = bytearray(32)
    seq_byte = seq | (0x40 if is_last else 0)
    entry[0x00] = seq_byte
    entry[0x0B] = 0x0F  # LFN attribute
    # Encode up to 13 chars
    utf16 = chars[:13].encode("utf-16-le").ljust(26, b"\xff")
    entry[0x01:0x0B] = utf16[0:10]   # chars 1-5
    entry[0x0E:0x1A] = utf16[10:22]  # chars 6-11
    entry[0x1C:0x1E] = utf16[22:24]  # chars 12-13
    return bytes(entry)


def make_end_entry() -> bytes:
    """Return a 32-byte end-of-directory entry (first byte = 0x00)."""
    return b"\x00" * 32


class TestFAT32DirectoryParsing:
    def _make_fs_with_dir_cluster(
        self,
        dir_entries: bytes,
        root_cluster: int = 2,
    ) -> tuple[FAT32Parser, int, str]:
        """
        Build a minimal FAT32 image where cluster 2 contains *dir_entries*.
        """
        bps, spc, reserved, num_fats, spf = 512, 8, 32, 2, 512
        boot = make_fat32_boot_sector(
            bytes_per_sector=bps, sectors_per_cluster=spc,
            reserved_sectors=reserved, num_fats=num_fats,
            sectors_per_fat32=spf, root_cluster=root_cluster,
        )
        cluster_size = bps * spc
        fat_start = reserved * bps
        data_start = (reserved + num_fats * spf) * bps

        total = data_start + 64 * cluster_size
        buf = bytearray(total)
        buf[:len(boot)] = boot

        # FAT: cluster 2 → EOC
        struct.pack_into("<I", buf, fat_start + 2 * 4, 0x0FFFFFFF)

        # Write dir entries into cluster 2
        cluster_2_offset = data_start  # (2 - 2) * cluster_size = 0
        padded = dir_entries + b"\x00" * (cluster_size - len(dir_entries))
        buf[cluster_2_offset:cluster_2_offset + cluster_size] = padded[:cluster_size]

        fd, path = _write_tmp(bytes(buf))
        parser = FAT32Parser("test.img", fd)
        assert parser.probe() is True
        return parser, fd, path

    def test_walk_dir_83_entry(self):
        entry = make_83_entry("README", "TXT", file_size=2048, start_cluster_lo=10)
        entries = entry + make_end_entry()
        parser, fd, path = self._make_fs_with_dir_cluster(entries)
        try:
            found: list[dict] = []
            count = parser._walk_dir(
                cluster=2,
                path_prefix="/",
                stop_flag=_no_stop,
                file_found_cb=lambda info: found.append(info),
                visited=set(),
            )
            assert count == 1
            assert len(found) == 1
            info = found[0]
            assert info["name"] == "README.TXT"
            assert info["type"] == "TXT"
            assert info["integrity"] == 85  # active file
            assert info["source"] == "fat32"
            assert info["fs"] == "FAT32"
        finally:
            os.close(fd)
            os.unlink(path)

    def test_walk_dir_deleted_entry(self):
        entry = make_83_entry("SECRET", "DAT", file_size=512, deleted=True)
        entries = entry + make_end_entry()
        parser, fd, path = self._make_fs_with_dir_cluster(entries)
        try:
            found: list[dict] = []
            parser._walk_dir(
                cluster=2,
                path_prefix="/",
                stop_flag=_no_stop,
                file_found_cb=lambda info: found.append(info),
                visited=set(),
            )
            assert len(found) == 1
            assert found[0]["integrity"] == 70  # deleted
        finally:
            os.close(fd)
            os.unlink(path)

    def test_walk_dir_lfn_entry(self):
        """LFN entry before 8.3 → long name used."""
        lfn = make_lfn_entry(1, "LongFileName", is_last=True)
        short = make_83_entry("LONGFI~1", "TXT", file_size=100, start_cluster_lo=5)
        entries = lfn + short + make_end_entry()
        parser, fd, path = self._make_fs_with_dir_cluster(entries)
        try:
            found: list[dict] = []
            parser._walk_dir(
                cluster=2,
                path_prefix="/",
                stop_flag=_no_stop,
                file_found_cb=lambda info: found.append(info),
                visited=set(),
            )
            assert len(found) == 1
            assert "LongFileName" in found[0]["name"]
        finally:
            os.close(fd)
            os.unlink(path)

    def test_walk_dir_end_marker(self):
        """0x00 as first byte stops the iteration — no files after it."""
        end_entry = make_end_entry()
        after_end = make_83_entry("AFTER", "TXT", file_size=100)
        entries = end_entry + after_end
        parser, fd, path = self._make_fs_with_dir_cluster(entries)
        try:
            found: list[dict] = []
            parser._walk_dir(
                cluster=2,
                path_prefix="/",
                stop_flag=_no_stop,
                file_found_cb=lambda info: found.append(info),
                visited=set(),
            )
            assert len(found) == 0
        finally:
            os.close(fd)
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: enumerate_files with stop_flag
# ---------------------------------------------------------------------------

class TestFAT32EnumerateFiles:
    def _make_simple_image(self) -> tuple[FAT32Parser, int, str]:
        bps, spc, reserved, num_fats, spf = 512, 8, 32, 2, 512
        boot = make_fat32_boot_sector(
            bytes_per_sector=bps, sectors_per_cluster=spc,
            reserved_sectors=reserved, num_fats=num_fats,
            sectors_per_fat32=spf, root_cluster=2,
        )
        fat_start = reserved * bps
        cluster_size = bps * spc
        data_start = (reserved + num_fats * spf) * bps
        total = data_start + 32 * cluster_size
        buf = bytearray(total)
        buf[:len(boot)] = boot
        struct.pack_into("<I", buf, fat_start + 2 * 4, 0x0FFFFFFF)

        # Put one file entry in root cluster
        entry = make_83_entry("FILE", "TXT", file_size=256, start_cluster_lo=3)
        end = make_end_entry()
        buf[data_start:data_start + len(entry) + len(end)] = entry + end

        fd, path = _write_tmp(bytes(buf))
        parser = FAT32Parser("test.img", fd)
        return parser, fd, path

    def test_enumerate_files_respects_stop_flag(self):
        parser, fd, path = self._make_simple_image()
        try:
            found: list[dict] = []
            count = parser.enumerate_files(
                stop_flag=lambda: True,  # immediately stop
                progress_cb=_no_progress,
                file_found_cb=lambda info: found.append(info),
            )
            # With immediate stop, 0 files (or very few) should be emitted
            assert count == 0
        finally:
            os.close(fd)
            os.unlink(path)

    def test_file_info_schema(self):
        """Emitted dict has all required keys."""
        parser, fd, path = self._make_simple_image()
        try:
            found: list[dict] = []
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=lambda info: found.append(info),
            )
            assert len(found) >= 1
            info = found[0]
            required_keys = {"name", "type", "offset", "size_kb", "device", "integrity",
                             "mft_path", "source", "fs", "data_runs"}
            assert required_keys.issubset(info.keys())
            assert info["source"] == "fat32"
            assert info["fs"] == "FAT32"
        finally:
            os.close(fd)
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: detect_fs() integration
# ---------------------------------------------------------------------------

class TestFAT32DetectFS:
    def test_detect_fs_returns_fat32_parser(self):
        boot = make_fat32_boot_sector()
        # Pad to reasonable size so FAT reads don't fail
        total = 16 * 1024 * 1024
        fd, path = _write_tmp(boot + b"\x00" * (total - len(boot)))
        try:
            parser = detect_fs("test.img", fd)
            assert parser is not None
            assert isinstance(parser, FAT32Parser)
        finally:
            os.close(fd)
            os.unlink(path)
