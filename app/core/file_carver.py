"""
Lumina - File Carver Engine
Raw binary disk reading with Magic Number / file signature detection.

v2.0 — Plugin-based architecture:
  * Plugins under `app/plugins/carvers/` define their own signatures and a
    `validate_mime()` method for Apache Tika-style content validation.
  * Legacy static SIGNATURES dict still handles formats not yet migrated.
  * Plugin signatures override legacy for the same extension family.

Production-grade: WinError 483 / bad-sector recovery, adaptive block size,
full logging to logs/lumina.log.
"""

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import re
import threading
from collections.abc import Callable
from typing import Any

from app.core.recovery import ensure_lumina_log
from app.plugins.carvers.base_plugin import BaseCarverPlugin

# ── Logger setup ──────────────────────────────────────────────────────────────
ensure_lumina_log()
_log = logging.getLogger("lumina.carver")

# ── Constants ─────────────────────────────────────────────────────────────────
SKIP_ON_ERR  = 1024 * 1024   # Jump 1 MB ahead on any read error (protects dying disk)
MAX_FILE_CAP = 500 * 1024 * 1024  # Hard cap on single-file extraction: 500 MB

# Size of the candidate window handed to `plugin.validate_mime()`.
_MIME_WINDOW = 4096

# Adaptive block size: larger blocks = fewer syscalls = faster on big drives
def _optimal_block_size(device_size_bytes: int) -> int:
    gb = device_size_bytes / (1024 ** 3) if device_size_bytes > 0 else 0
    if gb < 100:
        return 512 * 1024        # 512 KB  — small drives / USB sticks
    if gb < 1000:
        return 4 * 1024 * 1024   # 4 MB   — standard HDDs
    return 16 * 1024 * 1024      # 16 MB  — large HDDs / NVMe drives

