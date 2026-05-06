from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.disk_detector import DiskDetector


class DiskListWorker(QThread):
    loaded = pyqtSignal(list, str)

    def run(self) -> None:
        try:
            self.loaded.emit(DiskDetector.list_disks(), "")
        except Exception as exc:
            self.loaded.emit([], str(exc))
