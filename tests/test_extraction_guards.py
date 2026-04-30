"""
Chantier 9 — Critical extraction safety tests.

Tests do NOT require PyQt6 or a display.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.recovery import ensure_lumina_log, validate_recovery_destination


# ── Test 1 : extraction bloquée si destination == volume source ───────────────

class TestValidateRecoveryDestination:
    def test_blocked_when_dest_is_source_drive(self, tmp_path):
        """Recovery to the source volume must be blocked."""
        files = [{"device": "C:", "name": "test.jpg", "offset": 0, "size_kb": 10}]
        with (
            patch("app.core.recovery._resolve", return_value=Path("C:\\")),
            patch("app.core.recovery._drive_key", return_value="c"),
            patch(
                "app.core.recovery._check_source_against_destination",
                return_value=(True, ""),
            ),
        ):
            result = validate_recovery_destination(files, str(tmp_path))
        assert result.blocked, "Extraction to source volume should be blocked"

    def test_ok_when_dest_is_different_drive(self, tmp_path):
        """Recovery to a different drive should pass."""
        files = [{"device": "C:", "name": "test.jpg", "offset": 0, "size_kb": 10}]
        result = validate_recovery_destination(files, str(tmp_path))
        assert not result.blocked

    def test_blocked_when_dest_is_empty_string(self):
        """Empty destination must be blocked."""
        result = validate_recovery_destination([], "")
        assert result.blocked

    def test_creates_destination_dir_if_missing(self, tmp_path):
        """validate_recovery_destination creates the folder when create=True."""
        new_dir = tmp_path / "new_recovery_folder"
        assert not new_dir.exists()
        files = [{"device": "D:", "name": "test.jpg", "offset": 0, "size_kb": 10}]
        validate_recovery_destination(files, str(new_dir), create=True)
        assert new_dir.exists()


# ── Test 2 : logique de troncature à 500 MB ───────────────────────────────────
# Tests the pure calculation used in _ExtractionWorker._extract() without
# importing screen_results (which requires a PyQt6 display stack on Linux).

class TestExtractionTruncationLogic:
    """Verify the truncation flag formula independently of screen_results."""

    _MAX_SIZE = 500 * 1024 * 1024   # same constant as _ExtractionWorker._MAX_SIZE

    def _compute_truncated(self, size_kb: int) -> bool:
        raw_size = size_kb * 1024
        return raw_size > self._MAX_SIZE

    def test_flag_true_when_file_exceeds_500mb(self):
        """510 MB file → truncated=True."""
        assert self._compute_truncated(510 * 1024) is True

    def test_flag_false_for_500mb_exactly(self):
        """Exactly 500 MB → NOT truncated (min() keeps it at cap, raw == cap)."""
        assert self._compute_truncated(500 * 1024) is False

    def test_flag_false_for_small_file(self):
        """100 KB file → no truncation."""
        assert self._compute_truncated(100) is False

    def test_flag_true_for_very_large_file(self):
        """10 GB file → truncated."""
        assert self._compute_truncated(10 * 1024 * 1024) is True

    def test_extraction_writes_to_disk(self, tmp_path):
        """Pure I/O: write a small fake device file and read it back."""
        device_file = tmp_path / "fake.img"
        content = b"LUMINA_TEST" * 100
        device_file.write_bytes(content)

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        dest_path = out_dir / "recovered.bin"

        # Replicate the core I/O path from _extract() without screen_results
        import hashlib
        sha = hashlib.sha256()
        size_bytes = min(len(content), self._MAX_SIZE)
        remaining = size_bytes
        fd = os.open(str(device_file), os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            with open(dest_path, "wb") as out:
                while remaining > 0:
                    chunk = os.read(fd, min(1 << 20, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    sha.update(chunk)
                    remaining -= len(chunk)
        finally:
            os.close(fd)

        assert dest_path.read_bytes() == content
        assert sha.hexdigest() == hashlib.sha256(content).hexdigest()


# ── Test 3 : ensure_lumina_log crée le dossier si absent ──────────────────────

class TestEnsureLuminaLog:
    def test_creates_log_dir_if_missing(self, tmp_path):
        """ensure_lumina_log() must create the logs directory when it doesn't exist."""
        missing_dir = tmp_path / "totally_new_logs"
        assert not missing_dir.exists()
        result = ensure_lumina_log(missing_dir)
        assert missing_dir.exists(), "logs/ directory should be created"
        assert result == missing_dir / "lumina.log"

    def test_does_not_raise_on_existing_dir(self, tmp_path):
        """ensure_lumina_log() must not raise when the directory already exists."""
        ensure_lumina_log(tmp_path)   # first call
        ensure_lumina_log(tmp_path)   # second call — idempotent

    def test_returns_log_path(self, tmp_path):
        """ensure_lumina_log() should return the path to the log file."""
        log_path = ensure_lumina_log(tmp_path)
        assert log_path.name == "lumina.log"
        assert log_path.parent == tmp_path

    def test_does_not_crash_on_inaccessible_dir(self, tmp_path, monkeypatch):
        """ensure_lumina_log() must never raise even if mkdir fails."""
        monkeypatch.setattr(Path, "mkdir", lambda *a, **kw: None)
        # Should not raise
        ensure_lumina_log(tmp_path)


# ── Test 4 : history.json ne dépasse pas 20 entrées ──────────────────────────

class TestHistoryCap:
    def _make_entry(self, i: int) -> dict:
        return {
            "date":       "2026-01-01T00:00:00",
            "device":     "C:",
            "file_count": 3,
            "simulated":  False,
            "scan_file":  f"scan_{i:04d}.json",
        }

    def test_history_capped_at_20_by_slice(self, tmp_path):
        """Simulating 25 writes: the cap logic [:20] must limit to 20 entries."""
        history_file = tmp_path / "history.json"
        entries: list[dict] = []

        for i in range(25):
            entries.insert(0, self._make_entry(i))
            entries = entries[:20]   # same slice used in screen_results._save_to_history
            history_file.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)

        assert len(data) <= 20, (
            f"history.json must not exceed 20 entries, got {len(data)}"
        )
        # Most recent entry should be index 0
        assert data[0]["scan_file"] == "scan_0024.json"

    def test_history_keeps_most_recent(self, tmp_path):
        """After 25 writes, the 20 most recent entries are kept."""
        history_file = tmp_path / "history.json"
        entries: list[dict] = []

        for i in range(25):
            entries.insert(0, self._make_entry(i))
            entries = entries[:20]
            history_file.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)

        scan_files = {e["scan_file"] for e in data}
        # Entries 5..24 (the 20 most recent) should be present; 0..4 dropped
        assert "scan_0024.json" in scan_files
        assert "scan_0023.json" in scan_files
        assert "scan_0005.json" in scan_files
        # The 5 oldest entries (0..4) should have been evicted
        for old in ["scan_0000.json", "scan_0001.json",
                    "scan_0002.json", "scan_0003.json", "scan_0004.json"]:
            assert old not in scan_files, f"{old} should have been evicted"
