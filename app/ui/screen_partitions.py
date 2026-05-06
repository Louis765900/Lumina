"""
Lumina — Ecran 4 : Gestion des partitions (style Windows 98)
Affiche les partitions detectees via psutil et des outils de gestion.
"""

import psutil
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.palette import (
    ACCENT as _ACCENT,
)
from app.ui.palette import (
    CARD as _CARD,
)
from app.ui.palette import (
    ERR as _ERR,
)
from app.ui.palette import (
    OK as _OK,
)
from app.ui.palette import (
    SUB as _SUB,
)
from app.ui.palette import (
    TEXT as _TEXT,
)
from app.ui.palette import (
    WARN as _WARN,
)

_PANEL = "#F8FAFC"
_SURFACE = "#FFFFFF"
_LINE = "#D0D5DD"
_SOFT_BLUE = "#EAF2FB"
_FONT = "'Segoe UI', Arial"


def _fmt_gb(n_bytes: int) -> str:
    return f"{n_bytes / (1024**3):.1f} Go"


def _section_hdr(title: str) -> QWidget:
    w = QWidget()
    w.setFixedHeight(30)
    w.setStyleSheet(f"background-color: {_CARD};")
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 4, 0, 0)
    row.setSpacing(8)
    lbl = QLabel(title.upper())
    lbl.setStyleSheet(
        f"color: {_ACCENT}; font-size: 12px; font-weight: 800;"
        f"font-family: {_FONT}; background: transparent;"
    )
    row.addWidget(lbl)
    row.addStretch()
    return w


# ═══════════════════════════════════════════════════════════════════════════════
#  Ligne de partition
# ═══════════════════════════════════════════════════════════════════════════════

