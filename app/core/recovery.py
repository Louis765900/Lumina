from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable

from app.core.settings import load_settings, save_settings

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOG_DIR = _ROOT / "logs"
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_MAX_LOG_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class DestinationCheck:
    destination: Path
    blocked: bool = False
    warning: bool = False
    message: str = ""


def ensure_lumina_log(log_dir: str | Path | None = None) -> Path:
    target_dir = Path(log_dir) if log_dir is not None else _DEFAULT_LOG_DIR
    log_path = target_dir / "lumina.log"
    logger = logging.getLogger("lumina")
    logger.setLevel(logging.INFO)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if not any(
            isinstance(handler, logging.FileHandler)
            and Path(getattr(handler, "baseFilename", "")) == log_path
            for handler in logger.handlers
        ):
            handler = RotatingFileHandler(
                log_path,
                maxBytes=_MAX_LOG_BYTES,
                backupCount=2,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(_LOG_FORMAT))
            logger.addHandler(handler)
    except OSError:
        if not any(isinstance(handler, logging.NullHandler) for handler in logger.handlers):
            logger.addHandler(logging.NullHandler())
    return log_path


def default_recovery_dir(settings_file: str | Path | None = None) -> str:
    return str(load_settings(settings_file)["default_recovery_dir"])


def persist_recovery_dir(destination: str | Path, settings_file: str | Path | None = None) -> None:
    settings = load_settings(settings_file)
    settings["default_recovery_dir"] = str(Path(destination))
    save_settings(settings, settings_file)


def validate_recovery_destination(
    files: Iterable[dict],
    destination: str | Path,
    *,
    create: bool = True,
) -> DestinationCheck:
    dest_raw = str(destination).strip()
    if not dest_raw:
        return DestinationCheck(Path(), blocked=True, message="Dossier de destination obligatoire.")

    dest = Path(dest_raw).expanduser()
    if dest.exists() and not dest.is_dir():
        return DestinationCheck(
            dest,
            blocked=True,
            message="La destination de récupération doit être un dossier.",
        )
    if create:
        dest.mkdir(parents=True, exist_ok=True)

    dest_resolved = _resolve(dest)
    dest_drive = _drive_key(dest_resolved)
    warning = ""

    for device in _source_devices(files):
        block, warn = _check_source_against_destination(device, dest_resolved, dest_drive)
        if block:
            return DestinationCheck(
                dest_resolved,
                blocked=True,
                message="Vous ne pouvez pas récupérer sur le disque source",
            )
        if warn and not warning:
            warning = warn

    if warning:
        return DestinationCheck(dest_resolved, warning=True, message=warning)
    return DestinationCheck(dest_resolved)


def _source_devices(files: Iterable[dict]) -> set[str]:
    return {
        str(info.get("device", "")).strip()
        for info in files
        if str(info.get("device", "")).strip()
    }


def _check_source_against_destination(
    device: str,
    dest: Path,
    dest_drive: str,
) -> tuple[bool, str]:
    logical = _logical_drive_from_device(device)
    if logical and logical == dest_drive:
        return True, ""

    if device.upper().startswith("\\\\.\\PHYSICALDRIVE"):
        return False, (
            "Lumina ne peut pas confirmer que la destination est sur un autre disque "
            "physique. Continuer peut écraser des données récupérables."
        )

    source_path = Path(device).expanduser()
    if source_path.exists():
        source_resolved = _resolve(source_path)
        source_drive = _drive_key(source_resolved)
        if source_resolved == dest:
            return True, ""
        if source_resolved.is_dir() and _is_relative_to(dest, source_resolved):
            return True, ""
        if source_resolved.is_file() and source_drive and source_drive == dest_drive:
            return False, (
                "La destination semble être sur la même lettre de lecteur que l'image source. "
                "Confirmez uniquement si cette image n'est pas le disque en cours de récupération."
            )

    return False, ""


def _logical_drive_from_device(device: str) -> str:
    value = device.strip().replace("/", "\\")
    upper = value.upper()
    if len(upper) >= 2 and upper[1] == ":" and upper.rstrip("\\") == upper[:2]:
        return upper[:2]
    for prefix in ("\\\\.\\", "\\\\?\\"):
        if upper.startswith(prefix) and len(upper) >= len(prefix) + 2:
            candidate = upper[len(prefix):len(prefix) + 2]
            if len(candidate) == 2 and candidate[1] == ":":
                return candidate
    return ""


def _drive_key(path: Path) -> str:
    drive = path.drive.upper()
    if drive:
        return drive
    anchor = path.anchor.upper()
    if len(anchor) >= 2 and anchor[1] == ":":
        return anchor[:2]
    return anchor


def _resolve(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return Path(os.path.abspath(str(path)))


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
