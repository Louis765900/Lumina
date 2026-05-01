"""
Lumina v2.0 — Écran 0 : Accueil
Grille de cartes disques, scénarios de récupération et accès rapide.
Animations de fondu échelonnées, overlay "Scanner" au survol.
"""

import datetime
import json
import os

_HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs", "history.json",
)

from PyQt6.QtCore import (
    Qt, QEasingCurve, QPropertyAnimation, QRectF,
    QTimer, QVariantAnimation, pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.core.disk_detector import DiskDetector
from app.ui.palette import (
    ACCENT as _ACCENT,
    BORDER as _BORDER,
    CARD as _CARD,
    HBORDER as _HBORDER,
    MUTED as _MUTED,
    SUB as _SUB,
    TEXT as _TEXT,
)

# Couleurs par type de disque
_DTYPE_COLORS = {
    "nvme":  (59,  130, 246),   # bleu
    "ssd":   (16,  185, 129),   # vert
    "usb":   (168,  85, 247),   # violet
    "hdd":   (251, 146,  60),   # orange
    "other": (59,  130, 246),
}
_DTYPE_ICONS = {
    "nvme": "⚡", "ssd": "💾", "usb": "🔌", "hdd": "🖥", "other": "💾",
}

# Scénarios de récupération
_SCENARIOS = [
    ("🗑️", "Fichiers supprimés",  "Récupérer des fichiers effacés ou perdus.",     "#3B82F6"),
    ("♻️", "Corbeille",           "Restaurer les fichiers vidés de la Corbeille.",  "#10B981"),
    ("💿", "Disque formaté",      "Récupérer les données d'un disque formaté.",     "#8B5CF6"),
    ("🦠", "Attaque virale",      "Récupérer des données perdues suite à un virus.","#EF4444"),
    ("💻", "Panne système",       "Récupérer des fichiers d'un PC non démarrable.", "#F59E0B"),
    ("📱", "Appareils externes",  "USB, cartes SD, appareils photo, etc.",          "#06B6D4"),
]

# Accès rapide
_QUICK = [
    ("💿", "Image / ISO",  "Analyser une image disque .img / .iso"),
    ("🖥️", "Bureau",       "Récupérer des fichiers supprimés du Bureau"),
    ("📁", "Dossier",      "Choisir un dossier ciblé à scanner"),
    ("🗑️", "Corbeille",    "Récupérer les fichiers de la Corbeille"),
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
#  Mini barre d'usage (4 px)
# ═══════════════════════════════════════════════════════════════════════════════

class _UsageBar(QWidget):
    H = 4

    def __init__(self, pct: float, r: int, g: int, b: int, parent=None):
        super().__init__(parent)
        self._pct  = max(0.0, min(1.0, pct))
        self._fill = QColor(r, g, b)
        self.setFixedHeight(self.H)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rad   = h / 2.0

        p.setBrush(QBrush(QColor(255, 255, 255, 20)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, w, h), rad, rad)

        fw = int(w * self._pct)
        if fw > 2:
            p.setBrush(QBrush(self._fill))
            p.drawRoundedRect(QRectF(0, 0, fw, h), rad, rad)
        p.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  Overlay "Scanner" (survol de la carte disque)
# ═══════════════════════════════════════════════════════════════════════════════

class _ScanOverlay(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._alpha = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.hide()

    def set_alpha(self, a: float):
        self._alpha = float(a)
        self.setVisible(self._alpha > 0.01)
        self.update()

    def paintEvent(self, _):
        if self._alpha <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Voile sombre
        p.setBrush(QBrush(QColor(10, 12, 28, int(110 * self._alpha))))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, w, h, 12, 12)

        # Bouton pilule bleu
        pw, ph = 108, 34
        px = (w - pw) / 2
        py = (h - ph) / 2 + 4 * (1.0 - self._alpha)   # légère remontée

        p.setBrush(QBrush(QColor(0, 122, 255, int(255 * self._alpha))))
        p.drawRoundedRect(QRectF(px, py, pw, ph), 17, 17)

        # Texte
        p.setPen(QPen(QColor(255, 255, 255, int(255 * self._alpha))))
        font = p.font()
        font.setFamily("Inter")
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(px, py, pw, ph), Qt.AlignmentFlag.AlignCenter, "Scanner")
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  Carte disque (280 × 120)
# ═══════════════════════════════════════════════════════════════════════════════

class DiskCard(QFrame):
    clicked = pyqtSignal(dict)

    W, H = 280, 120

    def __init__(self, disk: dict, parent=None):
        super().__init__(parent)
        self._disk  = disk
        self._anim: QVariantAnimation | None = None

        self.setFixedSize(self.W, self.H)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._set_border(False)

        dtype        = _disk_type(disk)
        r, g, b      = _DTYPE_COLORS.get(dtype, _DTYPE_COLORS["other"])
        accent       = f"rgb({r},{g},{b})"
        total        = disk.get("size_gb", 0.0)
        used         = disk.get("used_gb", 0.0)
        pct          = (used / total) if total > 0 else 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(0)

        # ── Ligne du haut : icône + nom ───────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(12)

        ico = QLabel(_DTYPE_ICONS.get(dtype, "💾"))
        ico.setFixedSize(36, 36)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"font-size: 18px; background: rgba({r},{g},{b},0.15);"
            "border-radius: 8px;"
        )

        info = QVBoxLayout()
        info.setSpacing(3)
        name = disk.get("name", "Disque")
        if len(name) > 26:
            name = name[:24] + "…"
        n_lbl = QLabel(name)
        n_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: 600;"
            "font-family: 'Inter', 'Segoe UI', Arial; background: transparent;"
        )
        d_lbl = QLabel(disk.get("device", ""))
        d_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px;"
            "font-family: 'SF Mono', Consolas, monospace; background: transparent;"
        )
        info.addWidget(n_lbl)
        info.addWidget(d_lbl)
        info.addStretch()

        top.addWidget(ico)
        top.addLayout(info, stretch=1)
        lay.addLayout(top)
        lay.addStretch()

        # ── Ligne du bas : stats + barre ─────────────────────────────────────
        stats = QHBoxLayout()
        vol_txt = (
            f"{used:.1f} / {total:.1f} GB" if used > 0 else f"{total:.1f} GB"
        )
        v_lbl = QLabel(vol_txt)
        v_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 11px;"
            "font-family: 'Inter', 'Segoe UI', Arial; background: transparent;"
        )
        p_lbl = QLabel(f"{int(pct * 100)}%")
        p_lbl.setStyleSheet(
            f"color: {accent}; font-size: 11px; font-weight: 600;"
            "font-family: 'Inter'; background: transparent;"
        )
        stats.addWidget(v_lbl)
        stats.addStretch()
        stats.addWidget(p_lbl)
        lay.addLayout(stats)
        lay.addSpacing(6)
        lay.addWidget(_UsageBar(pct, r, g, b))

        # ── Overlay "Scanner" ─────────────────────────────────────────────────
        self._overlay = _ScanOverlay(self)
        self._overlay.resize(self.W, self.H)
        self._overlay.clicked.connect(lambda: self.clicked.emit(self._disk))

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(200)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._overlay.set_alpha)

    def _set_border(self, hovered: bool):
        brd = f"1.5px solid {_HBORDER}" if hovered else f"1px solid {_BORDER}"
        self.setStyleSheet(
            f"DiskCard {{ background: {_CARD}; border: {brd}; border-radius: 12px; }}"
        )

    def enterEvent(self, e):
        self._set_border(True)
        self._hover_anim.setStartValue(self._overlay._alpha)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._set_border(False)
        self._hover_anim.setStartValue(self._overlay._alpha)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  Carte scénario de récupération (192 × 128)
