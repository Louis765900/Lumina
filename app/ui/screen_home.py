"""
Lumina — Ecran 0 : Accueil (style Windows 98)
Liste des disques, scenarios de recuperation et acces rapide.
"""

import datetime
import json
import os

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
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
    CARD as _CARD,
)
from app.ui.palette import (
    HOVER as _HOVER,
)
from app.ui.palette import (
    OK as _OK,
)
from app.ui.palette import (
    OK_BG as _OK_BG,
)
from app.ui.palette import (
    SUB as _SUB,
)
from app.ui.palette import (
    TEXT as _TEXT,
)

_PANEL = "#F8FAFC"
_SURFACE = "#FFFFFF"
_LINE = "#D0D5DD"
_FONT = "'Segoe UI', Arial"

_HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs", "history.json",
)

# Icones par type de disque
_DTYPE_ICONS = {
    "nvme": "NVMe", "ssd": "SSD", "usb": "USB", "hdd": "HDD", "other": "DRV",
}

_EXTERNAL_MARKERS = (
    " usb ",
    " removable ",
    " sd ",
    " sdxc ",
    " sdhc ",
    " card reader ",
)

# Scenarios de recuperation
_SCENARIOS = [
    ("Fichiers supprimés",  "Récupérer des fichiers effacés ou perdus."),
    ("Corbeille",           "Restaurer les fichiers vidés de la Corbeille."),
    ("Disque formaté",      "Récupérer les données d'un disque formaté."),
    ("Attaque virale",      "Récupérer des données perdues suite à un virus."),
    ("Panne système",       "Récupérer des fichiers d'un PC non démarrable."),
    ("Appareils externes",  "USB, cartes SD, appareils photo, etc."),
]

