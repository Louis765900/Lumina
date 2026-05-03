"""
Tests for ExFATParser in app/core/fs_parser.py

Uses tempfile.mkstemp() to create real binary files — no PyQt6.
"""

from __future__ import annotations

import os
import struct
import tempfile
from unittest.mock import patch

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
            parser = ExFATParser(r"\\.\PhysicalDrive0", 99)
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


# ---------------------------------------------------------------------------
# Real exFAT enumeration tests
# ---------------------------------------------------------------------------

# Geometry shared by all enumeration tests
_BPS_SHIFT = 9
_SPC_SHIFT = 3
_BPS = 1 << _BPS_SHIFT  # 512
_CLUSTER_SIZE = _BPS << _SPC_SHIFT  # 4096
_FAT_OFFSET_SEC = 8
_FAT_LENGTH_SEC = 8
_HEAP_OFFSET_SEC = 16
_CLUSTER_COUNT = 100
_FAT_OFFSET = _FAT_OFFSET_SEC * _BPS
_HEAP_OFFSET = _HEAP_OFFSET_SEC * _BPS
_ROOT_CLUSTER = 2


def _make_exfat_vbr(
    *,
    first_cluster_root: int = _ROOT_CLUSTER,
    bps_shift: int = _BPS_SHIFT,
    spc_shift: int = _SPC_SHIFT,
    fat_offset_sec: int = _FAT_OFFSET_SEC,
    fat_length_sec: int = _FAT_LENGTH_SEC,
    heap_offset_sec: int = _HEAP_OFFSET_SEC,
    cluster_count: int = _CLUSTER_COUNT,
    num_fats: int = 1,
) -> bytes:
    vbr = bytearray(_BPS)
    vbr[3:11] = b"EXFAT   "
    struct.pack_into("<I", vbr, 0x50, fat_offset_sec)
    struct.pack_into("<I", vbr, 0x54, fat_length_sec)
    struct.pack_into("<I", vbr, 0x58, heap_offset_sec)
    struct.pack_into("<I", vbr, 0x5C, cluster_count)
    struct.pack_into("<I", vbr, 0x60, first_cluster_root)
    vbr[0x6C] = bps_shift
    vbr[0x6D] = spc_shift
    vbr[0x6E] = num_fats
    return bytes(vbr)


def _file_entry(*, secondary_count: int, is_dir: bool, deleted: bool = False) -> bytes:
    e = bytearray(32)
    e[0] = 0x05 if deleted else 0x85
    e[1] = secondary_count
    attrs = 0x10 if is_dir else 0x20
    struct.pack_into("<H", e, 4, attrs)
    return bytes(e)


def _stream_entry(
    *,
    name_length: int,
    first_cluster: int,
    file_size: int,
    no_fat_chain: bool = True,
    deleted: bool = False,
) -> bytes:
    e = bytearray(32)
    e[0] = 0x40 if deleted else 0xC0
    flags = 0x01  # AllocationPossible
    if no_fat_chain:
        flags |= 0x02
    e[1] = flags
    e[3] = name_length
    struct.pack_into("<I", e, 0x14, first_cluster)
    struct.pack_into("<Q", e, 0x18, file_size)
    return bytes(e)


def _name_entries(name: str, *, deleted: bool = False) -> bytes:
    """Pack a UTF-16-LE name into one or more 0xC1 (or 0x41) entries."""
    encoded = name.encode("utf-16-le")
    blocks: list[bytes] = []
    for k in range(0, len(encoded), 30):
        chunk = encoded[k : k + 30]
        e = bytearray(32)
        e[0] = 0x41 if deleted else 0xC1
        e[1] = 0  # GeneralSecondaryFlags (unused for name)
        e[2 : 2 + len(chunk)] = chunk
        # Pad remaining UTF-16 cells with 0xFFFF (per spec) — using 0x00 is OK too.
        blocks.append(bytes(e))
    return b"".join(blocks)


def _build_directory_entry_set(
    name: str,
    *,
    is_dir: bool,
    first_cluster: int,
    file_size: int,
    deleted: bool = False,
    no_fat_chain: bool = True,
) -> bytes:
    name_blocks = _name_entries(name, deleted=deleted)
    n_name = len(name_blocks) // 32
    secondary_count = 1 + n_name  # 1 stream + name entries
    primary = _file_entry(
        secondary_count=secondary_count,
        is_dir=is_dir,
        deleted=deleted,
    )
    stream = _stream_entry(
        name_length=len(name),
        first_cluster=first_cluster,
        file_size=file_size,
        no_fat_chain=no_fat_chain,
        deleted=deleted,
    )
    return primary + stream + name_blocks


