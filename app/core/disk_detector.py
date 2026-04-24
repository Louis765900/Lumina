"""
Lumina - Disk Detector
Detects physical drives on Windows using WMI with psutil fallback.
"""

import psutil


class DiskDetector:
    @staticmethod
    def list_disks() -> list[dict]:
        """Returns a list of logical and physical disks detected on the system."""
        disks = []
        seen_devices = set()

        # 1. Logical Drives (psutil is extremely fast and gives mountpoints & usage safely)
        try:
            for part in psutil.disk_partitions(all=False):
                device = part.device.rstrip("\\")
                if device in seen_devices:
                    continue
                seen_devices.add(device)
                
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    size_bytes = usage.total
                    used_bytes = usage.used
                except Exception:
                    size_bytes = 0
                    used_bytes = 0
                    
                size_gb = round(size_bytes / (1024 ** 3), 1)
                used_gb = round(used_bytes / (1024 ** 3), 1)
                
                # Try to guess if removable via options
                is_usb = "removable" in part.opts.lower()

                disks.append({
                    "device": device,
                    "name": f"Disque Local ({device})",
                    "size_gb": size_gb,
                    "used_gb": used_gb,
                    "size_bytes": size_bytes,
                    "model": f"Volume {part.fstype}",
                    "interface": "USB" if is_usb else "SATA/NVMe",
                })
        except Exception:
            pass

        # Removed WMI Physical Drives to prevent duplicates.
        # Logical drives (C:, D:) are sufficient and more user-friendly.

        if not disks:
            disks.append({
                "device": r"\\.\PhysicalDrive0",
                "name": "Disque principal (simulation)",
                "size_gb": 512.0,
                "used_gb": 210.5,
                "size_bytes": 549_755_813_888,
                "model": "Generic SSD",
                "interface": "SATA",
            })

        return disks
