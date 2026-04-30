"""
Lumina – NTFS File System Parser
Reads the MFT (Master File Table) to recover deleted files with their
original filename and directory path.

Supports:
  * Physical drives  (\\\\.\\PhysicalDriveX) — parses MBR or GPT to locate
    the first NTFS partition, then reads its BPB.
  * Logical volumes  (\\\\.\\C:) — reads the BPB directly at byte offset 0.

Contract with ScanWorker (CLAUDE.md rule):
  The caller opens the file descriptor with os.open() and passes it here.
  This module only calls os.lseek() / os.read() on that fd.
  It never opens or closes a file descriptor of its own.
"""

from __future__ import annotations

import logging
import os
import struct
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ── Logger ────────────────────────────────────────────────────────────────────
_log = logging.getLogger("lumina.recovery")

# ── NTFS constants ─────────────────────────────────────────────────────────────
_MFT_ENTRY_SIZE = 1024
# 100-ns ticks between Windows epoch (1601-01-01) and Unix epoch (1970-01-01)
_FILETIME_EPOCH = 116_444_736_000_000_000

# Well-known MFT entry indices
_IDX_ROOT           = 5   # Root directory ($.)  — parent of all top-level items
_IDX_MAX_SYSTEM     = 11  # Indices 0–11 are NTFS metadata files; skip them

# MFT entry flags
_FLAG_IN_USE        = 0x01
_FLAG_DIR           = 0x02

# Attribute type IDs we care about
_ATTR_STANDARD_INFO = 0x10
_ATTR_FILE_NAME     = 0x30
_ATTR_DATA          = 0x80
_ATTR_END           = 0xFFFF_FFFF

# Batch size for MFT reads (entries per syscall — 64 × 1024 = 64 KB)
_BATCH              = 64

# GPT basic-data-partition type GUID (little-endian encoding)
# {EBD0A0A2-B9E5-4433-87C0-68B6B72699C7}
_GPT_BASIC_DATA_GUID = bytes([
    0xA2, 0xA0, 0xD0, 0xEB,        # EBD0A0A2  (LE)
    0xE5, 0xB9,                    # B9E5      (LE)
    0x33, 0x44,                    # 4433      (LE)
    0x87, 0xC0,                    # 87C0      (BE — unchanged)
    0x68, 0xB6, 0xB7, 0x26, 0x99, 0xC7,
])


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class BootSector:
    bytes_per_sector:      int
    sectors_per_cluster:   int
    cluster_size:          int   # = bytes_per_sector × sectors_per_cluster
    mft_start_byte:        int   # Absolute byte offset of $MFT on device
    total_sectors:         int
    partition_offset:      int   # Byte offset of this NTFS volume on device (0 for logical vols)


@dataclass
class DataRun:
    start_cluster:    int   # Absolute LCN
    length_clusters:  int


@dataclass
class _MFTEntry:
    index:         int
    flags:         int
    is_deleted:    bool
    name:          str
    parent_index:  int
    size_bytes:    int
    created:       datetime | None
    modified:      datetime | None
    data_runs:     list[DataRun] = field(default_factory=list)
    resident_data: bytes | None = None


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _filetime_to_dt(filetime: int) -> datetime | None:
    if filetime == 0:
        return None
    try:
        ts = (filetime - _FILETIME_EPOCH) / 10_000_000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _decode_data_runs(run_list: bytes) -> list[DataRun]:
    """
    Decode the NTFS data-run list (compact VCN→LCN encoding).
    Each run starts with a header byte:
      high nibble = number of bytes for the signed LCN offset
      low  nibble = number of bytes for the unsigned length
    A 0x00 byte terminates the list.
    """
    runs: list[DataRun] = []
    pos = 0
    current_lcn = 0
    while pos < len(run_list):
        header = run_list[pos]
        if header == 0:
            break
        pos += 1
        len_sz    = header & 0x0F
        offset_sz = (header >> 4) & 0x0F
        if len_sz == 0 or pos + len_sz + offset_sz > len(run_list):
            break
        length = int.from_bytes(run_list[pos:pos + len_sz], "little", signed=False)
        pos += len_sz
        if offset_sz:
            delta = int.from_bytes(run_list[pos:pos + offset_sz], "little", signed=True)
            current_lcn += delta
            pos += offset_sz
        if length > 0 and current_lcn >= 0:
            runs.append(DataRun(start_cluster=current_lcn, length_clusters=length))
    return runs


def _resolve_path(entry: _MFTEntry, dir_cache: dict[int, tuple[str, int]]) -> str:
    """Walk parent_index chain up to root; return '/dir/subdir/filename'."""
    parts: list[str] = [entry.name]
    visited: set[int] = {entry.index}
    cur = entry.parent_index
    for _ in range(32):                        # depth cap — no infinite loops
        if cur in (_IDX_ROOT, 5):
            break
        if cur in visited:
            parts.append("[cycle]")
            break
        visited.add(cur)
        if cur not in dir_cache:
            parts.append("[orphan]")
            break
        dir_name, parent = dir_cache[cur]
        parts.append(dir_name)
        cur = parent
    parts.reverse()
    return "/" + "/".join(parts)


