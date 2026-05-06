"""Shared search and filtering engine for recovered files."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

TYPE_GROUPS: dict[str, set[str]] = {
    "Images": {
        "JPG",
        "JPEG",
        "PNG",
        "BMP",
        "GIF",
        "TIFF",
        "WEBP",
        "HEIC",
        "HEIF",
        "PSD",
        "SVG",
        "CR2",
        "CR3",
        "NEF",
        "ARW",
        "DNG",
        "ORF",
        "RW2",
        "RAF",
        "PEF",
        "SRW",
        "AI",
        "EPS",
        "INDD",
        "WMF",
    },
    "Videos": {"MP4", "MOV", "MKV", "AVI", "FLV", "WMV", "MPG", "M2TS", "3GP", "VOB", "RM", "MXF", "MKA"},
    "Audio": {"MP3", "WAV", "FLAC", "AAC", "OGG", "WMA", "M4A", "AIFF", "OPUS", "APE", "WV"},
    "Documents": {
        "PDF",
        "DOC",
        "DOCX",
        "XLS",
        "XLSX",
        "PPT",
        "PPTX",
        "ODT",
        "ODS",
        "TXT",
        "HTML",
        "XML",
        "RTF",
        "EML",
        "PST",
        "VCF",
        "ICS",
        "DWG",
        "ACCDB",
    },
    "Archives": {"ZIP", "RAR", "7Z", "GZ", "BZ2", "XZ", "TAR", "ISO", "EPUB", "CAB", "SWF"},
}

SYSTEM_TYPES: frozenset[str] = frozenset(
    {
        "EXE",
        "DLL",
        "SYS",
        "MSI",
        "MSP",
        "MSU",
        "OCX",
        "COM",
        "SCR",
        "CPL",
        "PIF",
        "INF",
        "CAT",
        "INI",
        "DAT",
        "LOG",
        "TMP",
        "LNK",
        "PDB",
    }
)


@dataclass(frozen=True)
class FilterCriteria:
    query: str = ""
    group: str = "Tous"
    types: frozenset[str] = field(default_factory=frozenset)
    min_size_kb: int | None = None
    max_size_kb: int | None = None
    min_integrity: int | None = None
    sources: frozenset[str] = field(default_factory=frozenset)
    hide_system: bool = False
    sort_key: str = ""
    sort_desc: bool = True


def normalize(text: object) -> str:
    value = "" if text is None else str(text)
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()


def _integrity(info: dict[str, Any]) -> int:
    raw = info.get("integrity_score", info.get("integrity", 0))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _matches_group(
    ftype: str,
    group: str,
    type_groups: dict[str, set[str]],
) -> bool:
    if not group or group == "Tous":
        return True
    if group == "Autres":
        return not any(ftype in values for values in type_groups.values() if values)
    return ftype in type_groups.get(group, set())


def matches_file(
    info: dict[str, Any],
    criteria: FilterCriteria,
    *,
    type_groups: dict[str, set[str]] | None = None,
    system_types: frozenset[str] = SYSTEM_TYPES,
) -> bool:
    groups = type_groups or TYPE_GROUPS
    ftype = str(info.get("type", "")).upper()

    if criteria.hide_system and ftype in system_types:
        return False

    if criteria.types and ftype not in criteria.types:
        return False

    if not _matches_group(ftype, criteria.group, groups):
        return False

    size_kb = int(info.get("size_kb", 0) or 0)
    if criteria.min_size_kb is not None and size_kb < criteria.min_size_kb:
        return False
    if criteria.max_size_kb is not None and size_kb > criteria.max_size_kb:
        return False

    if criteria.min_integrity is not None and _integrity(info) < criteria.min_integrity:
        return False

    if criteria.sources:
        source = str(info.get("source", "")).lower()
        if source not in criteria.sources:
            return False

    query = normalize(criteria.query)
    if query:
        haystack = " ".join(
            normalize(info.get(key, ""))
            for key in ("name", "type", "source", "fs", "mft_path", "device")
        )
        if query not in haystack:
            return False

    return True


def apply_filters(
    files: list[dict[str, Any]],
    criteria: FilterCriteria,
    *,
    type_groups: dict[str, set[str]] | None = None,
    system_types: frozenset[str] = SYSTEM_TYPES,
) -> list[dict[str, Any]]:
    result = [
        info
        for info in files
        if matches_file(info, criteria, type_groups=type_groups, system_types=system_types)
    ]

    if criteria.sort_key == "integrity":
        result.sort(key=_integrity, reverse=criteria.sort_desc)
    elif criteria.sort_key == "size":
        result.sort(key=lambda f: int(f.get("size_kb", 0) or 0), reverse=criteria.sort_desc)
    elif criteria.sort_key == "name":
        result.sort(key=lambda f: str(f.get("name", "")).lower(), reverse=criteria.sort_desc)
    elif criteria.sort_key == "type":
        result.sort(key=lambda f: str(f.get("type", "")).upper(), reverse=criteria.sort_desc)

    return result