def _build_exfat_image(
    *, root_entries: bytes, extra_clusters: dict[int, bytes] | None = None
) -> bytes:
    """Build a complete exFAT image with the given root directory bytes.

    extra_clusters maps cluster index → cluster contents (used for subdirectory data).
    """
    image_size = _HEAP_OFFSET + _CLUSTER_COUNT * _CLUSTER_SIZE
    img = bytearray(image_size)
    img[0:_BPS] = _make_exfat_vbr()
    # Root cluster heap at cluster 2
    root_off = _HEAP_OFFSET + (_ROOT_CLUSTER - 2) * _CLUSTER_SIZE
    truncated = root_entries[:_CLUSTER_SIZE]
    img[root_off : root_off + len(truncated)] = truncated
    if extra_clusters:
        for clus, payload in extra_clusters.items():
            off = _HEAP_OFFSET + (clus - 2) * _CLUSTER_SIZE
            cut = payload[:_CLUSTER_SIZE]
            img[off : off + len(cut)] = cut
    return bytes(img)


def _open_image(data: bytes) -> tuple[int, str]:
    fd, path = tempfile.mkstemp(suffix=".img")
    try:
        os.write(fd, data)
        os.lseek(fd, 0, os.SEEK_SET)
    except Exception:
        os.close(fd)
        os.unlink(path)
        raise
    return fd, path


