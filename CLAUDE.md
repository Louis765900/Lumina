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
python -m PyInstaller lumina.spec --noconfirm
```

## Architecture

**Lumina** is a Windows-only PyQt6 desktop app for data recovery. It requires Administrator rights to open raw disk devices (`\\.\C:`, `\\.\PhysicalDrive0`). A UAC re-launch is triggered automatically on startup if not elevated.

Product version: **v1.0.0**.

### Entry flow

```
main.py
  ├── _is_admin() → ShellExecuteW "runas" if not admin
  ├── loads app/ui/styles.qss globally onto QApplication
  ├── ensure_setup_complete() → first-launch setup wizard if needed
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
5. Production path creates `ScanWorker(disk, simulate=False)` and starts a real scan path
6. Worker emits `progress(int)`, `status_text(str)`, `files_batch_found(list)` during scan
7. Worker emits `finished(list)` → `ScanScreen.scan_finished(list)` → `_go_results(files)`
8. `ResultsScreen.load_results(files)` displays results and writes to history

**Critical**: fake/demo scan data is forbidden in the normal product path. `simulate=True` is development-only and must be guarded by `LUMINA_ENABLE_DEMO=1`. Quick Scan is now metadata-only: it attempts NTFS MFT enumeration and never falls through to carving or fake data. Unsupported quick-scan sources emit "Scan rapide non disponible pour cette source" and ask the user to run Deep Scan.

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
    "simulated": True,                # development-only demo data; forbidden in production
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
Extracts selected files to a validated destination folder. Normal product scans never emit simulated files. For real files, reads bytes directly from the raw device using `os.open` + `os.lseek` + `os.read`. Caps extraction at 500 MB per file.

### `_SmartWorker` (`screen_tools.py`)
Runs a PowerShell `Get-CimInstance Win32_DiskDrive | ConvertTo-Json` command to get S.M.A.R.T. data. Handles single-disk (dict) vs multi-disk (list) JSON output. Timeout: 20s.

---

## Core engine

### Product V1 real-app guardrails

- The normal user journey must never display generated/fake recovery results.
- The legacy simulation path is retained only for developer testing and requires `LUMINA_ENABLE_DEMO=1`.
- Quick Scan is no longer allowed to mean fake data. Product V1 delivery 2 maps it to real NTFS MFT metadata enumeration only; it does not run carving.
- Persistent application settings live in `%APPDATA%/Lumina/settings.json` through `app/core/settings.py`.
- Settings defaults are safe: French language, `auto` scan engine, image-first preference enabled, disclaimer not accepted, and first launch not completed.
- `app/core/i18n.py` provides a deliberately small FR/EN dictionary with French fallback.
- `LUMINA_SCAN_ENGINE` remains a developer/CI override. If absent, the persisted `scan_engine` setting is used.
- Product V1 delivery 3 adds `app/ui/setup_wizard.py`. On startup, Lumina shows the setup wizard when `first_launch_done=false` or `accepted_disclaimer=false`; otherwise Home opens normally.
- The setup wizard captures language, default recovery directory, scan engine, image-first preference, and the mandatory recovery disclaimer, then saves the validated settings.
- Product V1 delivery 4 adds recovery destination guardrails in `app/core/recovery.py`: extraction always asks for a destination, starts from the persisted recovery directory, creates the folder when needed, blocks detectable writes to the source volume, warns on ambiguous same-drive image cases, and persists the last approved destination.
- `logs/lumina.log` is created through `ensure_lumina_log()` and records scan mode/engine/source plus extraction destination, recovered counts, and failures.
- Product V1 delivery 5 finalizes distribution: version `v1.0.0`, PyInstaller windowed tracebacks disabled, `lumina.spec` bundles the Rust helper, plugins, stylesheet, and icon, and `MANUAL_TESTING.md` documents the release checklist.
- Logs rotate at 5 MB with two backups. Log setup must never crash the app if the log file is inaccessible.

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

### Objective 8 / Chantier 3 - Multi-pattern search benchmark (re vs Aho-Corasick)

- **Modified**: [scripts/bench_carver.py](scripts/bench_carver.py) - synthetic benchmark for the signature search hot path.
  - Compares current `re.Pattern.finditer()` against optional `pyahocorasick.Automaton.iter()`.
  - Supports `BENCH_CARVER_MB` and `BENCH_CARVER_SEEDS` to scale the workload without editing the script.
  - Uses Latin-1 byte-to-string mapping for `pyahocorasick`, preserving exact byte values while including the conversion cost in timings.
  - Console output is ASCII-only to avoid Windows `cp1252` crashes.
- **Benchmark result** (April 26, 2026, 32 MB synthetic buffer, 1,250 seeded signatures, 91 loaded signatures):
  - `re` best: **21.582 s** / **1.5 MB/s**
  - `pyahocorasick` best: **18.425 s** / **1.7 MB/s**
  - Speedup: **1.17x**
  - Decision: **keep `re`** because the measured gain is below the agreed **2.0x** swap threshold.
- **Architectural decisions validated**:
  - No runtime dependency on `pyahocorasick` is introduced for now.
  - `FileCarver` stays on the existing regex engine, so there is no behavioral risk around overlapping signatures or plugin dispatch.
  - The benchmark remains available for future re-testing if the signature table grows substantially or if a different Aho-Corasick binding is evaluated.
- **Status**: Chantier 3 complete. Optimization rejected by evidence; regex path retained deliberately.

### Objective 9 / B1 Phase 1 - Rust native candidate scanner helper

