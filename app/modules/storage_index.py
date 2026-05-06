"""SQLite/FTS5 storage index for optional scan search."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.modules.registry import is_module_enabled

_log = logging.getLogger("lumina.modules.storage_index")


def default_index_path() -> Path:
    from app.core.platform import settings_dir

    return Path(settings_dir()) / "indexes" / "storage-index.sqlite3"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _fts_query(text: str) -> str:
    terms = re.findall(r"[\w.-]+", text, flags=re.UNICODE)
    return " AND ".join(f'"{term}"' for term in terms)


class StorageIndex:
    """Small SQLite database that stores scan results and exposes FTS5 search."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_index_path()

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def fts5_supported(conn: sqlite3.Connection) -> bool:
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp._lumina_fts5_probe USING fts5(x)")
            conn.execute("DROP TABLE temp._lumina_fts5_probe")
            return True
        except sqlite3.DatabaseError:
            return False

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS scans (
                    scan_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    module_version INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_id TEXT NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    device TEXT NOT NULL,
                    offset INTEGER NOT NULL DEFAULT 0,
                    size_kb INTEGER NOT NULL DEFAULT 0,
                    integrity INTEGER NOT NULL DEFAULT 0,
                    integrity_score INTEGER,
                    source TEXT,
                    fs TEXT,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(scan_id, device, offset, name)
                );

                CREATE INDEX IF NOT EXISTS idx_files_scan ON files(scan_id);
                CREATE INDEX IF NOT EXISTS idx_files_type ON files(file_type);
                CREATE INDEX IF NOT EXISTS idx_files_integrity ON files(integrity);
                """
            )
            if not self.fts5_supported(conn):
                raise RuntimeError("SQLite FTS5 is not available in this Python build")
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS file_fts USING fts5(
                    name,
                    file_type,
                    device,
                    source,
                    metadata
                )
                """
            )

    def index_files(
        self,
        files: Iterable[dict[str, Any]],
        *,
        scan_id: str | None = None,
        source: str | None = None,
    ) -> str:
        self.initialize()
        file_list = list(files)
        resolved_scan_id = scan_id or uuid.uuid4().hex
        resolved_source = source or (str(file_list[0].get("device", "")) if file_list else "unknown")
        now = _utc_now()

        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO scans(scan_id, source, created_at)
                VALUES (?, ?, ?)
                """,
                (resolved_scan_id, resolved_source, now),
            )
            for info in file_list:
                metadata = _json_dump(info)
                integrity = int(info.get("integrity", 0) or 0)
                integrity_score = info.get("integrity_score")
                row = conn.execute(
                    """
                    INSERT OR REPLACE INTO files(
                        scan_id, name, file_type, device, offset, size_kb,
                        integrity, integrity_score, source, fs, deleted,
                        metadata_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (
                        resolved_scan_id,
                        str(info.get("name", "")),
                        str(info.get("type", "")).upper(),
                        str(info.get("device", resolved_source)),
                        int(info.get("offset", 0) or 0),
                        int(info.get("size_kb", 0) or 0),
                        integrity,
                        int(integrity_score) if integrity_score is not None else None,
                        str(info.get("source", "")),
                        str(info.get("fs", "")),
                        1 if info.get("deleted") else 0,
                        metadata,
                        now,
                    ),
                ).fetchone()
                if row is None:
                    continue
                rowid = int(row["id"])
                conn.execute("DELETE FROM file_fts WHERE rowid = ?", (rowid,))
                conn.execute(
                    """
                    INSERT INTO file_fts(rowid, name, file_type, device, source, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rowid,
                        str(info.get("name", "")),
                        str(info.get("type", "")).upper(),
                        str(info.get("device", resolved_source)),
                        str(info.get("source", "")),
                        " ".join(
                            str(info.get(key, ""))
                            for key in ("fs", "mft_path", "integrity_label", "device")
                        ),
                    ),
                )
        return resolved_scan_id

    def search(
        self,
        query: str = "",
        *,
        file_types: set[str] | None = None,
        min_integrity: int | None = None,
        scan_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.initialize()
        where: list[str] = []
        params: list[object] = []
        joins = ""

        fts = _fts_query(query)
        if fts:
            joins = "JOIN file_fts ON file_fts.rowid = files.id"
            where.append("file_fts MATCH ?")
            params.append(fts)

        if file_types:
            normalized = sorted(t.upper() for t in file_types)
            where.append(f"files.file_type IN ({','.join('?' for _ in normalized)})")
            params.extend(normalized)

        if min_integrity is not None:
            where.append("COALESCE(files.integrity_score, files.integrity) >= ?")
            params.append(min_integrity)

        if scan_id:
            where.append("files.scan_id = ?")
            params.append(scan_id)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sql = (
            "SELECT files.* FROM files "
            f"{joins} {where_sql} "
            "ORDER BY COALESCE(files.integrity_score, files.integrity) DESC, files.name ASC "
            "LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_file(row) for row in rows]

    @staticmethod
    def _row_to_file(row: sqlite3.Row) -> dict[str, Any]:
        try:
            metadata = json.loads(row["metadata_json"])
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        metadata.update(
            {
                "name": row["name"],
                "type": row["file_type"],
                "device": row["device"],
                "offset": row["offset"],
                "size_kb": row["size_kb"],
                "integrity": row["integrity"],
                "source": row["source"],
                "fs": row["fs"],
                "deleted": bool(row["deleted"]),
                "scan_id": row["scan_id"],
            }
        )
        if row["integrity_score"] is not None:
            metadata["integrity_score"] = row["integrity_score"]
        return metadata


def index_scan_results(
    files: Iterable[dict[str, Any]],
    *,
    source: str | None = None,
    scan_id: str | None = None,
) -> str | None:
    """Index scan results when the module is enabled; never fail the scan."""

    if not is_module_enabled("storage-index"):
        return None
    try:
        return StorageIndex().index_files(files, source=source, scan_id=scan_id)
    except Exception as exc:
        _log.debug("storage-index skipped: %s", exc)
        return None
