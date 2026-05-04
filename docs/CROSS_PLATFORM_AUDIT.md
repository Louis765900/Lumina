# Cross-Platform Readiness Audit

Date: 2026-05-04. Branch: `main` @ `f30ab08`.

## Method

Static scan of `app/`, `main.py`, and `lumina.spec` for:

- direct Windows API calls (`ctypes.windll`, `ShellExecuteW`)
- Windows-only subprocess flags (`CREATE_NO_WINDOW`, `cp850` encoding)
- hardcoded executables (`powershell`, `chkdsk`, `sfc`, `dism`, `wmic`, `Get-CimInstance`)
- Windows path syntax (`\\.\X:`, `APPDATA`, drive-letter assumptions)
- bypasses of the existing `app/core/platform.py` abstraction

Result: **5 files** still hard-couple to Windows. The `platform.py`
abstraction landed in Pass 1 but was not threaded back into the older
modules. Two of those modules (`screen_repair.py`, large parts of
`screen_tools.py`) are *philosophically* Windows-only — the tools they
expose (CHKDSK / SFC / DISM) have no clean Linux/macOS equivalent.

---

## Findings

### 1. `main.py` — UAC entry point

```python
def _is_admin() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())  # NameError on POSIX

def _request_elevation():
    ctypes.windll.shell32.ShellExecuteW(...)             # NameError on POSIX
```

**Severity:** blocker. `ctypes.windll` does not exist on macOS/Linux —
`main.py` would crash at import.

**Fix:** delete the local helpers, use
`from app.core.platform import is_admin, request_elevation` (already
written, already tested).

**Effort:** 5 min.

### 2. `app/workers/scan_worker.py` — duplicate `_to_raw_device`

```python
def _to_raw_device(device: str) -> str:           # private, Windows-only
    if dev.startswith("\\\\.\\") or ...:
    if len(dev) >= 2 and dev[1] == ":":
        return f"\\\\.\\{dev[0].upper()}:"
    raise ValueError(...)
```

**Severity:** medium. Real-disk scans on macOS/Linux currently raise
`ValueError("Chemin invalide")`. Image-file scans still work because the
function is bypassed for `_is_local_image_source(...)`.

**Fix:** delete the private function, use
`from app.core.platform import to_raw_device`.

**Effort:** 10 min.

### 3. `app/core/settings.py` — Windows-only `settings_dir`

```python
def settings_dir(env=None):
    appdata = values.get("APPDATA")
    if appdata:
        return Path(appdata) / "Lumina"
    return Path.home() / "AppData" / "Roaming" / "Lumina"   # garbage on POSIX
```

**Severity:** medium. On Linux/macOS the fallback puts settings under
`~/AppData/Roaming/Lumina/` — works (creates a folder with that literal
name) but violates platform conventions.

**Fix:** delegate to `app.core.platform.settings_dir()` which already
implements the right paths (`~/Library/Application Support/Lumina` on
macOS, `$XDG_CONFIG_HOME/lumina` on Linux). The `env` mapping argument
needs preserved for the existing tests, so wrap rather than replace.

**Effort:** 20 min (need to keep settings.py tests green).

### 4. `app/ui/screen_tools.py` — `_SmartWorker` hardcodes PowerShell

```python
ps_cmd = "Get-CimInstance Win32_DiskDrive | ConvertTo-Json -Depth 2"
subprocess.check_output(
    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
    creationflags=subprocess.CREATE_NO_WINDOW,
    ...
)
```

**Severity:** medium. The SMART card hangs on POSIX (powershell.exe
not on PATH). `app/core/platform.smart_command(disk)` already returns
`["smartctl", "-a", disk, "--json"]` for non-Windows.

**Fix:** call `smart_command(disk)`, parse the smartctl JSON output
(different schema from `Get-CimInstance`). On platforms without
smartctl, surface an actionable message ("Install smartmontools").

