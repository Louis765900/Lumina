# Lumina optional modules

Lumina V2 keeps the recovery core stable and adds premium capabilities through
optional modules under `app/modules`.

Implemented now:

- `storage-index`: SQLite database with FTS5 search for scan results.
- `integrity-score`: conservative recoverability scoring enrichment.
- `search-filters`: shared filtering and sorting engine for CLI/UI result sets.
- `reporting-suite`: shared JSON, CSV, DFXML, and HTML report emitters.
- `disk-health`: read-only disk health collection with optional `smartctl`.

Registered for later, disabled by default:

- `core-scan-engine`
- `rescue-imaging`
- `filesystem-analyzers`
- `evidence-readers`
- `file-identification`
- `metadata-extraction`
- `preview-engine`
- `security-scan`
- `hash-dedup`
- `forensic-chain`
- `premium-ui`
- `smart-recovery`
- `windows-deep-recovery`
- `format-validators`
- `content-intelligence`
- `timeline`
- `observability`
- `quality-lab`
- `release-engine`
- `plugin-sdk`
- `help-center`
- `local-assistant`

Feature flags:

- Disable one module: `LUMINA_DISABLE_STORAGE_INDEX=1`
- Disable many modules: `LUMINA_MODULES_DISABLED=storage-index,disk-health`
- Enable an implemented module explicitly: `LUMINA_MODULE_REPORTING_SUITE=1`
- Settings file override:

```json
{
  "modules": {
    "storage-index": { "enabled": false },
    "disk-health": true
  }
}
```

All current implementations use Python standard-library dependencies only.
`disk-health` uses `smartctl` only when it is already present on PATH or when
`LUMINA_SMARTCTL_PATH` points to it; otherwise Windows falls back to read-only
CIM data. PyInstaller specs collect `app.modules` explicitly so optional module
imports remain available in frozen builds.
