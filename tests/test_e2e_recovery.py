"""
End-to-end recovery pipeline test on a synthetic FAT32 image.

The test exercises the chain a real Quick Scan walks:

    detect_fs(raw_device, fd)
        → FAT32Parser.probe()
        → FAT32Parser.enumerate_files(stop, progress, file_found_cb)
        → for each file_info, read data_runs back from the device
        → sha256(read_bytes) == sha256(original_payload)

If anything in that chain (probe, BPB parsing, cluster offset arithmetic,
data_runs construction, byte read-back, dedup index) regresses, this test
fails before the user notices on a real disk.
"""

from __future__ import annotations

import hashlib
import os
import struct
import tempfile

from app.core.fs_parser import FAT32Parser, detect_fs
from tests.test_fat32_parser import make_83_entry, make_fat32_boot_sector

# ── Geometry shared by the test image ─────────────────────────────────────
_BPS = 512
_SPC = 8
_RESERVED = 32
_NUM_FATS = 2
_SPF = 512
_CLUSTER_SIZE = _BPS * _SPC  # 4096
_FAT_START = _RESERVED * _BPS  # 16_384
_DATA_START = (_RESERVED + _NUM_FATS * _SPF) * _BPS  # 540_672


def _cluster_offset(cluster: int) -> int:
    """Absolute byte offset of cluster *cluster* in the image."""
    return _DATA_START + (cluster - 2) * _CLUSTER_SIZE


def _build_e2e_image() -> tuple[bytes, dict[str, bytes]]:
    """
    Build a 64-cluster FAT32 image with three files in the root directory.

    Returns (image_bytes, name_to_payload_map).

    Layout:
      cluster 2  : root directory (3 x 8.3 entries + end marker)
      cluster 10 : payload of HELLO.TXT (single cluster)
      cluster 11 : payload of NOTES.TXT (single cluster, partial)
      cluster 12 : payload of BLOB.BIN  cluster 1
      cluster 13 : payload of BLOB.BIN  cluster 2 (contiguous)
    """
    files: dict[str, bytes] = {
        "HELLO.TXT": b"Hello, world! This is a recoverable file." + b"\x00" * 8,
        "NOTES.TXT": b"Quick brown fox\n" * 4,
        "BLOB.BIN": bytes(range(256)) * 32,  # 8 KiB → spans 2 clusters
    }

    # Build root directory (cluster 2)
    dir_bytes = (
        make_83_entry("HELLO", "TXT", file_size=len(files["HELLO.TXT"]), start_cluster_lo=10)
        + make_83_entry("NOTES", "TXT", file_size=len(files["NOTES.TXT"]), start_cluster_lo=11)
        + make_83_entry("BLOB", "BIN", file_size=len(files["BLOB.BIN"]), start_cluster_lo=12)
        + b"\x00" * 32  # end marker
    )

    boot = make_fat32_boot_sector(
        bytes_per_sector=_BPS,
        sectors_per_cluster=_SPC,
        reserved_sectors=_RESERVED,
        num_fats=_NUM_FATS,
        sectors_per_fat32=_SPF,
        root_cluster=2,
    )

    image = bytearray(_DATA_START + 64 * _CLUSTER_SIZE)
    image[: len(boot)] = boot

    # FAT entries (cluster N → next cluster, 0x0FFFFFFF = EOC)
    # Cluster 2 (root)            : EOC
    # Clusters 10, 11             : EOC (single-cluster files)
    # Cluster 12 → 13 → EOC       : 2-cluster file
    for cluster, value in (
        (2, 0x0FFFFFFF),
        (10, 0x0FFFFFFF),
        (11, 0x0FFFFFFF),
        (12, 13),
        (13, 0x0FFFFFFF),
    ):
        struct.pack_into("<I", image, _FAT_START + cluster * 4, value)

    # Root directory contents
    root_off = _cluster_offset(2)
    image[root_off : root_off + len(dir_bytes)] = dir_bytes

    # File payloads
    for name, cluster_start in (("HELLO.TXT", 10), ("NOTES.TXT", 11)):
        off = _cluster_offset(cluster_start)
        payload = files[name]
        image[off : off + len(payload)] = payload

    # BLOB.BIN spans clusters 12 and 13 (8 KiB = 2 x 4 KiB).
    blob = files["BLOB.BIN"]
    off = _cluster_offset(12)
    image[off : off + len(blob)] = blob

    return bytes(image), files


