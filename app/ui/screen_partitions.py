"""
Lumina v2.0 — Écran 4 : Gestion des partitions
Affiche les partitions détectées via psutil et des outils de gestion.
"""

import psutil
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.palette import (
    ACCENT as _ACCENT,
)
from app.ui.palette import (
    BORDER as _BORDER,
)
from app.ui.palette import (
    CARD as _CARD,
)
from app.ui.palette import (
    ERR as _ERR,
)
from app.ui.palette import (
    HOVER as _HOVER,
)
from app.ui.palette import (
    MUTED as _MUTED,
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


def _fmt_gb(n_bytes: int) -> str:
    return f"{n_bytes / (1024**3):.1f} Go"


def _section_hdr(title: str) -> QWidget:
    w = QWidget()
    w.setFixedHeight(28)
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    lbl = QLabel(title.upper())
    lbl.setStyleSheet(
        f"color: {_MUTED}; font-size: 10px; font-weight: 700; letter-spacing: 1.2px;"
        "font-family: 'Inter'; background: transparent;"
    )
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {_BORDER}; border: none;")
    row.addWidget(lbl)
    row.addWidget(line, stretch=1)
    return w


# ═══════════════════════════════════════════════════════════════════════════════
#  Ligne de partition
# ═══════════════════════════════════════════════════════════════════════════════

class _PartRow(QFrame):
    def __init__(self, part, parent=None):
        super().__init__(parent)
        self.setFixedHeight(72)
        self.setStyleSheet(
            f"_PartRow {{ background: {_CARD}; border: 1px solid {_BORDER}; border-radius: 10px; }}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(20)

        # Icône
        is_sys = part.mountpoint in ("C:\\", "/")
        ico = QLabel("💿" if is_sys else "🗂")
        ico.setFixedSize(34, 34)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            "font-size: 17px; background: rgba(0,122,255,0.12); border-radius: 7px;"
        )
        lay.addWidget(ico)

        # Device + point de montage
        col = QVBoxLayout()
        col.setSpacing(3)
        d = QLabel(part.device)
        d.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: 600;"
            "font-family: 'Inter'; background: transparent;"
        )
        m = QLabel(f"{part.mountpoint}  ·  {part.fstype or 'inconnu'}")
        m.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px;"
            "font-family: 'SF Mono', Consolas, monospace; background: transparent;"
        )
        col.addWidget(d)
        col.addWidget(m)
        lay.addLayout(col, stretch=1)

        # Usage
        try:
            usage   = psutil.disk_usage(part.mountpoint)
            sz_txt  = f"{_fmt_gb(usage.total)}  ·  {_fmt_gb(usage.free)} libres"
            pct     = usage.percent
            pct_col = _ERR if pct > 90 else (_WARN if pct > 75 else _OK)
            pct_txt = f"{pct:.0f}%"
        except (PermissionError, OSError):
            sz_txt  = "Accès refusé"
            pct_txt = "—"
            pct_col = _MUTED

        sz = QLabel(sz_txt)
        sz.setStyleSheet(
            f"color: {_SUB}; font-size: 12px; font-family: 'Inter'; background: transparent;"
        )
        lay.addWidget(sz)

        p = QLabel(pct_txt)
        p.setFixedWidth(40)
        p.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        p.setStyleSheet(
            f"color: {pct_col}; font-size: 12px; font-weight: 700;"
            "font-family: 'Inter'; background: transparent;"
        )
        lay.addWidget(p)

        info_btn = QPushButton("ⓘ  Détails")
        info_btn.setFixedSize(82, 26)
        info_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        info_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {_BORDER};"
            f"  border-radius: 7px; color: {_MUTED}; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {_HOVER}; color: {_TEXT}; }}"
        )
        info_btn.clicked.connect(lambda: _PartDetailDialog(part, self).exec())
        lay.addWidget(info_btn)


# ═══════════════════════════════════════════════════════════════════════════════
#  Dialog informations détaillées
# ═══════════════════════════════════════════════════════════════════════════════