- **Added**: [native/lumina_scan/](native/lumina_scan/) - standalone Rust helper scaffold for the future native Deep Scan hot path.
  - `Cargo.toml` declares `aho-corasick`, `serde`, `serde_json`, and `thiserror`.
  - `src/main.rs` implements the JSONL stdin/stdout process wrapper with concurrent scan threads and `stop` dispatch by `request_id`.
  - `src/protocol.rs` defines the minimal B1 contract: `scan`, `stop`, `progress`, batched `candidates`, `finished`, and `error`.
  - `src/scanner.rs` implements image-file-only scanning with `BufReader`, reusable chunk buffer, dynamic overlap (`max_signature_len - 1`), batched candidates, progress throttling, and stop checks inside the match loop.
  - `src/signatures.rs` decodes Python-provided hex signatures and builds a Rust `aho_corasick::AhoCorasick` matcher.
  - `src/control.rs` exposes the cooperative stop flag used by both the process wrapper and unit tests.
  - `tests/protocol.rs` locks JSONL parsing/serialization for the public protocol.
- **Protocol decisions validated for Phase 1**:
  - Rust receives signatures from Python; it does not own plugin logic or MIME validation.
  - Rust returns only `{offset, signature_id, ext}` candidates in batches; Python will keep validation, sizing, integrity, SHA-256, DFXML, and provenance in later phases.
  - Source scope is deliberately limited to `kind="image"`; no `PhysicalDrive`, VSS, or acquisition path is touched in Phase 1.
  - I/O strategy is buffered sequential reads (`BufReader`, default 16 MiB chunk), not mmap, to keep stop/progress behavior predictable on removable and large local images.
  - Candidate batching is part of the protocol from the start to avoid one JSON event per match.
  - `.gitignore` now ignores Rust `target/` build output.
- **Tests planned/added**:
  - Scanner unit tests cover single hit, boundary-split signature via overlap, candidate batching, intra-match-loop stop, and non-image source rejection.
  - Protocol integration tests cover `scan`, `stop`, and `candidates` event JSON.
- **Verification status**:
  - `cargo test`: **11 passed** (8 unit tests + 3 protocol integration tests), 0 failed.
  - Python `FileCarver` is untouched in this phase; no runtime integration has been made yet.
- **Status**: B1 Phase 1 code is ready for Phase 2. Native helper is not integrated into Python yet.

### Objective 10 / B1 Phase 2 - Python NativeScanClient + anomaly/fallback

- **Added**: [app/core/native/](app/core/native/) - isolated Python client layer for the Rust JSONL helper.
  - `protocol.py` defines strict dataclasses and JSONL parsing/serialization for `scan`, `stop`, `progress`, batched `candidates`, `finished`, and `error`.
  - `anomaly.py` validates functional consistency: candidate bounds (`offset < 0` or `offset >= source_size`), unknown `signature_id`, extension mismatch, oversized batch, progress regression, missing `finished`, stopped mismatch, and candidate-count mismatch.
  - `settings.py` reads `LUMINA_SCAN_ENGINE=auto|python|native`; invalid values return `auto` and log a warning on `lumina.native`.
  - `client.py` launches the helper as a process, drains stdout through a reader thread + `Queue`, drains stderr in a daemon thread, sends cooperative `stop`, and always cleans up stdin/process handles.
- **Fallback rules validated**:
  - `native` mode never falls back silently; helper absence, protocol errors, or critical anomalies raise explicit exceptions.
  - `python` mode never starts Rust and requires an injected Python fallback callable.
  - `auto` mode may fall back only before any candidate batch has been delivered.
  - **Fallback auto uniquement avant émission de candidates. Après émission, erreur explicite pour éviter incohérence UI.**
  - Candidate callbacks always receive a fresh copied list, not an internal mutable buffer.
- **Added tests**:
  - [tests/test_native_protocol.py](tests/test_native_protocol.py) - strict JSONL parsing, command serialization, wrong request IDs, unknown events, schema extras, bool-as-int rejection, invalid engine warning.
  - [tests/test_native_anomaly.py](tests/test_native_anomaly.py) - critical anomaly coverage for offsets, signatures, extensions, batch size, progress, missing finish, stop mismatch; candidate-count mismatch remains a warning in Phase 2.
  - [tests/test_native_client.py](tests/test_native_client.py) - fake-helper process tests for streaming batches, copied callbacks, stop command, auto fallback, native-forced errors, and "anomaly after candidates => no fallback".
  - [tests/test_native_parity.py](tests/test_native_parity.py) - simple Rust helper parity smoke test when `target/release/lumina_scan(.exe)` exists; skips cleanly if not built.
- **Added**: [scripts/bench_native_carver.py](scripts/bench_native_carver.py) - preliminary Phase 2 benchmark harness.
  - Generates a synthetic image, extracts signatures from current `FileCarver`, compares Python regex candidate offsets against Rust helper candidate offsets when the release helper exists, and writes JSON under `benchmarks/results/`.
  - Full performance gate (`>= 100 MB/s`, mismatch analysis, duplicates) remains Phase 3.
- **Verification result**:
  - `cargo test`: **11 passed**, 0 failed.
  - `cargo build --release`: success; helper binary builds in optimized mode.
  - `python -m pytest`: **148 passed**, 0 failed.
  - `python -m ruff check app/core/native tests/test_native_*.py scripts/bench_native_carver.py`: success.
  - Cargo emitted transient "Blocking waiting for file lock on package cache" messages while `cargo test` and `cargo build --release` ran in parallel; both commands completed successfully.
- **Status**: B1 Phase 2 complete. Native client is testable independently; no `ScanWorker` or UI integration yet.

### Objective 11 / B1 Phase 3 - Native benchmark and parity gate

