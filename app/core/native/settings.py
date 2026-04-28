from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

ScanEngine = Literal["auto", "python", "native"]

_log = logging.getLogger("lumina.native")
_VALID_ENGINES: set[str] = {"auto", "python", "native"}


def get_scan_engine(
    env: Mapping[str, str] | None = None,
    settings_file: str | Path | None = None,
) -> ScanEngine:
    values = env if env is not None else os.environ
    env_raw = values.get("LUMINA_SCAN_ENGINE")
    if env_raw is not None:
        raw = env_raw.strip().lower()
        if raw in _VALID_ENGINES:
            return raw  # type: ignore[return-value]

        _log.warning(
            "Invalid LUMINA_SCAN_ENGINE=%r; falling back to 'auto'. "
            "Expected one of: auto, python, native.",
            env_raw,
        )
        return "auto"

    try:
        from app.core.settings import load_settings

        raw = str(load_settings(settings_file).get("scan_engine", "auto")).strip().lower()
        if raw in _VALID_ENGINES:
            return raw  # type: ignore[return-value]
    except Exception as exc:  # pragma: no cover - settings fallback is deliberately defensive
        _log.warning("Cannot load persisted scan engine; falling back to 'auto': %s", exc)

    return "auto"
