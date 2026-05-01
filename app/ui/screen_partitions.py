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
    ERR as _ERR,
)
from app.ui.palette import (
    OK as _OK,
)
from app.ui.palette import (
    WARN as _WARN,
)


def _fmt_gb(n_bytes: int) -> str:
    return f"{n_bytes / (1024**3):.1f} Go"


def _section_hdr(title: str) -> QWidget:
    w = QWidget()
    w.setFixedHeight(24)
    w.setStyleSheet("background-color: #C0C0C0;")
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 4, 0, 0)
    row.setSpacing(8)
    lbl = QLabel(title.upper())
    lbl.setStyleSheet(
        "color: #000000; font-size: 10px; font-weight: 700;"
        "font-family: 'Work Sans', Arial; background: transparent;"
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
        self.setFixedHeight(60)
        self.setStyleSheet(
            "_PartRow {"
            "  background-color: #C0C0C0;"
            "  border-top: 2px solid #FFFFFF; border-left: 2px solid #FFFFFF;"
            "  border-bottom: 2px solid #808080; border-right: 2px solid #808080;"
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
            "background-color: #000080; color: #FFFFFF;"
            "font-size: 9px; font-weight: 700; font-family: 'Work Sans', Arial;"
        )
        lay.addWidget(badge)

        col = QVBoxLayout()
        col.setSpacing(2)
        d = QLabel(part.device)
        d.setStyleSheet(
            "color: #000000; font-size: 12px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        m = QLabel(f"{part.mountpoint}  |  {part.fstype or 'inconnu'}")
        m.setStyleSheet(
            "color: #404040; font-size: 10px;"
            "font-family: 'Work Sans', Arial; background: transparent;"
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
            "color: #404040; font-size: 11px; font-family: 'Work Sans', Arial; background: transparent;"
        )
        lay.addWidget(sz)

        p = QLabel(pct_txt)
        p.setFixedWidth(38)
        p.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        p.setStyleSheet(
            f"color: {pct_col}; font-size: 11px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
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
#  Carte outil
# ═══════════════════════════════════════════════════════════════════════════════

class _ToolCard(QFrame):
    def __init__(self, title: str, desc: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.setStyleSheet(
            "_ToolCard {"
            "  background-color: #C0C0C0;"
            "  border-top: 2px solid #FFFFFF; border-left: 2px solid #FFFFFF;"
            "  border-bottom: 2px solid #808080; border-right: 2px solid #808080;"
            "}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)

        txt = QVBoxLayout()
        txt.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(
            "color: #000000; font-size: 12px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        d = QLabel(desc)
        d.setStyleSheet(
            "color: #404040; font-size: 11px; font-family: 'Work Sans', Arial; background: transparent;"
        )
        txt.addWidget(t)
        txt.addWidget(d)
        lay.addLayout(txt, stretch=1)

        btn = QPushButton("Bientot disponible")
        btn.setFixedSize(130, 24)
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        btn.setEnabled(False)
        btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #C0C0C0; color: #808080;"
            "  border-top: 2px solid #FFFFFF; border-left: 2px solid #FFFFFF;"
            "  border-bottom: 2px solid #808080; border-right: 2px solid #808080;"
            "}"
        )
        lay.addWidget(btn)


# ═══════════════════════════════════════════════════════════════════════════════
#  Ecran partitions
# ═══════════════════════════════════════════════════════════════════════════════

_TOOLS_LIST = [
    ("Migration systeme",       "Migrez Windows vers un nouveau disque sans reinstallation."),
    ("Conversion MBR vers GPT", "Convertissez le style de partition sans perte de donnees."),
    ("Clone de disque",         "Copiez l'integralite d'un disque sur un autre a l'identique."),
    ("Sauvegarde de partition", "Creez une image de sauvegarde de vos partitions."),
]


class PartitionsScreen(QWidget):
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
            "background-color: #C0C0C0; border-bottom: 2px solid #808080;"
        )
        hr = QHBoxLayout(hdr)
        hr.setContentsMargins(8, 4, 8, 4)
        title = QLabel("Gestion des partitions")
        title.setStyleSheet(
            "color: #000000; font-size: 12px; font-weight: 700;"
            "font-family: 'Work Sans', Arial; background: transparent;"
        )
        hr.addWidget(title)
        hr.addStretch()
        root.addWidget(hdr)

        # Zone scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: #C0C0C0; border: none; }")

        cw = QWidget()
        cw.setStyleSheet("background-color: #C0C0C0;")
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        lay.addWidget(_section_hdr("Partitions detectees"))
        try:
            for part in psutil.disk_partitions(all=False):
                lay.addWidget(_PartRow(part))
        except Exception:
            e = QLabel("Impossible de lister les partitions.")
            e.setStyleSheet("color: #800000; font-size: 12px; background: transparent;")
            lay.addWidget(e)

        lay.addSpacing(12)
        lay.addWidget(_section_hdr("Outils de gestion"))
        for t, d in _TOOLS_LIST:
            lay.addWidget(_ToolCard(t, d))

        lay.addStretch()
        scroll.setWidget(cw)
        root.addWidget(scroll, stretch=1)