- **Modified**: [scripts/bench_native_carver.py](scripts/bench_native_carver.py) - upgraded from preliminary harness to full Phase 3 benchmark.
  - Supports `--mode python|native|both`, `--size-mb`, `--seeds`, `--keep-image`, `--force-rebuild`, and JSON output under `benchmarks/results/`.
  - Generates a deterministic synthetic image with seeded signatures from image/document/archive families (`.gif`, `.jpg`, `.pdf`, `.png`, `.zip`).
  - Injects signatures at known offsets, including offsets around 16 MiB chunk boundaries to validate native overlap behavior.
  - Separates seeded-vs-engine parity fields explicitly:
    - `seeded_missing_native = expected_set - native_set`
    - `parity_missing_vs_python = python_set - native_set`
    - `native_extra_vs_seeded = native_set - expected_set`
    - `native_extra_vs_python = native_set - python_set`
  - Splits false positives into `false_positive_common`, `false_positive_native_only`, and `false_positive_python_only`.
  - Reports duplicates, exact-offset extension mismatches, `mbps`, `duration_ms`, `candidate_count`, and `candidates_per_sec`.
- **Benchmark result** (April 27, 2026, `--mode both --size-mb 256 --seeds 5000 --keep-image`):
  - JSON report: `benchmarks/results/native_phase3_1777290329.json`.
  - Synthetic image: `benchmarks/corpus/native_phase3_256mb.img` (kept locally; ignored by git).
  - Python regex: **91,970 ms**, **2.78 MB/s**, **5,000 candidates**, **54.37 candidates/s**.
  - Rust helper: **6,025 ms**, **42.48 MB/s**, **5,000 candidates**, **829.88 candidates/s**.
  - Rust wall-clock via Python client: **6,602 ms**, **38.77 MB/s**.
- **Parity result**:
  - `seeded_missing_native`: **0**
  - `parity_missing_vs_python`: **0**
  - `native_extra_vs_seeded`: **0**
  - `native_extra_vs_python`: **0**
  - `mismatched_ext`: **0**
  - `duplicates_native`: **0**
  - `false_positive_common`: **0**
  - `false_positive_native_only`: **0**
  - `false_positive_python_only`: **0**
- **Gate decision**:
  - Correctness gate passed: no seeded misses, no Python-vs-Rust missing candidates, no extension mismatches, no native duplicates.
  - Performance gate failed: Rust helper measured **42.48 MB/s**, below the required **100 MB/s**.
  - **Decision**: do **not** integrate into `ScanWorker` yet. Phase 4 image-only integration is blocked until the native helper reaches the 100 MB/s gate.
- **Verification result**:
  - `cargo test`: **11 passed**, 0 failed.
  - `cargo build --release`: success.
  - `python -m pytest`: **148 passed**, 0 failed.
  - `python -m ruff check scripts/bench_native_carver.py`: success.
- **Status**: B1 Phase 3 complete as a benchmark/parity pass, but the native engine is not eligible for Phase 4 integration yet.

### Objective 12 / B1 Phase 3.1 - Native helper bottleneck analysis

- **Added**: [native/lumina_scan/src/bin/internal_bench.rs](native/lumina_scan/src/bin/internal_bench.rs) - Rust-only benchmark binary for isolating native scanner bottlenecks without changing the production JSONL helper behavior.
  - Measures read-only throughput.
  - Measures `find_overlapping_iter` without JSONL.
  - Measures `find_iter` + `MatchKind::LeftmostFirst` without JSONL.
  - Measures no-copy boundary scanning variants for both overlapping and leftmost modes.
  - Measures real `scan_image()` JSON serialization path with chunk sizes **16/32/64 MiB**, candidate batch sizes **512/2048/8192**, and progress intervals **250/1000 ms**.
- **Benchmark inputs**:
  - Original OneDrive corpus: `benchmarks/corpus/native_phase3_256mb.img`.
  - External local copy: `C:\LuminaBench\native_phase3_256mb.img`.
  - Result reports:
    - `benchmarks/results/internal_bench_onedrive.json`
    - `benchmarks/results/internal_bench_c_luminabench.json`
    - `benchmarks/results/internal_bench_c_luminabench_nocopy.json`
    - Phase 3 rerun: `benchmarks/results/native_phase3_1777294484.json`
- **Key diagnostic results**:
  - OneDrive read-only best: **171.25 MB/s** (16 MiB chunks).
  - OneDrive `LeftmostFirst/find_iter` best without JSONL: **68.88 MB/s**.
  - OneDrive JSONL scanner best: **19.21 MB/s** (32 MiB chunks, batch 2048, progress 250 ms).
  - `C:\LuminaBench` read-only best: **111.35 MB/s** (32 MiB chunks) in the no-copy run; earlier local run reached **185.70 MB/s** read-only.
  - `C:\LuminaBench` `find_overlapping_iter` best without JSONL: **19.23 MB/s**.
  - `C:\LuminaBench` `LeftmostFirst/find_iter` best without JSONL: **59.12 MB/s**.
  - `C:\LuminaBench` `LeftmostFirst/find_iter` no-copy best: **70.80 MB/s**.
  - `C:\LuminaBench` JSONL scanner best in the no-copy benchmark run: **16.01 MB/s**.
- **Phase 3 rerun after adding the internal benchmark** (`--mode both --size-mb 256 --seeds 5000 --keep-image`):
  - Python regex: **258,541 ms**, **0.99 MB/s**, **5,000 candidates**.
  - Rust helper: **17,950 ms**, **14.26 MB/s**, **5,000 candidates**.
  - Parity remained perfect: `seeded_missing_native=0`, `parity_missing_vs_python=0`, `mismatched_ext=0`, `duplicates_native=0`.
  - Gate remained failed: Rust below **100 MB/s**.