# Acces rapide
_QUICK = [
    ("Image / ISO",  "Analyser une image disque .img / .iso"),
    ("Bureau",       "Récupérer des fichiers supprimés du Bureau"),
    ("Dossier",      "Choisir un dossier cible à scanner"),
    ("Corbeille",    "Récupérer les fichiers de la Corbeille"),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _disk_type(disk: dict) -> str:
    iface = disk.get("interface", "").lower()
    model = disk.get("model", "").lower()
    if disk.get("removable") or _has_external_marker(iface, model):
        return "usb"
    if "nvme" in iface or "nvme" in model:
        return "nvme"
    if "ssd" in model:
        return "ssd"
    if any(x in iface or x in model for x in ("sata", "hdd", "ide")):
        return "hdd"
    return "other"


def _is_external(disk: dict) -> bool:
    if disk.get("removable"):
        return True
    iface = disk.get("interface", "").lower()
    model = disk.get("model", "").lower()
    return _has_external_marker(iface, model)


def _has_external_marker(*parts: str) -> bool:
    text = " ".join(parts)
    normalized = f" {text.replace('-', ' ').replace('_', ' ').lower()} "
    return "microsd" in normalized or any(
        marker in normalized for marker in _EXTERNAL_MARKERS
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Barre de capacite Win98 (horizontale, 8px de haut)
# ═══════════════════════════════════════════════════════════════════════════════

class _UsageBar(QWidget):
    H = 8

    def __init__(self, pct: float, parent=None):
        super().__init__(parent)
        self._pct = max(0.0, min(1.0, pct))
        self.setFixedHeight(self.H)
        self.setStyleSheet(
            f"background-color: {_BEVEL_LIGHT};"
            f"border-top: 1px solid {_BEVEL_SHADOW};"
            f"border-left: 1px solid {_BEVEL_SHADOW};"
            f"border-bottom: 1px solid {_BEVEL_LIGHT};"
            f"border-right: 1px solid {_BEVEL_LIGHT};"
        )

    def paintEvent(self, _):
        p = QPainter(self)
        w = self.width()
        h = self.height()
        # Background
        p.fillRect(0, 0, w, h, QColor(f"{_BEVEL_LIGHT}"))
        # Filled portion
        fw = int(w * self._pct)
        if fw > 0:
            p.fillRect(0, 0, fw, h, QColor(f"{_ACCENT}"))
        p.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  Carte disque Win98 (280 x 100)
# ═══════════════════════════════════════════════════════════════════════════════

class DiskCard(QFrame):
    clicked = pyqtSignal(dict)

    W, H = 270, 90

    def __init__(self, disk: dict, parent=None):
        super().__init__(parent)
        self._disk    = disk
        self._hovered = False

        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_style(False)

        dtype  = _disk_type(disk)
        total  = disk.get("size_gb", 0.0)
        used   = disk.get("used_gb", 0.0)
        pct    = (used / total) if total > 0 else 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(5)

        # Ligne du haut : badge type + nom + device
        top = QHBoxLayout()
        top.setSpacing(8)

        badge = QLabel(_DTYPE_ICONS.get(dtype, "DRV"))
        badge.setFixedSize(38, 20)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background-color: {_OK_BG}; color: {_ACCENT};"
            f"border: 1px solid {_LINE}; border-radius: 2px;"
            "font-size: 10px; font-weight: 800;"
            f"font-family: {_FONT};"
        )

        info = QVBoxLayout()
        info.setSpacing(1)
        full_name = disk.get("name", "Disque")
        name = full_name
        if len(name) > 28:
            name = name[:26] + "..."
        n_lbl = QLabel(name)
        n_lbl.setToolTip(full_name)
        n_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        d_lbl = QLabel(disk.get("device", ""))
        d_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 11px;"
            f"font-family: {_FONT}; background: transparent;"
        )
        info.addWidget(n_lbl)
        info.addWidget(d_lbl)

        top.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)
        top.addLayout(info, stretch=1)
        lay.addLayout(top)
        lay.addStretch()

        # Stats
        stats = QHBoxLayout()
        vol_txt = (
            f"{used:.1f} / {total:.1f} Go" if used > 0 else f"{total:.1f} Go"
        )
        v_lbl = QLabel(vol_txt)
        v_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 11px; background: transparent;"
            f"font-family: {_FONT};"
        )
        p_lbl = QLabel(f"{int(pct * 100)}%")
        p_lbl.setStyleSheet(
            f"color: {_ACCENT}; font-size: 11px; font-weight: 800; background: transparent;"
            f"font-family: {_FONT};"
        )
        stats.addWidget(v_lbl)
        stats.addStretch()
        stats.addWidget(p_lbl)
        lay.addLayout(stats)
        lay.addWidget(_UsageBar(pct))

    def _set_style(self, hovered: bool):
        if hovered:
            self.setStyleSheet(
                "DiskCard {"
                f"  background-color: {_HOVER};"
                f"  border: 1px solid {_ACCENT};"
                "  border-radius: 4px;"
                "}"
            )
        else:
            self.setStyleSheet(
                "DiskCard {"
                f"  background-color: {_SURFACE};"
                f"  border: 1px solid {_LINE};"
                "  border-radius: 4px;"
                "}"
            )

    def enterEvent(self, e):
        self._hovered = True
        self._set_style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False
        self._set_style(False)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._disk)
        super().mousePressEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  Carte scenario (Win98 button)
# ═══════════════════════════════════════════════════════════════════════════════

