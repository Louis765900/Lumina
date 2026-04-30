"""
Lumina v2.0 — Écran 3 : Cartes SD & Périphériques externes
Détection automatique des périphériques amovibles, bouton scanner.
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor
from PyQt6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.core.disk_detector import DiskDetector

from app.ui.palette import (
    ACCENT as _ACCENT,
    BORDER as _BORDER,
    CARD as _CARD,
    HOVER as _HOVER,
    MUTED as _MUTED,
    OK as _OK,
    SUB as _SUB,
    TEXT as _TEXT,
    WARN as _WARN,
)


def _is_external(disk: dict) -> bool:
    if disk.get("removable"):
        return True
    iface = disk.get("interface", "").lower()
    model = disk.get("model", "").lower()
    return any(x in iface or x in model for x in ("usb", "sd", "removable"))


# ═══════════════════════════════════════════════════════════════════════════════
#  Carte de périphérique externe
# ═══════════════════════════════════════════════════════════════════════════════

class _DeviceCard(QFrame):
    scan_requested = pyqtSignal(dict)

    def __init__(self, disk: dict, parent=None):
        super().__init__(parent)
        self._disk = disk
        self.setFixedHeight(90)
        self.setStyleSheet(
            f"_DeviceCard {{ background: {_CARD}; border: 1px solid {_BORDER};"
            "border-radius: 12px; }}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(16)

        # Icône
        ico = QLabel("💳")
        ico.setFixedSize(40, 40)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            "font-size: 20px; background: rgba(168,85,247,0.15); border-radius: 8px;"
        )
        lay.addWidget(ico)

        # Infos
        info = QVBoxLayout()
        info.setSpacing(4)
        name = disk.get("name", "Périphérique")
        n_lbl = QLabel(name)
        n_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: 600;"
            "font-family: 'Inter'; background: transparent;"
        )

        total   = disk.get("size_gb", 0.0)
        used    = disk.get("used_gb", 0.0)
        device  = disk.get("device", "")
        size_txt = f"{used:.1f} / {total:.1f} Go" if used > 0 else f"{total:.1f} Go"
        d_lbl = QLabel(f"{device}  ·  {size_txt}")
        d_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px;"
            "font-family: 'SF Mono', Consolas, monospace; background: transparent;"
        )
        info.addWidget(n_lbl)
        info.addWidget(d_lbl)
        lay.addLayout(info, stretch=1)

        # Bouton scanner
        scan_btn = QPushButton("Scanner →")
        scan_btn.setFixedSize(100, 32)
        scan_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        scan_btn.setStyleSheet(
            f"QPushButton {{ background: {_ACCENT}; color: white; border: none;"
            "  border-radius: 8px; font-size: 12px; font-weight: 700; }}"
            "QPushButton:hover { background: #005FCC; }"
        )
        scan_btn.clicked.connect(lambda: self.scan_requested.emit(self._disk))
        lay.addWidget(scan_btn)


# ═══════════════════════════════════════════════════════════════════════════════
#  État vide
# ═══════════════════════════════════════════════════════════════════════════════

class _EmptyState(QWidget):
    refresh_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(16)

        ico = QLabel("💳")
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet("font-size: 52px; background: transparent;")
        lay.addWidget(ico)

        title = QLabel("Aucun périphérique externe détecté")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: 700;"
            "font-family: 'Inter'; background: transparent;"
        )
        lay.addWidget(title)

        sub = QLabel(
            "Connectez une carte SD, une clé USB ou un appareil photo,\n"
            "puis actualisez la liste."
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(
            f"color: {_MUTED}; font-size: 13px;"
            "font-family: 'Inter'; background: transparent;"
        )
        lay.addWidget(sub)

        btn = QPushButton("↻  Actualiser")
        btn.setFixedSize(140, 36)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(
            f"QPushButton {{ background: {_ACCENT}; color: white; border: none;"
            "  border-radius: 8px; font-size: 13px; font-weight: 600; }}"
            "QPushButton:hover { background: #005FCC; }"
        )
        btn.clicked.connect(self.refresh_clicked)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)


# ═══════════════════════════════════════════════════════════════════════════════
#  Écran carte SD
# ═══════════════════════════════════════════════════════════════════════════════

class SdCardScreen(QWidget):
    disk_selected = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # En-tête
        hdr = QWidget()
        hdr.setFixedHeight(100)
        hdr.setStyleSheet("background: transparent;")
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(40, 20, 40, 20)

        col = QVBoxLayout()
        col.setSpacing(6)
        title = QLabel("Cartes SD & Périphériques externes")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 22px; font-weight: 700;"
            "font-family: 'Inter';"
        )
        sub = QLabel("Récupérez les données de vos clés USB, cartes SD et appareils photos.")
        sub.setStyleSheet(
            f"color: {_SUB}; font-size: 13px;"
            "font-family: 'Inter';"
        )
        col.addWidget(title)
        col.addWidget(sub)
        hr.addLayout(col)
        hr.addStretch()

        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(38, 38)
        refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        refresh_btn.setToolTip("Actualiser")
        refresh_btn.setStyleSheet(
            f"QPushButton {{ background: {_CARD}; border: 1px solid {_BORDER};"
            "  border-radius: 19px; color: #FFF; font-size: 18px; }}"
            f"QPushButton:hover {{ background: rgba(255,255,255,0.1); }}"
        )
        refresh_btn.clicked.connect(self.refresh)
        hr.addWidget(refresh_btn)
        root.addWidget(hdr)

        # Contenu scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(40, 0, 40, 40)
        self._layout.setSpacing(16)
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
        while self._layout.count():
            item = self._layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        disks = [d for d in DiskDetector.list_disks() if _is_external(d)]

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
