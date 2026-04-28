# Lumina

Lumina is a Windows-first data recovery application built with PyQt6.

## Product V1 Rules

- Normal user flows must never show fake or generated recovery results.
- Quick Scan is reserved for real filesystem metadata recovery. Until the real metadata path is available for a source, Lumina reports that Quick Scan is unavailable and offers Deep Scan.
- Deep Scan performs carving. Local disk images can use the Rust native scanner; other sources use the compatible Python engine.
- The legacy demo scan is hidden behind `LUMINA_ENABLE_DEMO=1` for development only.

## Settings

Lumina stores persistent settings at:

```text
%APPDATA%/Lumina/settings.json
```

Current settings include language, default recovery directory, scan engine, image-first preference, disclaimer acceptance, and first-launch state.
