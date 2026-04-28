# Lumina

Lumina is a Windows-first data recovery application built with PyQt6.

## Product V1 Rules

- Normal user flows must never show fake or generated recovery results.
- Quick Scan is reserved for real filesystem metadata recovery. In Product V1 it supports NTFS MFT metadata only; unsupported sources report that Quick Scan is unavailable and offer Deep Scan.
- Deep Scan performs carving. Local disk images can use the Rust native scanner; other sources use the compatible Python engine.
- The legacy demo scan is hidden behind `LUMINA_ENABLE_DEMO=1` for development only.

## Settings

Lumina stores persistent settings at:

```text
%APPDATA%/Lumina/settings.json
```

Current settings include language, default recovery directory, scan engine, image-first preference, disclaimer acceptance, and first-launch state.

## First Launch

When `first_launch_done` is false or the recovery disclaimer has not been accepted, Lumina opens a setup wizard before the Home screen. The wizard collects language, default recovery folder, scan engine, image-first preference, and the mandatory recovery warning.