class TestExFATFullEnumeration:
    def test_active_short_name_file_emitted(self):
        entries = _build_directory_entry_set(
            "hello.txt",
            is_dir=False,
            first_cluster=10,
            file_size=2048,
        )
        img = _build_exfat_image(root_entries=entries)
        fd, path = _open_image(img)
        try:
            parser = ExFATParser("test.img", fd)
            assert parser.probe()
            found: list[dict] = []
            count = parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=found.append,
            )
            assert count == 1
            assert len(found) == 1
            info = found[0]
            assert info["name"] == "hello.txt"
            assert info["fs"] == "exFAT"
            assert info["source"] == "exfat"
            assert info["type"] == "TXT"
            assert info["integrity"] == 85
            assert info["mft_path"] == "/hello.txt"
            assert info["offset"] == _HEAP_OFFSET + (10 - 2) * _CLUSTER_SIZE
            assert info["data_runs"]
            assert "deleted" not in info
        finally:
            os.close(fd)
            os.unlink(path)

    def test_long_unicode_name_reconstructed(self):
        long_name = "thumbnail-very-long-name-2026.JPEG"  # 35 chars > 15
        assert len(long_name) > 15
        entries = _build_directory_entry_set(
            long_name,
            is_dir=False,
            first_cluster=15,
            file_size=1024,
        )
        img = _build_exfat_image(root_entries=entries)
        fd, path = _open_image(img)
        try:
            parser = ExFATParser("test.img", fd)
            found: list[dict] = []
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=found.append,
            )
            assert len(found) == 1
            assert found[0]["name"] == long_name
            assert found[0]["type"] == "JPEG"
        finally:
            os.close(fd)
            os.unlink(path)

    def test_deleted_entry_emitted_with_lower_integrity(self):
        active = _build_directory_entry_set(
            "kept.txt",
            is_dir=False,
            first_cluster=10,
            file_size=512,
        )
        deleted = _build_directory_entry_set(
            "lost.dat",
            is_dir=False,
            first_cluster=20,
            file_size=4096,
            deleted=True,
        )
        img = _build_exfat_image(root_entries=active + deleted)
        fd, path = _open_image(img)
        try:
            parser = ExFATParser("test.img", fd)
            found: list[dict] = []
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=found.append,
            )
            names = {info["name"]: info for info in found}
            assert set(names) == {"kept.txt", "lost.dat"}
            assert names["kept.txt"]["integrity"] == 85
            assert "deleted" not in names["kept.txt"]
            assert names["lost.dat"]["integrity"] == 60
            assert names["lost.dat"]["deleted"] is True
        finally:
            os.close(fd)
            os.unlink(path)

    def test_subdirectory_recursed(self):
        sub_entries = _build_directory_entry_set(
            "inside.bin",
            is_dir=False,
            first_cluster=30,
            file_size=128,
        )
        sub_cluster_payload = bytearray(_CLUSTER_SIZE)
        sub_cluster_payload[: len(sub_entries)] = sub_entries

        dir_entry = _build_directory_entry_set(
            "subdir",
            is_dir=True,
            first_cluster=20,
            file_size=_CLUSTER_SIZE,
        )

        img = _build_exfat_image(
            root_entries=dir_entry,
            extra_clusters={20: bytes(sub_cluster_payload)},
        )
        fd, path = _open_image(img)
        try:
            parser = ExFATParser("test.img", fd)
            found: list[dict] = []
            count = parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=found.append,
            )
            assert count == 1
            info = found[0]
            assert info["name"] == "inside.bin"
            assert info["mft_path"] == "/subdir/inside.bin"
        finally:
            os.close(fd)
            os.unlink(path)

    def test_no_fat_chain_uses_data_length_for_run_count(self):
        # File spans 3 contiguous clusters.
        entries = _build_directory_entry_set(
            "big.bin",
            is_dir=False,
            first_cluster=10,
            file_size=3 * _CLUSTER_SIZE,
            no_fat_chain=True,
        )
        img = _build_exfat_image(root_entries=entries)
        fd, path = _open_image(img)
        try:
            parser = ExFATParser("test.img", fd)
            found: list[dict] = []
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=found.append,
            )
            assert len(found) == 1
            runs = found[0]["data_runs"]
            # Contiguous → single run.
            assert len(runs) == 1
            assert runs[0][0] == _HEAP_OFFSET + (10 - 2) * _CLUSTER_SIZE
            assert runs[0][1] == 3 * _CLUSTER_SIZE
        finally:
            os.close(fd)
            os.unlink(path)

    def test_fat_chain_followed_for_fragmented_file(self):
        # File at cluster 10 → 12 → 14 (fragmented), file_size = 3 cluster.
        # Build FAT: entry[10]=12, entry[12]=14, entry[14]=0xFFFFFFFF
        entries = _build_directory_entry_set(
            "frag.bin",
            is_dir=False,
            first_cluster=10,
            file_size=3 * _CLUSTER_SIZE,
            no_fat_chain=False,
        )
        img = bytearray(_build_exfat_image(root_entries=entries))
        # Patch FAT entries (each 4 bytes LE)
        struct.pack_into("<I", img, _FAT_OFFSET + 10 * 4, 12)
        struct.pack_into("<I", img, _FAT_OFFSET + 12 * 4, 14)
        struct.pack_into("<I", img, _FAT_OFFSET + 14 * 4, 0xFFFFFFFF)
        fd, path = _open_image(bytes(img))
        try:
            parser = ExFATParser("test.img", fd)
            found: list[dict] = []
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=found.append,
            )
            assert len(found) == 1
            runs = found[0]["data_runs"]
            # Three non-contiguous clusters → three runs of one cluster each.
            assert len(runs) == 3
            for _start, length in runs:
                assert length == _CLUSTER_SIZE
        finally:
            os.close(fd)
            os.unlink(path)

    def test_fat_chain_cycle_does_not_loop_forever(self):
        entries = _build_directory_entry_set(
            "loop.bin",
            is_dir=False,
            first_cluster=10,
            file_size=10 * _CLUSTER_SIZE,
            no_fat_chain=False,
        )
        img = bytearray(_build_exfat_image(root_entries=entries))
        struct.pack_into("<I", img, _FAT_OFFSET + 10 * 4, 11)
        struct.pack_into("<I", img, _FAT_OFFSET + 11 * 4, 10)  # cycle
        fd, path = _open_image(bytes(img))
        try:
            parser = ExFATParser("test.img", fd)
            found: list[dict] = []
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=found.append,
            )
            assert len(found) == 1  # parser must not hang
        finally:
            os.close(fd)
            os.unlink(path)

    def test_stop_flag_aborts_enumeration_quickly(self):
        # Build root with several files
        entries = b""
        for k in range(5):
            entries += _build_directory_entry_set(
                f"file{k}.bin",
                is_dir=False,
                first_cluster=10 + k,
                file_size=512,
            )
        img = _build_exfat_image(root_entries=entries)
        fd, path = _open_image(img)
        try:
            parser = ExFATParser("test.img", fd)
            found: list[dict] = []
            count = parser.enumerate_files(
                stop_flag=lambda: True,
                progress_cb=_no_progress,
                file_found_cb=found.append,
            )
            assert count == 0
            assert found == []
        finally:
            os.close(fd)
            os.unlink(path)

    def test_invalid_vbr_falls_back_to_zero(self):
        img = bytearray(_HEAP_OFFSET + _CLUSTER_COUNT * _CLUSTER_SIZE)
        img[3:11] = b"EXFAT   "  # OEM only, rest zero — VBR shifts invalid
        fd, path = _open_image(bytes(img))
        try:
            parser = ExFATParser("test.img", fd)
            assert parser.probe()  # OEM-based probe still passes
            found: list[dict] = []
            count = parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=found.append,
            )
            assert count == 0
            assert found == []
        finally:
            os.close(fd)
            os.unlink(path)

    def test_recursive_loop_in_subdirectory_is_safe(self):
        # Subdir entry that points back to root cluster — visited set prevents loop.
        dir_entry = _build_directory_entry_set(
            "selfref",
            is_dir=True,
            first_cluster=_ROOT_CLUSTER,
            file_size=_CLUSTER_SIZE,
        )
        img = _build_exfat_image(root_entries=dir_entry)
        fd, path = _open_image(img)
        try:
            parser = ExFATParser("test.img", fd)
            found: list[dict] = []
            parser.enumerate_files(
                stop_flag=_no_stop,
                progress_cb=_no_progress,
                file_found_cb=found.append,
            )
            # No files (only directory pointing to root which is visited)
            assert len(found) == 0
        finally:
            os.close(fd)
            os.unlink(path)

    def test_progress_callback_reaches_100_on_success(self):
        entries = _build_directory_entry_set(
            "ok.txt",
            is_dir=False,
            first_cluster=10,
            file_size=128,
        )
        img = _build_exfat_image(root_entries=entries)
        fd, path = _open_image(img)
        try:
            parser = ExFATParser("test.img", fd)
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