# ═══════════════════════════════════════════════════════════════════════════════

class _ScenarioCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, icon: str, title: str, desc: str, accent: str, parent=None):
        super().__init__(parent)
        self._accent  = accent
        self._hovered = False
        self.setFixedSize(192, 128)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._set_style()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)

        top = QHBoxLayout()
        ico = QLabel(icon)
        ico.setStyleSheet("font-size: 26px; background: transparent;")
        top.addWidget(ico)
        top.addStretch()
        lay.addLayout(top)

        t = QLabel(title)
        t.setWordWrap(True)
        t.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: 700;"
            "font-family: 'Inter'; background: transparent;"
        )
        lay.addWidget(t)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(
            f"color: {_SUB}; font-size: 10px;"
            "font-family: 'Inter'; background: transparent;"
        )
        lay.addWidget(d, stretch=1)

    def _set_style(self):
        if self._hovered:
            self.setStyleSheet(
                f"_ScenarioCard {{ background: rgba(255,255,255,0.08);"
                f"  border: 1px solid {self._accent}; border-radius: 12px; }}"
            )
        else:
            self.setStyleSheet(
                f"_ScenarioCard {{ background: {_CARD};"
                f"  border: 1px solid {_BORDER}; border-radius: 12px; }}"
            )

    def enterEvent(self, e):
        self._hovered = True
        self._set_style()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False
        self._set_style()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # Émettre le titre (premier QLabel enfant)
            for child in self.children():
                if isinstance(child, QLabel) and child.text() not in ("",):
                    # Skip the icon label
                    txt = child.text()
                    if len(txt) > 3:   # icon labels are short emoji
                        self.clicked.emit(txt)
                        break
        super().mousePressEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  Carte accès rapide (140 × 140)