- **Architectural decision**:
  - Do **not** replace production `find_overlapping_iter` yet.
  - `LeftmostFirst/find_iter` improves throughput but does not reach **100 MB/s** on the measured corpus, even with no-copy boundary scanning.
  - Read-only throughput can exceed **100 MB/s**, so the bottleneck is not purely disk I/O; the scanner hot path remains dominated by matching strategy and/or JSONL scanner overhead.
  - No `ScanWorker` or UI integration is allowed yet.
- **Verification result**:
  - `cargo test`: **11 passed**, 0 failed.
  - `cargo build --release`: success.
  - `python -m pytest`: **148 passed**, 0 failed.
- **Status**: Phase 3.1 diagnostic complete. No production scanner patch was applied because the performance gate was not met.

### Objective 13 / B1 Phase 3.2 - PrefixMatcher experiment

- **Added**: [native/lumina_scan/src/prefix_matcher.rs](native/lumina_scan/src/prefix_matcher.rs) - isolated Rust prefix-index matcher for evaluating an alternative to Aho-Corasick without touching the production scanner.
  - Builds u32/u16/u8 prefix buckets from Python-provided signatures.
  - Preserves leftmost-longest semantics for prefix collisions.
  - Keeps deterministic input-order tie-breaking for same-length ambiguous signatures.
  - Exposes only isolated matching primitives; it is not wired into `scan_image()` or any Python/UI path.
- **Added benchmark variants** in [native/lumina_scan/src/bin/internal_bench.rs](native/lumina_scan/src/bin/internal_bench.rs):
  - `scan_prefix_u32_no_jsonl`
  - `scan_prefix_u32_no_copy_no_jsonl`
  - `scan_prefix_u32_jsonl_simulated`
  - Existing comparison baselines remain: Aho overlapping, Aho `LeftmostFirst`, no-copy Aho variants, read-only, and real JSONL scanner path.
- **Semantic Rust tests added**:
  - Leftmost-longest behavior with `ABC` / `ABCD` / `ABCDE`.
  - Adjacent matches.
  - Multiple matches in one buffer.
  - Split-boundary match via overlap window.
  - Ambiguous identical signatures using deterministic input order.
- **Benchmark result** (April 27, 2026, `C:\LuminaBench\native_phase3_256mb.img`):
  - JSON report: `benchmarks/results/internal_bench_prefix_c_luminabench.json`.
  - Read-only best: **101.88 MB/s** (64 MiB chunks).
  - Aho overlapping best: **15.90 MB/s**.
  - Aho overlapping no-copy best: **19.29 MB/s**.
  - Aho `LeftmostFirst` best: **51.75 MB/s**.
  - Aho `LeftmostFirst` no-copy best: **49.60 MB/s** in this run.
  - Real production JSONL scanner best: **22.92 MB/s** (32 MiB chunks, batch 8192, progress 250 ms).
  - Prefix u32 no JSONL best: **7.26 MB/s**.
  - Prefix u32 no-copy best: **6.12 MB/s**.
  - Prefix u32 JSONL simulated best: **8.97 MB/s** (32 MiB chunks, batch 2048, progress 1000 ms).
- **Phase 3 parity rerun** (`python scripts/bench_native_carver.py --mode both --size-mb 256 --seeds 5000 --keep-image`):
  - JSON report: `benchmarks/results/native_phase3_1777301544.json`.
  - Python regex: **551,153 ms**, **0.46 MB/s**, **5,000 candidates**.
  - Rust production helper: **28,361 ms**, **9.03 MB/s**, **5,000 candidates**.
  - `seeded_missing_native`: **0**
  - `parity_missing_vs_python`: **0**
  - `mismatched_ext`: **0**
  - `duplicates_native`: **0**
  - `false_positive_common`: **0**
  - `false_positive_native_only`: **0**
  - `false_positive_python_only`: **0**
- **Gate decision**:
  - PrefixMatcher correctness tests passed, but measured throughput is far below both Aho `LeftmostFirst` and the required **100 MB/s** gate.
  - Production Aho scanner remains unchanged.
  - No `ScanWorker` or UI integration was made.
  - Next optimization should not use naive byte-by-byte prefix probing; likely candidates are SIMD/memchr-driven first-byte scanning, rarer-prefix grouping, or a specialized matcher that can skip non-candidate bytes.
- **Verification result**:
  - `cargo test`: **16 Rust tests passed** (13 library/bin unit tests + 3 protocol integration tests), 0 failed.
  - `cargo build --release`: success.
  - `python -m pytest`: **148 passed**, 0 failed.
- **Status**: Phase 3.2 complete as an isolated experiment. The production helper is still blocked from Phase 4 integration because the **100 MB/s** gate is not met.

### Objective 14 / B1 Phase 3.3 - Rust profile breakdown

- **Added**: `--profile-breakdown` mode to [native/lumina_scan/src/bin/internal_bench.rs](native/lumina_scan/src/bin/internal_bench.rs).
  - Outputs structured JSON with per-run timings for read, buffer/overlap construction, matching, batching, JSONL serialization/write path, and unaccounted time.
  - Reports chunks, bytes read, bytes copied, candidates, events, MB/s, matcher mode, chunk size, copy strategy, and JSONL on/off.
  - Covers chunk sizes **16/32/64 MiB**, Aho `find_overlapping_iter`, Aho `LeftmostFirst`, copy-overlap scan buffer, no-copy boundary overlap, JSONL enabled, and JSONL disabled.
  - This is an internal benchmark/profiling mode only; the production `scan_image()` path remains unchanged.
