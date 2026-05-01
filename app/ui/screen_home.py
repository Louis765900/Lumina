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

from app.core.disk_detector import DiskDetector

_HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs", "history.json",
)

# Icones par type de disque
_DTYPE_ICONS = {
    "nvme": "NVMe", "ssd": "SSD", "usb": "USB", "hdd": "HDD", "other": "DRV",
}

# Scenarios de recuperation
_SCENARIOS = [
    ("Fichiers supprimes",  "Recuperer des fichiers effacees ou perdus."),
    ("Corbeille",           "Restaurer les fichiers vides de la Corbeille."),
    ("Disque formate",      "Recuperer les donnees d'un disque formate."),
    ("Attaque virale",      "Recuperer des donnees perdues suite a un virus."),
    ("Panne systeme",       "Recuperer des fichiers d'un PC non demarrable."),
    ("Appareils externes",  "USB, cartes SD, appareils photo, etc."),
]

# Acces rapide
_QUICK = [
    ("Image / ISO",  "Analyser une image disque .img / .iso"),
    ("Bureau",       "Recuperer des fichiers supprimes du Bureau"),
    ("Dossier",      "Choisir un dossier cible a scanner"),
    ("Corbeille",    "Recuperer les fichiers de la Corbeille"),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _disk_type(disk: dict) -> str:
    iface = disk.get("interface", "").lower()
    model = disk.get("model", "").lower()
    if any(x in iface or x in model for x in ("usb", "sd", "removable")):
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
    return any(x in iface or x in model for x in ("usb", "sd", "removable"))


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
            "background-color: #FFFFFF;"
            "border-top: 1px solid #808080;"
            "border-left: 1px solid #808080;"
            "border-bottom: 1px solid #FFFFFF;"
            "border-right: 1px solid #FFFFFF;"
        )

    def paintEvent(self, _):
        p = QPainter(self)
        w = self.width()
        h = self.height()
        # Background
        p.fillRect(0, 0, w, h, QColor("#FFFFFF"))
        # Filled portion
        fw = int(w * self._pct)
        if fw > 0:
            p.fillRect(0, 0, fw, h, QColor("#000080"))
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
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        # Ligne du haut : badge type + nom + device
        top = QHBoxLayout()
        top.setSpacing(8)

        badge = QLabel(_DTYPE_ICONS.get(dtype, "DRV"))
        badge.setFixedSize(32, 16)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "background-color: #000080; color: #FFFFFF;"
            "font-size: 9px; font-weight: 700;"
            "font-family: 'Work Sans', Arial;"
        )

        info = QVBoxLayout()
        info.setSpacing(1)
        name = disk.get("name", "Disque")
        if len(name) > 28:
            name = name[:26] + "..."
        n_lbl = QLabel(name)
        n_lbl.setStyleSheet(
            "color: #000000; font-size: 11px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        d_lbl = QLabel(disk.get("device", ""))
        d_lbl.setStyleSheet(
            "color: #404040; font-size: 10px;"
            "font-family: 'Work Sans', Arial; background: transparent;"
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
            "color: #000000; font-size: 10px; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )
        p_lbl = QLabel(f"{int(pct * 100)}%")
        p_lbl.setStyleSheet(
            "color: #000080; font-size: 10px; font-weight: 700; background: transparent;"
            "font-family: 'Work Sans', Arial;"
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
                "  background-color: #D4D0C8;"
                "  border-top: 2px solid #808080;"
                "  border-left: 2px solid #808080;"
                "  border-bottom: 2px solid #FFFFFF;"
                "  border-right: 2px solid #FFFFFF;"
                "}"
            )
        else:
            self.setStyleSheet(
                "DiskCard {"
                "  background-color: #C0C0C0;"
                "  border-top: 2px solid #FFFFFF;"
                "  border-left: 2px solid #FFFFFF;"
                "  border-bottom: 2px solid #808080;"
                "  border-right: 2px solid #808080;"
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
            "color: #000000; font-size: 11px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        lay.addWidget(t)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(
            "color: #404040; font-size: 10px;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        lay.addWidget(d, stretch=1)

    def _set_style(self, hovered: bool):
        if hovered:
            self.setStyleSheet(
                "_ScenarioCard {"
                "  background-color: #D4D0C8;"
                "  border-top: 2px solid #808080;"
                "  border-left: 2px solid #808080;"
                "  border-bottom: 2px solid #FFFFFF;"
                "  border-right: 2px solid #FFFFFF;"
                "}"
            )
        else:
            self.setStyleSheet(
                "_ScenarioCard {"
                "  background-color: #C0C0C0;"
                "  border-top: 2px solid #FFFFFF;"
                "  border-left: 2px solid #FFFFFF;"
                "  border-bottom: 2px solid #808080;"
                "  border-right: 2px solid #808080;"
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
            "  background-color: #C0C0C0;"
            "  color: #000000;"
            "  font-size: 11px; font-weight: 400;"
            "  font-family: 'Work Sans', Arial;"
            "  border-top: 2px solid #FFFFFF;"
            "  border-left: 2px solid #FFFFFF;"
            "  border-bottom: 2px solid #808080;"
            "  border-right: 2px solid #808080;"
            "}"
            "QPushButton:hover {"
            "  background-color: #D4D0C8;"
            "}"
            "QPushButton:pressed {"
            "  border-top: 2px solid #808080;"
            "  border-left: 2px solid #808080;"
            "  border-bottom: 2px solid #FFFFFF;"
            "  border-right: 2px solid #FFFFFF;"
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

        self.setFixedHeight(22)
        if self._can_reload:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_style(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(12)

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
            "color: #404040; font-size: 10px; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )
        lay.addWidget(date_lbl)

        dev_lbl = QLabel(entry.get("device", "-"))
        dev_lbl.setStyleSheet(
            "color: #000000; font-size: 10px; font-weight: 700; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )
        lay.addWidget(dev_lbl)
        lay.addStretch()

        if entry.get("simulated"):
            sim_lbl = QLabel("[simulation]")
            sim_lbl.setStyleSheet(
                "color: #808080; font-size: 10px; background: transparent;"
            )
            lay.addWidget(sim_lbl)

        n = entry.get("file_count", 0)
        count_lbl = QLabel(f"{n} fichier{'s' if n != 1 else ''}")
        count_lbl.setStyleSheet(
            "color: #000080; font-size: 10px; font-weight: 700; background: transparent;"
            "font-family: 'Work Sans', Arial;"
        )
        lay.addWidget(count_lbl)

        if self._can_reload:
            reload_lbl = QLabel("[recharger]")
            reload_lbl.setStyleSheet(
                "color: #808080; font-size: 10px; background: transparent;"
            )
            lay.addWidget(reload_lbl)

    def _set_style(self, hovered: bool):
        if hovered and self._can_reload:
            self.setStyleSheet(
                "_HistoryRow { background-color: #000080; border: 0px; }"
            )
            for child in self.findChildren(QLabel):
                child.setStyleSheet(
                    child.styleSheet().replace("color: #000000", "color: #FFFFFF")
                    .replace("color: #404040", "color: #FFFFFF")
                    .replace("color: #000080", "color: #FFFFFF")
                    .replace("color: #808080", "color: #FFFFFF")
                )
        else:
            self.setStyleSheet(
                "_HistoryRow { background-color: transparent; border: 0px; }"
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
        self.setFixedHeight(20)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        lbl = QLabel(title)
        lbl.setStyleSheet(
            "color: #000000; font-size: 11px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
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
        self.setStyleSheet("background-color: #C0C0C0;")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # En-tete
        hdr = QWidget()
        hdr.setFixedHeight(40)
        hdr.setStyleSheet(
            "background-color: #C0C0C0;"
            "border-bottom: 2px solid #808080;"
        )
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(8, 4, 8, 4)

        title_lbl = QLabel("Selectionnez un emplacement pour demarrer la recuperation")
        title_lbl.setStyleSheet(
            "color: #000000; font-size: 12px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        hr.addWidget(title_lbl)
        hr.addStretch()

        self._refresh_btn = QPushButton("Actualiser")
        self._refresh_btn.setFixedSize(80, 24)
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
            "QScrollArea { background-color: #C0C0C0; border: none; }"
        )

        self._content = QWidget()
        self._content.setStyleSheet("background-color: #C0C0C0;")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(12, 8, 12, 12)
        self._layout.setSpacing(16)

        scroll.setWidget(self._content)
        root.addWidget(scroll, stretch=1)

        self.refresh_disks()

    # ── Actualisation ─────────────────────────────────────────────────────────

    def refresh_disks(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        disks    = DiskDetector.list_disks()
        internal = [d for d in disks if not _is_external(d)]
        external = [d for d in disks if _is_external(d)]

        delay = 0
        if internal:
            self._add_disk_section("Disques durs", internal, delay)
            delay += len(internal)
        if external:
            self._add_disk_section("Peripheriques externes", external, delay)
            delay += len(external)

        self._add_scenarios(delay)
        self._add_quick()
        self._add_history()
        self._layout.addStretch()

    # ── Sections ──────────────────────────────────────────────────────────────

    def _add_disk_section(self, title: str, disks: list, delay_start: int):
        self._layout.addWidget(_SectionHdr(title))

        # Sunken panel for disk list
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame {"
            "  background-color: #FFFFFF;"
            "  border-top: 2px solid #808080;"
            "  border-left: 2px solid #808080;"
            "  border-bottom: 2px solid #FFFFFF;"
            "  border-right: 2px solid #FFFFFF;"
            "}"
        )
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(6, 6, 6, 6)
        panel_lay.setSpacing(8)

        current_row: QHBoxLayout | None = None
        for i, disk in enumerate(disks):
            if i % 3 == 0:
                current_row = QHBoxLayout()
                current_row.setSpacing(12)
                panel_lay.addLayout(current_row)

            card = DiskCard(disk)
            card.clicked.connect(self.disk_selected)
            current_row.addWidget(self._fade_wrap(card, (delay_start + i) * 60))

        if current_row:
            current_row.addStretch()

        self._layout.addWidget(panel)

    def _add_scenarios(self, delay_start: int):
        self._layout.addWidget(_SectionHdr("Scenarios de recuperation"))

        outer = QWidget()
        outer.setStyleSheet("background-color: #C0C0C0;")
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
        self._layout.addWidget(_SectionHdr("Acces rapide"))

        wrap = QWidget()
        wrap.setStyleSheet("background-color: #C0C0C0;")
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

        self._layout.addWidget(_SectionHdr("Scans recents"))

        # Win98 sunken list panel
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame {"
            "  background-color: #FFFFFF;"
            "  border-top: 2px solid #808080;"
            "  border-left: 2px solid #808080;"
            "  border-bottom: 2px solid #FFFFFF;"
            "  border-right: 2px solid #FFFFFF;"
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
                sep.setStyleSheet("background-color: #C0C0C0; border: 0px;")
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
