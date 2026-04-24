# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the app — must be Administrator on Windows (UAC required)
python main.py

# Lint
ruff check .

# Format
ruff format .

# Type-check (strict on app/core/*, relaxed elsewhere)
mypy app/

# Run all tests
pytest

# Run a single test file
pytest tests/test_file_carver.py -v

# Run with coverage (excludes app/ui/*)
pytest --cov=app --cov-report=term-missing

# Build executable (PyInstaller)
pyinstaller lumina.spec
```

## Architecture

**Lumina** is a Windows-only PyQt6 desktop app for data recovery. It requires Administrator rights to open raw disk devices (`\\.\C:`, `\\.\PhysicalDrive0`). A UAC re-launch is triggered automatically on startup if not elevated.

### Entry flow

```
main.py
  ├── _is_admin() → ShellExecuteW "runas" if not admin
  ├── loads app/ui/styles.qss globally onto QApplication
  └── launches MainWindow (frameless, WA_TranslucentBackground)
```

### Window layout

```
MainWindow (QMainWindow, frameless)
  └── central QWidget "LuminaCentral" (gradient bg, border-radius 12px)
       ├── TitleBar (44px, macOS traffic lights, drag-to-move, dbl-click maximize)
       └── body QHBoxLayout
            ├── Sidebar (240px fixed)
            └── QStackedWidget (7 screens, IDX 0–6)
