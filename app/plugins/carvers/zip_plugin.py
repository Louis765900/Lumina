"""
Lumina v2.0 — ZIP family carver plugin.

Handles .zip and its derivatives (OOXML .docx/.xlsx/.pptx, ODF .odt/.ods/.odp,
APK, JAR, EPUB) via a single PK\\x03\\x04 signature. The specific extension
is refined by inspecting the initial 2 KB for family-specific markers.

MIME validation parses the ZIP Local File Header structure and checks the
compression method + file-name length fields for plausibility.
"""

from __future__ import annotations

import struct

from .base_plugin import BaseCarverPlugin

# Standard + common ZIP compression methods (PKWARE APPNOTE §4.4.5)
_VALID_METHODS = frozenset((0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 18, 19, 95, 98, 99))


class ZipPlugin(BaseCarverPlugin):
    extension          = ".zip"
    category           = "archive"
    min_size           = 128
    default_size_kb    = 10240
    handled_extensions = (
        ".zip", ".docx", ".xlsx", ".pptx",
        ".odt", ".ods", ".odp",
        ".jar", ".apk", ".epub",
    )

    @property
    def signatures(self) -> list[tuple[bytes, bytes | None]]:
        return [
            (b"PK\x03\x04", b"PK\x05\x06"),
        ]

    def validate_mime(self, file_bytes: bytes) -> bool:
        if len(file_bytes) < 30 or not file_bytes.startswith(b"PK\x03\x04"):
            return False

        try:
            # Local File Header layout (little-endian):
            #   0-3   PK\x03\x04
            #   4-5   version needed to extract
            #   6-7   general purpose bit flag
            #   8-9   compression method
            #   26-27 file name length
            method   = struct.unpack_from("<H", file_bytes, 8)[0]
            name_len = struct.unpack_from("<H", file_bytes, 26)[0]
        except struct.error:
            return False

        if method not in _VALID_METHODS:
            return False
        return not (name_len == 0 or name_len > 2048)

    def refine_extension(self, data: bytes, idx: int) -> str:
        chunk = data[idx : idx + 2048]

        # OOXML (Microsoft Office)
        if b"word/" in chunk or b"word\\" in chunk:
            return ".docx"
        if b"xl/" in chunk or b"xl\\" in chunk:
            return ".xlsx"
        if b"ppt/" in chunk or b"ppt\\" in chunk:
            return ".pptx"

        # ODF (LibreOffice / OpenDocument)
        if b"opendocument.text" in chunk:
            return ".odt"
        if b"opendocument.spreadsheet" in chunk:
            return ".ods"
        if b"opendocument.presentation" in chunk:
            return ".odp"

        # EPUB (e-book)
        if b"application/epub+zip" in chunk:
            return ".epub"

        # Android / Java
        if b"AndroidManifest.xml" in chunk:
            return ".apk"
        if b"META-INF/MANIFEST.MF" in chunk:
            return ".jar"

        return ".zip"
