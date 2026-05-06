"""Read-only disk health collection with optional smartctl support."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any

from app.core.platform import PLATFORM
from app.modules.registry import is_module_enabled

_log = logging.getLogger("lumina.modules.disk_health")


def _creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if PLATFORM == "win32" else 0


def smartctl_path(env: Mapping[str, str] | None = None) -> str | None:
    values = env if env is not None else os.environ
    configured = values.get("LUMINA_SMARTCTL_PATH")
    if configured:
        return configured
    return shutil.which("smartctl")


def _run_json(cmd: list[str], timeout: int = 20) -> Any:
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creationflags(),
        timeout=timeout,
        check=False,
    )
    if completed.returncode not in {0, 2}:
        raise RuntimeError((completed.stderr or completed.stdout or "command failed").strip())
    payload = (completed.stdout or "").strip()
    return json.loads(payload) if payload else {}


def _smartctl_devices(smartctl: str) -> list[str]:
    try:
        data = _run_json([smartctl, "--scan-open", "--json"], timeout=15)
    except Exception as exc:
        _log.debug("smartctl scan failed: %s", exc)
        return []
    devices = data.get("devices", []) if isinstance(data, dict) else []
    return [str(item.get("name")) for item in devices if item.get("name")]


def _normalize_smartctl(data: dict[str, Any], device: str) -> dict[str, str]:
    smart_status = data.get("smart_status") if isinstance(data.get("smart_status"), dict) else {}
    passed = smart_status.get("passed")
    status = "OK" if passed is True else ("FAIL" if passed is False else "Unknown")
    capacity = data.get("user_capacity") if isinstance(data.get("user_capacity"), dict) else {}
    device_info = data.get("device") if isinstance(data.get("device"), dict) else {}
    temperature = data.get("temperature") if isinstance(data.get("temperature"), dict) else {}
    power_on = data.get("power_on_time") if isinstance(data.get("power_on_time"), dict) else {}

    return {
        "Caption": str(data.get("model_name") or device_info.get("name") or device),
        "SerialNumber": str(data.get("serial_number") or "-").strip(),
        "Status": status,
        "Size": str(capacity.get("bytes") or 0),
        "InterfaceType": str(data.get("protocol") or device_info.get("type") or "-"),
        "MediaType": str(data.get("rotation_rate") or data.get("form_factor") or "-"),
        "FirmwareRevision": str(data.get("firmware_version") or "-").strip(),
        "Partitions": "-",
        "PredictFailure": "TRUE" if passed is False else "FALSE",
        "HealthSource": "smartctl",
        "Device": device,
        "Temperature": str(temperature.get("current") or "-"),
        "PowerOnHours": str(power_on.get("hours") or "-"),
    }


def _collect_smartctl(device: str | None, smartctl: str) -> list[dict[str, str]]:
    devices = [device] if device else _smartctl_devices(smartctl)
    results: list[dict[str, str]] = []
    for dev in devices:
        if not dev:
            continue
        try:
            data = _run_json([smartctl, "-a", dev, "--json"], timeout=25)
            if isinstance(data, dict):
                results.append(_normalize_smartctl(data, dev))
        except Exception as exc:
            _log.debug("smartctl health read failed for %s: %s", dev, exc)
    return results


def _collect_windows_cim() -> list[dict[str, str]]:
    ps_cmd = (
        "Get-CimInstance Win32_DiskDrive | "
        "Select-Object Caption,SerialNumber,Status,Size,"
        "InterfaceType,MediaType,FirmwareRevision,Partitions | "
        "ConvertTo-Json -Depth 2"
    )
    data = _run_json(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
        timeout=20,
    )
    if isinstance(data, dict):
        rows = [data]
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    disks: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        caption = str(row.get("Caption") or "-")
        if caption == "-":
            continue
        disks.append(
            {
                "Caption": caption,
                "SerialNumber": str(row.get("SerialNumber") or "-").strip(),
                "Status": str(row.get("Status") or "Unknown"),
                "Size": str(row.get("Size") or 0),
                "InterfaceType": str(row.get("InterfaceType") or "-"),
                "MediaType": str(row.get("MediaType") or "-"),
                "FirmwareRevision": str(row.get("FirmwareRevision") or "-").strip(),
                "Partitions": str(row.get("Partitions") or "-"),
                "PredictFailure": "FALSE",
                "HealthSource": "windows-cim",
            }
        )
    return disks


def collect_disk_health(
    device: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Collect read-only disk health. smartctl is used when available."""

    if not is_module_enabled("disk-health", env=env):
        raise RuntimeError("disk-health module is disabled")

    smartctl = smartctl_path(env)
    if smartctl:
        smart_results = _collect_smartctl(device, smartctl)
        if smart_results:
            return smart_results

    if PLATFORM == "win32":
        return _collect_windows_cim()
    return []