class _PartRow(QFrame):
    def __init__(self, part, parent=None):
        super().__init__(parent)
        self.setObjectName("PartRow")
        self.setFixedHeight(68)
        self.setStyleSheet(
            "QFrame#PartRow {"
            f"  background-color: {_SURFACE};"
            f"  border: 1px solid {_LINE};"
            "  border-radius: 4px;"
            "}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(14)

        # Badge type
        is_sys = part.mountpoint in ("C:\\", "/")
        badge = QLabel("SYS" if is_sys else "DAT")
        badge.setFixedSize(28, 16)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background-color: {_SOFT_BLUE}; color: {_ACCENT};"
            f"border: 1px solid {_LINE}; border-radius: 3px;"
            f"font-size: 9px; font-weight: 800; font-family: {_FONT};"
        )
        lay.addWidget(badge)

        col = QVBoxLayout()
        col.setSpacing(2)
        d = QLabel(part.device)
        d.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        m = QLabel(f"{part.mountpoint}  |  {part.fstype or 'inconnu'}")
        m.setStyleSheet(
            f"color: {_SUB}; font-size: 11px;"
            f"font-family: {_FONT}; background: transparent;"
        )
        col.addWidget(d)
        col.addWidget(m)
        lay.addLayout(col, stretch=1)

        try:
            usage   = psutil.disk_usage(part.mountpoint)
            sz_txt  = f"{_fmt_gb(usage.total)}  |  {_fmt_gb(usage.free)} libres"
            pct     = usage.percent
            pct_col = _ERR if pct > 90 else (_WARN if pct > 75 else _OK)
            pct_txt = f"{pct:.0f}%"
        except (PermissionError, OSError):
            sz_txt  = "Acces refuse"
            pct_txt = "—"
            pct_col = "#808080"

        sz = QLabel(sz_txt)
        sz.setStyleSheet(
            f"color: {_SUB}; font-size: 12px; font-family: {_FONT}; background: transparent;"
        )
        lay.addWidget(sz)

        p = QLabel(pct_txt)
        p.setFixedWidth(38)
        p.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        p.setStyleSheet(
            f"color: {pct_col}; font-size: 12px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        lay.addWidget(p)

        info_btn = QPushButton("Details")
        info_btn.setFixedSize(60, 22)
        info_btn.setCursor(Qt.CursorShape.ArrowCursor)
        info_btn.clicked.connect(lambda: _PartDetailDialog(part, self).exec())
        lay.addWidget(info_btn)


# ═══════════════════════════════════════════════════════════════════════════════
#  Dialog informations detaillees
# ═══════════════════════════════════════════════════════════════════════════════

class _PartDetailDialog(QDialog):
    def __init__(self, part, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Partition — {part.device}")
        self.setMinimumWidth(400)
        self.setStyleSheet(
            "QDialog { background-color: #C0C0C0; }"
            "QLabel  { font-family: 'Work Sans', Arial; background: transparent; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        title_lbl = QLabel(part.device)
        title_lbl.setStyleSheet(
            "color: #000000; font-size: 14px; font-weight: 700;"
        )
        root.addWidget(title_lbl)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(
            "border-top: 1px solid #808080; border-bottom: 1px solid #FFFFFF;"
            "border-left: none; border-right: none;"
        )
        root.addWidget(sep)

        try:
            usage = psutil.disk_usage(part.mountpoint)
            total_str = _fmt_gb(usage.total)
            used_str  = _fmt_gb(usage.used)
            free_str  = _fmt_gb(usage.free)
            pct_str   = f"{usage.percent:.1f}%"
        except (PermissionError, OSError):
            total_str = used_str = free_str = pct_str = "Acces refuse"

        rows = [
            ("Peripherique",       part.device),
            ("Point de montage",   part.mountpoint),
            ("Systeme de fichiers", part.fstype or "inconnu"),
            ("Options de montage", part.opts or "—"),
            ("Taille totale",      total_str),
            ("Espace utilise",     used_str),
            ("Espace libre",       free_str),
            ("Utilisation",        pct_str),
        ]
        if hasattr(part, "maxfile") and part.maxfile:
            rows.append(("Nom de fichier max", str(part.maxfile)))
        if hasattr(part, "maxpath") and part.maxpath:
            rows.append(("Chemin max", str(part.maxpath)))

        grid = QVBoxLayout()
        grid.setSpacing(6)
        for label, value in rows:
            row_w = QWidget()
            row_w.setStyleSheet("background-color: #C0C0C0;")
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(8)
            lbl = QLabel(label)
            lbl.setFixedWidth(170)
            lbl.setStyleSheet("color: #808080; font-size: 11px;")
            val = QLabel(value)
            val.setWordWrap(True)
            val.setStyleSheet("color: #000000; font-size: 11px; font-weight: 700;")
            row_l.addWidget(lbl)
            row_l.addWidget(val, stretch=1)
            grid.addWidget(row_w)
        root.addLayout(grid)

        sep2 = QFrame()
        sep2.setFixedHeight(2)
        sep2.setStyleSheet(
            "border-top: 1px solid #808080; border-bottom: 1px solid #FFFFFF;"
            "border-left: none; border-right: none;"
        )
        root.addWidget(sep2)

        close_btn = QPushButton("Fermer")
        close_btn.setFixedSize(80, 26)
        close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)


# ═══════════════════════════════════════════════════════════════════════════════
#  Ecran partitions
# ═══════════════════════════════════════════════════════════════════════════════

class PartitionsScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_CARD};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # En-tete
        hdr = QWidget()
        hdr.setFixedHeight(62)
        hdr.setStyleSheet(
            f"background-color: {_PANEL}; border-bottom: 1px solid {_LINE};"
        )
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(18, 10, 18, 10)
        title = QLabel("Gestion des partitions")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 15px; font-weight: 800;"
            f"font-family: {_FONT}; background: transparent;"
        )
        hr.addWidget(title)
        hr.addStretch()
        root.addWidget(hdr)

        # Zone scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background-color: {_CARD}; border: none; }}")

        cw = QWidget()
        cw.setStyleSheet(f"background-color: {_CARD};")
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(18, 16, 18, 18)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        lay.addWidget(_section_hdr("Partitions detectees"))
        try:
            for part in psutil.disk_partitions(all=False):
                lay.addWidget(_PartRow(part))
        except Exception:
            e = QLabel("Impossible de lister les partitions.")
            e.setStyleSheet(f"color: {_ERR}; font-size: 12px; background: transparent;")
            lay.addWidget(e)

        lay.addStretch()
        scroll.setWidget(cw)
        root.addWidget(scroll, stretch=1)