```

### Screen index map

| IDX | Constant | Class | File |
|-----|----------|-------|------|
| 0 | IDX_HOME | `HomeScreen` | screen_home.py |
| 1 | IDX_SCAN | `ScanScreen` | screen_scan.py |
| 2 | IDX_RESULTS | `ResultsScreen` | screen_results.py |
| 3 | IDX_SD | `SdCardScreen` | screen_sd_card.py |
| 4 | IDX_PARTITIONS | `PartitionsScreen` | screen_partitions.py |
| 5 | IDX_REPAIR | `RepairScreen` | screen_repair.py |
| 6 | IDX_TOOLS | `ToolsScreen` | screen_tools.py |

The sidebar highlights IDX_HOME for both IDX_SCAN and IDX_RESULTS (both belong to the recovery flow).

### Signal wiring (MainWindow)

```
HomeScreen.disk_selected(dict)          → _go_scan()
HomeScreen.history_scan_requested(list) → _go_results()
SdCardScreen.disk_selected(dict)        → _go_scan()
ScanScreen.scan_finished(list)          → _go_results()
ScanScreen.scan_cancelled()             → show_home()
ResultsScreen.new_scan_requested()      → show_home()
```

### Screen transitions

`_fade_to(idx)` applies a `QGraphicsOpacityEffect` on the entire `QStackedWidget` (100ms fade-out → switch index → 180ms fade-in). The previous effect is always cleared with `setGraphicsEffect(None)` + `deleteLater()` before creating a new one to prevent QPainter crashes.

`show_home()` delays `refresh_disks()` by 310ms via `QTimer.singleShot` to avoid overlapping effects during the transition.

---

## Scan flow (step-by-step)

1. User clicks a `DiskCard` → `HomeScreen.disk_selected(dict)` emitted
2. `MainWindow._go_scan(disk)` opens `_ScanModeDialog` (modal, frameless)
3. User picks **Quick** or **Deep** → `disk["scan_mode"] = "quick" | "deep"`
4. `ScanScreen.start_scan(disk)` called
5. `ScanWorker(disk, simulate=(mode == "quick"))` created and started
6. Worker emits `progress(int)`, `status_text(str)`, `files_batch_found(list)` during scan
7. Worker emits `finished(list)` → `ScanScreen.scan_finished(list)` → `_go_results(files)`
8. `ResultsScreen.load_results(files)` displays results and writes to history

**Critical**: `simulate=True` = Quick (fake data for demo), `simulate=False` = Deep (real `FileCarver`). Never invert.

---

## Data structures

### Disk dict (from `DiskDetector.list_disks()`)
```python
{
    "device":      "C:",              # logical drive letter
    "name":        "Disque Local (C:)",
    "size_gb":     465.8,
    "used_gb":     210.5,
    "size_bytes":  500_107_862_016,
    "model":       "Volume NTFS",     # psutil fstype
    "interface":   "SATA/NVMe",       # "USB" if removable
    # optional, added by MainWindow:
    "scan_mode":   "quick" | "deep",
}
```

### File info dict (emitted by ScanWorker / stored in results)
```python
{
    "name":      "photo_vacances.jpg",
    "type":      "JPG",               # uppercase, no dot
    "offset":    123456789,           # byte offset on raw device
    "size_kb":   2048,
    "device":    "C:",
    "integrity": 95,                  # 0–100, estimated recoverability
    "simulated": True,                # only in Quick scan
}
```

---

## Workers

### `ScanWorker` (`app/workers/scan_worker.py`)
QThread with cooperative stop/pause via `threading.Event`.

| Signal | Args | Meaning |
|--------|------|---------|
| `progress` | `int` | 0–100 |
| `status_text` | `str` | Human-readable phase |
| `files_batch_found` | `list[dict]` | Incremental batch of found files |
| `finished` | `list[dict]` | Complete list at end |
| `error` | `str` | Fatal error |

Public methods: `stop()`, `pause()`, `resume()`, `is_paused()`.

`ScanScreen._detach_worker()` disconnects all signals and calls `stop()` without blocking the UI thread. The worker deletes itself via `finished.connect(worker.deleteLater)`.

### `_CmdWorker` (`screen_repair.py`)
Runs `chkdsk`, `sfc`, or `dism` subprocess. Encodes stdout with `cp850` (Windows OEM). Emits `output(str)` line by line and `done(int)` with return code.

### `_ThumbnailLoader` (`screen_results.py`)
Loads real image thumbnails from raw disk in a background QThread. Uses `QImage` (thread-safe) and emits `ready(int, QImage)`. Conversion to `QPixmap` happens in the main thread in `_on_thumb_ready`.

### `_ExtractionWorker` (`screen_results.py`)
Extracts selected files to a destination folder. For **simulated** files, writes a placeholder text file. For real files, reads bytes directly from the raw device using `os.open` + `os.lseek` + `os.read`. Caps extraction at 500 MB per file.

### `_SmartWorker` (`screen_tools.py`)
Runs a PowerShell `Get-CimInstance Win32_DiskDrive | ConvertTo-Json` command to get S.M.A.R.T. data. Handles single-disk (dict) vs multi-disk (list) JSON output. Timeout: 20s.

---

## Core engine

### `DiskDetector` (`app/core/disk_detector.py`)
Lists **logical drives** only (via `psutil.disk_partitions(all=False)`). WMI physical drives were removed to avoid duplicates. Falls back to a fake `\\.\PhysicalDrive0` simulation entry if no drives found.

### `FileCarver` (`app/core/file_carver.py`)
Pure Python sector-by-sector scanner. Called only by `ScanWorker._run_real()`.

- **Block size**: adaptive — 512 KB (< 100 GB), 4 MB (100 GB–1 TB), 16 MB (> 1 TB)
- **Bad sector recovery**: skips 1 MB ahead (`SKIP_ON_ERR`) on `OSError`/`WinError 483`
- **Signatures**: 50+ magic number pairs `(header_bytes, footer_bytes)` in `SIGNATURES` dict
- **Interface**: `carver.scan(raw_dev, progress_cb, file_found_cb, stop_flag)` — all callbacks run in the worker thread
- Logs to `logs/lumina.log`

**Unused files** (left in place, not imported): `app/core/c_bridge.py`, `app/core/gemini_assistant.py`. Do not reactivate.

---

## Screen details

### HomeScreen (`screen_home.py`)
- Disk grid: `DiskCard` (280×120), 3 per row, staggered fade-in via `_fade_wrap(widget, delay_ms)`
- `_fade_wrap` attaches `QGraphicsOpacityEffect` to a wrapper widget and clears it in the animation's `finished` signal to avoid nested-effect crashes
- Hover overlay: `_ScanOverlay` custom-painted widget (semi-transparent dark + blue pill button)
- Sections: internal disks, external disks, 6 recovery scenarios, 4 quick-access cards, last 5 scans from history
- History loaded from `logs/history.json`; clickable rows reload a previous scan from `logs/scan_YYYYMMDD_HHMMSS.json`
- Disk type detection: NVMe, SSD, USB, HDD, Other — based on `interface` and `model` string matching

### ScanScreen (`screen_scan.py`)
- `CircularProgress` widget: custom QPainter ring with conical gradient + animated particles at arc tip (~30 FPS via QTimer)
- ETA: rolling 12-second window of `(timestamp, pct)` pairs to compute %/s speed
- Log list: `QListWidget` with `_FileRow` item widgets; capped at 800 entries
- Pause button toggles `ScanWorker.pause()`/`resume()` and changes ring color to amber
- Cancel: calls `_detach_worker()` then emits `scan_cancelled()`

### ResultsScreen (`screen_results.py`)
- Grid: `FileThumb` (140×160), 6 columns, with gradient thumbnail and checkbox
- Filters: Tous / Images / Vidéos / Audio / Documents / Archives / Autres + sort combo
- Search: Unicode-normalized (`unicodedata.NFKD`) case-insensitive substring match
- `_GradientThumb`: shows a per-type linear gradient + emoji icon by default; replaced by real image if `_ThumbnailLoader` succeeds
- Detail panel: `_FileDetailPanel` (290px, slides in from right, shows metadata + integrity bar + single-file recover)
- Export: generates a dark-themed HTML report
- Persistence: each `load_results()` call saves to `logs/history.json` (max 20 entries) + `logs/scan_*.json`

### SdCardScreen (`screen_sd_card.py`)
- Auto-refreshes every 5 seconds via `QTimer`
- Shows only external/removable disks (USB/SD detection same logic as HomeScreen)
- Empty state widget with manual refresh button

### RepairScreen (`screen_repair.py`)
- Stats container `_stats_container` / `_stats_lay`: cleared with `while count > 1: takeAt(0)` then `insertWidget(i, card)` (the trailing `addStretch()` is index −1, kept)
- `_CmdWorker` runs only one at a time (guarded by `isRunning()` check)
- CHKDSK target: extracts drive letter from `disk["device"]`, appends `/scan`
- SFC: always system-wide (`sfc /scannow`)
- DISM: `dism /Online /Cleanup-Image /CheckHealth`

### ToolsScreen (`screen_tools.py`)
- Only **S.M.A.R.T. report** is functional (`available=True` in `_TOOLS` tuple); all others show "Bientôt disponible"
- S.M.A.R.T. uses PowerShell `Get-CimInstance` (not wmic, which is deprecated in Windows 11)
- `_SmartDialog`: scrollable, with QComboBox selector if multiple disks

### PartitionsScreen (`screen_partitions.py`)
- Static display only — lists `psutil.disk_partitions()` rows
- Tool cards (migration, MBR→GPT, clone, backup) are all "Bientôt disponible"

---

## Persistence / file system

```
logs/
  lumina.log          # FileCarver + ExtractionWorker log (rotating, UTF-8)
  history.json        # Last 20 scan sessions [{date, device, file_count, simulated, scan_file}]
  scan_YYYYMMDD_HHMMSS.json  # Full file list for each session
