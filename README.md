# Lumina v1.0.0

Lumina is a Windows-first data recovery application for scanning disks, volumes, and local disk images. It focuses on real recovery paths only: no fake results are shown in the normal product flow.

## What Lumina Does

- Quick Scan: reads NTFS metadata from the MFT when the source supports it.
- Deep Scan: performs file carving for common formats including JPEG, PNG, PDF, ZIP/Office, MP4/MOV, and SQLite.
- Native image scan: uses the bundled Rust scanner for fast signature discovery on local disk images.
- Python compatibility scan: keeps the portable Python engine available for sources not yet supported by the native helper.
- Recovery safety: blocks recovery to a detected source volume and warns when the destination is ambiguous.
- Reports and provenance: keeps DFXML/export support, SHA-256 after extraction, source provenance, and integrity metadata.

## Important Limits

- Recovery is never guaranteed.
- SSDs with TRIM enabled may erase deleted data before Lumina can recover it.
- Quick Scan currently supports NTFS MFT metadata only.
- FAT32, exFAT, ext4, and APFS metadata parsing are not part of v1.0.0.
- Physical drives still use the compatible Python deep scan path; the native helper is image-only in v1.0.0.
- Damaged media should be imaged before deep scanning whenever possible.

## Disclaimer

Do not install Lumina on the disk you want to recover. Do not recover files to the source disk. If the data is important, create a byte-to-byte image first and scan the image. The user is responsible for choosing a safe recovery destination.

## Installation

Build the Windows executable with:

```powershell
python -m PyInstaller lumina.spec --noconfirm
```

The executable is generated at:

```text
dist/Lumina.exe
```

Run Lumina as Administrator. Windows raw disk access requires elevated privileges.

## First Launch

On first launch, Lumina opens a setup wizard before Home. The wizard asks for:

- language: French or English;
- default recovery folder;
- scan engine: auto, native, or Python;
- image-first preference;
- mandatory recovery disclaimer acceptance.

Settings are stored locally at:

```text
%APPDATA%/Lumina/settings.json
```

## Logs

Runtime logs are written to:

```text
logs/lumina.log
```

Logs rotate automatically when they exceed 5 MB.