- **Profile reports generated**:
  - `benchmarks/results/profile_breakdown_c_luminabench.json` for `C:\LuminaBench\native_phase3_256mb.img`.
  - `benchmarks/results/profile_breakdown_onedrive.json` for `benchmarks/corpus/native_phase3_256mb.img`.
- **Key C:\LuminaBench results**:
  - Best `LeftmostFirst` no-copy/no-JSONL: **288.76 MB/s** (16 MiB chunks).
  - Best `LeftmostFirst` no-copy/JSONL: **261.13 MB/s** (64 MiB chunks).
  - Best overlapping no-copy/JSONL: **80.66 MB/s** (16 MiB chunks).
  - Best overlapping copy/JSONL: **79.14 MB/s** (16 MiB chunks).
  - `LeftmostFirst` no-copy/JSONL time split at best: read **54.0%**, matching **42.8%**, JSONL **1.3%**, buffer/copy approximately **0%**.
  - Overlapping no-copy/JSONL time split at best: read **14.7%**, matching **84.7%**, JSONL **0.4%**, buffer/copy approximately **0%**.
- **Key OneDrive results**:
  - Best `LeftmostFirst` no-copy/no-JSONL: **272.68 MB/s** (16 MiB chunks).
  - Best `LeftmostFirst` no-copy/JSONL: **247.66 MB/s** (16 MiB chunks).
  - Best overlapping no-copy/JSONL: **77.42 MB/s** (16 MiB chunks).
  - Best overlapping copy/JSONL: **75.32 MB/s** (32 MiB chunks).
  - `LeftmostFirst` no-copy/JSONL time split at best: read **52.0%**, matching **46.3%**, JSONL **1.0%**, buffer/copy approximately **0%**.
  - Overlapping no-copy/JSONL time split at best: read **15.4%**, matching **84.0%**, JSONL **0.4%**, buffer/copy approximately **0%**.
- **Diagnostic conclusion**:
  - JSONL serialization/write overhead inside the Rust process is not the dominant bottleneck on the current sparse-candidate corpus; it stays around **0.2-2.3%** in measured JSONL runs.
  - Full scan-buffer reconstruction copies roughly the whole image per pass (`~268 MB` copied on a 256 MB image) and costs up to **~26%** in some copy-overlap runs.
  - The dominant bottleneck for the current production-compatible `find_overlapping_iter` strategy is matching: usually **~80-85%** of runtime for overlapping/no-copy runs.
  - Aho `LeftmostFirst` plus no-copy overlap is fast enough in the internal benchmark, but it is **not production-eligible yet** because Phase 3 parity and false-positive analysis must be rerun against Python before any scanner replacement.
  - The previous slow production helper benchmark likely includes additional process/client/runtime effects not isolated by this in-process `io::sink()` profiler; this remains a separate measurement target before Phase 4.
- **No production change applied**:
  - `scan_image()` still uses the existing production matcher path.
  - No `ScanWorker` or UI integration was made.
  - Phase 4 remains blocked until a production helper build, measured through the Python client, reaches **>=100 MB/s** with perfect parity.
- **Verification result**:
  - `cargo test`: **16 Rust tests passed** (13 library/bin unit tests + 3 protocol integration tests), 0 failed.
  - `cargo build --release`: success.
  - `python -m pytest`: **148 passed**, 0 failed.
- **Status**: Phase 3.3 complete. The next safe optimization candidate is a separate parity-gated production experiment for Aho `LeftmostFirst` + no-copy overlap, not another blind matcher rewrite.

### Objective 15 / B1 Phase 3.4 - Production-gated Aho LeftmostFirst + no-copy overlap

- **Modified**: [native/lumina_scan/src/scanner.rs](native/lumina_scan/src/scanner.rs) - added two internal scanner modes:
  - `overlapping_copy`: legacy baseline, still available with `LUMINA_NATIVE_MATCHER=overlapping_copy`.
  - `leftmost_no_copy`: production default after this phase.
- **Modified**: [native/lumina_scan/src/signatures.rs](native/lumina_scan/src/signatures.rs) - signature compilation now supports Aho `MatchKind::LeftmostFirst`.
  - Signatures are sorted by descending header length, preserving input order for ties.
  - This mirrors Python regex behavior where longer headers win at the same offset.
- **No-copy overlap strategy adopted**:
  - Each chunk is scanned directly.
  - A small boundary window is built as `previous_tail + current_prefix`.
  - Boundary candidates are emitted only when strictly crossing the chunk boundary:
    - `match.start < overlap_len`
    - `match.end > overlap_len`
  - Absolute offsets are computed from `bytes_scanned - overlap_len + match.start` for boundary hits and `bytes_scanned + match.start` for chunk-local hits.
  - This avoids duplicate candidates while preserving split-signature recovery.
- **Rust tests added**:
  - Prefix ambiguity: `ABC` / `ABCD` / `ABCDE` emits only `ABCDE`.
  - Adjacent matches are emitted.
  - Signature split across chunks is detected.
  - No duplicate near chunk boundary.
  - Absolute offsets are exact.
  - Leftmost/no-copy output matches a simulated Python regex scan on a synthetic corpus.
- **Candidate benchmark before default adoption** (`LUMINA_NATIVE_MATCHER=leftmost_no_copy python scripts/bench_native_carver.py --mode both --size-mb 256 --seeds 5000 --keep-image`):
  - Native helper: **922 ms**, **277.49 MB/s**, **5,000 candidates**.
  - Native wall-clock through Python client: **1,626 ms**, **157.35 MB/s**.
  - `seeded_missing_native`: **0**
  - `parity_missing_vs_python`: **0**
  - `mismatched_ext`: **0**
  - `duplicates_native`: **0**
  - Gate passed.