# ── File Signatures (legacy — not yet migrated to plugins) ────────────────────
# Format: { extension: [(header_bytes, footer_bytes_or_None), ...] }
# Extensions handled by plugins are filtered out at FileCarver init time.
SIGNATURES: dict[str, list[tuple[bytes, bytes | None]]] = {

    # ── Images ────────────────────────────────────────────────────────
    ".png": [
        (b"\x89PNG\r\n\x1a\n", b"IEND\xaeB`\x82"),
    ],
    ".bmp": [
        (b"BM", None),
    ],
    ".gif": [
        (b"GIF87a", b"\x3b"),
        (b"GIF89a", b"\x3b"),
    ],
    ".tiff": [
        (b"II*\x00", None),   # Little-endian (Intel)
        (b"MM\x00*", None),   # Big-endian (Motorola)
    ],
    # .webp is detected via the RIFF discriminator (see .avi entry below)
    ".heic": [
        (b"ftypheic", None),
        (b"ftypheix", None),
        (b"ftypheim", None),
        (b"ftypmif1", None),
    ],
    ".heif": [
        (b"ftypheif", None),
    ],
    # .ico / .cur intentionally excluded: their 4-byte headers (\x00\x00\x01\x00 /
    # \x00\x00\x02\x00) appear thousands of times per GB in Windows binary data,
    # flooding the scan with false positives on system drives.
    ".psd": [
        (b"8BPS", None),
    ],
    # RAW camera formats (TIFF-based — will be detected by .tiff headers too,
    # but listed separately so future discrimination can apply)
    ".cr2": [
        (b"II*\x00\x10\x00\x00\x00CR", None),  # Canon CR2
    ],
    ".nef": [
        (b"MM\x00\x2a", None),    # Nikon NEF (big-endian TIFF)
    ],
    ".arw": [
        (b"II*\x00", None),       # Sony ARW (TIFF-based)
    ],
    ".svg": [
        (b"<?xml", b"</svg>"),
        (b"<svg",  b"</svg>"),
    ],

    # ── Video ─────────────────────────────────────────────────────────
    ".mp4": [
        (b"\x00\x00\x00\x18ftypmp42", None),
        (b"\x00\x00\x00\x20ftyp",     None),
        (b"\x00\x00\x00\x1Cftyp",     None),
        (b"ftypisom",                  None),
        (b"ftypmp41",                  None),
        (b"ftypavc1",                  None),
        (b"ftypF4V ",                  None),
    ],
    ".mov": [
        (b"ftypqt  ", None),
        (b"\x00\x00\x00\x08wide", None),
        (b"moov",    None),
    ],
    ".mkv": [
        (b"\x1a\x45\xdf\xa3", None),   # EBML header (also .webm)
    ],
    ".avi": [
        # RIFF container — sub-type (AVI/WAV/WEBP) discriminated at offset+8 by _riff_ext()
        (b"RIFF", None),
    ],
    ".flv": [
        (b"FLV\x01", None),
    ],
    ".wmv": [
        (b"\x30\x26\xb2\x75\x8e\x66\xcf\x11", None),  # ASF header (also WMA)
    ],
    ".3gp": [
        (b"ftyp3gp", None),
        (b"ftyp3g2", None),
    ],
    ".mpg": [
        (b"\x00\x00\x01\xba", b"\x00\x00\x01\xb9"),  # MPEG-PS
        (b"\x00\x00\x01\xb3", b"\x00\x00\x01\xb7"),  # MPEG Video
    ],
    ".m2ts": [
        (b"\x47\x40\x00\x10", None),  # MPEG-TS sync 0x47 at start
    ],
    ".f4v": [
        (b"ftypF4V ", None),
    ],

    # ── Audio ─────────────────────────────────────────────────────────
    ".mp3": [
        (b"\xff\xfb", None),   # MPEG-1 Layer 3
        (b"\xff\xfa", None),   # MPEG-1 Layer 3 (no CRC)
        (b"\xff\xf3", None),   # MPEG-2 Layer 3
        (b"\xff\xf2", None),   # MPEG-2 Layer 3 (no CRC)
        (b"ID3",      None),   # ID3v2 tag header
    ],
    # .wav is detected via the RIFF discriminator (see .avi entry)
    ".flac": [
        (b"fLaC", None),
    ],
    ".aac": [
        (b"\xff\xf1", None),   # ADTS AAC
        (b"\xff\xf9", None),   # ADTS AAC (no CRC)
    ],
    ".m4a": [
        (b"ftypM4A ", None),
        (b"ftypM4B ", None),
    ],
    ".ogg": [
        (b"OggS", None),
    ],
    ".wma": [
        # Shares header with WMV — discriminated by content
        (b"\x30\x26\xb2\x75\x8e\x66\xcf\x11\xa6\xd9", None),
    ],
    # .aiff is detected via RIFF-style FORM container discriminated at offset+8.
    # The 4-byte size field is never zero in real files, so we match on FORM
    # prefix only and discriminate the sub-type (AIFF/AIFC) in _form_ext().
    ".aiff": [
        (b"FORM", None),   # discriminated by _form_ext() at offset+8
    ],
    ".opus": [
        (b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00", None),  # Ogg Opus
    ],

    # ── Documents & Archives (.pdf and ZIP family now handled by plugins) ──
    # OLE2 / Compound Document: .doc, .xls, .ppt, .msg, .msi, .vsd
    ".doc": [
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", None),
    ],
    ".rar": [
        (b"Rar!\x1a\x07\x00", None),    # RAR v4
        (b"Rar!\x1a\x07\x01\x00", None),  # RAR v5
    ],
    ".7z": [
        (b"7z\xbc\xaf\x27\x1c", None),
    ],
    ".gz": [
        (b"\x1f\x8b\x08", None),
    ],
    ".bz2": [
        (b"BZh", None),
    ],
    ".xz": [
        (b"\xfd7zXZ\x00", None),
    ],
    ".tar": [
        # "ustar" magic at offset 257 — we search for it as a header here;
        # offset will be adjusted by -257 in post-processing
        (b"ustar\x00", None),
        (b"ustar  \x00", None),
    ],
    ".iso": [
        # CD001 primary volume descriptor at byte offset 0x8001
        (b"CD001", None),
    ],

    # ── Executables & System ──────────────────────────────────────────
    ".exe": [
        (b"MZ", None),   # DOS MZ / PE executable (.exe, .dll, .sys, .ocx, .scr)
    ],
    ".elf": [
        (b"\x7fELF", None),  # Linux ELF binary
    ],
    ".class": [
        (b"\xca\xfe\xba\xbe", None),  # Java class file
    ],

    # ── Databases & Misc ──────────────────────────────────────────────
    ".sqlite": [
        (b"SQLite format 3\x00", None),
    ],
    ".pst": [
        (b"!BDN", None),   # Outlook PST/OST
    ],
    ".vmdk": [
        (b"KDMV", None),   # VMware VMDK sparse extent
        (b"COWD", None),   # VMware VMDK COW disk
    ],
    ".vhd": [
        (b"conectix", None),
    ],
    ".torrent": [
        (b"d8:announce", None),
        (b"d13:announce", None),
    ],
    ".xml": [
        (b"<?xml ", b"</"),
    ],
    ".html": [
        (b"<!DOCTYPE html", b"</html>"),
        (b"<html",          b"</html>"),
    ],
    # "From: " and "X-Pop: " are too generic (appear in plain text).
    # These headers are distinctive enough to anchor an EML safely.
    ".eml": [
        (b"MIME-Version: 1.0",  None),
        (b"Return-Path: <",     None),
        (b"Message-ID: <",      None),
    ],

    # ── Additional RAW / Photo ────────────────────────────────────────
    # .dng intentionally omitted: it shares the exact TIFF header (II*\x00 or
    # MM\x00*) and cannot be distinguished in the first 4 bytes without reading
    # IFD tags. Real DNG files are covered by the .tiff entry above; the
    # extension may be refined by a future DNG plugin that reads tag 0xC612.
    ".ai": [
        (b"%PDF-", b"%%EOF"),      # Adobe Illustrator (PDF container)
    ],
    ".eps": [
        (b"%!PS-Adobe", None),
    ],
    ".indd": [
        (b"\x06\x06\xed\xf5\xd8\x1d\x46\xe5\xbd\x31\xef\xe7\xfe\x74\xb7\x1d", None),  # InDesign
    ],

    # ── Additonal Audio ───────────────────────────────────────────────
    ".ape": [
        (b"MAC ", None),      # Monkey's Audio
    ],
    ".wv": [
        (b"wvpk", None),      # WavPack
    ],
    ".mka": [
        (b"\x1a\x45\xdf\xa3", None),  # Matroska Audio (same EBML as MKV)
    ],

    # ── Additional Video ──────────────────────────────────────────────
    ".rm": [
        (b".RMF\x00", None),   # RealMedia
    ],
    ".mxf": [
        # MXF KLV Universal Label
        (b"\x06\x0e\x2b\x34\x02\x05\x01\x01\x0d\x01\x02\x01\x01\x02", None),
    ],
    ".vob": [
        (b"\x00\x00\x01\xba", None),  # DVD VOB (same pack header as MPG)
    ],

    # ── Additional Documents ──────────────────────────────────────────
    ".rtf": [
        (b"{\\rtf1", b"}"),
    ],
    ".accdb": [
        # MS Access 2007+ (OLE2-based but with ACCDB-specific header bytes)
        (b"\x00\x01\x00\x00Standard ACE DB", None),
    ],

    # ── Contact / Calendar ────────────────────────────────────────────
    ".vcf": [
        (b"BEGIN:VCARD", b"END:VCARD"),
    ],
    ".ics": [
        (b"BEGIN:VCALENDAR", b"END:VCALENDAR"),
    ],

    # ── Windows system / installer formats ───────────────────────────
    ".cab": [
        (b"MSCF\x00\x00\x00\x00", None),   # Microsoft Cabinet
    ],
    ".swf": [
        (b"FWS", None),   # Flash (uncompressed)
        (b"CWS", None),   # Flash (zlib-compressed)
        (b"ZWS", None),   # Flash (LZMA-compressed)
    ],
    ".wmf": [
        # Aldus Placeable WMF (most common variant with magic header)
        (b"\xd7\xcd\xc6\x9a", None),
    ],
    ".dwg": [
        # AutoCAD drawing - version string AC10xx
        (b"AC1009", None),   # AutoCAD R12
        (b"AC1012", None),   # AutoCAD R13
        (b"AC1014", None),   # AutoCAD R14
        (b"AC1015", None),   # AutoCAD 2000
        (b"AC1018", None),   # AutoCAD 2004
        (b"AC1021", None),   # AutoCAD 2007
        (b"AC1024", None),   # AutoCAD 2010
        (b"AC1027", None),   # AutoCAD 2013
        (b"AC1032", None),   # AutoCAD 2018+
    ],
}


# ── RIFF sub-type discrimination ──────────────────────────────────────────────
def _riff_ext(data: bytes, idx: int) -> str:
    """Return specific extension based on RIFF sub-type at idx."""
    try:
        sub = data[idx + 8: idx + 12]
        if sub == b"WEBP":
            return ".webp"
        if sub == b"WAVE":
            return ".wav"
        if sub == b"AVI ":
            return ".avi"
        if sub == b"RMID":
            return ".mid"
        if sub[:3] == b"CDX":
            return ".cda"
    except IndexError:
        pass
    return ".bin"   # unknown RIFF sub-type — don't pretend it's AVI


# ── FORM/IFF sub-type discrimination (AIFF, AIFC, others) ────────────────────
def _form_ext(data: bytes, idx: int) -> str:
    """Return .aiff, .aifc, or .avi (RIFF fallback) from FORM/RIFF sub-type."""
    try:
        sub = data[idx + 8: idx + 12]
        if sub == b"AIFF":
            return ".aiff"
        if sub == b"AIFC":
            return ".aiff"
        # Could be a RIFF container mislabelled as FORM — delegate
        return _riff_ext(data, idx)
    except IndexError:
        return ".bin"


# ── OLE2 sub-type discrimination ─────────────────────────────────────────────
def _ole2_ext(data: bytes, idx: int) -> str:
    """Return .doc, .xls, .ppt or .msg based on OLE2 entry names."""
    chunk = data[idx: idx + 2048]
    if b"W\x00o\x00r\x00k\x00b\x00o\x00o\x00k" in chunk:  # "Workbook" in UTF-16
        return ".xls"
    if b"P\x00o\x00w\x00e\x00r\x00P\x00o\x00i\x00n\x00t" in chunk:
        return ".ppt"
    if b"S\x00u\x00b\x00s\x00t\x00i\x00t\x00u\x00t\x00e" in chunk:
        return ".msg"
    return ".doc"


class FileCarver:
    """
    Performs raw disk File Carving with robust bad-sector handling and a
    plugin-based signature engine.

    Plugins under `app/plugins/carvers/` are loaded dynamically at init time.
    Their signatures override legacy entries for the same extension family,
    and their `validate_mime()` method is invoked before emitting a match
    (false positives are rejected silently).

    Usage:
        carver = FileCarver()
        files = carver.scan(device, progress_cb, file_found_cb, stop_flag)
    """

    def __init__(self) -> None:
        self._plugins: list[BaseCarverPlugin] = []
        # header_bytes -> (extension, footer, plugin_or_None)
        self._header_map: dict[bytes, tuple[str, bytes | None, BaseCarverPlugin | None]] = {}
        self._signature_id_map: dict[
            str, tuple[bytes, str, bytes | None, BaseCarverPlugin | None]
        ] = {}
        self._pattern: re.Pattern[bytes] = re.compile(b"(?!)")
        self._max_header_len: int = 0

        self._load_plugins()
        self._build_signature_tables()

    # ── Plugin loading ────────────────────────────────────────────────────────
    def _load_plugins(self) -> None:
        """Dynamically discover and instantiate every BaseCarverPlugin subclass
        under `app.plugins.carvers`. Failures are logged and non-fatal."""
        try:
            from app.plugins import carvers as _carvers_pkg
        except ImportError as exc:
            _log.warning("Plugin package not found: %s — plugins disabled.", exc)
            return

        for modinfo in pkgutil.iter_modules(_carvers_pkg.__path__):
            name = modinfo.name
            if name.startswith("_") or name == "base_plugin":
                continue
            try:
                module = importlib.import_module(f"app.plugins.carvers.{name}")
            except Exception as exc:
                _log.warning("Failed to import plugin '%s': %s", name, exc)
                continue

            for attr in vars(module).values():
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseCarverPlugin)
                    and attr is not BaseCarverPlugin
                ):
                    try:
                        self._plugins.append(attr())
                        _log.info(
                            "Loaded plugin %s (ext=%s, category=%s)",
                            attr.__name__, attr.extension, attr.category,
                        )
                    except Exception as exc:
                        _log.warning(
                            "Failed to instantiate plugin %s: %s", attr.__name__, exc,
                        )

    def _build_signature_tables(self) -> None:
        """Merge legacy SIGNATURES and plugin signatures into a single header
        map and a compiled alternation regex."""
        plugin_family: set[str] = set()
        for plugin in self._plugins:
            plugin_family.update(plugin.handled_extensions)
            plugin_family.add(plugin.extension)

        # Legacy first — but skip any extension claimed by a plugin family.
        for ext, sigs in SIGNATURES.items():
            if ext in plugin_family:
                continue
            for header, footer in sigs:
                if header not in self._header_map:
                    self._header_map[header] = (ext, footer, None)

        # Plugins override / add.
        for plugin in self._plugins:
            for header, footer in plugin.signatures:
                self._header_map[header] = (plugin.extension, footer, plugin)

        if not self._header_map:
            _log.error("No signatures loaded — FileCarver will find nothing.")
            return

        self._max_header_len = max(len(h) for h in self._header_map)
        self._pattern = re.compile(
            b"|".join(re.escape(h) for h in sorted(self._header_map, key=len, reverse=True)),
            re.DOTALL,
        )
        self._signature_id_map = {
            self.signature_id(ext, header): (header, ext, footer, plugin)
            for header, (ext, footer, plugin) in self._header_map.items()
        }
        _log.info(
            "FileCarver ready: %d plugin(s), %d total signature(s).",
            len(self._plugins), len(self._header_map),
        )

    @staticmethod
    def signature_id(ext: str, header: bytes) -> str:
        return f"{ext.lstrip('.')}_{header.hex()}"

    def native_signature_records(self) -> list[tuple[str, str, bytes]]:
        return [
            (signature_id, ext, header)
            for signature_id, (header, ext, _footer, _plugin) in self._signature_id_map.items()
        ]

    def build_file_info_from_candidate(
        self,
        *,
        signature_id: str,
        candidate_offset: int,
        data: bytes,
        data_base_offset: int,
        device: str,
        counter: dict[str, int],
        dedup_check: Callable[..., Any] | None = None,
        source: str = "carver",
    ) -> tuple[dict | None, str | None]:
        """
        Validate and convert a signature candidate into Lumina's file_info dict.

        This is shared by the Python regex scanner and the Rust native candidate
        pipeline so MIME validation, extension refinement, size estimation, ftyp
        offset correction, and dedup semantics stay identical.
        """
        entry = self._signature_id_map.get(signature_id)
        if entry is None:
            return None, "unknown_signature"

        header, ext, footer, plugin = entry
        idx = candidate_offset - data_base_offset
        if idx < 0 or idx + len(header) > len(data) or data[idx: idx + len(header)] != header:
            return None, "mismatch"

        if plugin is not None:
            ext = plugin.refine_extension(data, idx)
            candidate = data[idx: idx + _MIME_WINDOW]

            if len(candidate) >= plugin.min_size and not plugin.validate_mime(candidate):
                _log.debug(
                    "Rejected %s @ %d (MIME validation failed)",
                    ext,
                    candidate_offset,
                )
                return None, "reject"

            size_kb, integrity = plugin.estimate_size(data, idx, footer)
        else:
            # ── Legacy format validation before size estimation ────────────
            if header == b"MZ":
                # Validate PE header when it's reachable within the data window.
                # If the window is too small (fragmented file), keep the candidate
                # at reduced integrity rather than discarding a real executable.
                pe_off_pos = idx + 0x3C
                if pe_off_pos + 4 <= len(data):
                    pe_off = int.from_bytes(data[pe_off_pos:pe_off_pos + 4], "little")
                    pe_sig_pos = idx + pe_off
                    if pe_off >= 4 and pe_sig_pos + 4 <= len(data) and data[pe_sig_pos:pe_sig_pos + 4] != b"PE\x00\x00":
                        return None, "reject"
                    # pe_off out of window → accept with integrity 60 (set below)

            elif header == b"BM":
                # BMP reserved bytes 6-9 must be zero; pixel-data offset must be sane.
                if idx + 14 > len(data):
                    return None, "reject"
                if data[idx + 6:idx + 10] != b"\x00\x00\x00\x00":
                    return None, "reject"
                pix_off = int.from_bytes(data[idx + 10:idx + 14], "little")
                if pix_off < 26 or pix_off > 16384:
                    return None, "reject"

            if header == b"RIFF" or header == b"FORM":
                ext = _form_ext(data, idx) if header == b"FORM" else _riff_ext(data, idx)
            elif ext == ".doc" and header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                ext = _ole2_ext(data, idx)
            elif header.startswith(b"\x30\x26\xb2\x75"):
                chunk = data[idx: idx + 48]
                ext = ".wma" if b"\xf8\x03\x36\x4c\x65\x18\xcf\x11" in chunk else ".wmv"

            size_kb, integrity = self._estimate_size(data, idx, footer, ext)

        ftyp_offset = 4 if header[:4] == b"ftyp" and idx >= 4 else 0
        abs_offset = candidate_offset - ftyp_offset

        if dedup_check is not None:
            try:
                if dedup_check(abs_offset, max(size_kb, 1) * 1024):
                    return None, "dedup"
            except Exception as exc:
                _log.debug("dedup_check raised: %s — treating as non-dup.", exc)

        counter[ext] = counter.get(ext, 0) + 1
        return {
            "name":      f"recovered_{ext.lstrip('.')}_{counter[ext]:04d}{ext}",
            "type":      ext.upper().lstrip("."),
            "offset":    abs_offset,
            "size_kb":   size_kb,
            "device":    device,
            "integrity": integrity,
            "source":    source,
        }, None

    # ── Scan ──────────────────────────────────────────────────────────────────
    def scan(
        self,
        device: str,
        progress_cb: Callable[..., Any] | None = None,
        file_found_cb: Callable[..., Any] | None = None,
        stop_flag: Callable[..., Any] | None = None,
        max_bytes: int | None = None,
        dedup_check: Callable[..., Any] | None = None,
    ) -> list[dict]:
        """
        Scan a raw device for known file signatures.
        Returns list of dicts: {name, type, offset, size_kb, device, integrity, source}

        dedup_check: optional callable (abs_offset: int, size_bytes: int) -> bool.
            If provided and returns True, the candidate is silently dropped (used
            by ScanWorker to suppress duplicates of files already enumerated via
            the filesystem's metadata table).
        """
        found: list[dict] = []
        counter: dict[str, int] = {}
        dedup_count = 0

        _log.info("Scan start: %s", device)

        # ── Open device — close FD no matter what ─────────────────────
        try:
            fd = os.open(device, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        except OSError as e:
            _log.error("Cannot open %s: %s", device, e)
            raise PermissionError(
                f"Impossible d'ouvrir {device} : {e}\n"
                "Assurez-vous de lancer Lumina en tant qu'administrateur."
            ) from e

        skip_count    = 0
        reject_count  = 0

        try:
            total_bytes = max_bytes or self._get_device_size(device)
            block_size  = _optimal_block_size(total_bytes)
            bytes_read  = 0
            overlap     = b""

            while True:
                if stop_flag and stop_flag():
                    _log.info("Scan cancelled at offset %d.", bytes_read)
                    break

                # ── Read one block ─────────────────────────────────────
                try:
                    block = os.read(fd, block_size)
                except OSError as exc:
                    winerr = getattr(exc, "winerror", 0) or 0
                    _log.warning(
                        "Unreadable sector @ offset %d (WinError %d: %s) — skipping %d B.",
                        bytes_read, winerr, exc, SKIP_ON_ERR,
                    )
                    skip_count += 1
                    bytes_read += SKIP_ON_ERR
                    try:
                        os.lseek(fd, bytes_read, os.SEEK_SET)
                    except OSError as seek_err:
                        _log.error("Cannot reposition: %s — aborting.", seek_err)
                        break
                    overlap = b""
                    if total_bytes > 0 and progress_cb:
                        progress_cb(min(98, int(bytes_read * 100 / total_bytes)))
                    continue

                if not block:
                    break

                # offset_base BEFORE incrementing bytes_read
                offset_base = bytes_read - len(overlap)
                data = overlap + block

                # ── Multi-pattern search (single pass over data) ───────
                for m in self._pattern.finditer(data):
                    header = m.group(0)
                    entry  = self._header_map.get(header)
                    if entry is None:
                        continue

                    ext, _footer, _plugin = entry
                    idx = m.start()
                    file_info, reason = self.build_file_info_from_candidate(
                        signature_id=self.signature_id(ext, header),
                        candidate_offset=offset_base + idx,
                        data=data,
                        data_base_offset=offset_base,
                        device=device,
                        counter=counter,
                        dedup_check=dedup_check,
                        source="carver",
                    )
                    if file_info is None:
                        if reason == "reject":
                            reject_count += 1
                        elif reason == "dedup":
                            dedup_count += 1
                        continue

                    found.append(file_info)
                    _log.info(
                        "Found: %s @ offset %d (%d KB, integrity %d%%)",
                        file_info["name"],
                        file_info["offset"],
                        file_info["size_kb"],
                        file_info["integrity"],
                    )
                    if file_found_cb:
                        file_found_cb(file_info)

                # NOW increment bytes_read
                bytes_read += len(block)
                overlap = data[-self._max_header_len:] if self._max_header_len else b""

                if total_bytes > 0 and progress_cb:
                    progress_cb(min(99, int(bytes_read * 100 / total_bytes)))

                if max_bytes and bytes_read >= max_bytes:
                    break

        finally:
            os.close(fd)

        if progress_cb:
            progress_cb(100)

        _log.info(
            "Scan complete: %d file(s) found, %d sector(s) skipped, %d candidate(s) rejected, %d deduplicated vs FS metadata.",
            len(found), skip_count, reject_count, dedup_count,
        )
        return found

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_device_size(self, device: str) -> int:
        """Get device size via a dedicated FD with a 5-second timeout.

        Opens its own file descriptor so that a timeout cannot leave an orphan
        thread racing against the main scan FD.
        """
        result = [0]

        def _seek() -> None:
            try:
                tmp_fd = os.open(device, os.O_RDONLY | getattr(os, "O_BINARY", 0))
                try:
                    result[0] = os.lseek(tmp_fd, 0, os.SEEK_END)
                finally:
                    os.close(tmp_fd)
            except OSError:
                result[0] = 0

        t = threading.Thread(target=_seek, daemon=True)
        t.start()
        t.join(timeout=5.0)
        if t.is_alive():
            _log.warning("Device size query timed out — will scan without progress.")
            return 0
        return result[0]

    def _estimate_size(
        self,
        data: bytes,
        start: int,
        footer: bytes | None,
        ext: str,
    ) -> tuple[int, int]:
        """
        Legacy size estimator (non-plugin extensions only).
        Returns (size_kb, integrity_score 0-100).
        integrity: 100 = header+footer found; 60 = header only; 30 = unknown
        """
        if footer:
            end = data.find(footer, start + 1)
            if end != -1:
                size_bytes = end - start + len(footer)
                size_kb = max(1, size_bytes // 1024)
                return size_kb, 100  # Header + footer found: excellent

        # No footer found — heuristic size estimates per type
        defaults_kb: dict[str, int] = {
            ".png": 1024,    # ~1 MB average PNG
            ".bmp": 5120,    # ~5 MB uncompressed
            ".gif": 512,     # ~500 KB animation
            ".tiff": 8192,   # ~8 MB RAW/TIFF
            ".webp": 512,
            ".heic": 3072,
            ".psd": 20480,   # ~20 MB PSD
            ".mp4": 50000,   # ~50 MB clip
            ".mov": 100000,
            ".mkv": 700000,  # ~700 MB movie
            ".avi": 700000,
            ".flv": 50000,
            ".wmv": 200000,
            ".mpg": 300000,
            ".mp3": 4096,    # ~4 MB song
            ".wav": 30000,
            ".flac": 20000,
            ".ogg": 5000,
            ".doc": 256,
            ".rar": 10240,
            ".7z":  10240,
            ".exe": 1024,
            ".sqlite": 1024,
            ".cab": 5120,
            ".swf": 2048,
            ".wmf": 512,
            ".dwg": 4096,
        }
        size_kb = defaults_kb.get(ext, 1024)

        # Try to find the next known header to bound the size
        try:
            next_m = self._pattern.search(data, start + 512)
            if next_m:
                bounded = (next_m.start() - start) // 1024
                if 1 <= bounded < size_kb:
                    size_kb = bounded
        except Exception:
            pass

        return size_kb, 60  # Header found only: partial confidence


# ── Singleton accessor ────────────────────────────────────────────────────────

_carver_instance: FileCarver | None = None
_carver_lock = threading.Lock()


def get_carver() -> FileCarver:
    """Return the process-wide FileCarver instance (plugins loaded once)."""
    global _carver_instance
    if _carver_instance is None:
        with _carver_lock:
            if _carver_instance is None:
                _carver_instance = FileCarver()
    return _carver_instance
