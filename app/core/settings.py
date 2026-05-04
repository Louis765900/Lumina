from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_log = logging.getLogger("lumina.settings")

VALID_LANGUAGES = {"fr", "en"}
VALID_SCAN_ENGINES = {"auto", "python", "native"}


def _default_recovery_dir() -> str:
    return str(Path.home() / "Lumina Recovery")


def default_settings() -> dict[str, Any]:
    return {
        "language": "fr",
        "default_recovery_dir": _default_recovery_dir(),
        "scan_engine": "auto",
        "prefer_image_first": True,
        "accepted_disclaimer": False,
        "first_launch_done": False,
    }


def settings_dir(env: Mapping[str, str] | None = None) -> Path:
    """
    Resolve the per-user settings directory.

    With ``env`` supplied (test path), keep the legacy Windows-shaped
    lookup so existing tests can drive APPDATA explicitly. With no
    ``env`` argument, defer to the shared cross-platform implementation
    in :mod:`app.core.platform` which honours XDG on Linux,
    ``Library/Application Support`` on macOS, and ``%APPDATA%`` on
    Windows.
    """
    if env is not None:
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata) / "Lumina"
        return Path.home() / "AppData" / "Roaming" / "Lumina"
    from app.core.platform import settings_dir as _platform_settings_dir

    return Path(_platform_settings_dir())


def settings_path(env: Mapping[str, str] | None = None) -> Path:
    return settings_dir(env) / "settings.json"


def validate_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    settings = default_settings()
    if not isinstance(raw, Mapping):
        return settings

    language = raw.get("language")
    if isinstance(language, str) and language.strip().lower() in VALID_LANGUAGES:
        settings["language"] = language.strip().lower()

    recovery_dir = raw.get("default_recovery_dir")
    if isinstance(recovery_dir, str) and recovery_dir.strip():
        settings["default_recovery_dir"] = recovery_dir.strip()

    scan_engine = raw.get("scan_engine")
    if isinstance(scan_engine, str) and scan_engine.strip().lower() in VALID_SCAN_ENGINES:
        settings["scan_engine"] = scan_engine.strip().lower()

    prefer_image_first = raw.get("prefer_image_first")
    if isinstance(prefer_image_first, bool):
        settings["prefer_image_first"] = prefer_image_first

    accepted_disclaimer = raw.get("accepted_disclaimer")
    if isinstance(accepted_disclaimer, bool):
        settings["accepted_disclaimer"] = accepted_disclaimer

    first_launch_done = raw.get("first_launch_done")
    if isinstance(first_launch_done, bool):
        settings["first_launch_done"] = first_launch_done

    return settings


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else settings_path()
    try:
        with target.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return default_settings()
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("Cannot read Lumina settings at %s; using defaults: %s", target, exc)
        return default_settings()

    return validate_settings(raw)


def save_settings(settings: Mapping[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    validated = validate_settings(settings)
    target = Path(path) if path is not None else settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(validated, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(target)
    return validated


def is_demo_enabled(env: Mapping[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    return values.get("LUMINA_ENABLE_DEMO", "").strip() == "1"