- **Final benchmark after default adoption** (`python scripts/bench_native_carver.py --mode both --size-mb 256 --seeds 5000 --keep-image`):
  - JSON report: `benchmarks/results/native_phase3_1777305707.json`.
  - Python regex: **72,167 ms**, **3.55 MB/s**, **5,000 candidates**.
  - Native helper: **857 ms**, **298.46 MB/s**, **5,000 candidates**.
  - Native wall-clock through Python client: **2,126 ms**, **120.38 MB/s**.
  - `seeded_missing_native`: **0**
  - `parity_missing_vs_python`: **0**
  - `mismatched_ext`: **0**
  - `duplicates_native`: **0**
  - `false_positive_common`: **0**
  - `false_positive_native_only`: **0**
  - `false_positive_python_only`: **0**
- **Gate decision**:
  - Rust native throughput gate passed: **298.46 MB/s >= 100 MB/s**.
  - Python-client wall throughput also passed: **120.38 MB/s >= 100 MB/s**.
  - Correctness/parity gate passed with no missing candidates, no extension mismatches, and no native duplicates.
  - The production Rust helper now defaults to Aho `LeftmostFirst` + no-copy overlap.
  - `ScanWorker` and UI remain untouched; Phase 4 integration is now unblocked but not performed in this phase.
- **Verification result**:
  - `cargo test`: **22 Rust tests passed** (19 library/bin unit tests + 3 protocol integration tests), 0 failed.
  - `cargo build --release`: success.
  - `python -m pytest`: **148 passed**, 0 failed.
- **Status**: Phase 3.4 complete. The native helper is now performance-eligible for Phase 4 image-only integration.

### Objective 16 / B1 Phase 4 - ScanWorker image-only native integration

- **Modified**: [app/workers/scan_worker.py](app/workers/scan_worker.py) - wired `NativeScanClient` into the real `ScanWorker` pipeline for local disk-image files only.
  - Local image detection requires a normal readable file path.
  - `PhysicalDrive`, logical volumes, VSS, drive roots, and raw `\\.\...` paths remain outside native Phase 4.
  - If `LUMINA_SCAN_ENGINE=native` is used on a non-image source, `ScanWorker` emits: **"Native engine Phase 4 supports image files only."**
- **Routing policy**:
  - `LUMINA_SCAN_ENGINE=python`: always uses the existing Python `FileCarver`; Rust is never constructed.
  - `LUMINA_SCAN_ENGINE=auto` + image file: attempts Rust native scan; on helper absence/crash/anomaly before UI commit, discards the native transaction buffer and falls back to Python `FileCarver`.
  - `LUMINA_SCAN_ENGINE=native` + image file: attempts Rust native scan; helper absence/crash/anomaly is explicit and does not silently fall back.
  - Non-image sources stay on the existing Python path unless native is forced, in which case the image-only error is emitted.
- **Transaction buffer**:
  - Native candidate batches are consumed and validated in the worker thread but are not emitted to the UI while the helper is running.
  - `files_batch_found` is emitted only after native `finished` returns cleanly.
  - If the native transaction fails before `finished`, the local native buffer is discarded.
  - Duplicate native candidates are suppressed by `(offset, signature_id)` before validation.
- **Shared validation path**:
  - [app/core/file_carver.py](app/core/file_carver.py) now exposes `signature_id()`, `native_signature_records()`, and `build_file_info_from_candidate()`.
  - Both Python regex carving and native candidate validation use the same MIME validation, extension refinement, size estimation, ftyp offset correction, dedup, naming, and `file_info` construction path.
  - Native-origin results use `source="native_carver"`; Python fallback keeps `source="carver"`.
- **Stop behavior**:
  - `ScanWorker.stop()` is passed to `NativeScanClient`, which sends the helper `stop` command.
  - If native returns `finished(stopped=true)`, already validated buffered results are committed and no fallback is attempted.
  - If an anomaly/error happens while stop is requested, the native buffer is discarded and the worker terminates cleanly without fallback.
- **Packaging**:
  - [lumina.spec](lumina.spec) now includes `native/lumina_scan/target/release/lumina_scan.exe` as `native/lumina_scan/lumina_scan.exe` when the release helper exists.
  - This matches the frozen helper resolution path used by `NativeScanClient`.
- **Tests added**:
  - [tests/test_scan_worker_native.py](tests/test_scan_worker_native.py) covers image-native routing, forced Python routing, auto fallback when helper is absent, native forced helper absence error, native forced non-image error, transaction discard before fallback, no `files_batch_found` before native `finished`, clean native stop commit, and duplicate suppression.
- **Benchmark result** (`python scripts/bench_native_carver.py --mode both --size-mb 256 --seeds 5000 --keep-image`, April 28, 2026):
  - JSON report: `benchmarks/results/native_phase3_1777380526.json`.
  - Python regex: **15,109 ms**, **16.94 MB/s**, **5,000 candidates**.
  - Native helper: **297 ms**, **861.66 MB/s**, **5,000 candidates**.
  - Native wall-clock through Python client: **424 ms**, **603.60 MB/s**.
  - `seeded_missing_native`: **0**
  - `parity_missing_vs_python`: **0**
  - `mismatched_ext`: **0**
  - `duplicates_native`: **0**
  - Gate passed.
