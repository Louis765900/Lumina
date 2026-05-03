from __future__ import annotations

import struct
from typing import Any

from app.core.fs_parser import (
    _GPT_BASIC_DATA_GUID,
    _MFT_ENTRY_SIZE,
    BootSector,
    NTFSParser,
)

_ATTR_END = 0xFFFF_FFFF
_ATTR_FILE_NAME = 0x30
_ATTR_DATA = 0x80
_FLAG_IN_USE = 0x01
_FLAG_DIR = 0x02


def _ntfs_bpb(
    *,
    bytes_per_sector: int = 512,
    sectors_per_cluster: int = 8,
    total_sectors: int = 100_000,
    mft_start_cluster: int = 4,
) -> bytes:
    bpb = bytearray(512)
    bpb[3:11] = b"NTFS    "
    struct.pack_into("<H", bpb, 0x0B, bytes_per_sector)
    bpb[0x0D] = sectors_per_cluster
    struct.pack_into("<Q", bpb, 0x28, total_sectors)
    struct.pack_into("<Q", bpb, 0x30, mft_start_cluster)
    return bytes(bpb)


def _mbr_with_partition(*, partition_type: int, lba: int) -> bytes:
    mbr = bytearray(512)
    base = 0x1BE
    mbr[base + 4] = partition_type
    struct.pack_into("<I", mbr, base + 8, lba)
    mbr[510:512] = b"\x55\xaa"
    return bytes(mbr)


def _file_name_attr(name: str, *, parent_index: int = 5, size_bytes: int = 0) -> bytes:
    name_bytes = name.encode("utf-16-le")
    value = bytearray(0x42 + len(name_bytes))
    struct.pack_into("<Q", value, 0x00, parent_index)
    struct.pack_into("<Q", value, 0x28, size_bytes)
    struct.pack_into("<Q", value, 0x30, size_bytes)
    value[0x40] = len(name)
    value[0x41] = 1
    value[0x42 : 0x42 + len(name_bytes)] = name_bytes
    return _resident_attr(_ATTR_FILE_NAME, bytes(value))


def _resident_attr(attr_type: int, value: bytes) -> bytes:
    attr_len = 0x18 + len(value)
    attr = bytearray(attr_len)
    struct.pack_into("<I", attr, 0x00, attr_type)
    struct.pack_into("<I", attr, 0x04, attr_len)
    attr[0x08] = 0
    struct.pack_into("<I", attr, 0x10, len(value))
    struct.pack_into("<H", attr, 0x14, 0x18)
    attr[0x18:] = value
    return bytes(attr)


def _nonresident_data_attr(*, actual_size: int, run_list: bytes) -> bytes:
    attr_len = 0x40 + len(run_list)
    attr = bytearray(attr_len)
    struct.pack_into("<I", attr, 0x00, _ATTR_DATA)
    struct.pack_into("<I", attr, 0x04, attr_len)
    attr[0x08] = 1
    struct.pack_into("<H", attr, 0x20, 0x40)
    struct.pack_into("<Q", attr, 0x28, actual_size)
    struct.pack_into("<Q", attr, 0x30, actual_size)
    struct.pack_into("<Q", attr, 0x38, actual_size)
    attr[0x40:] = run_list
    return bytes(attr)


def _mft_record(*, flags: int, attrs: list[bytes]) -> bytes:
    record = bytearray(_MFT_ENTRY_SIZE)
    record[:4] = b"FILE"
    struct.pack_into("<H", record, 0x04, 0x28)
    struct.pack_into("<H", record, 0x06, 3)
    record[0x28:0x2A] = b"\xaa\xbb"
    record[0x2A:0x2E] = b"\x00\x00\x00\x00"
    record[510:512] = b"\xaa\xbb"
    record[1022:1024] = b"\xaa\xbb"
    struct.pack_into("<H", record, 0x14, 0x38)
    struct.pack_into("<H", record, 0x16, flags)

    pos = 0x38
    for attr in attrs:
        record[pos : pos + len(attr)] = attr
        pos += len(attr)
    struct.pack_into("<I", record, pos, _ATTR_END)
    return bytes(record)


def test_logical_ntfs_bpb_parses_mft_location(monkeypatch):
    parser = NTFSParser(r"\\.\C:", fd=999)

    monkeypatch.setattr(parser, "_read_raw", lambda _offset, _size: _ntfs_bpb())

    boot = parser.read_boot_sector()

    assert boot is not None
    assert boot.cluster_size == 4096
    assert boot.mft_start_byte == 16_384
    assert boot.partition_offset == 0


