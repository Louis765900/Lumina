"""
Lumina v2.0 — Base class for FileCarver plugins.

Each plugin declares the file signatures it recognises, validates candidate
bytes via MIME/structure inspection (Apache Tika-style), and may refine the
detected extension or estimate a size/integrity score.

Integrity score conventions emitted by plugins:
  100 → header + footer found (exact size)
   75 → header + MIME validated (content confirmed, no footer)
   60 → header only (legacy code path, no MIME validation)
   30 → unknown / fragmentary
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseCarverPlugin(ABC):
    """Abstract base for all FileCarver plugins."""

    # ── Class-level metadata (override in subclasses) ─────────────────────────
    extension:          str = ".bin"
    category:           str = "other"
    min_size:           int = 64
    default_size_kb:    int = 1024

    # Extensions this plugin authoritatively handles (used to filter the legacy
    # SIGNATURES dict). Must include `extension` plus any family members that
    # `refine_extension()` may return (e.g. ZIP → .docx/.xlsx/.pptx/...).
    handled_extensions: tuple[str, ...] = ()

    # ── Mandatory API ─────────────────────────────────────────────────────────
    @property
    @abstractmethod
    def signatures(self) -> list[tuple[bytes, bytes | None]]:
        """Return list of (header_bytes, footer_bytes_or_None) tuples."""

    @abstractmethod
    def validate_mime(self, file_bytes: bytes) -> bool:
        """
        Verify a candidate buffer actually matches this file type.

        `file_bytes` is the first ~4 KB starting at the header offset.
        Return True if the byte pattern is consistent with this format's
        specification, False if the header match was a false positive.
        """

    # ── Optional hooks ────────────────────────────────────────────────────────
    def refine_extension(self, data: bytes, idx: int) -> str:
        """
        Inspect bytes around `idx` to pick a specific extension within a
        family. Default: returns self.extension. ZIP plugin overrides to
        return .docx/.xlsx/.pptx/.apk/.jar/.epub/...
        """
        return self.extension

    def estimate_size(
        self,
        data: bytes,
        start: int,
        footer: bytes | None,
    ) -> tuple[int, int]:
        """
        Return (size_kb, integrity_score).

        Default implementation scans for the footer if provided, otherwise
        falls back to `default_size_kb` with integrity 75 (since MIME
        validation has already succeeded by the time this is called).
        """
        if footer:
            end = data.find(footer, start + 1)
            if end != -1:
                size_bytes = end - start + len(footer)
                return max(1, size_bytes // 1024), 100
        return self.default_size_kb, 75