- **Verification result**:
  - `cargo test`: **22 Rust tests passed** (19 library/bin unit tests + 3 protocol integration tests), 0 failed.
  - `cargo build --release`: success.
  - `python -m pytest`: **157 passed**, 0 failed.
- **Status**: Phase 4 image-only integration complete. Native scanning is available in the real worker for local images, while `PhysicalDrive`, VSS, and UI-visible native streaming remain intentionally out of scope.

### Chantier A — Multi-filesystem parsers (FAT32, exFAT, ext4, HFS+, APFS)

- **Context**: Parsers for FAT32 and exFAT already existed in `app/core/fs_parser.py`; ext4, HFS+, and APFS were added, and test suites were written for all five.
- **Added**: `Ext4Parser(BaseFSParser)` in `app/core/fs_parser.py`.
  - `probe()`: superblock at offset 1024, magic `0xEF53`, validates block size (1024–8192), inode size ({128,256,512}).
  - `enumerate_files()`: group descriptor table, inode table per group, extent tree (magic `0xF30A`, depth-0 leaf entries), block pointer fallback, recursive directory walk from inode 2; deleted inodes (i_dtime ≠ 0 or i_links_count = 0) → integrity 60.
  - Limitations (v1): no journal replay, no inline data, no xattrs.
- **Added**: `HFSPlusParser(BaseFSParser)` in `app/core/fs_parser.py`.
  - `probe()`: Volume Header at offset 1024, signatures `H+` (0x482B) or `HX` (0x4858), Big-Endian block size ≥ 512 and power-of-2.
  - `enumerate_files()`: locates Catalog B-Tree via Volume Header catalogFile extent record, traverses leaf nodes (kind == -1), extracts Catalog File Records (dataFork extents → data_runs).
  - Limitations (v1): no journal replay, no resource forks, no HFS+ compression.
- **Added**: `APFSParser(BaseFSParser)` in `app/core/fs_parser.py`.
  - `probe()`: NX Superblock at offset 0, magic `NXSB` at bytes 32–35, `nx_block_size ≥ 4096`.
  - `enumerate_files()`: stub — logs "APFS detected — full enumeration not implemented in v1" and returns 0; recovery uses FileCarver carving pass.
- **Updated**: `FS_PARSERS` registry: `[NTFSParser, FAT32Parser, ExFATParser, Ext4Parser, HFSPlusParser, APFSParser]`.
- **Added test files**: `tests/test_fat32_parser.py` (17 tests), `tests/test_exfat_parser.py` (12 tests), `tests/test_ext4_parser.py` (16 tests), `tests/test_hfsplus_parser.py` (13 tests), `tests/test_apfs_parser.py` (15 tests).
- **Architectural decisions validated**:
  - All parsers follow the `BaseFSParser` contract: `probe()` swallows exceptions silently (logged at DEBUG), `enumerate_files()` takes stop_flag/progress_cb/file_found_cb callbacks.
  - Registry order is specificity-first: NTFS → FAT32 → exFAT → ext4 → HFS+ → APFS.
  - APFS v1 is probe-only; full B-Tree traversal deferred (spec ~200 pages, encryption/snapshots/clones out of scope).
  - `fs` field in emitted `file_info` is always the parser's `.name` attribute (e.g. `"ext4"`, `"HFS+"`).
- **Test result**: 221 passed (all non-PyQt6 tests), 0 failed.

### Chantier F — Centralized color palette

- **Existing**: `app/ui/palette.py` already defined Win98 palette constants (`WIN98_SILVER`, `WIN98_NAVY`, etc.) and high-level aliases (`CARD`, `ACCENT`, `BEVEL_LIGHT`, `BEVEL_SHADOW`, `TEXT`, `SUB`, `MUTED`, `OK`, `WARN`, `ERR`, `HOVER`, etc.).
- **Updated**: Four screen files that still used inline hex strings were migrated to import from `palette.py`:
  - `app/ui/screen_home.py` — added 10-constant import, all 75 inline hex strings replaced with palette variable references (f-strings).
  - `app/ui/screen_scan.py` — added 11-constant import, all Win98 hex strings replaced.
  - `app/ui/screen_sd_card.py` — added 7-constant import, all inline hex replaced.
  - `app/ui/screen_results.py` — added 9-constant import; Win98 palette colors replaced; gradient colors in `_THUMB_GRAD` dict left as-is (file-type-specific, not palette colors).
- **Already imported**: `main_window.py`, `screen_partitions.py`, `screen_repair.py`, `screen_tools.py`.
- **Architectural decisions validated**:
  - `_THUMB_GRAD` gradient tuples remain as raw hex — they are per-filetype aesthetic data, not UI palette constants.
  - Palette variables imported with `as _NAME` convention (leading underscore = module-private).
  - No visual regression risk: all replaced values are byte-for-byte identical to the palette constants.
- **Test result**: 0 new tests (UI layer excluded from coverage); all 296 existing tests continue to pass.

### Chantier C1 — CLI scriptable interface

- **Added**: `app/cli/__init__.py` (empty package marker) and `app/cli/main.py`.
  - Subcommands: `scan`, `list-disks`, `recover`, `info`, `version`.
  - `scan`: synchronous (no QThread) scan using `FileCarver` + `detect_fs` + `_DedupIndex` directly; Phase 1 FS enumeration (dedup) + Phase 2 carving (deep only); `--mode quick|deep`, `--engine auto|native|python`, `--output`, `--format json|csv|dfxml`, `--report`, `--types`, `--min-size`, `--max-size`, `--no-recover`, `--hash`, `--verbose`, `--quiet`, `--progress`.
  - Output: JSONL streaming to stdout in `--format json` without `--report`; progression to stderr; exit codes 0/1/2/3.
  - `list-disks`: table or JSON output from `DiskDetector.list_disks()`.
  - `recover`: re-extracts files from a saved JSON report.
  - `info`: opens device, calls `detect_fs()`, reports FS type and file size.
  - SIGINT handled via `threading.Event` for cooperative stop.