class _PartDetailDialog(QDialog):
    def __init__(self, part, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Partition — {part.device}")
        self.setMinimumWidth(420)
        self.setStyleSheet(
            "QDialog { background: #0F1120; }"
            "QLabel  { font-family: 'Inter'; background: transparent; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title_lbl = QLabel(f"💿  {part.device}")
        title_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 17px; font-weight: 700;"
        )
        root.addWidget(title_lbl)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_BORDER}; border: none;")
        root.addWidget(sep)

        # Collect usage info
        try:
            usage = psutil.disk_usage(part.mountpoint)
            total_str = _fmt_gb(usage.total)
            used_str  = _fmt_gb(usage.used)
            free_str  = _fmt_gb(usage.free)
            pct_str   = f"{usage.percent:.1f}%"
        except (PermissionError, OSError):
            total_str = used_str = free_str = pct_str = "Accès refusé"

        rows = [
            ("Périphérique",    part.device),
            ("Point de montage", part.mountpoint),
            ("Système de fichiers", part.fstype or "inconnu"),
            ("Options de montage", part.opts or "—"),
            ("Taille totale",  total_str),
            ("Espace utilisé", used_str),
            ("Espace libre",   free_str),
            ("Utilisation",    pct_str),
        ]
        if hasattr(part, "maxfile") and part.maxfile:
            rows.append(("Nom de fichier max", str(part.maxfile)))
        if hasattr(part, "maxpath") and part.maxpath:
            rows.append(("Chemin max", str(part.maxpath)))

        grid = QVBoxLayout()
        grid.setSpacing(8)
        for label, value in rows:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(8)
            lbl = QLabel(label)
            lbl.setFixedWidth(180)
            lbl.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
            val = QLabel(value)
            val.setWordWrap(True)
            val.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: 600;")
            row_l.addWidget(lbl)
            row_l.addWidget(val, stretch=1)
            grid.addWidget(row_w)
        root.addLayout(grid)

        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {_BORDER}; border: none;")
        root.addWidget(sep2)

        close_btn = QPushButton("Fermer")
        close_btn.setFixedSize(90, 32)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {_ACCENT}; color: white; border: none;"
            "  border-radius: 8px; font-size: 12px; font-weight: 600; }}"
            "QPushButton:hover { background: #005FCC; }"
        )
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)


# ═══════════════════════════════════════════════════════════════════════════════
#  Carte outil
# ═══════════════════════════════════════════════════════════════════════════════

class _ToolCard(QFrame):
    def __init__(self, icon: str, title: str, desc: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(76)
        self.setStyleSheet(
            f"_ToolCard {{ background: {_CARD}; border: 1px solid {_BORDER}; border-radius: 12px; }}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(16)

        ico = QLabel(icon)
        ico.setFixedSize(36, 36)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            "font-size: 19px; background: rgba(0,122,255,0.1); border-radius: 8px;"
        )
        lay.addWidget(ico)

        txt = QVBoxLayout()
        txt.setSpacing(3)
        t = QLabel(title)
        t.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: 600;"
            "font-family: 'Inter'; background: transparent;"
        )
        d = QLabel(desc)
        d.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; font-family: 'Inter'; background: transparent;"
        )
        txt.addWidget(t)
        txt.addWidget(d)
        lay.addLayout(txt, stretch=1)

        btn = QPushButton("Bientôt disponible")
        btn.setFixedSize(150, 28)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {_BORDER};"
            f"  border-radius: 8px; color: {_MUTED}; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {_HOVER}; color: {_TEXT}; }}"
        )
        btn.clicked.connect(lambda: QMessageBox.information(
            self,
            "Bientôt disponible",
            f"La fonctionnalité « {title} » sera disponible\ndans une prochaine version de Lumina.",
        ))
        lay.addWidget(btn)


# ═══════════════════════════════════════════════════════════════════════════════
#  Écran partitions
# ═══════════════════════════════════════════════════════════════════════════════

_TOOLS = [
    ("🔄", "Migration système",       "Migrez Windows vers un nouveau disque sans réinstallation."),
    ("🔁", "Conversion MBR → GPT",    "Convertissez le style de partition sans perte de données."),
    ("📋", "Clone de disque",         "Copiez l'intégralité d'un disque sur un autre à l'identique."),
    ("📦", "Sauvegarde de partition", "Créez une image de sauvegarde de vos partitions."),
]


class PartitionsScreen(QWidget):
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
        title = QLabel("Gestion des partitions")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 22px; font-weight: 700; font-family: 'Inter';"
        )
        sub = QLabel("Consultez, migrez et gérez les partitions de vos disques.")
        sub.setStyleSheet(f"color: {_SUB}; font-size: 13px; font-family: 'Inter';")
        col.addWidget(title)
        col.addWidget(sub)
        hr.addLayout(col)
        root.addWidget(hdr)

        # Zone scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        cw = QWidget()
        cw.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(40, 0, 40, 40)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        lay.addWidget(_section_hdr("Partitions détectées"))
        try:
            for part in psutil.disk_partitions(all=False):
                lay.addWidget(_PartRow(part))
        except Exception:
            e = QLabel("Impossible de lister les partitions.")
            e.setStyleSheet(f"color: {_WARN}; font-size: 13px; background: transparent;")
            lay.addWidget(e)

        lay.addSpacing(20)
        lay.addWidget(_section_hdr("Outils de gestion"))
        for icon, t, d in _TOOLS:
            lay.addWidget(_ToolCard(icon, t, d))

        lay.addStretch()
        scroll.setWidget(cw)
        root.addWidget(scroll, stretch=1)