def test_physical_mbr_ntfs_partition_parses_bpb_at_partition_offset(monkeypatch):
    parser = NTFSParser(r"\\.\PhysicalDrive0", fd=999)
    partition_offset = 2_048 * 512

    def read_raw(offset: int, _size: int) -> bytes:
        if offset == 0:
            return _mbr_with_partition(partition_type=0x07, lba=2_048)
        if offset == partition_offset:
            return _ntfs_bpb(mft_start_cluster=8)
        raise AssertionError(f"unexpected read offset: {offset}")

    monkeypatch.setattr(parser, "_read_raw", read_raw)

    boot = parser.read_boot_sector()

    assert boot is not None
    assert boot.partition_offset == partition_offset
    assert boot.mft_start_byte == partition_offset + 8 * 4096


def test_physical_gpt_basic_data_partition_parses_bpb(monkeypatch):
    parser = NTFSParser(r"\\.\PhysicalDrive0", fd=999)
    entry_lba = 4
    partition_lba = 4_096
    partition_offset = partition_lba * 512
    gpt = bytearray(512)
    gpt[:8] = b"EFI PART"
    struct.pack_into("<Q", gpt, 72, entry_lba)
    struct.pack_into("<I", gpt, 80, 1)
    struct.pack_into("<I", gpt, 84, 128)
    entry = bytearray(128)
    entry[:16] = _GPT_BASIC_DATA_GUID
    struct.pack_into("<Q", entry, 32, partition_lba)

    def read_raw(offset: int, _size: int) -> bytes:
        if offset == 0:
            return _mbr_with_partition(partition_type=0xEE, lba=1)
        if offset == 512:
            return bytes(gpt)
        if offset == entry_lba * 512:
            return bytes(entry)
        if offset == partition_offset:
            return _ntfs_bpb(mft_start_cluster=2)
        raise AssertionError(f"unexpected read offset: {offset}")

    monkeypatch.setattr(parser, "_read_raw", read_raw)

    boot = parser.read_boot_sector()

    assert boot is not None
    assert boot.partition_offset == partition_offset
    assert boot.mft_start_byte == partition_offset + 2 * 4096


def test_mft_entry_count_uses_nonresident_mft_data_size(monkeypatch):
    parser = NTFSParser(r"\\.\C:", fd=999)
    boot = BootSector(512, 8, 4096, 16_384, 100_000, 0)
    mft_record = _mft_record(
        flags=_FLAG_IN_USE,
        attrs=[_nonresident_data_attr(actual_size=19 * _MFT_ENTRY_SIZE, run_list=b"\x00")],
    )

    monkeypatch.setattr(parser, "_read_raw", lambda _offset, _size: mft_record)

    assert parser._get_mft_entry_count(boot) == 19


def test_scan_mft_emits_deleted_file_with_original_path_and_runs(monkeypatch):
    parser = NTFSParser(r"\\.\C:", fd=999)
    boot = BootSector(512, 8, 4096, 16_384, 100_000, 0)
    total_entries = 13
    mft_metadata = _mft_record(
        flags=_FLAG_IN_USE,
        attrs=[
            _nonresident_data_attr(
                actual_size=total_entries * _MFT_ENTRY_SIZE,
                run_list=b"\x00",
            )
        ],
    )
    users_dir = _mft_record(
        flags=_FLAG_IN_USE | _FLAG_DIR,
        attrs=[_file_name_attr("Users", parent_index=5)],
    )
    deleted_file = _mft_record(
        flags=0,
        attrs=[
            _file_name_attr("lost.txt", parent_index=6, size_bytes=8192),
            _nonresident_data_attr(actual_size=8192, run_list=b"\x11\x02\x07\x00"),
        ],
    )
    entries = [mft_metadata] + [bytes(_MFT_ENTRY_SIZE) for _ in range(total_entries - 1)]
    entries[6] = users_dir
    entries[12] = deleted_file
    batch = b"".join(entries)

    def read_raw(offset: int, size: int) -> bytes:
        if offset == boot.mft_start_byte and size == _MFT_ENTRY_SIZE:
            return mft_metadata
        if offset == boot.mft_start_byte and size == total_entries * _MFT_ENTRY_SIZE:
            return batch
        raise AssertionError(f"unexpected read offset={offset} size={size}")

    found: list[dict[str, Any]] = []
    progress: list[int] = []
    monkeypatch.setattr(parser, "_read_raw", read_raw)

    count = parser.scan_mft(
        boot,
        stop_flag=lambda: False,
        progress_cb=progress.append,
        file_found_cb=found.append,
    )

    assert count == 1
    assert found == [
        {
            "name": "lost.txt",
            "type": "TXT",
            "offset": 28_672,
            "size_kb": 8,
            "device": r"\\.\C:",
            "integrity": 80,
            "mft_path": "/Users/lost.txt",
            "source": "mft",
            "fs": "NTFS",
            "data_runs": [(28_672, 8192)],
            "deleted": True,
        }
    ]
    assert progress[-1] == 100