def _file_ext(filename: str) -> str:
    dot = filename.rfind(".")
    if 0 < dot < len(filename) - 1:
        return filename[dot:]
    return ""


def _runs_to_byte_ranges(
    runs: list[DataRun], boot: BootSector,
) -> list[tuple[int, int]]:
    """Convert NTFS data runs (clusters) to absolute (byte_offset, byte_length) tuples."""
    return [
        (
            boot.partition_offset + r.start_cluster * boot.cluster_size,
            r.length_clusters * boot.cluster_size,
        )
        for r in runs
        if r.length_clusters > 0 and r.start_cluster >= 0
    ]


# ── BaseFSParser ───────────────────────────────────────────────────────────────

class BaseFSParser(ABC):
    """
    Abstract contract for filesystem-level metadata parsers (NTFS today; ext4 /
    APFS in the future).

    Lifecycle (owned by ScanWorker):
        1. ScanWorker opens raw_device → fd
        2. Iterates FS_PARSERS; for each class, constructs `parser(raw_device, fd)`
           then calls `parser.probe()`. First parser returning True wins.
        3. ScanWorker calls `parser.enumerate_files(stop_flag, progress_cb,
           file_found_cb)` to harvest filesystem-level metadata.
        4. ScanWorker closes fd.

    Silent fallback contract: every failure path in probe() / enumerate_files()
    MUST return False / 0 without raising. Corrupt signatures, missing tables,
    truncated reads, OSError on the raw device — all are treated as "this FS
    doesn't apply" and the pipeline falls through to signature carving.

    Each file_found_cb dict should include:
        source="mft" (or equivalent), fs=self.name, data_runs=[(start, len), ...]
    so ScanWorker can index these ranges and dedup the subsequent carving pass.
    """

    name: str = "UNKNOWN"

    def __init__(self, raw_device: str, fd: int) -> None:
        self._device = raw_device
        self._fd = fd

    @abstractmethod
    def probe(self) -> bool:
        """Return True iff this parser's filesystem is present on the device."""

    @abstractmethod
    def enumerate_files(
        self,
        stop_flag: Callable[[], bool],
        progress_cb: Callable[[int], None],
        file_found_cb: Callable[[dict], None],
    ) -> int:
        """Emit filesystem-level file dicts via file_found_cb. Return the count."""


# ── NTFSParser ─────────────────────────────────────────────────────────────────

