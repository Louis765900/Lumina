"""
Lumina — Ecran 3 : Cartes SD & Peripheriques externes (style Windows 98)
Detection automatique des peripheriques amovibles, bouton scanner.
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.disk_refresh import DiskListWorker
from app.ui.palette import (
    ACCENT as _ACCENT,
)
from app.ui.palette import (
    BEVEL_LIGHT as _BEVEL_LIGHT,
)
from app.ui.palette import (
    BEVEL_SHADOW as _BEVEL_SHADOW,
)
from app.ui.palette import (
    BORDER as _BORDER,
)
from app.ui.palette import (
    CARD as _CARD,
)
from app.ui.palette import (
    SUB as _SUB,
)
from app.ui.palette import (
    TEXT as _TEXT,
)


def _is_external(disk: dict) -> bool:
    if disk.get("removable"):
        return True
    iface = disk.get("interface", "").lower()
    model = disk.get("model", "").lower()
    return any(x in iface or x in model for x in ("usb", "sd", "removable"))


# ═══════════════════════════════════════════════════════════════════════════════
#  Carte de peripherique externe (Win98 raised frame)
# ═══════════════════════════════════════════════════════════════════════════════

class _DeviceCard(QFrame):
    scan_requested = pyqtSignal(dict)

    def __init__(self, disk: dict, parent=None):
        super().__init__(parent)
        self._disk = disk
        self.setFixedHeight(60)
        self.setStyleSheet(
            f"_DeviceCard {{"
            f"  background-color: {_CARD};"
            f"  border-top: 2px solid {_BEVEL_LIGHT};"
            f"  border-left: 2px solid {_BEVEL_LIGHT};"
            f"  border-bottom: 2px solid {_BEVEL_SHADOW};"
            f"  border-right: 2px solid {_BEVEL_SHADOW};"
            f"}}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)

        # Badge type
        badge = QLabel("USB")
        badge.setFixedSize(28, 16)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background-color: {_ACCENT}; color: {_BEVEL_LIGHT};"
            "font-size: 9px; font-weight: 700; font-family: 'Work Sans', Arial;"
        )
        lay.addWidget(badge)

        # Infos
        info = QVBoxLayout()
        info.setSpacing(2)
        name = disk.get("name", "Peripherique")
        n_lbl = QLabel(name)
        n_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 11px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )

        total    = disk.get("size_gb", 0.0)
        used     = disk.get("used_gb", 0.0)
        device   = disk.get("device", "")
        size_txt = f"{used:.1f} / {total:.1f} Go" if used > 0 else f"{total:.1f} Go"
        d_lbl = QLabel(f"{device}  |  {size_txt}")
        d_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 10px;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        info.addWidget(n_lbl)
        info.addWidget(d_lbl)
        lay.addLayout(info, stretch=1)

        # Bouton scanner
        scan_btn = QPushButton("Scanner")
        scan_btn.setFixedSize(70, 24)
        scan_btn.setCursor(Qt.CursorShape.ArrowCursor)
        scan_btn.clicked.connect(lambda: self.scan_requested.emit(self._disk))
        lay.addWidget(scan_btn)


# ═══════════════════════════════════════════════════════════════════════════════
#  Etat vide
# ═══════════════════════════════════════════════════════════════════════════════

class _EmptyState(QWidget):
    refresh_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(12)

        title = QLabel("Aucun peripherique externe detecte")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        lay.addWidget(title)

        sub = QLabel(
            "Connectez une carte SD, une cle USB ou un appareil photo,\n"
            "puis actualisez la liste."
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(
            f"color: {_SUB}; font-size: 11px;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        lay.addWidget(sub)

        btn = QPushButton("Actualiser")
        btn.setFixedSize(100, 26)
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        btn.clicked.connect(self.refresh_clicked)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)


# ═══════════════════════════════════════════════════════════════════════════════
#  Ecran carte SD
# ═══════════════════════════════════════════════════════════════════════════════

class SdCardScreen(QWidget):
    disk_selected = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_CARD};")
        self._disk_worker: DiskListWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # En-tete
        hdr = QWidget()
        hdr.setFixedHeight(40)
        hdr.setStyleSheet(
            f"background-color: {_CARD}; border-bottom: 2px solid {_BORDER};"
        )
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(8, 4, 8, 4)

        title = QLabel("Cartes SD & Peripheriques externes")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        hr.addWidget(title)
        hr.addStretch()

        self._refresh_btn = QPushButton("Actualiser")
        self._refresh_btn.setFixedSize(80, 24)
        self._refresh_btn.setToolTip("Actualiser")
        self._refresh_btn.clicked.connect(self.refresh)
        hr.addWidget(self._refresh_btn)
        root.addWidget(hdr)

        # Contenu scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background-color: {_CARD}; border: none; }}")

        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {_CARD};")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(6)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self._content)
        root.addWidget(scroll, stretch=1)

        # Auto-actualisation toutes les 5 secondes
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(5000)
        self._auto_timer.timeout.connect(self.refresh)
        self._auto_timer.start()

        self.refresh()

    def refresh(self):
        if self._disk_worker and self._disk_worker.isRunning():
            return

        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("...")
        self._clear_layout()

        self._disk_worker = DiskListWorker(self)
        self._disk_worker.loaded.connect(self._on_disks_loaded)
        self._disk_worker.finished.connect(self._on_disk_worker_finished)
        self._disk_worker.start()

    def _on_disk_worker_finished(self):
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("Actualiser")
        if self._disk_worker:
            self._disk_worker.deleteLater()
            self._disk_worker = None

    def _on_disks_loaded(self, disks: list, _error: str):
        self._clear_layout()
        self._render_disks([d for d in disks if _is_external(d)])

    def _clear_layout(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

    def _render_disks(self, disks: list):
        if not disks:
            empty = _EmptyState()
            empty.refresh_clicked.connect(self.refresh)
            self._layout.addWidget(empty)
            return

        for disk in disks:
            card = _DeviceCard(disk)
            card.scan_requested.connect(self.disk_selected)
            self._layout.addWidget(card)

        self._layout.addStretch()