def _read_data_runs(fd: int, data_runs: list[tuple[int, int]], file_size: int) -> bytes:
    """Read bytes referenced by data_runs, capped at file_size."""
    out = bytearray()
    remaining = file_size
    for start, length in data_runs:
        if remaining <= 0:
            break
        take = min(length, remaining)
        os.lseek(fd, start, os.SEEK_SET)
        chunk = os.read(fd, take)
        out.extend(chunk)
        remaining -= len(chunk)
    return bytes(out)


def test_e2e_fat32_scan_recover_hash_round_trip():
    image_bytes, expected = _build_e2e_image()

    fd, path = tempfile.mkstemp(suffix=".img")
    try:
        os.write(fd, image_bytes)
        os.lseek(fd, 0, os.SEEK_SET)

        # 1. detect_fs returns the FAT32 parser.
        parser = detect_fs("test.img", fd)
        assert isinstance(parser, FAT32Parser), f"expected FAT32Parser, got {type(parser).__name__}"

        # 2. enumerate_files yields exactly the three files we wrote.
        found: list[dict] = []
        progress: list[int] = []
        count = parser.enumerate_files(
            stop_flag=lambda: False,
            progress_cb=progress.append,
            file_found_cb=found.append,
        )
        assert count == 3, f"expected 3 files, got {count}: {[f['name'] for f in found]}"
        assert progress and progress[-1] == 100
        names = sorted(info["name"] for info in found)
        assert names == ["BLOB.BIN", "HELLO.TXT", "NOTES.TXT"]

        # 3. Each file_info carries the right metadata + a usable data_runs list.
        by_name = {info["name"]: info for info in found}
        for name in ("HELLO.TXT", "NOTES.TXT", "BLOB.BIN"):
            info = by_name[name]
            assert info["fs"] == "FAT32"
            assert info["source"] == "fat32"
            assert info["integrity"] == 85  # active file
            assert info["mft_path"] == "/" + name
            assert info["data_runs"], f"missing data_runs for {name}"
            assert info["offset"] >= _DATA_START

        # 4. Round-trip every file through data_runs and check SHA-256.
        for name, payload in expected.items():
            info = by_name[name]
            file_size_bytes = len(payload)
            recovered = _read_data_runs(fd, info["data_runs"], file_size_bytes)
            assert len(recovered) == file_size_bytes, (
                f"{name}: read {len(recovered)} bytes, expected {file_size_bytes}"
            )
            assert hashlib.sha256(recovered).hexdigest() == hashlib.sha256(payload).hexdigest(), (
                f"hash mismatch for {name}"
            )

        # 5. The 2-cluster file must come back as a single coalesced run.
        blob_runs = by_name["BLOB.BIN"]["data_runs"]
        assert len(blob_runs) == 1, (
            f"BLOB.BIN should be one contiguous run, got {len(blob_runs)} runs"
        )
        # Run length covers both clusters (no truncation needed since file_size
        # aligns to cluster boundary).
        assert blob_runs[0][1] == 2 * _CLUSTER_SIZE
    finally:
        os.close(fd)
        os.unlink(path)


def test_e2e_fat32_size_kb_and_offset_match_first_cluster():
    """size_kb and offset fields are derived correctly for downstream UI."""
    image_bytes, _expected = _build_e2e_image()
    fd, path = tempfile.mkstemp(suffix=".img")
    try:
        os.write(fd, image_bytes)
        os.lseek(fd, 0, os.SEEK_SET)
        parser = detect_fs("test.img", fd)
        assert parser is not None
        found: list[dict] = []
        parser.enumerate_files(
            stop_flag=lambda: False,
            progress_cb=lambda _p: None,
            file_found_cb=found.append,
        )
        by_name = {info["name"]: info for info in found}
        # offset == _cluster_offset(start_cluster) for each file.
        assert by_name["HELLO.TXT"]["offset"] == _cluster_offset(10)
        assert by_name["NOTES.TXT"]["offset"] == _cluster_offset(11)
        assert by_name["BLOB.BIN"]["offset"] == _cluster_offset(12)
        # size_kb is bytes // 1024 (min 1).
        assert by_name["BLOB.BIN"]["size_kb"] == 8
    finally:
        os.close(fd)
        os.unlink(path)
