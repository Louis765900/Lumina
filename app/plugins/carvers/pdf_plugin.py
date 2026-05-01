"""
Lumina v2.0 — PDF carver plugin.

Detects %PDF-x.y header and %%EOF footer, validates via PDF version tuple
(1.0-1.7, 2.0-2.9) per ISO 32000.
"""

from __future__ import annotations

import re

from .base_plugin import BaseCarverPlugin

_VERSION_RE = re.compile(rb"^%PDF-(\d)\.(\d)")


class PdfPlugin(BaseCarverPlugin):
    extension          = ".pdf"
    category           = "document"
    min_size           = 256
    default_size_kb    = 1024
    handled_extensions = (".pdf",)

    @property
    def signatures(self) -> list[tuple[bytes, bytes | None]]:
        return [
            (b"%PDF-", b"%%EOF"),
        ]

    def validate_mime(self, file_bytes: bytes) -> bool:
        if len(file_bytes) < 8 or not file_bytes.startswith(b"%PDF-"):
            return False

        m = _VERSION_RE.match(file_bytes)
        if not m:
            return False

        major = int(m.group(1))
        minor = int(m.group(2))
        if major == 1 and 0 <= minor <= 7:
            return True
        return bool(major == 2 and 0 <= minor <= 9)
