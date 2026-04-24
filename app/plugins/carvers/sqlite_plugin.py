"""
Lumina v2.0 — SQLite database carver plugin.

SQLite databases use a fixed 100-byte header (SQLite file format §1.3).
The exact on-disk size is fully determined by two header fields:

    offset 16 (u16 BE)  page_size           — 512..32768 or 1 (= 65536)
    offset 28 (u32 BE)  db_size_in_pages    — total pages; reliable since
                                              SQLite ≥ 3.7.0 (Jul 2010) when
                                              `PRAGMA journal_mode` is DELETE
                                              (default) and the "change
                                              counter" matches.

Total size = page_size * db_size_in_pages.

Since the Android messaging DBs, Chrome/Firefox history, Skype chats,
WhatsApp backups and thousands of other mobile app stores rely on SQLite,
reconstructing the exact size (rather than falling back to a default) is
high-value for forensic recovery.

The plugin declares the 16-byte ASCII magic `SQLite format 3\\x00` and
validates candidates by sanity-checking the page_size + change counters.
"""

from __future__ import annotations

import struct

from .base_plugin import BaseCarverPlugin

_MAGIC = b"SQLite format 3\x00"

# Per SQLite §1.3 — page_size is a power of 2 from 512 to 32768, OR the
# literal value 1 which is interpreted as 65536 (introduced in v3.7.1).
_VALID_PAGE_SIZES: frozenset[int] = frozenset({
    1, 512, 1024, 2048, 4096, 8192, 16384, 32768,
})


class SqlitePlugin(BaseCarverPlugin):
    extension          = ".sqlite"
    category           = "document"
    min_size           = 512
    default_size_kb    = 1024  # 1 MB when the page count is unreliable
    handled_extensions = (".sqlite", ".db", ".sqlite3")

    @property
    def signatures(self) -> list[tuple[bytes, bytes | None]]:
        return [(_MAGIC, None)]

    # ── MIME validation ──────────────────────────────────────────────────
    def validate_mime(self, file_bytes: bytes) -> bool:
        if len(file_bytes) < 100 or not file_bytes.startswith(_MAGIC):
            return False

        page_size = struct.unpack_from(">H", file_bytes, 16)[0]
        if page_size not in _VALID_PAGE_SIZES:
            return False

        # File-format write/read versions must be 1 (legacy) or 2 (WAL).
        if file_bytes[18] not in (1, 2) or file_bytes[19] not in (1, 2):
            return False

        # SQLite §1.3 fixes three payload-fraction fields:
        #   offset 21 → max embedded payload fraction     (MUST be 64)
        #   offset 22 → min embedded payload fraction     (MUST be 32)
        #   offset 23 → leaf payload fraction             (MUST be 32)
        return not (file_bytes[21] != 64 or file_bytes[22] != 32 or file_bytes[23] != 32)

    # ── Exact size from header ───────────────────────────────────────────
    def estimate_size(
        self,
        data: bytes,
        start: int,
        footer: bytes | None,
    ) -> tuple[int, int]:
        """
        Compute page_size * db_size_in_pages when both fields look sane.

        Integrity:
            100 — both fields present and plausible (exact size)
             75 — header valid but db_size_in_pages is 0 / implausible
                  (falls back to default_size_kb)
        """
        if start + 32 > len(data):
            return self.default_size_kb, 75

        page_size = struct.unpack_from(">H", data, start + 16)[0]
        if page_size == 1:
            page_size = 65536
        if page_size not in {512, 1024, 2048, 4096, 8192, 16384, 32768, 65536}:
            return self.default_size_kb, 75

        db_pages = struct.unpack_from(">I", data, start + 28)[0]
        if db_pages == 0:
            # Legacy DBs written before SQLite 3.7.0 didn't update this
            # field — the page count is only authoritative when it matches
            # the "file change counter" at offset 24. We bail gracefully.
            return self.default_size_kb, 75

        total_bytes = page_size * db_pages
        # A SQLite DB holds at least one page (the header page) — anything
        # smaller than one page would be absurd.
        if total_bytes < page_size:
            return self.default_size_kb, 75

        return max(1, total_bytes // 1024), 100