**Effort:** 1.5h — schema differs significantly between PowerShell's
`Win32_DiskDrive` (Caption / SerialNumber / Size / InterfaceType /
MediaType / FirmwareRevision / Partitions) and smartctl's `--json`
output. Need a normaliser.

### 5. `app/ui/screen_repair.py` — CHKDSK / SFC / DISM are Windows-only by design

```python
def _run_chkdsk(self): self._run_cmd(["chkdsk", drive, "/scan"])
def _run_sfc(self):    self._run_cmd(["sfc", f"/{mode}"])
def _run_dism(self):   self._run_cmd(["dism", "/Online", "/Cleanup-Image", f"/{op}"])
```

Plus `subprocess.Popen(..., encoding="cp850", creationflags=CREATE_NO_WINDOW)`
which is Windows-codepage-specific.

**Severity:** philosophical. SFC and DISM **have no equivalent** on
macOS/Linux — they repair Windows system files and the Windows component
store. Chkdsk has a partial analog (`fsck`) but the UX doesn't translate.

**Fix options:**

- **A.** On macOS/Linux, hide the entire screen or replace with a
  read-only "Etat du disque" using `smartctl -H` + `df -h`. Users can
  still run real `fsck` from a terminal.
- **B.** Replace CHKDSK card with `fsck` (call via
  `platform.fsck_command()`), drop SFC/DISM cards entirely on POSIX.

**Effort:** 2-3h for option B (UI restructure + command worker
abstraction); option A is faster (~45 min) but lower-value.

---

## Cross-platform-clean modules (no changes needed)

- `app/core/disk_detector.py` — psutil-only, works everywhere.
- `app/core/file_carver.py` — pure Python, OS-agnostic.
- `app/core/fs_parser.py` — all parsers use `os.lseek`/`os.read`,
  endian-correct, no platform branches.
- `app/core/repair/{jpeg,mp4}_repair.py` — stdlib bytes ops.
- `app/core/native/client.py` — already guards `CREATE_NO_WINDOW`
  behind `os.name == "nt"`. Helper binary is the only platform-specific
  asset.
- `app/cli/main.py` — uses `app.core.platform.to_raw_device`.

## Native helper

`native/lumina_scan/` builds with `cargo build --release`. Output
binary name differs: `lumina_scan.exe` on Windows, `lumina_scan` on
POSIX. The Python `NativeScanClient` needs to discover both, and the
PyInstaller spec needs to bundle the right one — this is a packaging
detail, not a code-path issue.

---

## Effort estimate for "Lumina runs on macOS/Linux without crashing"

| Fix                                 | Effort | Severity   |
|-------------------------------------|--------|------------|
| 1. main.py UAC helpers              | 5 min  | blocker    |
| 2. scan_worker._to_raw_device       | 10 min | medium     |
| 3. settings.settings_dir            | 20 min | medium     |
| 4. screen_tools SMART               | 1.5h   | medium     |
| 5. screen_repair CHKDSK/SFC/DISM    | 2-3h   | UX rewrite |
| Total minimum (1+2+3 only)          | ~35 min| 🟢 launchable |
| Total recommended (1+2+3+5-A)       | ~1.5h  | 🟡 usable  |
| Total full (1+2+3+4+5-B)            | ~4-5h  | 🟢 polished |

**Verdict:** A is **cheap** for "doesn't crash on import" (35 min, 3
files). A is **medium** for "S.M.A.R.T. and disk health work" (~5h
total). PyInstaller specs for macOS / Linux + `.app` bundle + `.desktop`
file = on top of that, ~3h.

**Recommendation:** Land fixes 1-3 immediately as a single commit
("don't crash on import") regardless of whether full A ships. They are
trivial, already-tested by the platform.py unit tests, and they unblock
running the test suite on macOS/Linux CI.

Then choose: (a) ship a Windows-only v1.0.0 (status quo) and start C
features, or (b) commit ~1 day to a real cross-platform v1.1.0.
