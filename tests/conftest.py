"""
Lumina — Shared pytest fixtures.
"""

import pytest


@pytest.fixture(scope="session")
def qapp():
    """
    Application instance shared across the test session.

    Tests in this suite mix two needs:
      - QThread signal tests (no display) — happy with QCoreApplication.
      - Widget tests (ScanScreen, SetupWizard, ...) — require a real
        QApplication. Creating a QWidget with only a QCoreApplication
        previously caused open-ended hangs on Windows.

    A QApplication satisfies both. On headless CI the offscreen platform
    plugin keeps it from touching a real display; if PyQt6 widgets are
    not available at all, falling back to QCoreApplication keeps the
    QThread tests usable.
    """
    try:
        from PyQt6.QtWidgets import QApplication
    except (ImportError, OSError):
        from PyQt6.QtCore import QCoreApplication

        existing = QCoreApplication.instance()
        if existing is not None:
            yield existing
            return
        yield QCoreApplication([])
        return

    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return
    yield QApplication([])


@pytest.fixture
def sample_disk() -> dict:
    """A typical internal disk as returned by DiskDetector.list_disks()."""
    return {
        "device": "C:",
        "name": "Disque Local (C:)",
        "size_gb": 465.8,
        "used_gb": 210.5,
        "size_bytes": 500_107_862_016,
        "model": "Volume NTFS",
        "interface": "SATA/NVMe",
    }


@pytest.fixture
def sample_usb_disk() -> dict:
    """A removable USB disk as returned by DiskDetector.list_disks()."""
    return {
        "device": "D:",
        "name": "Disque Local (D:)",
        "size_gb": 14.5,
        "used_gb": 3.2,
        "size_bytes": 15_518_924_800,
        "model": "Volume FAT32",
        "interface": "USB",
        "removable": True,
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
            "device": "C:",
            "integrity": 95,
            "source": "carver",
        },
        {
            "name": "recovered_png_0001.png",
            "type": "PNG",
            "offset": 5_242_880,
            "size_kb": 768,
            "device": "C:",
            "integrity": 100,
            "source": "carver",
        },
        {
            "name": "recovered_pdf_0001.pdf",
            "type": "PDF",
            "offset": 10_485_760,
            "size_kb": 512,
            "device": "C:",
            "integrity": 75,
            "source": "mft",
        },
    ]
