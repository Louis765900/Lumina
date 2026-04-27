from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Literal

ScanEngine = Literal["auto", "python", "native"]

_log = logging.getLogger("lumina.native")
_VALID_ENGINES: set[str] = {"auto", "python", "native"}


def get_scan_engine(env: Mapping[str, str] | None = None) -> ScanEngine:
    values = env if env is not None else os.environ
    raw = values.get("LUMINA_SCAN_ENGINE", "auto").strip().lower()
    if raw in _VALID_ENGINES:
        return raw  # type: ignore[return-value]

    _log.warning(
        "Invalid LUMINA_SCAN_ENGINE=%r; falling back to 'auto'. "
        "Expected one of: auto, python, native.",
        values.get("LUMINA_SCAN_ENGINE"),
    )
    return "auto"
