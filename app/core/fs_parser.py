"""
Lumina - NTFS File System Parser
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
from datetime import UTC, datetime

# ── Logger ────────────────────────────────────────────────────────────────────
_log = logging.getLogger("lumina.recovery")

# ── NTFS constants ─────────────────────────────────────────────────────────────
_MFT_ENTRY_SIZE = 1024
# 100-ns ticks between Windows epoch (1601-01-01) and Unix epoch (1970-01-01)
_FILETIME_EPOCH = 116_444_736_000_000_000

# Well-known MFT entry indices
_IDX_ROOT           = 5   # Root directory ($.)  — parent of all top-level items
_IDX_MAX_SYSTEM     = 11  # Indices 0-11 are NTFS metadata files; skip them

# MFT entry flags
_FLAG_IN_USE        = 0x01
_FLAG_DIR           = 0x02

# Attribute type IDs we care about
_ATTR_STANDARD_INFO = 0x10
_ATTR_FILE_NAME     = 0x30
_ATTR_DATA          = 0x80
_ATTR_END           = 0xFFFF_FFFF

# Batch size for MFT reads (entries per syscall -- 64 * 1024 = 64 KB)
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
    cluster_size:          int   # = bytes_per_sector * sectors_per_cluster
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
        return datetime.fromtimestamp(ts, tz=UTC)
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
          Pass 1 (0-50 %): read all entries, build active-directory cache,
                           collect deleted-file entries.
          Pass 2 (50-100 %): resolve directory paths, emit file_found_cb.

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
                offset = int(lba) * 512
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
                offset = int(lba) * 512
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
                    return int(actual_sz) // _MFT_ENTRY_SIZE
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
        if not self._ready and not self.probe():
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

        # Filesystem type string is at bytes 82-89 ("FAT32   ")
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
        _eoc = 0x0FFF_FFFF
        try:
            fat_off = self._fat_start + cluster * 4
            raw = self._read_raw(fat_off, 4)
            if len(raw) < 4:
                return _eoc
            val = struct.unpack_from("<I", raw, 0)[0] & 0x0FFF_FFFF
            return int(val)
        except OSError:
            return _eoc

    def _collect_chain(self, start_cluster: int) -> list[int]:
        """Return the ordered list of clusters in a chain (cycle-safe, max 65536)."""
        _eoc_min = 0x0FFF_FFF8
        chain: list[int] = []
        seen: set[int] = set()
        cur = start_cluster
        while cur >= 2 and cur < _eoc_min and cur not in seen:
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
                ftype = name[dot + 1:].upper() if 0 < dot < len(name) - 1 else "UNKNOWN"

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


# ── Ext4Parser ────────────────────────────────────────────────────────────────

class Ext4Parser(BaseFSParser):
    """
    ext4 filesystem parser. Reads superblock, group descriptors, inodes,
    and directory entries to enumerate files on ext2/ext3/ext4 volumes.

    Reference: https://ext4.wiki.kernel.org/index.php/Ext4_Disk_Layout
    Limitations (v1): no journal replay, no inline data, no xattrs,
    no dir_htree beyond single-level, no encrypt/compress.
    """

    name = "ext4"

    # Superblock at byte 1024
    _SB_OFFSET = 1024
    _EXT4_MAGIC = 0xEF53
    _EXT4_EXTENTS_FL = 0x00080000  # inode uses extent tree
    _EXT4_INLINE_DATA_FL = 0x10000000  # inode has inline data (skip)
    _ROOT_INODE = 2

    def __init__(self, raw_device: str, fd: int) -> None:
        super().__init__(raw_device, fd)
        self._block_size: int = 0
        self._inodes_per_group: int = 0
        self._inode_size: int = 0
        self._blocks_per_group: int = 0
        self._first_data_block: int = 0
        self._desc_size: int = 0   # group descriptor size (32 or 64)
        self._ready: bool = False

    # ── BaseFSParser contract ─────────────────────────────────────────────────

    def probe(self) -> bool:
        """Return True iff a valid ext2/3/4 superblock is found at offset 1024."""
        try:
            return self._parse_superblock()
        except Exception as exc:
            _log.debug("[Ext4Parser] probe() raised %s — silent fallback.", exc)
            return False

    def enumerate_files(
        self,
        stop_flag: Callable[[], bool],
        progress_cb: Callable[[int], None],
        file_found_cb: Callable[[dict], None],
    ) -> int:
        if not self._ready and not self.probe():
            return 0
        try:
            count = self._enumerate_from_root(stop_flag, file_found_cb)
        except Exception as exc:
            _log.debug("[Ext4Parser] enumerate_files raised %s.", exc)
            count = 0
        progress_cb(100)
        _log.info("[Ext4Parser] ext4 enumeration complete: %d files found.", count)
        return count

    # ── Superblock parsing ────────────────────────────────────────────────────

    def _parse_superblock(self) -> bool:
        """Read and validate the ext4 superblock at offset 1024."""
        data = self._read_raw(0, self._SB_OFFSET + 256)
        if len(data) < self._SB_OFFSET + 4:
            return False

        sb = data[self._SB_OFFSET:]
        if len(sb) < 0x100:
            return False

        # Magic at superblock[0x38:0x3A]
        magic = struct.unpack_from("<H", sb, 0x38)[0]
        if magic != self._EXT4_MAGIC:
            _log.debug("[Ext4Parser] Bad magic 0x%04X (want 0x%04X).", magic, self._EXT4_MAGIC)
            return False

        # s_log_block_size at 0x18
        s_log_block_size = struct.unpack_from("<I", sb, 0x18)[0]
        block_size = 1024 << s_log_block_size

        if block_size not in (1024, 2048, 4096, 8192):
            _log.debug("[Ext4Parser] Invalid block size %d.", block_size)
            return False

        # s_first_data_block at 0x14
        first_data_block = struct.unpack_from("<I", sb, 0x14)[0]

        # s_blocks_per_group at 0x20
        blocks_per_group = struct.unpack_from("<I", sb, 0x20)[0]

        # s_inodes_per_group at 0x28
        inodes_per_group = struct.unpack_from("<I", sb, 0x28)[0]
        if inodes_per_group == 0:
            _log.debug("[Ext4Parser] inodes_per_group == 0.")
            return False

        # s_inode_size at 0x58 (16-bit field)
        inode_size = struct.unpack_from("<H", sb, 0x58)[0]
        if inode_size not in (128, 256, 512):
            _log.debug("[Ext4Parser] Invalid inode size %d.", inode_size)
            return False

        # s_desc_size at 0xFE (LE u16) — 0 means 32
        desc_size = struct.unpack_from("<H", sb, 0xFE)[0] if len(sb) >= 0x100 else 0
        if desc_size == 0:
            desc_size = 32

        self._block_size = block_size
        self._blocks_per_group = blocks_per_group
        self._inodes_per_group = inodes_per_group
        self._inode_size = inode_size
        self._first_data_block = first_data_block
        self._desc_size = desc_size
        self._ready = True

        _log.info(
            "[Ext4Parser] ext4 superblock OK — block_size=%d, inode_size=%d, "
            "inodes_per_group=%d, first_data_block=%d.",
            block_size, inode_size, inodes_per_group, first_data_block,
        )
        return True

    # ── Group descriptor helpers ───────────────────────────────────────────────

    def _get_inode_table_block(self, group: int) -> int:
        """Return the block number of the inode table for *group*."""
        gdt_start_block = self._first_data_block + 1
        gdt_offset = gdt_start_block * self._block_size + group * self._desc_size
        try:
            raw = self._read_raw(gdt_offset, max(32, self._desc_size))
        except OSError:
            return 0
        if len(raw) < 12:
            return 0
        # bg_inode_table_lo at offset 8 in the group descriptor
        return struct.unpack_from("<I", raw, 8)[0]

    # ── Inode helpers ──────────────────────────────────────────────────────────

    def _read_inode(self, inode_num: int) -> bytes | None:
        """Read the raw inode bytes for *inode_num* (1-based)."""
        group = (inode_num - 1) // self._inodes_per_group
        index = (inode_num - 1) % self._inodes_per_group
        inode_table_block = self._get_inode_table_block(group)
        if inode_table_block == 0:
            return None
        inode_offset = inode_table_block * self._block_size + index * self._inode_size
        try:
            raw = self._read_raw(inode_offset, self._inode_size)
        except OSError:
            return None
        if len(raw) < 128:
            return None
        return raw

    # ── Extent tree ───────────────────────────────────────────────────────────

    def _parse_extents(self, inode_data: bytes) -> list[tuple[int, int]]:
        """
        Parse the ext4 extent tree from inode_data[40:100].
        Returns list of (byte_offset, byte_length) tuples.
        """
        ext_header = inode_data[40:52]
        if len(ext_header) < 12:
            return []
        magic = struct.unpack_from("<H", ext_header, 0)[0]
        if magic != 0xF30A:
            return []
        num_entries = struct.unpack_from("<H", ext_header, 2)[0]
        depth = struct.unpack_from("<H", ext_header, 6)[0]

        runs: list[tuple[int, int]] = []
        if depth == 0:
            # Leaf node — entries are ext4_extent structs (12 bytes each)
            for i in range(min(num_entries, 4)):  # max 4 extents in inode
                offset = 40 + 12 + i * 12
                if offset + 12 > len(inode_data):
                    break
                ee_block = struct.unpack_from("<I", inode_data, offset)[0]
                ee_len = struct.unpack_from("<H", inode_data, offset + 4)[0]
                ee_start_hi = struct.unpack_from("<H", inode_data, offset + 6)[0]
                ee_start_lo = struct.unpack_from("<I", inode_data, offset + 8)[0]
                start_block = (ee_start_hi << 32) | ee_start_lo
                byte_offset = start_block * self._block_size
                byte_length = ee_len * self._block_size
                if byte_offset > 0 and byte_length > 0:
                    runs.append((byte_offset, byte_length))
        return runs

    # ── Block pointer helpers (non-extent inodes) ─────────────────────────────

    def _block_pointers(self, inode_data: bytes) -> list[tuple[int, int]]:
        """
        Read direct block pointers (legacy non-extent inodes).
        Returns list of (byte_offset, byte_length) for non-zero pointers.
        """
        runs: list[tuple[int, int]] = []
        for i in range(12):  # direct block pointers only
            bp_offset = 40 + i * 4
            if bp_offset + 4 > len(inode_data):
                break
            blk = struct.unpack_from("<I", inode_data, bp_offset)[0]
            if blk != 0:
                runs.append((blk * self._block_size, self._block_size))
        return runs

    # ── Directory reader ───────────────────────────────────────────────────────

    def _read_dir_block(self, block_num: int) -> list[tuple[int, int, str]]:
        """
        Read one directory block and return list of (inode, file_type, name) tuples.
        Skips entries with inode == 0.
        """
        entries: list[tuple[int, int, str]] = []
        try:
            raw = self._read_raw(block_num * self._block_size, self._block_size)
        except OSError:
            return entries

        pos = 0
        while pos + 8 <= len(raw):
            inode = struct.unpack_from("<I", raw, pos)[0]
            rec_len = struct.unpack_from("<H", raw, pos + 4)[0]
            if rec_len < 8:
                break
            name_len = raw[pos + 6]
            file_type = raw[pos + 7]
            if inode != 0 and name_len > 0 and pos + 8 + name_len <= len(raw):
                try:
                    name = raw[pos + 8:pos + 8 + name_len].decode("utf-8", errors="replace")
                except Exception:
                    name = f"_file_{inode}"
                entries.append((inode, file_type, name))
            pos += rec_len
        return entries

    # ── Main enumeration ───────────────────────────────────────────────────────

    def _enumerate_from_root(
        self,
        stop_flag: Callable[[], bool],
        file_found_cb: Callable[[dict], None],
    ) -> int:
        """Walk the directory tree starting from root inode 2."""
        count = 0
        visited_dirs: set[int] = set()
        queue: list[tuple[int, str]] = [(self._ROOT_INODE, "/")]

        while queue and not stop_flag():
            dir_inode, path_prefix = queue.pop(0)
            if dir_inode in visited_dirs:
                continue
            visited_dirs.add(dir_inode)

            inode_data = self._read_inode(dir_inode)
            if inode_data is None:
                continue

            # Get directory block list
            i_flags = struct.unpack_from("<I", inode_data, 32)[0]
            use_extents = bool(i_flags & self._EXT4_EXTENTS_FL)

            if use_extents:
                block_runs = self._parse_extents(inode_data)
            else:
                block_runs = self._block_pointers(inode_data)

            for (byte_off, byte_len) in block_runs:
                if stop_flag():
                    return count
                block_num = byte_off // self._block_size
                entries = self._read_dir_block(block_num)
                for (entry_inode, file_type, name) in entries:
                    if stop_flag():
                        return count
                    if name in (".", "..") or entry_inode < 11:
                        continue  # skip system inodes and dots
                    child_path = path_prefix.rstrip("/") + "/" + name

                    if file_type == 2:  # directory
                        if entry_inode not in visited_dirs:
                            queue.append((entry_inode, child_path + "/"))
                    elif file_type == 1:  # regular file
                        info = self._make_file_info(entry_inode, name, child_path)
                        if info is not None:
                            file_found_cb(info)
                            count += 1

        return count

    def _make_file_info(self, inode_num: int, name: str, path: str) -> dict | None:
        """Build a file_info dict for a regular file inode."""
        try:
            inode_data = self._read_inode(inode_num)
            if inode_data is None:
                return None

            i_size_lo = struct.unpack_from("<I", inode_data, 4)[0]
            i_size_hi = struct.unpack_from("<I", inode_data, 108)[0] if len(inode_data) >= 112 else 0
            file_size = (i_size_hi << 32) | i_size_lo

            i_dtime = struct.unpack_from("<I", inode_data, 20)[0]
            i_links_count = struct.unpack_from("<H", inode_data, 26)[0]
            i_flags = struct.unpack_from("<I", inode_data, 32)[0]

            is_deleted = i_dtime != 0 or i_links_count == 0
            integrity = 60 if is_deleted else 85

            use_extents = bool(i_flags & self._EXT4_EXTENTS_FL)
            if use_extents:
                data_runs = self._parse_extents(inode_data)
            else:
                data_runs = self._block_pointers(inode_data)

            byte_offset = data_runs[0][0] if data_runs else 0

            dot = name.rfind(".")
            ftype = name[dot + 1:].upper() if 0 < dot < len(name) - 1 else "UNKNOWN"

            return {
                "name":      name,
                "type":      ftype,
                "offset":    byte_offset,
                "size_kb":   max(1, file_size // 1024),
                "device":    self._device,
                "integrity": integrity,
                "mft_path":  path,
                "source":    "ext4",
                "fs":        "ext4",
                "data_runs": data_runs,
            }
        except Exception as exc:
            _log.debug("[Ext4Parser] _make_file_info(%d) raised %s.", inode_num, exc)
            return None

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


# ── HFSPlusParser ─────────────────────────────────────────────────────────────

class HFSPlusParser(BaseFSParser):
    """
    HFS+ (Mac OS Extended) filesystem parser.
    Reads the Volume Header and Catalog B-Tree to enumerate files.

    Reference: Apple Technical Note TN1150 "HFS Plus Volume Format"
    Note: HFS+ uses Big-Endian byte order throughout.
    Limitations (v1): no HFS+ journal replay, no resource forks,
    no compression (HFS+ transparent compression), no Unicode normalization.
    """

    name = "HFS+"

    _VH_OFFSET = 1024    # Volume Header at byte 1024
    _HFSPLUS_SIG = 0x482B   # "H+"
    _HFSX_SIG    = 0x4858   # "HX"
    _BTREE_NODE_SIZE = 512   # default; read from B-tree header

    def __init__(self, raw_device: str, fd: int) -> None:
        super().__init__(raw_device, fd)
        self._block_size: int = 0
        self._total_blocks: int = 0
        self._ready: bool = False

    # ── BaseFSParser contract ─────────────────────────────────────────────────

    def probe(self) -> bool:
        """Return True iff the volume has an HFS+ or HFSX signature."""
        try:
            return self._parse_volume_header()
        except Exception as exc:
            _log.debug("[HFSPlusParser] probe() raised %s — silent fallback.", exc)
            return False

    def enumerate_files(
        self,
        stop_flag: Callable[[], bool],
        progress_cb: Callable[[int], None],
        file_found_cb: Callable[[dict], None],
    ) -> int:
        if not self._ready and not self.probe():
            return 0
        count = 0
        try:
            count = self._walk_catalog(stop_flag, file_found_cb)
        except Exception as exc:
            _log.debug("[HFSPlusParser] enumerate_files raised %s.", exc)
        progress_cb(100)
        _log.info("[HFSPlusParser] HFS+ enumeration complete: %d files found.", count)
        return count

    # ── Volume Header parsing ──────────────────────────────────────────────────

    def _parse_volume_header(self) -> bool:
        """Read and validate the HFS+ Volume Header at byte 1024."""
        data = self._read_raw(self._VH_OFFSET, 162)
        if len(data) < 162:
            return False

        # Signature at offset 0 (BE u16)
        sig = struct.unpack_from(">H", data, 0)[0]
        if sig not in (self._HFSPLUS_SIG, self._HFSX_SIG):
            _log.debug("[HFSPlusParser] Bad signature 0x%04X.", sig)
            return False

        # blockSize at offset 40 (BE u32)
        block_size = struct.unpack_from(">I", data, 40)[0]
        if block_size < 512:
            _log.debug("[HFSPlusParser] Invalid block size %d.", block_size)
            return False
        # Must be a power of 2
        if block_size & (block_size - 1) != 0:
            _log.debug("[HFSPlusParser] Block size %d not a power of 2.", block_size)
            return False

        # totalBlocks at offset 44 (BE u32)
        total_blocks = struct.unpack_from(">I", data, 44)[0]
        if total_blocks == 0:
            _log.debug("[HFSPlusParser] totalBlocks == 0.")
            return False

        self._block_size = block_size
        self._total_blocks = total_blocks
        self._ready = True
        self._vh_data = data  # cache for enumerate_files

        _log.info(
            "[HFSPlusParser] HFS+/HFSX volume detected (sig=0x%04X, "
            "blockSize=%d, totalBlocks=%d).",
            sig, block_size, total_blocks,
        )
        return True

    # ── Catalog B-Tree walker ──────────────────────────────────────────────────

    def _walk_catalog(
        self,
        stop_flag: Callable[[], bool],
        file_found_cb: Callable[[dict], None],
    ) -> int:
        """Walk the Catalog B-Tree leaf nodes and emit file records."""
        count = 0
        try:
            # Volume Header cached from probe
            vh = self._vh_data

            # catalogFile fork info starts at offset 96 in Volume Header
            # extents start at offset 96 + 32 = 128
            catalog_ext_offset = 128
            if len(vh) < catalog_ext_offset + 8:
                return 0

            # First extent: startBlock (BE u32) + blockCount (BE u32)
            start_block = struct.unpack_from(">I", vh, catalog_ext_offset)[0]
            if start_block == 0:
                return 0

            # Read the B-Tree header node (node 0) at start_block * blockSize
            node0_offset = start_block * self._block_size
            node0 = self._read_raw(node0_offset, 512)
            if len(node0) < 256:
                return 0

            # Node descriptor: 14 bytes
            # BTHeaderRec follows at offset 14
            # firstLeafNode at offset 14 + 8 = 22 (BE u32)
            if len(node0) < 26:
                return 0
            first_leaf = struct.unpack_from(">I", node0, 22)[0]
            node_size = struct.unpack_from(">H", node0, 30)[0]
            if node_size < 512:
                node_size = 512

            if first_leaf == 0:
                return 0

            # Traverse leaf nodes
            current_node = first_leaf
            visited_nodes: set[int] = set()

            while current_node != 0 and not stop_flag():
                if current_node in visited_nodes:
                    break
                visited_nodes.add(current_node)

                node_offset = start_block * self._block_size + current_node * node_size
                try:
                    node_data = self._read_raw(node_offset, node_size)
                except OSError:
                    break

                if len(node_data) < 14:
                    break

                # Node descriptor
                flink = struct.unpack_from(">I", node_data, 0)[0]
                kind = struct.unpack_from(">b", node_data, 8)[0]   # signed byte
                num_records = struct.unpack_from(">H", node_data, 10)[0]

                if kind != -1:  # not a leaf node
                    current_node = flink
                    continue

                # Parse records using the offset table at the end of the node
                for rec_idx in range(num_records):
                    if stop_flag():
                        return count
                    try:
                        # Offset table entries are BE u16 at end of node, in reverse
                        table_entry_offset = node_size - (rec_idx + 1) * 2
                        if table_entry_offset < 14:
                            break
                        rec_offset = struct.unpack_from(">H", node_data, table_entry_offset)[0]

                        if rec_offset + 8 > len(node_data):
                            continue

                        # Skip key: first 2 bytes = key length (BE u16)
                        key_len = struct.unpack_from(">H", node_data, rec_offset)[0]
                        data_offset = rec_offset + 2 + key_len
                        # Align to 2 bytes
                        if data_offset % 2 != 0:
                            data_offset += 1

                        if data_offset + 2 > len(node_data):
                            continue

                        rec_type = struct.unpack_from(">H", node_data, data_offset)[0]
                        if rec_type != 0x0002:  # kHFSPlusFileRecord
                            continue

                        # File record: CNID at data_offset + 8 (BE u32)
                        if data_offset + 90 > len(node_data):
                            continue

                        # dataFork at data_offset + 88: logicalSize (BE u64)
                        logical_size = struct.unpack_from(">Q", node_data, data_offset + 88)[0]
                        # First extent of dataFork: startBlock at data_offset + 96
                        if data_offset + 104 > len(node_data):
                            continue
                        first_extent_start = struct.unpack_from(">I", node_data, data_offset + 96)[0]
                        first_extent_count = struct.unpack_from(">I", node_data, data_offset + 100)[0]

                        byte_offset = first_extent_start * self._block_size
                        byte_length = first_extent_count * self._block_size

                        # Extract name from key (parent ID = 4 bytes, then Pascal string)
                        if rec_offset + 6 + 2 > len(node_data):
                            name = "_hfsplus_file"
                        else:
                            name_len_chars = struct.unpack_from(">H", node_data, rec_offset + 6)[0]
                            name_bytes_len = name_len_chars * 2
                            name_start = rec_offset + 8
                            if name_start + name_bytes_len <= len(node_data):
                                try:
                                    name = node_data[name_start:name_start + name_bytes_len].decode(
                                        "utf-16-be", errors="replace"
                                    )
                                except Exception:
                                    name = "_hfsplus_file"
                            else:
                                name = "_hfsplus_file"

                        dot = name.rfind(".")
                        ftype = name[dot + 1:].upper() if 0 < dot < len(name) - 1 else "UNKNOWN"

                        file_info: dict = {
                            "name":      name,
                            "type":      ftype,
                            "offset":    byte_offset,
                            "size_kb":   max(1, logical_size // 1024),
                            "device":    self._device,
                            "integrity": 85,
                            "mft_path":  "/" + name,
                            "source":    "hfs+",
                            "fs":        "HFS+",
                            "data_runs": [(byte_offset, byte_length)] if byte_length > 0 else [],
                        }
                        file_found_cb(file_info)
                        count += 1

                    except Exception as exc:
                        _log.debug("[HFSPlusParser] Record parse error: %s", exc)
                        continue

                current_node = flink

        except Exception as exc:
            _log.debug("[HFSPlusParser] _walk_catalog raised %s.", exc)

        return count

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


# ── APFSParser ────────────────────────────────────────────────────────────────

class APFSParser(BaseFSParser):
    """
    APFS (Apple File System) detector.

    probe() identifies APFS containers by reading the NX Superblock.
    enumerate_files() is not implemented in v1 — APFS recovery uses
    the FileCarver signature-carving pass instead.

    Reference: Apple File System Reference (apple.com)
    Note: APFS is Little-Endian throughout.
    Magic: 'NXSB' (0x4253584E in LE, bytes b'NXSB' at offset 32).
    """

    name = "APFS"

    _NXSB_MAGIC = b"NXSB"  # at offset 32 in NX Superblock
    _APSB_MAGIC = b"APSB"  # Volume superblock

    def __init__(self, raw_device: str, fd: int) -> None:
        super().__init__(raw_device, fd)
        self._ready: bool = False

    # ── BaseFSParser contract ─────────────────────────────────────────────────

    def probe(self) -> bool:
        """Return True iff an APFS NX Superblock is found at offset 0."""
        try:
            data = self._read_raw(0, 40)
            if len(data) < 40:
                return False
            if data[32:36] != self._NXSB_MAGIC:
                _log.debug("[APFSParser] Bad NXSB magic.")
                return False
            nx_block_size = struct.unpack_from("<I", data, 36)[0]
            if nx_block_size < 4096:
                _log.debug("[APFSParser] nx_block_size=%d < 4096.", nx_block_size)
                return False
            self._ready = True
            _log.info("[APFSParser] APFS container detected on %s (block_size=%d).",
                      self._device, nx_block_size)
            return True
        except Exception as exc:
            _log.debug("[APFSParser] probe() raised %s — silent fallback.", exc)
            return False

    def enumerate_files(
        self,
        stop_flag: Callable[[], bool],
        progress_cb: Callable[[int], None],
        file_found_cb: Callable[[dict], None],
    ) -> int:
        """
        APFS enumeration is not implemented in v1.
        The FileCarver carving pass handles recovery on APFS volumes.
        """
        _log.info(
            "[APFSParser] APFS detected — full enumeration not implemented in v1. "
            "Using carver."
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
FS_PARSERS: list[type[BaseFSParser]] = [NTFSParser, FAT32Parser, ExFATParser, Ext4Parser, HFSPlusParser, APFSParser]


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