```

Both `file_carver.py` and `screen_results.py` independently set up the same `logs/` directory and `lumina.log` handler — they share the `lumina.carver` and `lumina.recovery` logger names.

---

## Styling

`app/ui/styles.qss` is loaded once onto `QApplication` at startup. It covers `QScrollBar`, `QComboBox`, `QListWidget`, `QProgressBar`, etc.

Palette constants are **duplicated** as module-level strings in each screen file (`_BG`, `_ACCENT`, `_BORDER`, etc.) and in `main_window.py`. There is no shared palette module — inline widget styles use f-strings with these locals.

### Color palette

| Name | Value | Usage |
|------|-------|-------|
| BG | `#0D0E1A` / `#0F1120` | Window background gradient |
| CARD | `rgba(255,255,255,0.04)` | Surface cards |
| BORDER | `rgba(255,255,255,0.08)` | Card borders |
| ACCENT | `#007AFF` | Primary blue |
| OK | `#34C759` | Success green |
| WARN | `#F59E0B` | Warning amber |
| ERR | `#EF4444` | Error red |
| TEXT | `#FFFFFF` / `#F1F5F9` | Primary text |
| SUB | `#94A3B8` | Secondary text |
| MUTED | `#64748B` | Tertiary / labels |

---

## Known pitfalls

