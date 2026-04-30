"""
RAW camera format plugin for FileCarver.

Handles formats with distinctive, non-TIFF headers:
  - ORF  (Olympus RAW): IIRO / MMOR prefix
  - RW2  (Panasonic RAW): IIU\x00 prefix
  - RAF  (Fujifilm RAW): FUJIFILMCCD-RAW prefix (16 bytes)

These headers do not collide with generic TIFF (.tiff / .arw / .nef) so
no MIME-level disambiguation is needed — the header match alone is
conclusive.

RAW files are always large (typically 8–50 MB). We can't reliably find an
EOF marker inside a 4 KB window, so estimate_size returns the default with
integrity 75 (MIME-confirmed, no footer found).
"""

from __future__ import annotations

from app.plugins.carvers.base_plugin import BaseCarverPlugin

# Minimum plausible RAW file (manufacturer thumbnails are at least 512 KB)
_MIN_RAW_KB = 512
_DEFAULT_KB  = 16_384   # 16 MB default — typical mid-range camera RAW


class RawPhotoPlugin(BaseCarverPlugin):
    """Carver for ORF, RW2, and RAF raw camera formats."""

    extension           = ".orf"
    category            = "image"
    min_size            = _MIN_RAW_KB * 1024
    default_size_kb     = _DEFAULT_KB
    handled_extensions  = (".orf", ".rw2", ".raf")

    # Maps the first N bytes of each signature to its extension.
    _MAGIC: dict[bytes, str] = {
        b"IIRO":             ".orf",   # Olympus LE
        b"MMOR":             ".orf",   # Olympus BE
        b"IIU\x00":         ".rw2",   # Panasonic RW2
        b"FUJIFILMCCD-RAW": ".raf",   # Fujifilm RAF
    }

    @property
    def signatures(self) -> list[tuple[bytes, bytes | None]]:
        return [
            (b"IIRO",             None),
            (b"MMOR",             None),
            (b"IIU\x00",         None),
            (b"FUJIFILMCCD-RAW", None),
        ]

    def validate_mime(self, file_bytes: bytes) -> bool:
        for magic in self._MAGIC:
            if file_bytes[: len(magic)] == magic:
                return True
        return False

    def refine_extension(self, data: bytes, idx: int) -> str:
        for magic, ext in self._MAGIC.items():
            n = len(magic)
            if data[idx: idx + n] == magic:
                return ext
        return self.extension

    def estimate_size(
        self,
        data: bytes,
        start: int,
        footer: bytes | None,
    ) -> tuple[int, int]:
        # RAW formats have no reliable in-buffer EOF marker.
        return self.default_size_kb, 75
