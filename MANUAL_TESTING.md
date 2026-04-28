# Lumina v1.0.0 Manual Testing

Use this checklist before distributing a build.

## 1. Launch

- Start `dist/Lumina.exe` as Administrator.
- Confirm no Python traceback or console appears.
- Confirm first-launch wizard appears when settings are absent.
- Complete the wizard and confirm Home opens.

## 2. Settings Persistence

- Close Lumina.
- Reopen Lumina.
- Confirm the wizard does not reappear after disclaimer acceptance.
- Confirm `%APPDATA%/Lumina/settings.json` exists.

## 3. Scan Image

- Select a local disk image.
- Run Deep Scan.
- Confirm the status shows `Moteur natif rapide` when the helper is available.
- Confirm results contain real files only and no simulated/demo entries.

## 4. Scan Disk Or Volume

- Select a logical volume or physical source.
- Run Deep Scan.
- Confirm the status shows `Moteur compatible Python` when native image scanning is not applicable.
- Confirm the UI remains responsive during scan.

## 5. Quick Scan

- Run Quick Scan on an NTFS-compatible source.
- Confirm results have `source=mft` metadata provenance.
- Run Quick Scan on an unsupported source.
- Confirm Lumina shows `Scan rapide non disponible pour cette source` and does not show fake results.

## 6. Cancel Scan

- Start a deep scan.
- Click cancel.
- Confirm Lumina returns safely without a crash.

## 7. Extraction Safety

- Select one or more recovered files.
- Try recovering to the detected source volume.
- Confirm Lumina blocks extraction with `Vous ne pouvez pas récupérer sur le disque source`.
- Recover to a separate folder.
- Confirm the folder is created if missing.
- Confirm extracted files are written and the last folder is remembered.

## 8. Logs

- Open `logs/lumina.log`.
- Confirm scan engine, source, destination, recovered counts, and errors are logged.
- Confirm the app still launches if `logs` is temporarily read-only or unavailable.

## 9. Packaging

- Confirm `dist/Lumina.exe` exists.
- Confirm the bundle includes:
  - `native/lumina_scan/lumina_scan.exe`;
  - `app/plugins/carvers`;
  - `app/ui/styles.qss`;
  - `lumina.ico`.