### QGraphicsEffect stacking
Never apply `QGraphicsOpacityEffect` to a widget that is already under another one in the same widget tree — Qt's QPainter crashes with a nested-effect error.

- `_fade_to()` always clears the stack's effect before creating a new one
- `_fade_wrap()` in `screen_home.py` calls `wrap.setGraphicsEffect(None)` in the animation's `finished` signal
- Never put `QGraphicsDropShadowEffect` on a `DiskCard` that has an opacity effect on its wrapper

### QSS border syntax
`border-color: #xxx` is silently ignored by Qt. Always use `border: 1px solid #xxx`.

### `_StatCard` layout rebuild
In `RepairScreen`, stats are rebuilt with `while self._stats_lay.count() > 1: takeAt(0)` (keeping the trailing `addStretch()` at index −1), then `insertWidget(i, card)`. Do not use a simpler `addWidget` loop — it adds after the stretch.

### ScanWorker cancel without blocking UI
`_detach_worker()` disconnects signals, calls `stop()`, and uses `finished.connect(worker.deleteLater)`. Never call `worker.wait()` from the main thread — it blocks the event loop.

### `DiskDetector` returns logical drives (letters), not PhysicalDrive paths
When passing a device to `FileCarver` or `_ExtractionWorker`, the code converts `"C:"` → `"\\.\C:"` using `_to_raw_device()` (in scan_worker.py) or an inline equivalent. Always check for this conversion before raw reads.

---

## Tests

`tests/` has three test files and a `conftest.py` with shared fixtures:

- `sample_disk` — a typical SCSI disk dict
- `sample_usb_disk` — a USB disk dict
- `sample_found_files` — a list of 3 recovered file dicts

