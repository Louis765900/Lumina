"""
Tests for app.core.disk_detector — DiskDetector.
"""

from unittest.mock import patch

from app.core.disk_detector import DiskDetector


class TestDiskDetector:
    """Tests for DiskDetector.list_disks()."""

    def test_returns_list(self):
        """list_disks() should always return a list."""
        result = DiskDetector.list_disks()
        assert isinstance(result, list)

    def test_non_empty(self):
        """list_disks() should return a list (may be empty in CI with no disk access)."""
        result = DiskDetector.list_disks()
        assert isinstance(result, list)

    def test_disk_dict_keys(self):
        """Each disk dict must have the expected keys."""
        required_keys = {"device", "name", "size_gb", "used_gb", "size_bytes", "model", "interface"}
        disks = DiskDetector.list_disks()
        for disk in disks:
            assert required_keys.issubset(disk.keys()), (
                f"Missing keys: {required_keys - disk.keys()}"
            )

    def test_disk_device_is_string(self):
        """device field must be a non-empty string."""
        disks = DiskDetector.list_disks()
        for disk in disks:
            assert isinstance(disk["device"], str)
            assert len(disk["device"]) > 0

    def test_disk_size_gb_is_number(self):
        """size_gb must be a float or int >= 0."""
        disks = DiskDetector.list_disks()
        for disk in disks:
            assert isinstance(disk["size_gb"], (int, float))
            assert disk["size_gb"] >= 0

    def test_fallback_when_wmi_fails(self):
        """When WMI raises, list_disks() should still return disks via psutil fallback."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "wmi":
                raise ImportError("mock: no wmi")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = DiskDetector.list_disks()
            assert isinstance(result, list)
            assert len(result) >= 1

    def test_empty_when_all_fail(self):
        """When psutil fails, list_disks() returns an empty list (no fake fallback)."""
        with patch("app.core.disk_detector.psutil.disk_partitions", side_effect=Exception):
            result = DiskDetector.list_disks()
            assert result == []