- **Added test file**: `tests/test_cli.py` (39 tests covering parser, subcommands, emit functions, platform module).
- **Architectural decisions validated**:
  - CLI never imports PyQt6; reuses `FileCarver`, `detect_fs`, `_DedupIndex`, `DiskDetector` directly.
  - `_run_scan_sync()` is the headless equivalent of `ScanWorker._run_real()` — same logic, callback-driven, no Qt dependency.
  - Platform-aware raw device conversion via `app.core.platform.to_raw_device()`.

### Chantier B1/B2 — Platform abstraction

- **Added**: `app/core/platform.py` — OS-agnostic utilities.
  - `is_admin()`: Windows → `ctypes.windll.shell32.IsUserAnAdmin()`; POSIX → `os.geteuid() == 0`.
  - `request_elevation(script_path)`: Windows → `ShellExecuteW runas`; macOS → `osascript with administrator privileges`; Linux → logs warning with `sudo` instructions.
  - `to_raw_device(device)`: Windows → `\\.\X:`; macOS → `/dev/disk*` → `/dev/rdisk*`; Linux → unchanged.
  - `settings_dir()`: Windows → `%APPDATA%/Lumina`; macOS → `~/Library/Application Support/Lumina`; Linux → `$XDG_CONFIG_HOME/lumina`.
  - `log_dir()`: Windows → `logs/` (relative to exe); macOS → `~/Library/Logs/Lumina`; Linux → `$XDG_DATA_HOME/lumina/logs`.
  - `smart_command(disk)`: Windows → PowerShell `Get-CimInstance`; Linux/macOS → `smartctl -a --json`.
  - `fsck_command(device)`: Windows → `chkdsk /scan`; macOS → `diskutil verifyVolume`; Linux → `fsck -n`.
- **Platform tests** included in `tests/test_cli.py` (8 platform-specific tests via `unittest.mock.patch`).
- **Architectural decisions validated**:
  - No import of `ctypes` or `subprocess` at module level — only inside each function; safe on all platforms.
  - `PLATFORM = sys.platform` as a module-level constant allows easy mocking in tests.

### Chantier D1/D2 — JPEG and MP4 file repair

- **Added**: `app/core/repair/__init__.py` (empty) and `app/core/repair/jpeg_repair.py`.
  - `repair_jpeg(input_path, output_path)` → `RepairReport` dataclass.
  - Strategy 1: garbage before SOI → strip; missing SOI → prepend `FF D8`.
  - Strategy 2: marker structure walk — handles fill bytes, byte-stuffing, RST markers, SOS entropy stream scan; invalid segment length → skip to next valid marker.
  - Strategy 3: missing EOI → append `FF D9`.
  - Returns `RepairReport(original_size, repaired_size, issues_found, repaired)`.
  - `is_valid_jpeg(path)`: quick SOI + EOI presence check.
- **Added**: `app/core/repair/mp4_repair.py`.
  - `repair_mp4(input_path, output_path)` → `Mp4RepairReport`.
  - `_parse_atoms(data)`: walks top-level ISO BMFF atoms; handles 32-bit size, 64-bit extended size (`size==1`), `size==0` (extends to EOF); clamps overflowing atoms.
  - Strategy 1: if `moov` is after `mdat` → reorder: ftyp → moov → rest (fast-start).
  - Strategy 2: detect atoms with declared size > file size and report them.
  - Missing `moov`: noted in report; full moov reconstruction deferred (codec-specific, out of scope for v1).
  - `is_valid_mp4(path)`: checks for presence of `ftyp` or `moov` atoms.
- **Added test files**: `tests/test_jpeg_repair.py` (16 tests), `tests/test_mp4_repair.py` (20 tests).
- **Architectural decisions validated**:
  - stdlib-only: no Pillow, no external MP4 libraries.
  - JPEG repair never discards data outside the SOI..EOI range; SOS entropy scan uses proper stuffing/RST rules from ISO/IEC 10918-1.
  - MP4 repair does not re-mux or re-encode; it only reorders atom blobs and logs structure issues.
  - Both repair functions write to a separate output file by default (`input + ".repaired.jpg"` / `".repaired.mp4"`).
- **Test result**: 75 tests (CLI 39 + JPEG 16 + MP4 20), all pass.

### Grand total after roadmap completion

- **Test result**: **296 passed**, 0 failed (full non-PyQt6 suite).
- **New files**: `app/core/repair/__init__.py`, `app/core/repair/jpeg_repair.py`, `app/core/repair/mp4_repair.py`, `app/core/platform.py`, `app/cli/__init__.py`, `app/cli/main.py`, `tests/test_fat32_parser.py`, `tests/test_exfat_parser.py`, `tests/test_ext4_parser.py`, `tests/test_hfsplus_parser.py`, `tests/test_apfs_parser.py`, `tests/test_cli.py`, `tests/test_jpeg_repair.py`, `tests/test_mp4_repair.py`.
- **Modified files**: `app/core/fs_parser.py` (ext4/HFS+/APFS added, registry extended), `app/ui/screen_home.py`, `app/ui/screen_scan.py`, `app/ui/screen_sd_card.py`, `app/ui/screen_results.py` (palette migration).

### Update policy

Append a new section to this changelog **every time a major implementation is finished**. Keep each entry to: what was added, files touched, key architectural decisions validated.