Coverage is configured to exclude `app/ui/` (UI widgets aren't unit-tested). `mypy` enforces typed defs only on `app/core/`.

---

## Build

The project includes `lumina.spec` (PyInstaller), `lumina.ico`, and a pre-compiled `lumina_engine.dll` (the old C bridge — unused). Build output goes to `build/` and `dist/`. The `stitch_export/` and `stitch_results/` folders appear to be export directories from a previous feature.

---

## Changelog / Historique des modifications

Track each major implementation milestone here. Keep entries brief: what was added, which files were touched, which architectural decisions were validated.

### Objective 1 — NTFS MFT parser (`app/core/fs_parser.py`)

- **Added**: `NTFSParser` class for MFT-based recovery (complement to signature carving).
- **Scope**: reads `$MFT`, iterates `FILE` records, extracts resident/non-resident data runs.
- **Integration**: standalone module, not yet wired into `ScanWorker` (future objective).

### Objective 2 — Plugin architecture + MIME validation

- **Added**: `app/plugins/carvers/` package with `BaseCarverPlugin` ABC and 3 reference plugins.
  - [app/plugins/carvers/base_plugin.py](app/plugins/carvers/base_plugin.py) — abstract base (`signatures`, `validate_mime`, `refine_extension`, `estimate_size`).
  - [app/plugins/carvers/jpeg_plugin.py](app/plugins/carvers/jpeg_plugin.py) — 10 SOI variants + marker-based validation.
  - [app/plugins/carvers/pdf_plugin.py](app/plugins/carvers/pdf_plugin.py) — version tuple check (1.0–1.7, 2.0–2.9).
  - [app/plugins/carvers/zip_plugin.py](app/plugins/carvers/zip_plugin.py) — single plugin covers full ZIP family (docx/xlsx/pptx/odt/ods/odp/apk/jar/epub) via `refine_extension()`.
- **Modified**: [app/core/file_carver.py](app/core/file_carver.py) — dynamic loading via `pkgutil.iter_modules` + `importlib`; instance-level `_header_map` / `_pattern` (replace module-level globals); MIME-reject candidates silently counted in final log.
- **Architectural decisions validated**:
  - Per-plugin `min_size` (default 64 B), no global floor.
  - 4 KB candidate window for `validate_mime` (RAM-bounded).
  - Integrity score: **75** when MIME-validated but no footer (up from legacy 60).
  - One plugin per file family (ZIP handles 10 extensions, not 10 separate plugins).
  - `handled_extensions` tuple on each plugin filters legacy `SIGNATURES` at table-build time (prevents double-registration).
- **Known desync**: `tests/test_file_carver.py` imports removed module-level symbols (`_HEADER_MAP`, `_MAX_HEADER_LEN`). Test repair deferred to a final dedicated pass (per user decision).

### Objective 3 — JPEG fragmentation heuristics

- **Modified**: [app/plugins/carvers/jpeg_plugin.py](app/plugins/carvers/jpeg_plugin.py) — added `_parse_structure()` syntactic walker inspired by FileScraper / JPEG-Restorer.
- **Behavior**:
  - `estimate_size()` fast path: naive `FF D9` search; trusted only if size ≥ 2 KB.
  - Slow path: ISO/IEC 10918-1 marker walk — handles fill bytes (`FF FF`), stuffing (`FF 00`), RSTn markers (`FF D0..D7`), SOS entropy stream scan, length-prefixed segments.
- **Integrity scoring**:
  - `100` — EOI found cleanly (fast path ≥ 2 KB, or structural walk).
  - `70` — parser finished without EOI (fragment reassembled at last valid scan boundary).
  - `75` — parser hit invalid marker (MIME already validated, fallback to `default_size_kb`).
- **Architectural decisions validated**:
  - Plugin operates **only on RAM buffer** — no disk I/O in plugin code.
  - Bad-sector recovery (1 MB skip on `OSError/WinError 483`) stays in `FileCarver._read_block()`.
  - No `FileCarver` changes — the adaptive block overlap (up to 16 MB) covers the vast majority of fragmentation cases.
  - Fragment threshold `_FRAGMENT_MIN_SIZE = 2048` bytes.

### Objective 4 — SHA-256 streaming + DFXML export

- **Modified**: [app/ui/screen_results.py](app/ui/screen_results.py)
  - `_ExtractionWorker` refactored for chunked read/write (1 MiB chunks) with incremental `hashlib.sha256()` — single disk pass, bounded RAM.
  - Cooperative cancellation via `threading.Event` (`stop()` method); `QProgressDialog.canceled` now wired to `stop()` instead of `terminate()`.
  - Real-file extraction now writes `info["sha256"]`, `info["extracted_name"]`, `info["extracted_size"]` back into the dict for downstream reporting.
  - Cancelled extractions raise `InterruptedError` inside the read loop — no hash finalisation on cancel.
  - Export button "📄 Rapport" converted to a `QMenu` with two actions: **Export HTML** (existing) and **Export DFXML** (new).
  - New `_on_export_dfxml()` — generates a DFXML 1.2.0 report via `xml.etree.ElementTree` (stdlib, no new dependency).
- **DFXML structure**:
  - Namespaces: default DFXML, `dc:` (Dublin Core), `lumina:` (extensions).
  - `<metadata>` + `<creator>` + `<source>` (device name/model/size/scan_mode).
  - One `<fileobject>` per scanned file: `<filename>`, `<filesize>`, `<byte_runs>` (with `img_offset`), `<hashdigest type="sha256">` (only when the file was extracted), plus `<lumina:integrity>`, `<lumina:filetype>`, `<lumina:simulated>`.
- **Architectural decisions validated**:
  - Chunk size **1 MiB** — balances RAM and cancel latency.
  - `lumina:` namespace kept — preserves integrity/type/simulated metadata while staying schema-extensible.
  - DFXML export serialises the current dict state (no extra disk reads); running it before extraction produces a structural report without `<hashdigest>` — legitimate per DFXML spec.
  - `QProgressDialog.canceled` signal wired alongside the polling check in `_on_prog` → redundant but guaranteed even when no progress updates flow.

### Objective 5 — Test suite realignment (final pass)

- **Rewritten**: [tests/test_file_carver.py](tests/test_file_carver.py) — 54 tests, complete rewrite against the new plugin-based architecture.
- **Coverage**:
  - **Constants / adaptive block size** — `_optimal_block_size()` thresholds (512 KB / 4 MB / 16 MB).
  - **FileCarver init** — plugin discovery, header-map priority (plugins override legacy), regex compilation.
  - **Legacy `_estimate_size(data, start, footer, ext)`** — 4-arg signature, 100/60 integrity split.
  - **Objective 1 — `NTFSParser` silent fallback** (`TestNtfsParserFallback`):
    - `os.lseek`/`os.read` patched via `unittest.mock.patch` — no real disk I/O.
    - Verifies `read_boot_sector()` returns `None` on: non-NTFS logical volume, truncated reads, `OSError` raw-device failures, MBR without 0x55AA signature, MBR with no type-0x07 entry.
  - **Objective 2 — MIME validation** (`TestMimeValidation`):
    - Valid + invalid JFIF / Exif / DQT-only JPEGs, bad marker bytes, too-short buffers.
    - PDF version tuple (1.0–1.7, 2.0–2.9 pass; 1.8, 9.9, non-numeric reject).
    - ZIP Local File Header method field + name_len sanity.
    - `refine_extension()` dispatch: `.docx`, `.xlsx`, `.epub`, `.apk`, `.zip` fallback.
  - **Objective 3 — JPEG fragmentation** (`TestJpegFragmentation`):
    - Fast path (size ≥ 2 KB) → integrity **100**.
    - Clean structural walk reaching EOI → **100**.
    - Scan finished without EOI but valid scan boundary → **70** (fragment reassembled).
    - Parser blocked on garbage → **75** (fallback to `default_size_kb`).
    - RSTn markers and FF 00 byte-stuffing inside entropy correctly handled.
  - **Objective 4 — FileCarver end-to-end**: plugin JPEG detection + integrity 100, legacy PNG path, PDF plugin, silent MIME rejection for PDF 9.9, stop-flag, empty file, DOCX refinement dispatched from ZIP plugin.
- **Architectural decisions validated**:
  - `unittest.mock.patch` on `app.core.fs_parser.os.lseek` / `os.read` — the only way to exercise `NTFSParser` without a real NTFS volume.
  - Fixture-free temp files (via `tempfile.mkstemp`) keep `FileCarver.scan()` tests self-contained.
  - The 4-KB `_MIME_WINDOW` is large enough for all structural-marker checks in synthetic buffers.
  - `BaseCarverPlugin` stays abstract — `TestBasePlugin.test_cannot_instantiate_abstract_base` locks the contract.
- **Test result**: 68 passed (54 new here + 14 pre-existing in `test_c_bridge.py` / `test_disk_detector.py`), 0 failed, 1 warning (unrelated docstring escape in `fs_parser.py`).
- **Status**: Objectives 1-5 complete. Engine refactor closed.

### Objective 6 / Chantier 1 — Full NTFSParser integration + FS abstraction

- **Added**: [app/core/fs_parser.py](app/core/fs_parser.py) — `BaseFSParser` ABC, `FS_PARSERS` registry, `detect_fs(raw_device, fd)` dispatcher.
  - `NTFSParser` now inherits `BaseFSParser`; exposes `probe()` (caches BPB) and `enumerate_files()` (wraps `scan_mft`).
  - `_runs_to_byte_ranges(runs, boot)` helper converts NTFS data runs from clusters to absolute (byte_offset, byte_length) tuples.
  - Silent fallback contract: any exception in `probe()` is swallowed and logged at DEBUG level; `detect_fs()` returns `None` so the pipeline falls through to pure carving.
- **Added**: [app/workers/scan_worker.py](app/workers/scan_worker.py) — `_DedupIndex` class.
  - Accumulates `(start, length)` ranges during Phase 1, `freeze()` merges overlaps, `overlaps(start, length)` answers in O(log n) via `bisect`.
  - Criterion: **any chevauchement** (partial or total) between a carved candidate and a recorded MFT run → silent drop.
- **Modified**: [app/workers/scan_worker.py](app/workers/scan_worker.py) — `_run_real()` now uses `detect_fs()` + `_DedupIndex`.
  - Progress split: **20% FS enumeration / 80% carving** (reflects the real time distribution).
  - The carver receives `dedup_check=dedup_index.overlaps` only when Phase 1 actually produced entries.
- **Modified**: [app/core/file_carver.py](app/core/file_carver.py) — `scan()` accepts a `dedup_check` callable.
  - Silently drops candidates that overlap a claimed range; emits `source="carver"` on every surviving hit; log line reports dedup count alongside skip/reject counters.
- **Modified**: [app/ui/screen_results.py](app/ui/screen_results.py) — UI surfaces the MFT provenance.
  - `FileThumb` shows a green `✨ NTFS` pill (top-left) when `source == "mft"`.
  - `_FileDetailPanel` adds conditional rows: **Origine**, **Chemin** (mft_path), **Système** (fs), **Runs** (fragment count ≥ 2).
  - DFXML export now emits one `<byte_run>` per entry in `data_runs` (multi-fragment support), plus `<lumina:source>`, `<lumina:fs>`, `<lumina:mft_path>`.
- **Enriched file_info schema** (new keys, all optional):
  - `source`: `"mft"` | `"carver"` — provenance of the record.
  - `fs`: `"NTFS"` | `"ext4"` | `"APFS"` | … — filesystem name when source is `"mft"`.
  - `data_runs`: `list[(byte_offset, byte_length)]` — physical fragments on the device.
  - `mft_path`: full reconstructed path (already emitted before, now consumed by UI/DFXML).
- **Architectural decisions validated**:
  - Overlap semantics chosen over exact-offset match — partial carved fragments of an MFT-known file are still considered duplicates.
  - Progress ratio 20/80 — MFT enumeration is O(N_files), carving is O(disk_bytes); the disproportion is intrinsic.
  - `data_runs` preserved in `file_info` (not just indexed) — essential for DFXML `<byte_runs>` forensic trace.
  - `NTFSParser` keeps its name (no rename to `NtfsFSParser`) — minimal diff, tests unaffected.
  - FS registry kept flat inside `fs_parser.py` for now — moves to a sub-package only when a second parser (ext4/APFS) ships.
- **Tests added**: 20 new tests (88 total, 2.27s).
  - `TestFSParserRegistry` (7 tests) — `BaseFSParser` abstractness, registry contents, `detect_fs()` match/fallback, `probe()` exception-swallowing, `_runs_to_byte_ranges` correctness + filtering.
  - `TestDedupIndex` (8 tests) — empty index, exact match, containment both directions, partial L/R overlap, non-overlap (including half-open end), adjacent merging, 1000-range scaling, zero-length/negative rejection.
  - `TestFileCarverDedup` (4 tests) — dedup_check dropping, non-matching pass-through, exception tolerance, `source="carver"` emission.
- **Status**: Chantier 1 complete. NTFS integration is live in the real-scan pipeline; architecture ready for ext4/APFS (add a subclass, append to `FS_PARSERS`).

### Objective 7 / Chantier 2 — High-value plugins (MP4/MOV + SQLite)

- **Added**: [app/plugins/carvers/mp4_plugin.py](app/plugins/carvers/mp4_plugin.py) — ISO-BMFF family carver (MP4, MOV, 3GP, M4A/B/V, F4V, HEIC) with full atom-tree walker.
  - **Signatures**: 17 `ftyp<brand>` tokens (isom, iso2, mp41/42, avc1, qt, M4A/B/V, 3gp4/5, 3g2a, F4V, heic/heix/heim/heis/hevc, mif1, dash) — `FileCarver` applies `-4` offset correction to land on the real box origin.
  - **`validate_mime()`**: confirms `ftyp` prefix + major brand ∈ `_VALID_BRANDS` (35 accepted brands).
  - **`refine_extension()`**: maps brand token → `.mov` / `.m4a` / `.m4v` / `.heic` / `.3gp` / `.3g2` / `.f4v` (fallback `.mp4`).
  - **`estimate_size()`**: walks top-level atoms (`size u32 BE + type 4-CC`), honours 64-bit extended size (`size == 1`), treats `size == 0` as "extends to EOF", accepts unknown printable 4-CCs (vendor extensions), bails on non-ASCII type or `size < 8`.
- **Added**: [app/plugins/carvers/sqlite_plugin.py](app/plugins/carvers/sqlite_plugin.py) — SQLite ≥ 3 database carver with exact-size reconstruction.
  - **Signature**: `SQLite format 3\x00` (16 B magic), covers `.sqlite`, `.db`, `.sqlite3`.
  - **`validate_mime()`**: checks page_size ∈ spec set `{1, 512, 1024, 2048, 4096, 8192, 16384, 32768}`, write/read versions ∈ `{1, 2}`, and the three fixed payload-fraction fields (offsets 21/22/23 must equal 64/32/32 per §1.3).
  - **`estimate_size()`**: returns exact `page_size * db_size_in_pages` (integrity **100**), falls back to `default_size_kb` + integrity **75** when `db_size_in_pages == 0` (pre-3.7.0 legacy DBs) or the page_size field is corrupt.
- **Modified**: [tests/test_file_carver.py](tests/test_file_carver.py) — 34 new tests across 5 classes.
  - `TestMp4Validation` (11) — brand whitelist, magic/length rejection, `refine_extension()` dispatch per brand family.
  - `TestMp4SizeCalculation` (8) — small/large files, declared-mdat overflow beyond buffer, 64-bit extended size, `moof`-fragmented, malformed size bail, non-ASCII atom type, `start < 4` graceful fallback.
  - `TestSqliteValidation` (7) — default/WAL headers pass, bad magic/page_size/write_ver/payload-fraction reject, short-buffer reject.
  - `TestSqliteSizeCalculation` (6) — exact 4K/8K page math, `page_size == 1` → 65536 interpretation, `db_pages == 0` fallback, short-buffer + invalid-page-size fallbacks.
  - `TestChantier2CarverIntegration` (2) — end-to-end `FileCarver.scan()` emits `MP4` hit at offset 512 with integrity 100 + exact `size_kb`, same for `SQLITE` with `page_size * db_pages` byte length.
- **Architectural decisions validated**:
  - `_FRAGMENT_MIN_SIZE = 8 KB` for MP4 — below this, a structurally-valid walk still drops to integrity 70 (likely fragment).
  - Integrity **100** when walker completed ≥ 2 top-level boxes AND total ≥ 8 KB — covers the "real file followed by zero padding on disk" case without over-counting tiny fragments.
  - Declared mdat size credited even when it overflows the in-RAM buffer — for real 50 MB videos the MIME window (4 KB) never contains the full mdat, and the atom walker uses the declared size as a trustworthy upper bound.
  - SQLite payload-fraction validation catches near-magic false positives (e.g. raw text buffers that happen to begin with `SQLite format 3\x00`).
  - Both plugins claim their full `handled_extensions` tuple so the legacy `SIGNATURES` entries (`.mp4`, `.mov`, `.m4a`, `.sqlite`, `.3gp`, `.f4v`, `.heic`) are filtered out at `FileCarver` init — no double-registration.
  - No change to `FileCarver` signature-scan logic: the existing `-4` ftyp offset correction already routes these hits correctly.
- **Test result**: 123 passed (109 in `test_file_carver.py` + 14 pre-existing elsewhere), 0 failed, 2.28 s.
- **Status**: Chantier 2 complete. MP4/MOV and SQLite now produce **exact** file sizes on recovery (no more `default_size_kb` guesses for these two families).

### Update policy

Append a new section to this changelog **every time a major implementation is finished**. Keep each entry to: what was added, files touched, key architectural decisions validated.

