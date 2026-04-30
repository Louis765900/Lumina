"""
Lumina — Shared pytest fixtures.
"""

import pytest


@pytest.fixture
def sample_disk() -> dict:
    """A sample disk dictionary as returned by DiskDetector."""
    return {
        "device": r"\\.\PhysicalDrive0",
        "name": "Samsung SSD 970 EVO",
        "size_gb": 465.8,
        "size_bytes": 500_107_862_016,
        "model": "Samsung SSD 970 EVO 500GB",
        "interface": "SCSI",
    }


@pytest.fixture
def sample_usb_disk() -> dict:
    """A sample USB disk dictionary."""
    return {
        "device": r"\\.\PhysicalDrive1",
        "name": "Kingston DataTraveler",
        "size_gb": 14.5,
        "size_bytes": 15_518_924_800,
        "model": "Kingston DataTraveler 3.0 USB Device",
        "interface": "USB",
    }


@pytest.fixture
def sample_found_files() -> list[dict]:
    """Sample list of recovered file dicts matching the file_info schema."""
    return [
        {
            "name": "recovered_jpg_0001.jpg",
            "type": "JPG",
            "offset": 1_048_576,
            "size_kb": 2048,
            "device": r"\\.\PhysicalDrive0",
            "integrity": 95,
            "source": "carver",
        },
        {
            "name": "recovered_png_0001.png",
            "type": "PNG",
            "offset": 5_242_880,
            "size_kb": 768,
            "device": r"\\.\PhysicalDrive0",
            "integrity": 100,
            "source": "carver",
        },
        {
            "name": "recovered_pdf_0001.pdf",
            "type": "PDF",
            "offset": 10_485_760,
            "size_kb": 512,
            "device": r"\\.\PhysicalDrive0",
            "integrity": 75,
            "source": "mft",
        },
    ]
