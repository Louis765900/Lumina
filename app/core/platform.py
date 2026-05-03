"""
Lumina — Platform abstraction layer.

Provides OS-agnostic access to:
  - Admin/root privilege detection and elevation
  - Raw device path conversion
  - Settings and log directory resolution
  - Disk listing (supplements psutil)
  - SMART data command selection

Supported platforms: win32, darwin, linux
"""
from __future__ import annotations

import logging
import os
import sys

_log = logging.getLogger("lumina.recovery")

PLATFORM = sys.platform  # "win32" | "darwin" | "linux"


def is_admin() -> bool:
    """Return True if the process has administrative/root privileges."""
    if PLATFORM == "win32":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    # POSIX (Linux + macOS)
    return os.geteuid() == 0


def request_elevation(script_path: str) -> None:
    """
    Re-launch the current process with elevated privileges.
    On Windows: ShellExecuteW runas.
    On macOS: osascript with administrator privileges dialog.
    On Linux: advise the user to run with sudo/pkexec (no auto-relaunch).
    """
    if PLATFORM == "win32":
        import ctypes
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, script_path, None, 1
        )
    elif PLATFORM == "darwin":
        import subprocess
        apple_script = (
            f'do shell script "python3 {script_path}" with administrator privileges'
        )
        subprocess.Popen(["osascript", "-e", apple_script])
    else:
        # Linux — cannot auto-elevate GUI apps; log a message
        _log.warning(
            "[platform] Root required. Re-run with: sudo %s %s",
            sys.executable, script_path,
        )


def to_raw_device(device: str) -> str:
    """
    Convert a user-facing device path to the OS-specific raw device path.

    Windows: "C:" -> "\\\\.\\C:"
    Linux:   "/dev/sda" -> "/dev/sda" (unchanged)
    macOS:   "/dev/disk0" -> "/dev/rdisk0" (raw character device)
    """
    dev = device.strip()
    if PLATFORM == "win32":
        if dev.startswith("\\\\.\\") or dev.startswith("\\\\?\\"):
            return dev
        if len(dev) >= 2 and dev[1] == ":":
            return f"\\\\.\\{dev[0].upper()}:"
        if dev.startswith("\\\\"):
            return dev
        raise ValueError(f"Invalid Windows device path: {dev!r}")
    elif PLATFORM == "darwin":
        # Prefer /dev/rdisk* (raw) over /dev/disk* (buffered)
        if dev.startswith("/dev/disk"):
            return dev.replace("/dev/disk", "/dev/rdisk", 1)
        return dev
    else:
        # Linux — path is already the raw device
        return dev


def settings_dir() -> str:
    """Return the platform-appropriate directory for Lumina settings."""
    if PLATFORM == "win32":
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(appdata, "Lumina")
    elif PLATFORM == "darwin":
        return os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", "Lumina"
        )
    else:
        # Linux — XDG Base Directory spec
        xdg = os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))
        return os.path.join(xdg, "lumina")


def log_dir() -> str:
    """Return the platform-appropriate directory for Lumina logs."""
    if PLATFORM == "win32":
        # Relative to executable (existing behaviour)
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "logs",
        )
    elif PLATFORM == "darwin":
        return os.path.join(
            os.path.expanduser("~"), "Library", "Logs", "Lumina"
        )
    else:
        xdg_data = os.environ.get(
            "XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")
        )
        return os.path.join(xdg_data, "lumina", "logs")


def smart_command(disk_device: str) -> list[str]:
    """
    Return the shell command to retrieve S.M.A.R.T. data for *disk_device*.
    Returns an empty list if no supported tool is available.
    """
    if PLATFORM == "win32":
        return [
            "powershell", "-Command",
            "Get-CimInstance Win32_DiskDrive | ConvertTo-Json",
        ]
    else:
        # smartctl (smartmontools) — available on Linux and macOS
        return ["smartctl", "-a", disk_device, "--json"]


def fsck_command(device: str) -> list[str]:
    """Return the filesystem check command for the given device."""
    if PLATFORM == "win32":
        # Extract drive letter from device like "C:" or "\\\\.\\C:"
        if len(device) >= 2 and device[1] == ":":
            letter = device[0].upper()
        elif device.startswith("\\\\.\\") and len(device) >= 6:
            letter = device[4].upper()
        else:
            letter = device[0].upper() if device else "C"
        return ["chkdsk", f"{letter}:", "/scan"]
    elif PLATFORM == "darwin":
        dev = to_raw_device(device) if not device.startswith("/dev/rdisk") else device
        return ["diskutil", "verifyVolume", dev]
    else:
        return ["fsck", "-n", device]