class NTFSParser(BaseFSParser):
    """
    Reads a raw device (fd already opened by ScanWorker) and extracts
    deleted NTFS files via the Master File Table.

    Typical use via the generic FS pipeline:
        parser = NTFSParser(raw_dev, fd)
        if parser.probe():
            count = parser.enumerate_files(stop_flag, progress_cb, file_found_cb)
    """

    name = "NTFS"

    def __init__(self, raw_device: str, fd: int) -> None:
        super().__init__(raw_device, fd)
        self._is_physical = "PHYSICALDRIVE" in raw_device.upper()
        self._boot: BootSector | None = None

    # ── BaseFSParser contract ─────────────────────────────────────────────────

    def probe(self) -> bool:
        """Cache the boot sector; return True if this device holds an NTFS volume."""
        try:
            self._boot = self.read_boot_sector()
        except Exception as exc:
            _log.debug("[NTFSParser] probe() raised %s — silent fallback.", exc)
            self._boot = None
        return self._boot is not None

    def enumerate_files(
        self,
        stop_flag: Callable[[], bool],
        progress_cb: Callable[[int], None],
        file_found_cb: Callable[[dict], None],
    ) -> int:
        if self._boot is None:
            self._boot = self.read_boot_sector()
            if self._boot is None:
                return 0
        return self.scan_mft(self._boot, stop_flag, progress_cb, file_found_cb)

    # ── Public API ─────────────────────────────────────────────────────────────

    def read_boot_sector(self) -> BootSector | None:
        """
        Locate the NTFS boot sector and parse the BPB.
        Returns None on any failure (caller should silently fallback).
        """
        partition_offset = 0
        if self._is_physical:
            partition_offset = self._find_ntfs_partition()
            if partition_offset < 0:
                _log.warning(
                    "[NTFSParser] No NTFS partition found on %s — FileCarver fallback.",
                    self._device,
                )
                return None
        return self._parse_bpb(partition_offset)

    def scan_mft(
        self,
        boot: BootSector,
        stop_flag: Callable[[], bool],
        progress_cb: Callable[[int], None],
        file_found_cb: Callable[[dict], None],
    ) -> int:
        """
        Two-pass MFT scan:
          Pass 1 (0–50 %): read all entries, build active-directory cache,
                           collect deleted-file entries.
          Pass 2 (50–100 %): resolve directory paths, emit file_found_cb.

        Returns the number of deleted files emitted.
        """
        total = self._get_mft_entry_count(boot)
        if total == 0:
            _log.warning("[NTFSParser] Cannot determine MFT size — aborting MFT scan.")
            return 0

        _log.info("[NTFSParser] MFT: %d entries to scan on %s.", total, self._device)

        # ── Pass 1 ────────────────────────────────────────────────────
        dir_cache: dict[int, tuple[str, int]] = {5: ("", 5)}   # root → itself
        active:    list[_MFTEntry] = []   # files still present on disk
        deleted:   list[_MFTEntry] = []   # files no longer in use

        for batch_start in range(0, total, _BATCH):
            if stop_flag():
                _log.info("[NTFSParser] Scan cancelled during Pass 1.")
                return len(active) + len(deleted)

            count = min(_BATCH, total - batch_start)
            offset = boot.mft_start_byte + batch_start * _MFT_ENTRY_SIZE
            try:
                raw = self._read_raw(offset, count * _MFT_ENTRY_SIZE)
            except OSError as exc:
                _log.debug("[NTFSParser] Batch read error @ entry %d: %s", batch_start, exc)
                continue

            for i in range(count):
                chunk = raw[i * _MFT_ENTRY_SIZE:(i + 1) * _MFT_ENTRY_SIZE]
                if len(chunk) < _MFT_ENTRY_SIZE:
                    break
                entry = self._parse_entry(batch_start + i, chunk)
                if entry is None:
                    continue
                is_dir = bool(entry.flags & _FLAG_DIR)
                if not entry.is_deleted:
                    if is_dir:
                        dir_cache[entry.index] = (entry.name, entry.parent_index)
                    elif entry.index > _IDX_MAX_SYSTEM:
                        active.append(entry)
                elif entry.index > _IDX_MAX_SYSTEM and not is_dir:
                    deleted.append(entry)

            pct = min(50, int((batch_start + count) * 50 / max(total, 1)))
            progress_cb(pct)

        _log.info(
            "[NTFSParser] Pass 1 done: %d dirs, %d active files, %d deleted files.",
            len(dir_cache), len(active), len(deleted),
        )

        # ── Pass 2 — emit active files first (integrity 95), then deleted (80) ──
        found = 0
        all_entries = [(e, 95) for e in active] + [(e, 80) for e in deleted]
        for j, (entry, integrity) in enumerate(all_entries):
            if stop_flag():
                _log.info("[NTFSParser] Scan cancelled during Pass 2.")
                break

            path      = _resolve_path(entry, dir_cache)
            ext       = _file_ext(entry.name)
            ftype     = ext.upper().lstrip(".") if ext else "UNKNOWN"
            offset    = self._runs_to_offset(entry.data_runs, boot)
            byte_runs = _runs_to_byte_ranges(entry.data_runs, boot)

            file_found_cb({
                "name":      entry.name,
                "type":      ftype,
                "offset":    offset,
                "size_kb":   max(1, entry.size_bytes // 1024) if entry.size_bytes else 1,
                "device":    self._device,
                "integrity": integrity,
                "mft_path":  path,
                "source":    "mft",
                "fs":        self.name,
                "data_runs": byte_runs,
                "deleted":   entry.is_deleted,
            })
            found += 1

            if j % 100 == 0:
                progress_cb(50 + min(49, int(j * 49 / max(len(all_entries), 1))))

        progress_cb(100)
        _log.info(
            "[NTFSParser] MFT scan complete: %d active + %d deleted = %d files.",
            len(active), len(deleted), found,
        )
        return found

    # ── Partition detection ────────────────────────────────────────────────────

    def _find_ntfs_partition(self) -> int:
        """Return byte offset of the first NTFS partition, or -1."""
        try:
            sector0 = self._read_raw(0, 512)
        except OSError as exc:
            _log.warning("[NTFSParser] Cannot read sector 0: %s", exc)
            return -1

        if len(sector0) < 512 or sector0[510:512] != b"\x55\xAA":
            _log.warning("[NTFSParser] No MBR boot signature on %s.", self._device)
            return -1

        # GPT protective partition → type 0xEE in any of the 4 MBR slots
        is_gpt = any(sector0[0x1BE + i * 16 + 4] == 0xEE for i in range(4))
        return self._find_gpt() if is_gpt else self._find_mbr(sector0)

    def _find_mbr(self, sector0: bytes) -> int:
        """Scan 4 primary MBR partition entries for type 0x07 (NTFS/exFAT)."""
        for i in range(4):
            base = 0x1BE + i * 16
            if sector0[base + 4] == 0x07:
                lba = struct.unpack_from("<I", sector0, base + 8)[0]
                offset = lba * 512
                _log.info("[NTFSParser] MBR slot %d: NTFS at LBA %d (offset %d B).", i, lba, offset)
                return offset
        _log.warning("[NTFSParser] No NTFS (type 07) entry found in MBR.")
        return -1

    def _find_gpt(self) -> int:
        """Parse GPT header + partition array for the first Basic Data partition."""
        try:
            hdr = self._read_raw(512, 512)   # LBA 1
        except OSError as exc:
            _log.warning("[NTFSParser] Cannot read GPT header: %s", exc)
            return -1

        if hdr[:8] != b"EFI PART":
            _log.warning("[NTFSParser] GPT signature absent.")
            return -1

        entry_lba   = struct.unpack_from("<Q", hdr, 72)[0]
        entry_count = struct.unpack_from("<I", hdr, 80)[0]
        entry_size  = struct.unpack_from("<I", hdr, 84)[0]  # typically 128

        for i in range(min(entry_count, 256)):
            off = entry_lba * 512 + i * entry_size
            try:
                entry = self._read_raw(off, max(entry_size, 48))
            except OSError:
                continue
            if len(entry) < 48:
                continue
            if entry[:16] == _GPT_BASIC_DATA_GUID:
                lba = struct.unpack_from("<Q", entry, 32)[0]
                offset = lba * 512
                _log.info("[NTFSParser] GPT: Basic Data partition at LBA %d (offset %d B).", lba, offset)
                return offset

        _log.warning("[NTFSParser] No Basic Data partition found in GPT.")
        return -1

    # ── Boot sector ────────────────────────────────────────────────────────────

    def _parse_bpb(self, partition_offset: int) -> BootSector | None:
        """Parse NTFS BPB at partition_offset; return None if not NTFS."""
        try:
            data = self._read_raw(partition_offset, 512)
        except OSError as exc:
            _log.warning("[NTFSParser] Cannot read BPB at offset %d: %s", partition_offset, exc)
            return None

        if len(data) < 512 or data[3:11] != b"NTFS    ":
            _log.warning(
                "[NTFSParser] Not NTFS at offset %d (OEM=%r).",
                partition_offset, data[3:11] if len(data) >= 11 else b"?",
            )
            return None

        bps  = struct.unpack_from("<H", data, 0x0B)[0]   # bytes per sector
        spc  = data[0x0D]                                  # sectors per cluster
        if bps == 0 or spc == 0:
            _log.warning("[NTFSParser] Invalid BPB (BPS=%d, SPC=%d).", bps, spc)
            return None

        total_sectors    = struct.unpack_from("<Q", data, 0x28)[0]
        mft_start_clus   = struct.unpack_from("<Q", data, 0x30)[0]
        cluster_size     = bps * spc
        mft_start_byte   = partition_offset + mft_start_clus * cluster_size

        _log.info(
            "[NTFSParser] BPB OK — BPS=%d, SPC=%d, cluster=%d B, "
            "MFT @ cluster %d = byte %d, total_sectors=%d.",
            bps, spc, cluster_size, mft_start_clus, mft_start_byte, total_sectors,
        )
        return BootSector(
            bytes_per_sector=bps,
            sectors_per_cluster=spc,
            cluster_size=cluster_size,
            mft_start_byte=mft_start_byte,
            total_sectors=total_sectors,
            partition_offset=partition_offset,
        )

    # ── MFT helpers ────────────────────────────────────────────────────────────

    def _get_mft_entry_count(self, boot: BootSector) -> int:
        """
        Read $MFT entry (index 0) → parse its DATA attribute to get MFT size.
        Falls back to a disk-size heuristic (1 MFT entry per 1 KB of disk).
        """
        try:
            raw = self._read_raw(boot.mft_start_byte, _MFT_ENTRY_SIZE)
        except OSError:
            return 0

        if len(raw) < _MFT_ENTRY_SIZE or raw[:4] != b"FILE":
            return 0

        data = bytearray(raw)
        _apply_fixups(data)
        first_attr = struct.unpack_from("<H", data, 0x14)[0]
        pos = first_attr
        while pos + 8 <= _MFT_ENTRY_SIZE:
            atype = struct.unpack_from("<I", data, pos)[0]
            if atype == _ATTR_END:
                break
            alen = struct.unpack_from("<I", data, pos + 4)[0]
            if alen < 8 or pos + alen > _MFT_ENTRY_SIZE:
                break
            non_res = data[pos + 8]
            if atype == _ATTR_DATA and non_res:
                actual_sz = struct.unpack_from("<Q", data, pos + 0x30)[0]
                if actual_sz > 0:
                    return actual_sz // _MFT_ENTRY_SIZE
            pos += alen

        # Heuristic: ~1 MFT record per 1 KB of total disk
        heuristic = (boot.total_sectors * boot.bytes_per_sector) // (1024 * 1024)
        _log.warning("[NTFSParser] Could not read $MFT DATA size — heuristic: %d entries.", heuristic)
        return heuristic

    def _parse_entry(self, index: int, raw: bytes) -> _MFTEntry | None:
        """Parse one 1024-byte MFT record; return None if invalid or nameless."""
        if raw[:4] not in (b"FILE", b"BAAD"):
            return None
        if raw[:4] == b"BAAD":
            return None

        data = bytearray(raw)
        _apply_fixups(data)

        flags      = struct.unpack_from("<H", data, 0x16)[0]
        is_deleted = not (flags & _FLAG_IN_USE)
        first_attr = struct.unpack_from("<H", data, 0x14)[0]

        name         = ""
        parent_index = _IDX_ROOT
        size_bytes   = 0
        created:  datetime | None = None
        modified: datetime | None = None
        data_runs: list[DataRun] = []
        resident_data: bytes | None = None

        pos = first_attr
        while pos + 8 <= _MFT_ENTRY_SIZE:
            atype = struct.unpack_from("<I", data, pos)[0]
            if atype == _ATTR_END:
                break
            alen = struct.unpack_from("<I", data, pos + 4)[0]
            if alen < 8 or pos + alen > _MFT_ENTRY_SIZE:
                break

            non_res  = data[pos + 8]
            attr     = bytes(data[pos:pos + alen])

            # ── 0x10 Standard Information ──────────────────────────────
            if atype == _ATTR_STANDARD_INFO and not non_res:
                voff = struct.unpack_from("<H", attr, 0x14)[0]
                vlen = struct.unpack_from("<I", attr, 0x10)[0]
                if vlen >= 32 and voff + 16 <= len(attr):
                    val = attr[voff:]
                    created  = _filetime_to_dt(struct.unpack_from("<Q", val, 0)[0])
                    modified = _filetime_to_dt(struct.unpack_from("<Q", val, 8)[0])

            # ── 0x30 File Name ─────────────────────────────────────────
            elif atype == _ATTR_FILE_NAME and not non_res:
                voff = struct.unpack_from("<H", attr, 0x14)[0]
                vlen = struct.unpack_from("<I", attr, 0x10)[0]
                if vlen >= 66 and voff + vlen <= len(attr):
                    val       = attr[voff:]
                    parent_ref   = struct.unpack_from("<Q", val, 0)[0]
                    parent_index = parent_ref & 0x0000_FFFF_FFFF_FFFF
                    namespace    = val[0x41] if len(val) > 0x41 else 0
                    fname_len    = val[0x40] if len(val) > 0x40 else 0
                    fname_bytes  = val[0x42:0x42 + fname_len * 2]
                    try:
                        candidate = fname_bytes.decode("utf-16-le", errors="replace")
                        # Prefer Win32 (1) or Win32&DOS (3) over DOS-only (2) or POSIX (0)
                        if namespace in (1, 3) or not name:
                            name = candidate
                    except Exception:
                        pass
                    if not size_bytes and vlen >= 0x38:
                        size_bytes = struct.unpack_from("<Q", val, 0x30)[0]

            # ── 0x80 Data ──────────────────────────────────────────────
            elif atype == _ATTR_DATA:
                if non_res:
                    actual_sz = struct.unpack_from("<Q", attr, 0x30)[0]
                    if actual_sz:
                        size_bytes = actual_sz
                    run_off  = struct.unpack_from("<H", attr, 0x20)[0]
                    data_runs = _decode_data_runs(attr[run_off:])
                else:
                    voff = struct.unpack_from("<H", attr, 0x14)[0]
                    vlen = struct.unpack_from("<I", attr, 0x10)[0]
                    resident_data = attr[voff:voff + vlen]
                    size_bytes    = vlen

            pos += alen

        if not name:
            return None

        return _MFTEntry(
            index=index,
            flags=flags,
            is_deleted=is_deleted,
            name=name,
            parent_index=parent_index,
            size_bytes=size_bytes,
            created=created,
            modified=modified,
            data_runs=data_runs,
            resident_data=resident_data,
        )

    # ── Low-level I/O ──────────────────────────────────────────────────────────

    def _read_raw(self, offset: int, size: int) -> bytes:
        """Seek + read with retry on partial reads (raw devices may short-read)."""
        os.lseek(self._fd, offset, os.SEEK_SET)
        buf = b""
        remaining = size
        while remaining > 0:
            chunk = os.read(self._fd, remaining)
            if not chunk:
                break
            buf += chunk
            remaining -= len(chunk)
        return buf

    @staticmethod
    def _runs_to_offset(runs: list[DataRun], boot: BootSector) -> int:
        """Convert first data run to an absolute byte offset on the device."""
        if not runs:
            return 0
        return boot.partition_offset + runs[0].start_cluster * boot.cluster_size


# ── Module-level helpers ───────────────────────────────────────────────────────

def _apply_fixups(data: bytearray) -> bool:
    """
    Apply the NTFS Update Sequence Array (USA) to restore the last 2 bytes of
    each 512-byte sector.  Returns False if the signature check fails (which
    indicates possible data corruption — callers may still attempt to parse).
    """
    if len(data) < 8:
        return False
    usa_off  = struct.unpack_from("<H", data, 4)[0]
    usa_size = struct.unpack_from("<H", data, 6)[0]
    if usa_off + usa_size * 2 > len(data):
        return False
    sig = data[usa_off:usa_off + 2]
    ok  = True
    for i in range(1, usa_size):
        sector_end = i * 512 - 2
        if sector_end + 2 > len(data):
            break
        if data[sector_end:sector_end + 2] != sig:
            ok = False          # mismatch — log at caller if needed
        orig = data[usa_off + i * 2:usa_off + i * 2 + 2]
        data[sector_end:sector_end + 2] = orig
    return ok


# ── FAT32Parser ────────────────────────────────────────────────────────────────

class FAT32Parser(BaseFSParser):
    """
    Reads a raw device (fd already opened by ScanWorker) and enumerates ALL
    files (active and deleted) found in the FAT32 directory tree.

    Layout references:
      - Boot sector BPB at offset 0 of the FAT32 volume.
      - FAT at fat_start (reserved sectors * bytes_per_sector).
      - Data region starts at data_start.
      - Root directory starts at root_cluster (BPB[0x2C]).
      - Each 32-byte directory entry follows Microsoft FAT32 specification.
    """

    name = "FAT32"

    # Directory entry attribute flags
    _ATTR_LFN       = 0x0F
    _ATTR_DIR       = 0x10
    _ATTR_ARCHIVE   = 0x20

    # Special first-byte values
    _ENTRY_DELETED  = 0xE5
    _ENTRY_END      = 0x00

    def __init__(self, raw_device: str, fd: int) -> None:
        super().__init__(raw_device, fd)
        # Parsed BPB fields (set by probe())
        self._bytes_per_sector: int = 0
        self._cluster_size:     int = 0
        self._fat_start:        int = 0
        self._data_start:       int = 0
        self._root_cluster:     int = 0
        self._ready:            bool = False

    # ── BaseFSParser contract ─────────────────────────────────────────────────

    def probe(self) -> bool:
        """Return True iff the volume at fd contains a FAT32 filesystem."""
        try:
            return self._parse_bpb()
        except Exception as exc:
            _log.debug("[FAT32Parser] probe() raised %s — silent fallback.", exc)
            return False

    def enumerate_files(
        self,
        stop_flag: Callable[[], bool],
        progress_cb: Callable[[int], None],
        file_found_cb: Callable[[dict], None],
    ) -> int:
        if not self._ready:
            if not self.probe():
                return 0
        visited: set[int] = set()
        count = self._walk_dir(
            cluster=self._root_cluster,
            path_prefix="/",
            stop_flag=stop_flag,
            file_found_cb=file_found_cb,
            visited=visited,
        )
        progress_cb(100)
        _log.info("[FAT32Parser] FAT32 enumeration complete: %d files found.", count)
        return count

    # ── BPB parsing ───────────────────────────────────────────────────────────

    def _parse_bpb(self) -> bool:
        """
        Read and validate the FAT32 BPB.  Populates instance fields.
        Returns False if the boot sector is absent or not FAT32.
        """
        data = self._read_raw(0, 512)
        if len(data) < 90:
            return False

        # Filesystem type string is at bytes 82–89 ("FAT32   ")
        fs_type = data[0x52:0x5A]
        if fs_type != b"FAT32   ":
            _log.debug(
                "[FAT32Parser] Not FAT32 (type string=%r).", fs_type
            )
            return False

        bps = struct.unpack_from("<H", data, 0x0B)[0]   # bytes per sector
        spc = data[0x0D]                                  # sectors per cluster
        reserved = struct.unpack_from("<H", data, 0x0E)[0]
        num_fats  = data[0x10]
        spf32    = struct.unpack_from("<I", data, 0x24)[0]  # sectors per FAT (FAT32)
        root_clus = struct.unpack_from("<I", data, 0x2C)[0]

        if bps == 0 or spc == 0 or num_fats == 0 or spf32 == 0:
            _log.debug(
                "[FAT32Parser] Invalid BPB fields (BPS=%d SPC=%d FATs=%d SPF=%d).",
                bps, spc, num_fats, spf32,
            )
            return False

        self._bytes_per_sector = bps
        self._cluster_size     = bps * spc
        self._fat_start        = reserved * bps
        self._data_start       = (reserved + num_fats * spf32) * bps
        self._root_cluster     = root_clus
        self._ready            = True

        _log.info(
            "[FAT32Parser] BPB OK — BPS=%d, SPC=%d, cluster=%d B, "
            "FAT@%d, data@%d, root_cluster=%d.",
            bps, spc, self._cluster_size,
            self._fat_start, self._data_start, root_clus,
        )
        return True

    # ── Cluster chain helpers ─────────────────────────────────────────────────

    def _cluster_offset(self, cluster: int) -> int:
        """Absolute byte offset of the first byte of *cluster* on the device."""
        return self._data_start + (cluster - 2) * self._cluster_size

    def _next_cluster(self, cluster: int) -> int:
        """
        Follow one FAT32 chain link.
        Returns the next cluster number, or 0x0FFF_FFFF (EOC sentinel) on any
        error or when the chain ends.
        """
        _EOC = 0x0FFF_FFFF
        try:
            fat_off = self._fat_start + cluster * 4
            raw = self._read_raw(fat_off, 4)
            if len(raw) < 4:
                return _EOC
            val = struct.unpack_from("<I", raw, 0)[0] & 0x0FFF_FFFF
            return val
        except OSError:
            return _EOC

    def _collect_chain(self, start_cluster: int) -> list[int]:
        """Return the ordered list of clusters in a chain (cycle-safe, max 65536)."""
        _EOC_MIN = 0x0FFF_FFF8
        chain: list[int] = []
        seen: set[int] = set()
        cur = start_cluster
        while cur >= 2 and cur < _EOC_MIN and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            cur = self._next_cluster(cur)
            if len(chain) > 65_536:      # safety cap for enormous chains
                break
        return chain

    # ── Directory walker ──────────────────────────────────────────────────────

    def _walk_dir(
        self,
        cluster: int,
        path_prefix: str,
        stop_flag: Callable[[], bool],
        file_found_cb: Callable[[dict], None],
        visited: set[int],
    ) -> int:
        """
        Recursively enumerate all 32-byte directory entries in the cluster chain
        rooted at *cluster*.  Emits both active and deleted files via
        *file_found_cb*.  Returns the number of file entries emitted (dirs not
        counted).
        """
        if cluster in visited or cluster < 2:
            return 0
        visited.add(cluster)

        chain = self._collect_chain(cluster)
        lfn_fragments: list[tuple[int, str]] = []   # (seq, chars)
        subdirs: list[tuple[int, str]] = []          # (cluster, path)
        count = 0

        for clus in chain:
            if stop_flag():
                return count
            offset = self._cluster_offset(clus)
            try:
                raw = self._read_raw(offset, self._cluster_size)
            except OSError as exc:
                _log.debug("[FAT32Parser] Cluster %d read error: %s", clus, exc)
                continue

            num_entries = len(raw) // 32
            for i in range(num_entries):
                if stop_flag():
                    return count
                entry = raw[i * 32:(i + 1) * 32]
                if len(entry) < 32:
                    break

                first_byte = entry[0]
                attr       = entry[0x0B]

                # End-of-directory marker
                if first_byte == self._ENTRY_END:
                    break

                # LFN entry — accumulate fragments
                if attr == self._ATTR_LFN:
                    seq_raw = entry[0x00] & 0x1F   # mask off the "last" flag (0x40)
                    chars = (
                        entry[0x01:0x0B]   # chars 1-5
                        + entry[0x0E:0x1A]  # chars 6-11
                        + entry[0x1C:0x1E]  # chars 12-13
                    )
                    try:
                        text = chars.decode("utf-16-le", errors="replace").rstrip("\x00￿")
                    except Exception:
                        text = ""
                    lfn_fragments.append((seq_raw, text))
                    continue

                # Skip volume-label entries (attr 0x08)
                if attr & 0x08 and not (attr & self._ATTR_DIR):
                    lfn_fragments = []
                    continue

                is_deleted = first_byte == self._ENTRY_DELETED

                # Resolve name (prefer LFN if available)
                if lfn_fragments:
                    # LFN fragments arrive in reverse order (highest seq first)
                    lfn_fragments.sort(key=lambda x: x[0])
                    long_name = "".join(text for _, text in lfn_fragments)
                    name = long_name if long_name.strip() else None
                    lfn_fragments = []
                else:
                    name = None

                if name is None:
                    # Fall back to 8.3 short name
                    raw_stem = entry[0x00:0x08]
                    raw_ext  = entry[0x08:0x0B]
                    # Fix deleted-entry first byte
                    if is_deleted and raw_stem[0:1] == b"\xe5":
                        raw_stem = b"_" + raw_stem[1:]
                    stem = raw_stem.rstrip(b" ").decode("latin-1", errors="replace")
                    ext3 = raw_ext.rstrip(b" ").decode("latin-1", errors="replace")
                    name = (stem + "." + ext3) if ext3 else stem

                name = name.strip()
                if not name or name in (".", ".."):
                    continue

                # Starting cluster (high 16 in 0x14, low 16 in 0x1A)
                hi  = struct.unpack_from("<H", entry, 0x14)[0]
                lo  = struct.unpack_from("<H", entry, 0x1A)[0]
                start_cluster = (hi << 16) | lo

                # Directory — recurse later (avoid deep recursion in large trees)
                if attr & self._ATTR_DIR:
                    child_path = path_prefix.rstrip("/") + "/" + name
                    if start_cluster >= 2 and start_cluster not in visited:
                        subdirs.append((start_cluster, child_path + "/"))
                    continue

                # Regular file (active or deleted)
                file_size = struct.unpack_from("<I", entry, 0x1C)[0]
                byte_offset = self._cluster_offset(start_cluster) if start_cluster >= 2 else 0

                dot = name.rfind(".")
                if 0 < dot < len(name) - 1:
                    ftype = name[dot + 1:].upper()
                else:
                    ftype = "UNKNOWN"

                mft_path = path_prefix + name
                integrity = 70 if is_deleted else 85

                file_info: dict = {
                    "name":      name,
                    "type":      ftype,
                    "offset":    byte_offset,
                    "size_kb":   max(1, file_size // 1024),
                    "device":    self._device,
                    "integrity": integrity,
                    "mft_path":  mft_path,
                    "source":    "fat32",
                    "fs":        "FAT32",
                    "data_runs": [(byte_offset, file_size)] if byte_offset > 0 else [],
                }
                file_found_cb(file_info)
                count += 1

        # Recurse into subdirectories
        for sub_cluster, sub_path in subdirs:
            if stop_flag():
                break
            count += self._walk_dir(sub_cluster, sub_path, stop_flag, file_found_cb, visited)

        return count

    # ── Low-level I/O (same contract as NTFSParser._read_raw) ─────────────────

    def _read_raw(self, offset: int, size: int) -> bytes:
        """Seek + read with retry on partial reads (raw devices may short-read)."""
        os.lseek(self._fd, offset, os.SEEK_SET)
        buf = b""
        remaining = size
        while remaining > 0:
            chunk = os.read(self._fd, remaining)
            if not chunk:
                break
            buf += chunk
            remaining -= len(chunk)
        return buf


# ── ExFATParser ────────────────────────────────────────────────────────────────

class ExFATParser(BaseFSParser):
    """
    Lightweight exFAT detector.  probe() identifies the volume; enumerate_files()
    intentionally returns 0 and delegates recovery entirely to the FileCarver
    signature-carving pass.

    exFAT boot sector OEM name "EXFAT   " lives at bytes 3-10.
    """

    name = "exFAT"

    def __init__(self, raw_device: str, fd: int) -> None:
        super().__init__(raw_device, fd)

    # ── BaseFSParser contract ─────────────────────────────────────────────────

    def probe(self) -> bool:
        """Return True iff the volume is exFAT (OEM name check)."""
        try:
            data = self._read_raw(0, 16)
            if len(data) < 11:
                return False
            oem = data[3:11]
            result = oem == b"EXFAT   "
            if result:
                _log.info("[ExFATParser] exFAT volume detected on %s.", self._device)
            return result
        except Exception as exc:
            _log.debug("[ExFATParser] probe() raised %s — silent fallback.", exc)
            return False

    def enumerate_files(
        self,
        stop_flag: Callable[[], bool],
        progress_cb: Callable[[int], None],
        file_found_cb: Callable[[dict], None],
    ) -> int:
        """
        exFAT enumeration is not implemented.  The FileCarver carving pass will
        handle recovery on exFAT volumes.
        """
        _log.info(
            "[ExFATParser] exFAT détecté — carving direct."
        )
        progress_cb(100)
        return 0

    # ── Low-level I/O ──────────────────────────────────────────────────────────

    def _read_raw(self, offset: int, size: int) -> bytes:
        """Seek + read with retry on partial reads."""
        os.lseek(self._fd, offset, os.SEEK_SET)
        buf = b""
        remaining = size
        while remaining > 0:
            chunk = os.read(self._fd, remaining)
            if not chunk:
                break
            buf += chunk
            remaining -= len(chunk)
        return buf


# ── FS registry ───────────────────────────────────────────────────────────────

# Append new BaseFSParser subclasses (Ext4Parser, ApfsParser, …) here. Order
# matters only if two parsers could probe() True on the same volume — put the
# most specific first.
FS_PARSERS: list[type[BaseFSParser]] = [NTFSParser, FAT32Parser, ExFATParser]


def detect_fs(raw_device: str, fd: int) -> BaseFSParser | None:
    """
    Try each registered parser. Return the first whose probe() succeeds, or
    None if the volume is not recognised. Silent: any exception from a probe
    is logged at DEBUG level and we move on — the caller will fall through to
    signature carving.
    """
    for cls in FS_PARSERS:
        try:
            parser = cls(raw_device, fd)
            if parser.probe():
                _log.info("[detect_fs] %s matched on %s.", cls.name, raw_device)
                return parser
        except Exception as exc:
            _log.debug("[detect_fs] %s raised on %s: %s", cls.__name__, raw_device, exc)
    _log.info("[detect_fs] No FS parser matched %s — carving only.", raw_device)
    return None