class _ScenarioCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, title: str, desc: str, parent=None):
        super().__init__(parent)
        self._title   = title
        self._hovered = False
        self.setFixedSize(180, 64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_style(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)

        t = QLabel(title)
        t.setStyleSheet(
            f"color: {_TEXT}; font-size: 11px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        lay.addWidget(t)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(
            f"color: {_SUB}; font-size: 10px;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        lay.addWidget(d, stretch=1)

    def _set_style(self, hovered: bool):
        if hovered:
            self.setStyleSheet(
                "_ScenarioCard {"
                f"  background-color: {_HOVER};"
                f"  border-top: 2px solid {_BEVEL_SHADOW};"
                f"  border-left: 2px solid {_BEVEL_SHADOW};"
                f"  border-bottom: 2px solid {_BEVEL_LIGHT};"
                f"  border-right: 2px solid {_BEVEL_LIGHT};"
                "}"
            )
        else:
            self.setStyleSheet(
                "_ScenarioCard {"
                f"  background-color: {_CARD};"
                f"  border-top: 2px solid {_BEVEL_LIGHT};"
                f"  border-left: 2px solid {_BEVEL_LIGHT};"
                f"  border-bottom: 2px solid {_BEVEL_SHADOW};"
                f"  border-right: 2px solid {_BEVEL_SHADOW};"
                "}"
            )

    def enterEvent(self, e):
        self._hovered = True
        self._set_style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False
        self._set_style(False)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._title)
        super().mousePressEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  Carte acces rapide (Win98 button 100x64)
# ═══════════════════════════════════════════════════════════════════════════════

class _QuickCard(QPushButton):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(110, 54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText(label)
        self.setStyleSheet(
            "QPushButton {"
            f"  background-color: {_CARD};"
            f"  color: {_TEXT};"
            "  font-size: 11px; font-weight: 400;"
            "  font-family: 'Work Sans', Arial;"
            f"  border-top: 2px solid {_BEVEL_LIGHT};"
            f"  border-left: 2px solid {_BEVEL_LIGHT};"
            f"  border-bottom: 2px solid {_BEVEL_SHADOW};"
            f"  border-right: 2px solid {_BEVEL_SHADOW};"
            "}"
            "QPushButton:hover {"
            f"  background-color: {_HOVER};"
            "}"
            "QPushButton:pressed {"
            f"  border-top: 2px solid {_BEVEL_SHADOW};"
            f"  border-left: 2px solid {_BEVEL_SHADOW};"
            f"  border-bottom: 2px solid {_BEVEL_LIGHT};"
            f"  border-right: 2px solid {_BEVEL_LIGHT};"
            "  padding-top: 2px; padding-left: 2px;"
            "}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Ligne d'historique de scan
# ═══════════════════════════════════════════════════════════════════════════════

class _HistoryRow(QFrame):
    reload_requested = pyqtSignal(list)

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self._entry      = entry
        self._can_reload = bool(
            entry.get("scan_file") and os.path.isfile(entry["scan_file"])
        )

        self.setFixedHeight(36)
        if self._can_reload:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_style(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(14)

        # Date
        try:
            dt   = datetime.datetime.fromisoformat(entry["date"])
            now  = datetime.datetime.now()
            diff = now - dt
            if diff.days == 0:
                hours = diff.seconds // 3600
                date_str = f"Il y a {hours}h" if hours > 0 else "A l'instant"
            elif diff.days == 1:
                date_str = f"Hier a {dt.strftime('%H:%M')}"
            else:
                date_str = dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            date_str = entry.get("date", "-")

        date_lbl = QLabel(date_str)
        date_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 11px; background: transparent;"
            f"font-family: {_FONT};"
        )
        lay.addWidget(date_lbl)

        dev_lbl = QLabel(entry.get("device", "-"))
        dev_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 11px; font-weight: 800; background: transparent;"
            f"font-family: {_FONT};"
        )
        lay.addWidget(dev_lbl)
        lay.addStretch()

        if entry.get("simulated"):
            sim_lbl = QLabel("[simulation]")
            sim_lbl.setStyleSheet(
                f"color: {_SUB}; font-size: 11px; background: transparent;"
                f"font-family: {_FONT};"
            )
            lay.addWidget(sim_lbl)

        n = entry.get("file_count", 0)
        count_lbl = QLabel(f"{n} fichier{'s' if n != 1 else ''}")
        count_lbl.setStyleSheet(
            f"color: {_ACCENT}; font-size: 11px; font-weight: 800; background: transparent;"
            f"font-family: {_FONT};"
        )
        lay.addWidget(count_lbl)

        if self._can_reload:
            reload_lbl = QLabel("[recharger]")
            reload_lbl.setStyleSheet(
                f"color: {_OK}; font-size: 11px; font-weight: 800; background: transparent;"
                f"font-family: {_FONT};"
            )
            lay.addWidget(reload_lbl)

    def _set_style(self, hovered: bool):
        if hovered and self._can_reload:
            self.setStyleSheet(
                f"_HistoryRow {{ background-color: {_ACCENT}; border: 0px; }}"
            )
            for child in self.findChildren(QLabel):
                child.setStyleSheet(
                    child.styleSheet().replace(f"color: {_TEXT}", f"color: {_BEVEL_LIGHT}")
                    .replace(f"color: {_SUB}", f"color: {_BEVEL_LIGHT}")
                    .replace(f"color: {_ACCENT}", f"color: {_BEVEL_LIGHT}")
                    .replace(f"color: {_BEVEL_SHADOW}", f"color: {_BEVEL_LIGHT}")
                )
        else:
            self.setStyleSheet(
                "_HistoryRow {"
                f" background-color: {_SURFACE};"
                f" border-bottom: 1px solid {_LINE};"
                "}"
            )

    def enterEvent(self, e):
        self._set_style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._set_style(False)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._can_reload:
            try:
                with open(self._entry["scan_file"], encoding="utf-8") as fh:
                    files = json.load(fh)
                self.reload_requested.emit(files)
            except Exception:
                pass
        super().mousePressEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  En-tete de section Win98
# ═══════════════════════════════════════════════════════════════════════════════

class _SectionHdr(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color: {_ACCENT}; font-size: 13px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        row.addWidget(lbl)
        row.addStretch()


# ═══════════════════════════════════════════════════════════════════════════════
#  Ecran d'accueil
# ═══════════════════════════════════════════════════════════════════════════════

class HomeScreen(QWidget):
    disk_selected          = pyqtSignal(dict)
    scenario_selected      = pyqtSignal(str)
    history_scan_requested = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_CARD};")
        self._disk_worker: DiskListWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # En-tete
        hdr = QWidget()
        hdr.setFixedHeight(62)
        hdr.setStyleSheet(
            f"background-color: {_PANEL};"
            f"border-bottom: 1px solid {_LINE};"
        )
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(18, 10, 18, 10)
        hr.setSpacing(12)

        title_lbl = QLabel("Sélectionnez un emplacement pour démarrer la récupération")
        title_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 15px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        hr.addWidget(title_lbl)
        hr.addStretch()

        self._refresh_btn = QPushButton("Actualiser")
        self._refresh_btn.setFixedSize(104, 34)
        self._refresh_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._refresh_btn.setToolTip("Actualiser les disques")
        self._refresh_btn.clicked.connect(self.refresh_disks)
        hr.addWidget(self._refresh_btn)
        root.addWidget(hdr)

        # Zone de defilement
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {_CARD}; border: none; }}"
        )

        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {_CARD};")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(18, 16, 18, 18)
        self._layout.setSpacing(14)

        scroll.setWidget(self._content)
        root.addWidget(scroll, stretch=1)

        self.refresh_disks()

    # ── Actualisation ─────────────────────────────────────────────────────────

    def refresh_disks(self):
        if self._disk_worker and self._disk_worker.isRunning():
            return

        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("...")
        self._clear_layout()
        self._add_disk_message("Recherche des disques...", "Énumération en cours.")

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

    def _on_disks_loaded(self, disks: list, error: str):
        self._clear_layout()
        self._render_disks(disks, error)

    def _clear_layout(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

    def _render_disks(self, disks: list, error: str = ""):
        internal = [d for d in disks if not _is_external(d)]
        external = [d for d in disks if _is_external(d)]

        delay = 0
        if error:
            self._add_disk_message("Aucun disque détecté", f"Erreur de détection : {error}")
        elif not disks:
            self._add_disk_message(
                "Aucun disque détecté",
                "Branchez un disque local, USB ou une carte SD, puis cliquez sur Actualiser.",
            )
        if internal:
            self._add_disk_section("Disques durs", internal, delay)
            delay += len(internal)
        if external:
            self._add_disk_section("Périphériques externes", external, delay)
            delay += len(external)

        self._add_history()
        self._layout.addStretch()

    # ── Sections ──────────────────────────────────────────────────────────────

    def _add_disk_message(self, title: str, detail: str):
        panel = QFrame()
        panel.setObjectName("HomeMessagePanel")
        panel.setStyleSheet(
            "QFrame#HomeMessagePanel {"
            f"  background-color: {_PANEL};"
            f"  border: 1px solid {_LINE};"
            "  border-radius: 4px;"
            "}"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(5)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 14px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        detail_lbl = QLabel(detail)
        detail_lbl.setWordWrap(True)
        detail_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 12px;"
            f"font-family: {_FONT}; background: transparent;"
        )
        lay.addWidget(title_lbl)
        lay.addWidget(detail_lbl)
        self._layout.addWidget(panel)

    def _add_disk_section(self, title: str, disks: list, delay_start: int):
        self._layout.addWidget(_SectionHdr(title))

        # Sunken panel for disk list
        panel = QFrame()
        panel.setObjectName("HomeDiskPanel")
        panel.setStyleSheet(
            "QFrame#HomeDiskPanel {"
            f"  background-color: {_PANEL};"
            f"  border: 1px solid {_LINE};"
            "  border-radius: 4px;"
            "}"
        )
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(10, 10, 10, 10)
        panel_lay.setSpacing(10)

        current_row: QHBoxLayout | None = None
        for i, disk in enumerate(disks):
            if i % 3 == 0:
                current_row = QHBoxLayout()
                current_row.setSpacing(14)
                panel_lay.addLayout(current_row)

            card = DiskCard(disk)
            card.clicked.connect(self.disk_selected)
            current_row.addWidget(self._fade_wrap(card, (delay_start + i) * 60))

        if current_row:
            current_row.addStretch()

        self._layout.addWidget(panel)

    def _add_scenarios(self, delay_start: int):
        self._layout.addWidget(_SectionHdr("Scénarios de récupération"))

        outer = QWidget()
        outer.setStyleSheet(f"background-color: {_CARD};")
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        for i, (title, desc) in enumerate(_SCENARIOS):
            card = _ScenarioCard(title, desc)
            card.clicked.connect(self.scenario_selected)
            (row1 if i < 3 else row2).addWidget(
                self._fade_wrap(card, (delay_start + i) * 50)
            )

        row1.addStretch()
        row2.addStretch()
        outer_lay.addLayout(row1)
        outer_lay.addLayout(row2)
        self._layout.addWidget(outer)

    def _add_quick(self):
        self._layout.addWidget(_SectionHdr("Accès rapide"))

        wrap = QWidget()
        wrap.setStyleSheet(f"background-color: {_CARD};")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        for label, _tooltip in _QUICK:
            card = _QuickCard(label)
            row.addWidget(card)
        row.addStretch()

        self._layout.addWidget(wrap)

    def _add_history(self):
        try:
            with open(_HISTORY_PATH, encoding="utf-8") as fh:
                history: list[dict] = json.load(fh)
        except Exception:
            return

        if not history:
            return

        self._layout.addWidget(_SectionHdr("Scans récents"))

        # Win98 sunken list panel
        panel = QFrame()
        panel.setObjectName("HomeHistoryPanel")
        panel.setStyleSheet(
            "QFrame#HomeHistoryPanel {"
            f"  background-color: {_SURFACE};"
            f"  border: 1px solid {_LINE};"
            "  border-radius: 4px;"
            "}"
        )
        col = QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        entries = history[:5]
        for i, entry in enumerate(entries):
            row_w = _HistoryRow(entry)
            row_w.reload_requested.connect(self.history_scan_requested)
            col.addWidget(row_w)
            if i < len(entries) - 1:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background-color: {_LINE}; border: 0px;")
                col.addWidget(sep)
        self._layout.addWidget(panel)

    # ── Animation fondu echelonne ─────────────────────────────────────────────

    @staticmethod
    def _fade_wrap(widget: QWidget, delay_ms: int) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(widget)

        effect = QGraphicsOpacityEffect(wrap)
        effect.setOpacity(0.0)
        wrap.setGraphicsEffect(effect)

        def _start():
            try:
                anim = QPropertyAnimation(effect, b"opacity", wrap)
                anim.setDuration(300)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.finished.connect(lambda: wrap.setGraphicsEffect(None))
                anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
                wrap._fade_anim = anim  # type: ignore[attr-defined]
            except RuntimeError:
                pass

        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(_start)
        timer.start(delay_ms)
        wrap._fade_timer = timer  # type: ignore[attr-defined]
        return wrap