# ═══════════════════════════════════════════════════════════════════════════════

class _QuickCard(QFrame):
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 140)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._set_style(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 24, 16, 24)
        lay.setSpacing(14)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ico = QLabel(icon)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet("font-size: 30px; background: transparent;")
        lay.addWidget(ico)

        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: 500;"
            "font-family: 'Inter', 'Segoe UI', Arial; background: transparent;"
        )
        lay.addWidget(lbl)

    def _set_style(self, hov: bool):
        bg = "rgba(255,255,255,0.09)" if hov else _CARD
        self.setStyleSheet(
            f"_QuickCard {{ background: {bg}; border: 1px solid {_BORDER}; border-radius: 12px; }}"
        )

    def enterEvent(self, e):
        self._set_style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._set_style(False)
        super().leaveEvent(e)


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

        self.setFixedHeight(44)
        if self._can_reload:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._set_style(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(16)

        # Date formatée
        try:
            dt   = datetime.datetime.fromisoformat(entry["date"])
            now  = datetime.datetime.now()
            diff = now - dt
            if diff.days == 0:
                hours = diff.seconds // 3600
                date_str = f"Il y a {hours}h" if hours > 0 else "À l'instant"
            elif diff.days == 1:
                date_str = f"Hier à {dt.strftime('%H:%M')}"
            else:
                date_str = dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            date_str = entry.get("date", "—")

        date_lbl = QLabel(f"🕐  {date_str}")
        date_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; font-family: 'Inter'; background: transparent;"
        )
        lay.addWidget(date_lbl)

        # Périphérique
        device = entry.get("device", "—")
        dev_lbl = QLabel(device)
        dev_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 11px; font-family: 'SF Mono', Consolas, monospace;"
            "background: transparent;"
        )
        lay.addWidget(dev_lbl)
        lay.addStretch()

        # Badge simulation
        if entry.get("simulated"):
            sim_lbl = QLabel("simulation")
            sim_lbl.setStyleSheet(
                f"color: {_MUTED}; font-size: 10px; background: rgba(255,255,255,0.05);"
                f"border: 1px solid {_BORDER}; border-radius: 6px; padding: 1px 7px;"
            )
            lay.addWidget(sim_lbl)

        # Compteur fichiers
        n = entry.get("file_count", 0)
        count_lbl = QLabel(f"{n} fichier{'s' if n != 1 else ''}")
        count_lbl.setStyleSheet(
            f"color: {_ACCENT}; font-size: 11px; font-weight: 700;"
            "font-family: 'Inter'; background: transparent;"
        )
        lay.addWidget(count_lbl)

        # Icône rechargeable
        if self._can_reload:
            reload_lbl = QLabel("↩")
            reload_lbl.setStyleSheet(
                f"color: {_MUTED}; font-size: 12px; background: transparent;"
            )
            lay.addWidget(reload_lbl)

    def _set_style(self, hovered: bool):
        if hovered and self._can_reload:
            self.setStyleSheet(
                "_HistoryRow { background: rgba(255,255,255,0.05);"
                "  border: none; border-radius: 0px; }"
            )
        else:
            self.setStyleSheet(
                "_HistoryRow { background: transparent; border: none; border-radius: 0px; }"
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
                with open(self._entry["scan_file"], "r", encoding="utf-8") as fh:
                    files = json.load(fh)
                self.reload_requested.emit(files)
            except Exception:
                pass
        super().mousePressEvent(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  En-tête de section
# ═══════════════════════════════════════════════════════════════════════════════

class _SectionHdr(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        lbl = QLabel(title.upper())
        lbl.setStyleSheet(
            "color: #c1c6d7; font-size: 10px; font-weight: 700; letter-spacing: 1.4px;"
            "font-family: 'Inter', 'Segoe UI', Arial; background: transparent;"
        )
        row.addWidget(lbl)
        row.addStretch()


# ═══════════════════════════════════════════════════════════════════════════════
#  Écran d'accueil
# ═══════════════════════════════════════════════════════════════════════════════

class HomeScreen(QWidget):
    disk_selected          = pyqtSignal(dict)
    scenario_selected      = pyqtSignal(str)
    history_scan_requested = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── En-tête de page ───────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(110)
        hdr.setStyleSheet("background: transparent;")
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(40, 20, 40, 20)

        title_col = QVBoxLayout()
        title_col.setSpacing(6)
        title_lbl = QLabel("Sélectionnez un emplacement pour démarrer")
        title_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 22px; font-weight: 700;"
            "font-family: 'Inter', 'SF Pro Display', 'Segoe UI', Arial;"
        )
        sub_lbl = QLabel("Choisissez le disque ou le dossier où vous avez perdu vos données.")
        sub_lbl.setStyleSheet(
            f"color: {_SUB}; font-size: 13px;"
            "font-family: 'Inter', 'Segoe UI', Arial;"
        )
        title_col.addWidget(title_lbl)
        title_col.addWidget(sub_lbl)
        hr.addLayout(title_col)
        hr.addStretch()

        # Bouton actualiser
        self._refresh_btn = QPushButton("↻")
        self._refresh_btn.setFixedSize(38, 38)
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setToolTip("Actualiser les disques")
        self._refresh_btn.setStyleSheet(
            f"QPushButton {{ background: {_CARD}; border: 1px solid {_BORDER};"
            f"  border-radius: 19px; color: {_TEXT}; font-size: 18px; }}"
            f"QPushButton:hover {{ background: rgba(255,255,255,0.1); }}"
        )
        self._refresh_btn.clicked.connect(self.refresh_disks)
        hr.addWidget(self._refresh_btn)
        root.addWidget(hdr)

        # ── Zone de défilement ────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )

        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(40, 0, 40, 40)
        self._layout.setSpacing(30)

        scroll.setWidget(self._content)
        root.addWidget(scroll, stretch=1)

        self.refresh_disks()

    # ── Actualisation ─────────────────────────────────────────────────────────

    def refresh_disks(self):
        # Vider le layout existant
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
            self._add_disk_section("Périphériques externes", external, delay)
            delay += len(external)

        self._add_scenarios(delay)
        self._add_quick(delay + len(_SCENARIOS))
        self._add_history()
        self._layout.addStretch()

    # ── Sections ─────────────────────────────────────────────────────────────

    def _add_disk_section(self, title: str, disks: list, delay_start: int):
        self._layout.addWidget(_SectionHdr(title))

        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        row_lay = QVBoxLayout(wrap)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(16)

        current_row: QHBoxLayout | None = None
        for i, disk in enumerate(disks):
            if i % 3 == 0:
                current_row = QHBoxLayout()
                current_row.setSpacing(20)
                row_lay.addLayout(current_row)

            card = DiskCard(disk)
            card.clicked.connect(self.disk_selected)
            current_row.addWidget(self._fade_wrap(card, (delay_start + i) * 60))

        if current_row:
            current_row.addStretch()

        self._layout.addWidget(wrap)

    def _add_scenarios(self, delay_start: int):
        self._layout.addWidget(_SectionHdr("Scénarios de récupération"))

        outer = QWidget()
        outer.setStyleSheet("background: transparent;")
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(16)

        row1 = QHBoxLayout()
        row1.setSpacing(16)
        row2 = QHBoxLayout()
        row2.setSpacing(16)

        for i, (icon, title, desc, accent) in enumerate(_SCENARIOS):
            card = _ScenarioCard(icon, title, desc, accent)
            card.clicked.connect(self.scenario_selected)
            (row1 if i < 3 else row2).addWidget(
                self._fade_wrap(card, (delay_start + i) * 50)
            )

        row1.addStretch()
        row2.addStretch()
        outer_lay.addLayout(row1)
        outer_lay.addLayout(row2)
        self._layout.addWidget(outer)

    def _add_quick(self, delay_start: int):
        self._layout.addWidget(_SectionHdr("Accès rapide"))

        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(20)

        for i, (icon, label, _tooltip) in enumerate(_QUICK):
            card = _QuickCard(icon, label)
            row.addWidget(self._fade_wrap(card, (delay_start + i) * 60))
        row.addStretch()

        self._layout.addWidget(wrap)

    def _add_history(self):
        """Affiche les 5 derniers scans depuis logs/history.json."""
        try:
            with open(_HISTORY_PATH, "r", encoding="utf-8") as fh:
                history: list[dict] = json.load(fh)
        except Exception:
            return   # pas d'historique → section absente

        if not history:
            return

        self._layout.addWidget(_SectionHdr("Scans récents"))
        # Conteneur carte avec séparateurs internes (style Stitch)
        wrap = QFrame()
        wrap.setStyleSheet(
            "QFrame { background: rgba(255,255,255,0.04);"
            "  border: 1px solid rgba(255,255,255,0.05);"
            "  border-radius: 12px; }"
        )
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        entries = history[:5]
        for i, entry in enumerate(entries):
            row = _HistoryRow(entry)
            row.reload_requested.connect(self.history_scan_requested)
            col.addWidget(row)
            if i < len(entries) - 1:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet("background: rgba(255,255,255,0.05); border: none;")
                col.addWidget(sep)
        self._layout.addWidget(wrap)

    # ── Animation fondu échelonné ─────────────────────────────────────────────

    @staticmethod
    def _fade_wrap(widget: QWidget, delay_ms: int) -> QWidget:
        """Enveloppe le widget dans un conteneur avec animation d'opacité différée."""
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
                anim.setDuration(380)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                # Nettoyer l'effet à la fin pour libérer les ressources
                anim.finished.connect(lambda: wrap.setGraphicsEffect(None))
                anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
                wrap._fade_anim = anim   # éviter la GC
            except RuntimeError:
                pass

        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(_start)
        timer.start(delay_ms)
        wrap._fade_timer = timer   # éviter la GC
        return wrap
